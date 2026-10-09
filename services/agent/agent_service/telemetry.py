import os
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

import httpx
from mcp.shared._httpx_utils import create_mcp_http_client
from openinference.instrumentation import TraceConfig
from openinference.instrumentation.langchain import LangChainInstrumentor
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

from agent_service.prompts import Prompt

SERVICE_NAME = "agent-service"

tracer = trace.get_tracer(SERVICE_NAME)

_turn: ContextVar[dict[str, str] | None] = ContextVar("turn_attributes", default=None)
_prompt: ContextVar[dict[str, str] | None] = ContextVar("prompt_attributes", default=None)


class TurnAttributes(SpanProcessor):
    """Give every span of a turn its user and session, and the model spans their prompt.

    LangChain spans are started by the instrumentation, outside our code, so the values
    travel in context variables and are copied onto each span when it starts.
    """

    def on_start(self, span: Span, parent_context: Context | None = None) -> None:  # type: ignore[override]
        span.set_attribute("openinference.span.kind", "CHAIN")
        for key, value in {**(_turn.get() or {}), **(_prompt.get() or {})}.items():
            span.set_attribute(key, value)

    def on_end(self, span: ReadableSpan) -> None:
        return None


def setup() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(TurnAttributes())
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    # Tokens and cost stay; what the user and the model said does not.
    hidden = TraceConfig(
        hide_inputs=True,
        hide_outputs=True,
        hide_input_messages=True,
        hide_output_messages=True,
        hide_input_text=True,
        hide_output_text=True,
        hide_llm_tools=True,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider, config=hidden)


def start_turn(user_id: str) -> None:
    """Called on the request span: mark it as the agent's turn and remember the user."""
    _turn.set({"user.id": user_id})
    span = trace.get_current_span()
    span.set_attribute("openinference.span.kind", "AGENT")
    span.set_attribute("user.id", user_id)


def set_session(conversation_id: str) -> None:
    _turn.set({**(_turn.get() or {}), "session.id": conversation_id})
    trace.get_current_span().set_attribute("session.id", conversation_id)


@contextmanager
def model_call(prompt: Prompt) -> Iterator[None]:
    token = _prompt.set({"prompt.id": prompt.id, "prompt.version": prompt.version})
    try:
        yield
    finally:
        _prompt.reset(token)


def record_harness(limit: str | None, steps_used: int) -> None:
    span = trace.get_current_span()
    span.set_attribute("harness.steps_used", steps_used)
    if limit:
        span.set_attribute("harness.limit", limit)
        span.set_status(Status(StatusCode.ERROR, limit))


def mark_failed(code: str) -> None:
    trace.get_current_span().set_status(Status(StatusCode.ERROR, code))


def record_save_failed() -> None:
    trace.get_current_span().set_attribute("save_failed", True)


async def inject_traceparent(request: httpx.Request) -> None:
    inject(request.headers)


def traced_http_client(
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | None = None,
    auth: httpx.Auth | None = None,
) -> httpx.AsyncClient:
    """The HTTP client of the MCP connection, sending `traceparent` on every request."""
    client = create_mcp_http_client(headers, timeout, auth)
    client.event_hooks["request"].append(inject_traceparent)
    return client
