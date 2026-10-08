import os

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

SERVICE_NAME = "context-service"


class SpanKindProcessor(SpanProcessor):
    """Give every span the OpenInference span kind used by Phoenix."""

    def on_start(self, span: ReadableSpan, parent_context: Context | None = None) -> None:
        span.set_attribute("openinference.span.kind", "CHAIN")  # type: ignore[attr-defined]


def setup() -> None:
    provider = TracerProvider(resource=Resource.create({"service.name": SERVICE_NAME}))
    provider.add_span_processor(SpanKindProcessor())
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)


def set_attribute(key: str, value: str) -> None:
    trace.get_current_span().set_attribute(key, value)


def mark_failed(code: str) -> None:
    trace.get_current_span().set_status(Status(StatusCode.ERROR, code))
