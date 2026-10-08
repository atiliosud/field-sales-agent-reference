import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from langchain_core.language_models import BaseChatModel
from langgraph.errors import GraphRecursionError

from agent_service.config import Settings
from agent_service.context_client import ContextClient, ContextRefused, ContextUnavailable
from agent_service.errors import ApiError
from agent_service.graph import Deps, build_graph
from agent_service.harness import Harness, HarnessLimit, Reason, WriteState
from agent_service.mcp_client import ToolRunner
from agent_service.model_factory import create_model
from agent_service.prompts import Prompt

logger = logging.getLogger(__name__)

PERSIST_TIMEOUT_S = 5.0
HISTORY_UNAVAILABLE = "I couldn't reach the conversation history; please try again."
LIMIT_READ_ONLY = "I couldn't finish this request; please try again or narrow it down."
WRITE_NOUNS = {"log_visit": ("visit", "logged"), "create_lead": ("lead", "created")}


@dataclass
class TurnResult:
    conversation_id: str
    answer: str
    pending_action: dict[str, str] | None = None
    limit: Reason | None = None
    steps_used: int = 0
    save_failed: bool = False


def limit_message(write: WriteState | None) -> str:
    if write is None or write.status == "failed":
        return LIMIT_READ_ONLY
    noun, done = WRITE_NOUNS[write.tool]
    if write.status == "done":
        return f"The {noun} was {done}, but I couldn't finish the rest of your request."
    return f"I'm not sure whether the {noun} was saved. Please check it before trying again."


class ChatService:
    """Runs one turn: load the context, run the graph inside the harness, save the turn."""

    def __init__(
        self,
        settings: Settings,
        model: BaseChatModel | None,
        orchestrator: Prompt,
        specialist: Prompt,
    ) -> None:
        self._settings = settings
        self._model = model
        self._orchestrator = orchestrator
        self._specialist = specialist

    async def chat(
        self, token: str, conversation_id: str | None, message: str, confirm: bool
    ) -> TurnResult:
        settings = self._settings
        harness = Harness(settings.max_steps, settings.tool_timeout_s, settings.turn_timeout_s)
        async with httpx.AsyncClient(base_url=settings.context_url, timeout=5.0) as http:
            context = ContextClient(http, token)
            loaded: dict[str, Any] = {}
            tools: ToolRunner | None = None

            async def work() -> dict[str, Any]:
                nonlocal conversation_id, loaded, tools
                if conversation_id is None:
                    conversation_id = await context.create_conversation()
                loaded = await context.load(conversation_id, "orchestrator")
                tools = ToolRunner(settings.mcp_url, token, conversation_id, harness)
                graph = build_graph(
                    Deps(
                        self._model or create_model(settings),
                        self._orchestrator,
                        self._specialist,
                        tools,
                        context,
                        conversation_id,
                    )
                )
                pending = loaded["facts"].get("pending_action", {}).get("value")
                state = {
                    "message": message,
                    "confirm": confirm,
                    "history": loaded["turns"],
                    "facts": loaded["facts"],
                    "pending": pending,
                }
                config = {
                    "callbacks": harness.callbacks,
                    "recursion_limit": 2 * settings.max_steps + 5,
                }
                return await graph.ainvoke(state, config)  # type: ignore[arg-type]

            limit: Reason | None = None
            final: dict[str, Any] = {}
            try:
                final = await harness.run_turn(work())
            except HarnessLimit as stop:
                limit = stop.reason
            except GraphRecursionError:
                limit = "max_steps"
            except ContextRefused as refused:
                raise ApiError(refused.status, refused.code, refused.message) from None
            except ContextUnavailable:
                if conversation_id is None:
                    raise ApiError(500, "INTERNAL", HISTORY_UNAVAILABLE) from None
                return TurnResult(conversation_id, HISTORY_UNAVAILABLE)

            if conversation_id is None:
                raise ApiError(500, "INTERNAL", HISTORY_UNAVAILABLE)
            if limit:
                result = TurnResult(conversation_id, limit_message(harness.write), limit=limit)
                new_pending = None
            else:
                new_pending = final.get("new_pending")
                result = TurnResult(
                    conversation_id,
                    final["answer"],
                    {"tool": new_pending["tool"], "summary": new_pending["summary"]}
                    if new_pending
                    else None,
                )
            result.steps_used = harness.steps_used

            customer = None if limit or tools is None else tools.customer
            visit = tools.visit if tools else None
            try:
                async with asyncio.timeout(PERSIST_TIMEOUT_S):
                    await save_turn(
                        context,
                        conversation_id,
                        message,
                        result.answer,
                        loaded.get("facts", {}),
                        new_pending,
                        customer,
                        visit,
                    )
            except Exception as error:
                logger.error("The turn could not be saved: %s", type(error).__name__)
                result.save_failed = True
            return result


async def save_turn(
    context: ContextClient,
    conversation_id: str,
    message: str,
    answer: str,
    facts: dict[str, Any],
    new_pending: dict[str, Any] | None,
    customer: dict[str, str] | None,
    visit: dict[str, Any] | None,
) -> None:
    """Save the turn, then the facts. The pending action goes last: it is only kept when
    the question reached the user, and a pending action that was not renewed is dropped."""

    def version(key: str) -> int:
        return facts.get(key, {}).get("version", 0)

    await context.add_turn(conversation_id, "user", message)
    await context.add_turn(conversation_id, "orchestrator", answer)
    if visit:
        await context.add_artifact(conversation_id, "visit_summary", visit)
    current = facts.get("current_customer", {}).get("value")
    if customer and customer != current:
        await context.put_fact(
            conversation_id, "current_customer", customer, version("current_customer")
        )
    if new_pending:
        await context.put_fact(
            conversation_id, "pending_action", new_pending, version("pending_action")
        )
    elif "pending_action" in facts:
        await context.put_fact(conversation_id, "pending_action", None, version("pending_action"))
