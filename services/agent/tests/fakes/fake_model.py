import asyncio
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field


def say(text: str) -> AIMessage:
    return AIMessage(content=text)


def call(name: str, **args: Any) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{name}"}])


class FakeChatModel(BaseChatModel):
    """A chat model that replays a script, so tests need no model key."""

    script: list[AIMessage] = Field(default_factory=list)
    delay_s: float = 0.0
    prompts: list[list[BaseMessage]] = Field(default_factory=list)
    bound: list[list[str]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "fake"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeChatModel":
        self.bound.append([t["function"]["name"] if isinstance(t, dict) else t.name for t in tools])
        return self

    def _generate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        raise NotImplementedError("the agents call the model asynchronously")

    async def _agenerate(self, messages: list[BaseMessage], **kwargs: Any) -> ChatResult:
        self.prompts.append(messages)
        await asyncio.sleep(self.delay_s)
        return ChatResult(generations=[ChatGeneration(message=self.script.pop(0))])
