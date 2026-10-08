from test_access import assert_error


def add_turn(client, headers, conversation, content, role="user"):
    response = client.post(
        f"/conversations/{conversation}/turns",
        headers=headers(),
        json={"channel": "text", "role": role, "content": content},
    )
    assert response.status_code == 201
    return response


def put_fact(client, headers, conversation, key, value, version):
    response = client.put(
        f"/conversations/{conversation}/facts/{key}",
        headers=headers(**{"If-Match": str(version)}),
        json={"value": value},
    )
    assert response.status_code == 200
    return response.json()


def context(client, headers, conversation, role):
    response = client.get(
        f"/conversations/{conversation}/context?agent={role}", headers=headers(role=role)
    )
    assert response.status_code == 200
    return response.json()


def test_add_turn_returns_the_contract_fields(client, headers, conversation):
    response = add_turn(client, headers, conversation, "What is open with Nordic Tools?")

    assert list(response.json()) == ["id", "created_at"]


def test_voice_turns_share_the_conversation(client, headers, conversation):
    response = client.post(
        f"/conversations/{conversation}/turns",
        headers=headers(),
        json={"channel": "voice", "role": "user", "content": "spoken question"},
    )

    assert response.status_code == 201
    [turn] = context(client, headers, conversation, "orchestrator")["turns"]
    assert turn["channel"] == "voice"


def test_orchestrator_slice_has_turns_facts_and_artifacts(client, headers, conversation):
    add_turn(client, headers, conversation, "hello")
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)
    client.post(
        f"/conversations/{conversation}/artifacts",
        headers=headers(),
        json={"type": "visit_summary", "payload": {"summary": "secret payload"}},
    )

    body = context(client, headers, conversation, "orchestrator")

    assert list(body) == ["conversation_id", "turns", "facts", "artifacts"]
    assert body["conversation_id"] == conversation
    assert [t["content"] for t in body["turns"]] == ["hello"]
    assert list(body["turns"][0]) == ["id", "channel", "role", "content", "created_at"]
    assert body["facts"] == {"current_customer": {"value": {"id": "c-001"}, "version": 1}}
    [artifact] = body["artifacts"]
    assert list(artifact) == ["id", "type", "created_at"]
    assert artifact["type"] == "visit_summary"
    assert "secret payload" not in str(body)


def test_orchestrator_slice_has_the_last_ten_turns_oldest_first(client, headers, conversation):
    for number in range(1, 13):
        add_turn(client, headers, conversation, f"turn {number}")

    turns = context(client, headers, conversation, "orchestrator")["turns"]

    assert [t["content"] for t in turns] == [f"turn {n}" for n in range(3, 13)]


def test_specialist_slice_has_only_the_current_customer(client, headers, conversation):
    add_turn(client, headers, conversation, "hello")
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)
    put_fact(client, headers, conversation, "pending_action", {"tool": "log_visit"}, 0)

    body = context(client, headers, conversation, "specialist")

    assert body == {
        "conversation_id": conversation,
        "facts": {"current_customer": {"value": {"id": "c-001"}, "version": 1}},
    }


def test_specialist_slice_without_a_current_customer_has_no_facts(client, headers, conversation):
    put_fact(client, headers, conversation, "pending_action", {"tool": "log_visit"}, 0)

    body = context(client, headers, conversation, "specialist")

    assert body == {"conversation_id": conversation, "facts": {}}


def test_agent_parameter_must_match_the_role_header(client, headers, conversation):
    response = client.get(
        f"/conversations/{conversation}/context?agent=specialist", headers=headers("orchestrator")
    )

    assert_error(response, 400, "INVALID_INPUT")


def test_unknown_or_missing_agent_parameter_is_invalid(client, headers, conversation):
    for query in ("?agent=admin", ""):
        response = client.get(f"/conversations/{conversation}/context{query}", headers=headers())

        assert_error(response, 400, "INVALID_INPUT")


def test_turn_with_a_bad_channel_or_empty_content_is_invalid(client, headers, conversation):
    for body in (
        {"channel": "fax", "role": "user", "content": "hello"},
        {"channel": "text", "role": "user", "content": ""},
        {"channel": "text", "role": "robot", "content": "hello"},
    ):
        response = client.post(f"/conversations/{conversation}/turns", headers=headers(), json=body)

        assert_error(response, 400, "INVALID_INPUT")
        assert "hello" not in response.text


def test_artifact_payload_is_stored_as_given(client, headers, conversation):
    response = client.post(
        f"/conversations/{conversation}/artifacts",
        headers=headers("specialist"),
        json={"type": "visit_summary", "payload": {"nested": [1, 2, {"a": None}]}},
    )

    assert response.status_code == 201
    assert list(response.json()) == ["id"]
