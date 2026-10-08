import json
from typing import Any

from mcp.types import CallToolResult, TextContent


class ToolFailure(Exception):
    """A failure that is reported to the caller using the error format of the contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def success(data: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data))],
        structuredContent=data,
    )


def failure(error: ToolFailure) -> CallToolResult:
    body = {"error": {"code": error.code, "message": error.message}}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(body))], isError=True)
