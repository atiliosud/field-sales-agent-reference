import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.callbacks import AsyncCallbackHandler

Reason = Literal["max_steps", "tool_timeout", "turn_timeout"]


class HarnessLimit(Exception):
    """A limit of the harness was reached and the turn must stop."""

    def __init__(self, reason: Reason) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class WriteState:
    tool: str
    status: Literal["unknown", "done", "failed"]


class StepCounter(AsyncCallbackHandler):
    """Counts the model calls of a turn and refuses the one after the last allowed step."""

    raise_error = True

    def __init__(self, harness: "Harness") -> None:
        self._harness = harness

    async def on_chat_model_start(self, *args: Any, **kwargs: Any) -> None:
        self._harness.count_step()


class Harness:
    """The limits of one turn: model calls, time per tool call and time per turn.

    A step is one call to the model, from the orchestrator or from the specialist.
    """

    def __init__(self, max_steps: int, tool_timeout_s: float, turn_timeout_s: float) -> None:
        self.max_steps = max_steps
        self.tool_timeout_s = tool_timeout_s
        self.turn_timeout_s = turn_timeout_s
        self.steps_used = 0
        self.write: WriteState | None = None

    @property
    def callbacks(self) -> list[AsyncCallbackHandler]:
        return [StepCounter(self)]

    def count_step(self) -> None:
        if self.steps_used >= self.max_steps:
            raise HarnessLimit("max_steps")
        self.steps_used += 1

    async def run_turn[T](self, work: Awaitable[T]) -> T:
        try:
            async with asyncio.timeout(self.turn_timeout_s):
                return await work
        except TimeoutError:
            raise HarnessLimit("turn_timeout") from None

    async def run_tool[T](self, call: Awaitable[T], *, write_tool: str | None = None) -> T:
        if write_tool:
            self.write = WriteState(write_tool, "unknown")
        try:
            async with asyncio.timeout(self.tool_timeout_s):
                return await call
        except TimeoutError:
            raise HarnessLimit("tool_timeout") from None

    def write_finished(self, succeeded: bool) -> None:
        if self.write:
            self.write.status = "done" if succeeded else "failed"
