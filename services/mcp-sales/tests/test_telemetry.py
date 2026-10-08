from opentelemetry.trace import StatusCode

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
PARENT_ID = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"


def finished_spans(span_exporter, name):
    return [s for s in span_exporter.get_finished_spans() if s.name == name]


def test_tool_span_has_tool_user_and_customer_attributes(call, span_exporter):
    call("get_customer", {"customer_id": "c-001"})

    [span] = finished_spans(span_exporter, "get_customer")
    assert dict(span.attributes) == {
        "openinference.span.kind": "TOOL",
        "tool.name": "get_customer",
        "user.id": "sp-001",
        "customer.id": "c-001",
    }


def test_span_without_a_customer_has_no_customer_attribute(call, span_exporter):
    call("check_stock", {"product_code": "P-104"})

    [span] = finished_spans(span_exporter, "check_stock")
    assert "customer.id" not in span.attributes


def test_traceparent_makes_the_tool_span_part_of_the_callers_trace(call, span_exporter):
    call("get_customer", {"customer_id": "c-001"}, headers={"traceparent": TRACEPARENT})

    [span] = finished_spans(span_exporter, "get_customer")
    assert f"{span.context.trace_id:032x}" == TRACE_ID
    assert f"{span.parent.span_id:016x}" == PARENT_ID


def test_failed_call_marks_the_span_as_an_error(call, span_exporter):
    call("get_customer", {"customer_id": "c-006"})

    [span] = finished_spans(span_exporter, "get_customer")
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "FORBIDDEN"


def test_unauthenticated_call_has_a_span_without_a_user(call, span_exporter):
    call("get_customer", {"customer_id": "c-001"}, token=None)

    [span] = finished_spans(span_exporter, "get_customer")
    assert "user.id" not in span.attributes
    assert span.status.description == "UNAUTHENTICATED"


def test_log_visit_emits_the_business_event_with_the_customer(call, span_exporter):
    arguments = {"customer_id": "c-001", "summary": "Secret summary", "outcome": "neutral"}
    call("log_visit", {**arguments, "confirmed": True})

    [span] = finished_spans(span_exporter, "log_visit")
    [event] = span.events
    assert event.name == "business.visit_logged"
    assert dict(event.attributes) == {"customer.id": "c-001"}


def test_create_lead_emits_the_business_event(call, span_exporter):
    arguments = {"company_name": "Harbour Fixings", "contact": "Anna Berg", "notes": "Hush"}
    call("create_lead", {**arguments, "confirmed": True})

    [span] = finished_spans(span_exporter, "create_lead")
    [event] = span.events
    assert event.name == "business.lead_created"


def test_unconfirmed_write_emits_no_business_event(call, span_exporter):
    arguments = {"customer_id": "c-001", "summary": "Secret summary", "outcome": "neutral"}
    call("log_visit", {**arguments, "confirmed": False})

    [span] = finished_spans(span_exporter, "log_visit")
    assert span.events == ()


def test_spans_never_contain_the_token_or_free_text(call, span_exporter, make_token):
    token = make_token()
    call(
        "log_visit",
        {
            "customer_id": "c-001",
            "summary": "Secret summary",
            "outcome": "neutral",
            "confirmed": True,
        },
        token=token,
    )
    call(
        "create_lead",
        {
            "company_name": "Harbour Fixings",
            "contact": "Anna Berg",
            "notes": "Hush",
            "confirmed": True,
        },
        token=token,
    )

    recorded = []
    for span in span_exporter.get_finished_spans():
        recorded += [span.name, str(dict(span.attributes)), str(span.status.description)]
        recorded += [f"{e.name} {dict(e.attributes or {})}" for e in span.events]
    text = " ".join(recorded)
    for secret in (token, "Secret summary", "Anna Berg", "Hush"):
        assert secret not in text


def test_session_id_header_becomes_the_session_id_attribute(call, span_exporter):
    call("get_customer", {"customer_id": "c-001"}, headers={"X-Session-Id": "conversation-42"})

    [span] = finished_spans(span_exporter, "get_customer")
    assert span.attributes["session.id"] == "conversation-42"


def test_span_without_the_session_id_header_has_no_session_id(call, span_exporter):
    call("get_customer", {"customer_id": "c-001"})

    [span] = finished_spans(span_exporter, "get_customer")
    assert "session.id" not in span.attributes


def test_every_tool_span_is_of_kind_tool(call, span_exporter):
    call("check_stock", {"product_code": "P-104"})
    call("get_customer", {"customer_id": "c-001"}, token=None)

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 2
    assert {s.attributes["openinference.span.kind"] for s in spans} == {"TOOL"}
