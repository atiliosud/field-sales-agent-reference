import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Span, SpanKind, Status, StatusCode

SERVICE_NAME = "mcp-sales"

tracer = trace.get_tracer(SERVICE_NAME)


def setup() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


@contextmanager
def tool_span(
    tool_name: str, headers: Mapping[str, str], customer_id: str | None
) -> Iterator[Span]:
    attributes = {"openinference.span.kind": "TOOL", "tool.name": tool_name}
    if customer_id:
        attributes["customer.id"] = customer_id
    session_id = headers.get("x-session-id")
    if session_id:
        attributes["session.id"] = session_id
    with tracer.start_as_current_span(
        tool_name,
        context=extract(dict(headers)),
        kind=SpanKind.SERVER,
        attributes=attributes,
    ) as span:
        yield span


def mark_failed(span: Span, code: str) -> None:
    span.set_status(Status(StatusCode.ERROR, code))


def business_event(name: str, customer_id: str | None = None) -> None:
    attributes = {"customer.id": customer_id} if customer_id else None
    trace.get_current_span().add_event(name, attributes)
