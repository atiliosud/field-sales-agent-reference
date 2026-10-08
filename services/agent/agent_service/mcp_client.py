import json
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient

from agent_service.harness import Harness, HarnessLimit

logger = logging.getLogger(__name__)

READ_TOOLS = ("get_customer", "list_opportunities", "check_stock")
WRITE_TOOLS = ("log_visit", "create_lead")
CUSTOMER_TOOLS = ("get_customer", "list_opportunities", "log_visit")


@dataclass
class ToolResult:
    ok: bool
    text: str

    @property
    def data(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.text)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _failure(code: str, message: str) -> ToolResult:
    return ToolResult(False, json.dumps({"error": {"code": code, "message": message}}))


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content if isinstance(block, dict))


class ToolRunner:
    """Calls the MCP tools of one turn with the identity of the user.

    Every call goes through the harness, so it has a time limit. A write tool only
    gets `confirmed: true` from the orchestrator, never from the model.
    """

    def __init__(self, url: str, token: str, conversation_id: str, harness: Harness) -> None:
        self._connection: dict[str, Any] = {
            "transport": "streamable_http",
            "url": url,
            "headers": {"Authorization": f"Bearer {token}", "X-Session-Id": conversation_id},
        }
        self._harness = harness
        self._tools: dict[str, BaseTool] | None = None
        self.customer: dict[str, str] | None = None
        self.visit: dict[str, Any] | None = None

    async def tools(self, names: tuple[str, ...]) -> list[BaseTool]:
        if self._tools is None:
            loaded = await MultiServerMCPClient({"sales": self._connection}).get_tools()  # type: ignore[arg-type]
            self._tools = {tool.name: tool for tool in loaded}
        return [self._tools[name] for name in names if name in self._tools]

    async def call(
        self, name: str, arguments: dict[str, Any], *, confirmed: bool = False
    ) -> ToolResult:
        write = name in WRITE_TOOLS
        if write:
            arguments = {**arguments, "confirmed": confirmed}
        try:
            available = await self.tools((name,))
            if not available:
                return _failure("INVALID_INPUT", f"The tool {name} is not available.")
            call = {"name": name, "args": arguments, "id": uuid.uuid4().hex, "type": "tool_call"}
            message = await self._harness.run_tool(
                available[0].ainvoke(call), write_tool=name if write else None
            )
        except HarnessLimit:
            raise
        except Exception as error:
            logger.error("Tool %s failed: %s", name, type(error).__name__)
            return _failure("INTERNAL", "The tool could not be reached.")
        result = ToolResult(message.status != "error", _text(message.content))
        if write:
            self._harness.write_finished(result.ok)
        if result.ok and name == "log_visit":
            self.visit = {**result.data, "outcome": arguments.get("outcome")}
        if result.ok and name in CUSTOMER_TOOLS and "customer_id" in arguments:
            self.customer = {"id": arguments["customer_id"]}
            if "name" in result.data:
                self.customer["name"] = result.data["name"]
        return result
