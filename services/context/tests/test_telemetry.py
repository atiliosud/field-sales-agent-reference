from opentelemetry.trace import StatusCode

TRACE_ID = "0af7651916cd43dd8448eb211c80319c"
PARENT_ID = "b7ad6b7169203331"
TRACEPARENT = f"00-{TRACE_ID}-{PARENT_ID}-01"
TURN = {"channel": "text", "role": "user", "content": "Confidential customer remark"}


def spans(span_exporter):
    return span_exporter.get_finished_spans()


def test_request_span_has_session_user_and_openinference_attributes(
    client, headers, conversation, span_exporter
):
    span_exporter.clear()

    client.post(f"/conversations/{conversation}/turns", headers=headers(), json=TURN)

    [span] = spans(span_exporter)
    assert span.name == "POST /conversations/{conversation_id}/turns"
    assert span.attributes["openinference.span.kind"] == "CHAIN"
    assert span.attributes["session.id"] == conversation
    assert span.attributes["user.id"] == "sp-001"
    assert span.attributes["http.route"] == "/conversations/{conversation_id}/turns"
    assert span.attributes["http.response.status_code"] == 201
    assert span.resource.attributes["service.name"] == "context-service"


def test_creating_a_conversation_puts_its_id_in_session_id(client, headers, span_exporter):
    response = client.post("/conversations", headers=headers())

    [span] = spans(span_exporter)
    assert span.attributes["session.id"] == response.json()["id"]


def test_traceparent_makes_the_span_part_of_the_callers_trace(
    client, headers, conversation, span_exporter
):
    span_exporter.clear()

    client.get(
        f"/conversations/{conversation}/context?agent=orchestrator",
        headers=headers(traceparent=TRACEPARENT),
    )

    [span] = spans(span_exporter)
    assert f"{span.context.trace_id:032x}" == TRACE_ID
    assert f"{span.parent.span_id:016x}" == PARENT_ID


def test_failed_request_marks_the_span_as_an_error(client, headers, conversation, span_exporter):
    span_exporter.clear()

    client.put(
        f"/conversations/{conversation}/facts/current_customer",
        headers=headers(role="specialist", **{"If-Match": "0"}),
        json={"value": 1},
    )

    [span] = spans(span_exporter)
    assert span.status.status_code is StatusCode.ERROR
    assert span.status.description == "FORBIDDEN"
    assert span.attributes["http.response.status_code"] == 403


def test_unauthenticated_request_has_a_span_without_a_user(client, span_exporter):
    client.post("/conversations", headers={"X-Agent-Role": "orchestrator"})

    [span] = spans(span_exporter)
    assert "user.id" not in span.attributes
    assert span.status.description == "UNAUTHENTICATED"


def test_health_checks_are_not_traced(client, span_exporter):
    client.get("/health")

    assert spans(span_exporter) == ()


def test_internal_failure_marks_the_span_as_an_error(
    client, headers, conversation, span_exporter, monkeypatch
):
    from context_service import slices

    async def broken(session, conversation_id):
        raise RuntimeError("boom with Confidential detail")

    monkeypatch.setattr(slices, "orchestrator_slice", broken)
    span_exporter.clear()

    client.get(f"/conversations/{conversation}/context?agent=orchestrator", headers=headers())

    [span] = spans(span_exporter)
    assert span.status.status_code is StatusCode.ERROR
    assert "Confidential" not in str(span.events) + str(dict(span.attributes))


def test_content_of_turns_facts_and_artifacts_never_reaches_a_span(
    client, headers, conversation, span_exporter, make_token
):
    token = make_token()
    client.post(f"/conversations/{conversation}/turns", headers=headers(), json=TURN)
    client.put(
        f"/conversations/{conversation}/facts/current_customer",
        headers=headers(**{"If-Match": "0"}),
        json={"value": {"note": "Confidential fact"}},
    )
    client.post(
        f"/conversations/{conversation}/artifacts",
        headers=headers(),
        json={"type": "visit_summary", "payload": {"summary": "Confidential artifact"}},
    )
    client.get(f"/conversations/{conversation}/context?agent=orchestrator", headers=headers())

    recorded = []
    for span in spans(span_exporter):
        recorded += [span.name, str(dict(span.attributes)), str(span.status.description)]
        recorded += [f"{e.name} {dict(e.attributes or {})}" for e in span.events]
    text = " ".join(recorded)
    for secret in (token, "Confidential", "customer remark"):
        assert secret not in text


def test_session_id_is_on_the_span_even_when_the_request_is_refused(
    client, headers, conversation, span_exporter
):
    span_exporter.clear()

    client.put(
        f"/conversations/{conversation}/facts/current_customer",
        headers=headers(role="specialist", **{"If-Match": "0"}),
        json={"value": 1},
    )
    client.get(f"/conversations/{conversation}/context?agent=orchestrator")

    forbidden, unauthenticated = spans(span_exporter)
    assert forbidden.attributes["session.id"] == conversation
    assert unauthenticated.attributes["session.id"] == conversation
    assert "user.id" not in unauthenticated.attributes


def test_a_malformed_conversation_id_is_not_put_in_session_id(client, headers, span_exporter):
    client.get("/conversations/not-a-uuid/context?agent=orchestrator", headers=headers())

    [span] = spans(span_exporter)
    assert "session.id" not in span.attributes
