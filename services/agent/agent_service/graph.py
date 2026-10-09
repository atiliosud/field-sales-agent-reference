import json
import logging
from dataclasses import dataclass
from typing import Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_service import telemetry
from agent_service.context_client import ContextClient
from agent_service.mcp_client import READ_TOOLS, WRITE_TOOLS, ToolRunner
from agent_service.prompts import Prompt

logger = logging.getLogger(__name__)

NOTHING_TO_CONFIRM = "There is no pending action to confirm."
NO_ANSWER = "I couldn't put an answer together; please try again."
TOOLS_UNAVAILABLE = '{"error": {"code": "INTERNAL", "message": "The sales tools are unavailable."}}'
TOOL_NOT_ALLOWED = '{"error": {"code": "FORBIDDEN", "message": "That tool is not allowed."}}'


class TurnState(TypedDict, total=False):
    message: str
    confirm: bool
    history: list[dict[str, Any]]
    facts: dict[str, Any]
    pending: dict[str, Any] | None
    rounds: int
    route: Literal["specialist", "confirm", "respond"]
    task: str
    execute: dict[str, Any]
    executed: bool
    specialist_result: str
    draft: str
    proposal: dict[str, Any]
    answer: str
    new_pending: dict[str, Any]


@dataclass
class Deps:
    model: BaseChatModel
    orchestrator: Prompt
    specialist: Prompt
    tools: ToolRunner
    context: ContextClient
    conversation_id: str


ROUTING_TOOLS: dict[str, dict[str, Any]] = {
    "answer": {"text": {"type": "string"}},
    "handoff": {"task": {"type": "string"}},
    "request_confirmation": {
        "tool": {"type": "string", "enum": list(WRITE_TOOLS)},
        "arguments": {"type": "object"},
        "summary": {"type": "string"},
    },
    "confirm_pending": {},
}


def _routing_tools(prompt: Prompt, names: list[str]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": prompt.tools[name],
                "parameters": {
                    "type": "object",
                    "properties": ROUTING_TOOLS[name],
                    "required": list(ROUTING_TOOLS[name]),
                },
            },
        }
        for name in names
    ]


def _text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(b.get("text", "") for b in message.content if isinstance(b, dict))


def _history(turns: list[dict[str, Any]]) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in turns) or "(none)"


def _json(value: Any) -> str:
    return json.dumps(value) if value else "(none)"


def _confirm_pending(pending: dict[str, Any] | None, rounds: int) -> TurnState:
    if pending:
        return {"rounds": rounds, "route": "specialist", "execute": pending}
    return {"rounds": rounds, "route": "respond", "draft": NOTHING_TO_CONFIRM}


def build_graph(deps: Deps) -> CompiledStateGraph:
    async def orchestrator(state: TurnState, config: RunnableConfig) -> TurnState:
        rounds = state.get("rounds", 0) + 1
        pending, first = state["pending"], rounds == 1
        if first and state["confirm"]:
            return _confirm_pending(pending, rounds)

        names = ["answer"]
        if not state.get("executed"):
            names += ["handoff", "request_confirmation"]
            if first and pending:
                names.append("confirm_pending")
        prompt = deps.orchestrator
        messages = [
            SystemMessage(prompt.system),
            HumanMessage(
                prompt.input.format(
                    history=_history(state["history"]),
                    facts=_json(
                        {k: v["value"] for k, v in state["facts"].items() if v["value"] is not None}
                    ),
                    pending=_json(pending),
                    message=state["message"],
                    specialist_result=state.get("specialist_result", "(none)"),
                )
            ),
        ]
        model = deps.model.bind_tools(_routing_tools(prompt, names))
        with telemetry.model_call(prompt):
            reply = await model.ainvoke(messages, config)
        call = reply.tool_calls[0] if reply.tool_calls else None
        if call is None or call["name"] not in names:
            return {"rounds": rounds, "route": "respond", "draft": _text(reply) or NO_ANSWER}
        args = call["args"]
        match call["name"]:
            case "handoff":
                return {"rounds": rounds, "route": "specialist", "task": args["task"]}
            case "request_confirmation":
                if args.get("tool") not in WRITE_TOOLS or not isinstance(
                    args.get("arguments"), dict
                ):
                    return {"rounds": rounds, "route": "respond", "draft": NO_ANSWER}
                return {"rounds": rounds, "route": "confirm", "proposal": args}
            case "confirm_pending":
                return _confirm_pending(pending, rounds)
            case _:
                return {"rounds": rounds, "route": "respond", "draft": args["text"]}

    async def specialist(state: TurnState, config: RunnableConfig) -> TurnState:
        slice_ = await deps.context.load(deps.conversation_id, "specialist")
        if action := state.get("execute"):
            result = await deps.tools.call(action["tool"], action["arguments"], confirmed=True)
            return {"specialist_result": result.text, "executed": True}

        try:
            tools = await deps.tools.tools(READ_TOOLS)
        except Exception as error:
            logger.error("The sales tools could not be loaded: %s", type(error).__name__)
            return {"specialist_result": TOOLS_UNAVAILABLE}
        prompt = deps.specialist
        current = slice_["facts"].get("current_customer", {}).get("value")
        messages: list[Any] = [
            SystemMessage(prompt.system),
            HumanMessage(prompt.input.format(task=state["task"], current_customer=_json(current))),
        ]
        model = deps.model.bind_tools(tools)
        while True:
            with telemetry.model_call(prompt):
                reply = await model.ainvoke(messages, config)
            messages.append(reply)
            if not reply.tool_calls:
                return {"specialist_result": _text(reply) or NO_ANSWER}
            for call in reply.tool_calls:
                if call["name"] in READ_TOOLS:
                    content = (await deps.tools.call(call["name"], call["args"])).text
                else:
                    content = TOOL_NOT_ALLOWED
                messages.append(ToolMessage(content=content, tool_call_id=call["id"]))

    def confirm(state: TurnState) -> TurnState:
        proposal = state["proposal"]
        pending = {
            "tool": proposal["tool"],
            "arguments": proposal["arguments"],
            "summary": proposal["summary"],
        }
        return {"answer": proposal["summary"], "new_pending": pending}

    def respond(state: TurnState) -> TurnState:
        return {"answer": state["draft"]}

    graph = StateGraph(TurnState)
    graph.add_node("orchestrator", orchestrator)
    graph.add_node("specialist", specialist)
    graph.add_node("confirm", confirm)
    graph.add_node("respond", respond)
    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges("orchestrator", lambda state: state["route"])
    graph.add_edge("specialist", "orchestrator")
    graph.add_edge("confirm", END)
    graph.add_edge("respond", END)
    return graph.compile()
