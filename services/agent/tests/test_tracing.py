import pytest
from fakes.fake_model import call, say
from opentelemetry.trace import SpanKind, StatusCode

SECRET_REMARK = "Confidential remark about the Nordic Tools buyer"
TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
TRACEPARENT = f"00-{TRACE_ID}-b7ad6b7169203331-01"


def finished(span_exporter):
    return span_exporter.get_finished_spans()


def own_spans(spans):
    """The spans of the agent: the fake servers run in this process and trace too."""
    return [
        s
        for s in spans
        if (s.kind is not SpanKind.SERVER or s.name == "POST /chat")
        and not str(s.attributes.get("code.function.name", "")).startswith("fakes.")
    ]


def request_span(span_exporter):
    [span] = [s for s in finished(span_exporter) if s.name == "POST /chat"]
    return span


def lookup_script(model):
    model.script += [
        call("handoff", task="Get c-001."),
        call("get_customer", customer_id="c-001"),
        say("It is Nordic Tools."),
        call("answer", text="Nordic Tools."),
    ]


def test_the_request_span_is_the_agent_span_of_the_user_and_the_conversation(
    chat, model, span_exporter
):
    lookup_script(model)

    cid = chat("Who is c-001?").json()["conversation_id"]

    span = request_span(span_exporter)
    assert span.attributes["openinference.span.kind"] == "AGENT"
    assert span.attributes["user.id"] == "sp-001"
    assert span.attributes["session.id"] == cid
    assert span.attributes["harness.steps_used"] == 4
    assert "harness.limit" not in span.attributes
    assert span.resource.attributes["service.name"] == "agent-service"


def test_every_span_of_the_turn_is_in_one_trace_with_session_and_user(chat, model, span_exporter):
    lookup_script(model)
    cid = chat("Who is c-001?").json()["conversation_id"]

    spans = finished(span_exporter)

    assert len({s.context.trace_id for s in spans}) == 1
    for span in own_spans(spans):
        assert span.attributes["session.id"] == cid, span.name
        assert span.attributes["user.id"] == "sp-001", span.name
        assert span.attributes["openinference.span.kind"], span.name


def test_model_spans_carry_the_prompt_id_and_version(chat, model, span_exporter):
    lookup_script(model)
    chat("Who is c-001?")

    models = [
        s for s in finished(span_exporter) if s.attributes.get("openinference.span.kind") == "LLM"
    ]

    prompts = [(s.attributes["prompt.id"], s.attributes["prompt.version"]) for s in models]
    assert prompts == [
        ("orchestrator", "v1"),
        ("specialist", "v1"),
        ("specialist", "v1"),
        ("orchestrator", "v1"),
    ]


def test_a_tool_call_has_a_span_with_the_tool_and_the_customer(chat, model, span_exporter):
    lookup_script(model)
    chat("Who is c-001?")

    [span] = [s for s in finished(span_exporter) if s.name == "call get_customer"]

    assert span.attributes["tool.name"] == "get_customer"
    assert span.attributes["customer.id"] == "c-001"
    assert span.status.status_code is StatusCode.UNSET


def test_a_refused_tool_call_marks_its_span_with_the_error_code(chat, model, span_exporter):
    model.script += [
        call("handoff", task="Get c-006."),
        call("get_customer", customer_id="c-006"),
        say("Not yours."),
        call("answer", text="That customer is not assigned to you."),
    ]

    chat("Tell me about c-006")

    [span] = [s for s in finished(span_exporter) if s.name == "call get_customer"]
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "FORBIDDEN"


def test_traceparent_is_sent_to_the_mcp_server_and_the_context_service(
    chat, model, mcp, context, span_exporter
):
    lookup_script(model)
    chat("Who is c-001?")

    trace_ids = {s.context.trace_id for s in finished(span_exporter)}
    [trace_id] = trace_ids
    for traceparent in [*context.traceparents, *(c.traceparent for c in mcp.calls)]:
        assert traceparent is not None
        assert traceparent.split("-")[1] == f"{trace_id:032x}"
    assert mcp.calls and context.traceparents


def test_the_mcp_call_is_a_child_of_the_tool_call_span(chat, model, mcp, span_exporter):
    lookup_script(model)
    chat("Who is c-001?")

    [span] = [s for s in finished(span_exporter) if s.name == "call get_customer"]

    [mcp_call] = mcp.calls
    assert mcp_call.traceparent.split("-")[2] == f"{span.context.span_id:016x}"


def test_an_incoming_traceparent_makes_the_turn_part_of_the_callers_trace(
    client, model, token, span_exporter
):
    model.script += [call("answer", text="Hello.")]

    client.post(
        "/chat",
        json={"message": "Hi"},
        headers={"Authorization": f"Bearer {token}", "traceparent": TRACEPARENT},
    )

    assert {f"{s.context.trace_id:032x}" for s in finished(span_exporter)} == {TRACE_ID}


def test_a_harness_limit_is_on_the_request_span_as_an_error(
    make_client, model, token, span_exporter
):
    client = make_client(max_steps=2)
    model.script += [call("handoff", task="Look at c-001.")]
    model.script += [call("get_customer", customer_id="c-001") for _ in range(5)]

    client.post("/chat", json={"message": "Look"}, headers={"Authorization": f"Bearer {token}"})

    span = request_span(span_exporter)
    assert span.attributes["harness.limit"] == "max_steps"
    assert span.attributes["harness.steps_used"] == 2
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "max_steps"


@pytest.mark.parametrize(("settings_change", "reason"), [({"tool_timeout_s": 0.1}, "tool_timeout")])
def test_a_tool_timeout_is_recorded(
    make_client, model, mcp, token, span_exporter, settings_change, reason
):
    client = make_client(**settings_change)
    mcp.delays["get_customer"] = 1
    model.script += [call("handoff", task="Get c-001."), call("get_customer", customer_id="c-001")]

    client.post(
        "/chat", json={"message": "Customer?"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert request_span(span_exporter).attributes["harness.limit"] == reason


def test_a_turn_that_could_not_be_saved_is_marked(chat, model, context, span_exporter):
    first = chat_hello(chat, model)
    context.failing["save"] = 500
    model.script += [call("answer", text="Hello again.")]
    span_exporter.clear()

    chat("Hi again", conversation_id=first["conversation_id"])

    assert request_span(span_exporter).attributes["save_failed"] is True


def chat_hello(chat, model):
    model.script += [call("answer", text="Hello.")]
    return chat("Hi").json()


def test_no_token_and_no_free_text_reach_a_span(chat, model, token, span_exporter):
    model.script += [
        call("handoff", task=f"Check this: {SECRET_REMARK}"),
        call("get_customer", customer_id="c-001"),
        say(f"Reply with {SECRET_REMARK}"),
        call("answer", text=f"Answer with {SECRET_REMARK}"),
    ]

    chat(SECRET_REMARK)

    seen = []
    for span in finished(span_exporter):
        seen += [str(v) for v in span.attributes.values()]
        for event in span.events:
            seen += [str(v) for v in (event.attributes or {}).values()]
    joined = "\n".join(seen)
    assert token not in joined
    assert "Confidential" not in joined
    assert "Bearer" not in joined
