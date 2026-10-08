from test_access import assert_error
from test_context import context, put_fact


def write(client, headers, conversation, key, value, version, role="orchestrator"):
    return client.put(
        f"/conversations/{conversation}/facts/{key}",
        headers=headers(role=role, **{"If-Match": str(version)}),
        json={"value": value},
    )


def test_if_match_zero_creates_the_fact(client, headers, conversation):
    response = write(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)

    assert response.status_code == 200
    assert response.json() == {"key": "current_customer", "value": {"id": "c-001"}, "version": 1}


def test_matching_version_updates_the_fact(client, headers, conversation):
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)

    response = write(client, headers, conversation, "current_customer", {"id": "c-002"}, 1)

    assert response.status_code == 200
    assert response.json()["version"] == 2
    facts = context(client, headers, conversation, "orchestrator")["facts"]
    assert facts["current_customer"] == {"value": {"id": "c-002"}, "version": 2}


def test_stale_version_is_a_conflict_and_changes_nothing(client, headers, conversation):
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)
    put_fact(client, headers, conversation, "current_customer", {"id": "c-002"}, 1)

    response = write(client, headers, conversation, "current_customer", {"id": "c-003"}, 1)

    assert_error(response, 409, "CONFLICT")
    facts = context(client, headers, conversation, "orchestrator")["facts"]
    assert facts["current_customer"] == {"value": {"id": "c-002"}, "version": 2}


def test_if_match_zero_on_an_existing_fact_is_a_conflict(client, headers, conversation):
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)

    response = write(client, headers, conversation, "current_customer", {"id": "c-002"}, 0)

    assert_error(response, 409, "CONFLICT")


def test_version_ahead_of_the_fact_is_a_conflict(client, headers, conversation):
    response = write(client, headers, conversation, "current_customer", {"id": "c-001"}, 5)

    assert_error(response, 409, "CONFLICT")


def test_specialist_cannot_write_a_fact(client, headers, conversation):
    response = write(
        client, headers, conversation, "current_customer", {"id": "c-001"}, 0, role="specialist"
    )

    assert_error(response, 403, "FORBIDDEN")
    assert context(client, headers, conversation, "orchestrator")["facts"] == {}


def test_missing_or_malformed_if_match_is_invalid(client, headers, conversation):
    url = f"/conversations/{conversation}/facts/current_customer"

    missing = client.put(url, headers=headers(), json={"value": 1})
    malformed = client.put(url, headers=headers(**{"If-Match": "latest"}), json={"value": 1})
    negative = client.put(url, headers=headers(**{"If-Match": "-1"}), json={"value": 1})

    for response in (missing, malformed, negative):
        assert_error(response, 400, "INVALID_INPUT")


def test_body_without_a_value_is_invalid(client, headers, conversation):
    response = client.put(
        f"/conversations/{conversation}/facts/current_customer",
        headers=headers(**{"If-Match": "0"}),
        json={},
    )

    assert_error(response, 400, "INVALID_INPUT")


def test_any_json_value_is_stored_as_given(client, headers, conversation):
    values = {
        "text": "free text",
        "number": 42,
        "list": [1, "two", None],
        "object": {"a": {"b": 1}},
    }

    for key, value in values.items():
        put_fact(client, headers, conversation, key, value, 0)

    facts = context(client, headers, conversation, "orchestrator")["facts"]
    assert {key: fact["value"] for key, fact in facts.items()} == values


def test_clearing_a_fact_raises_the_version_and_hides_it_from_the_slices(
    client, headers, conversation
):
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)
    put_fact(client, headers, conversation, "pending_action", {"tool": "log_visit"}, 0)

    cleared = write(client, headers, conversation, "current_customer", None, 1)

    assert cleared.status_code == 200
    assert cleared.json() == {"key": "current_customer", "value": None, "version": 2}
    orchestrator = context(client, headers, conversation, "orchestrator")
    assert list(orchestrator["facts"]) == ["pending_action"]
    assert context(client, headers, conversation, "specialist")["facts"] == {}


def test_a_cleared_fact_can_be_set_again_with_the_next_version(client, headers, conversation):
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)
    put_fact(client, headers, conversation, "current_customer", None, 1)

    response = write(client, headers, conversation, "current_customer", {"id": "c-002"}, 2)

    assert response.status_code == 200
    assert response.json()["version"] == 3


def test_facts_are_kept_per_conversation(client, headers, conversation):
    other = client.post("/conversations", headers=headers()).json()["id"]
    put_fact(client, headers, conversation, "current_customer", {"id": "c-001"}, 0)

    assert context(client, headers, other, "orchestrator")["facts"] == {}
    assert write(client, headers, other, "current_customer", {"id": "c-002"}, 0).status_code == 200
