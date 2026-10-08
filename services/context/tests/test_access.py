from datetime import timedelta

import pytest

SOMEONE_ELSES = "sp-002"


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert list(body) == ["error"]
    assert list(body["error"]) == ["code", "message"]
    assert body["error"]["code"] == code


def test_health_needs_no_token(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_conversation_returns_the_contract_fields(client, headers):
    response = client.post("/conversations", headers=headers())

    assert response.status_code == 201
    body = response.json()
    assert list(body) == ["id", "salesperson_id", "created_at"]
    assert body["salesperson_id"] == "sp-001"


def test_no_token_is_unauthenticated(client):
    response = client.post("/conversations", headers={"X-Agent-Role": "orchestrator"})

    assert_error(response, 401, "UNAUTHENTICATED")


def test_expired_token_is_unauthenticated(client, make_token):
    token = make_token(expires_in=timedelta(hours=-1))

    response = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {token}", "X-Agent-Role": "orchestrator"},
    )

    assert_error(response, 401, "UNAUTHENTICATED")
    assert response.json()["error"]["message"] == "The token has expired."


def test_token_signed_with_another_secret_is_unauthenticated(client, make_token):
    token = make_token(secret="another-secret-with-enough-length-for-hs256")

    response = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {token}", "X-Agent-Role": "orchestrator"},
    )

    assert_error(response, 401, "UNAUTHENTICATED")


def test_token_without_expiry_is_unauthenticated(client, make_token):
    token = make_token(expires_in=None)

    response = client.post(
        "/conversations",
        headers={"Authorization": f"Bearer {token}", "X-Agent-Role": "orchestrator"},
    )

    assert_error(response, 401, "UNAUTHENTICATED")


@pytest.mark.parametrize("role", [None, "", "admin"])
def test_missing_or_unknown_agent_role_is_invalid(client, make_token, role):
    request_headers = {"Authorization": f"Bearer {make_token()}"}
    if role is not None:
        request_headers["X-Agent-Role"] = role

    response = client.post("/conversations", headers=request_headers)

    assert_error(response, 400, "INVALID_INPUT")


def test_authentication_is_checked_before_the_agent_role(client):
    response = client.post("/conversations", headers={"X-Agent-Role": "admin"})

    assert_error(response, 401, "UNAUTHENTICATED")


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("get", "/context?agent=orchestrator", None),
        ("post", "/turns", {"channel": "text", "role": "user", "content": "hello"}),
        ("put", "/facts/current_customer", {"value": "c-001"}),
        ("post", "/artifacts", {"type": "visit_summary", "payload": {}}),
    ],
)
def test_conversation_of_another_salesperson_is_forbidden(
    client, headers, conversation, method, path, payload
):
    request_headers = headers(sub=SOMEONE_ELSES, **{"If-Match": "0"})

    response = client.request(
        method, f"/conversations/{conversation}{path}", headers=request_headers, json=payload
    )

    assert_error(response, 403, "FORBIDDEN")


def test_unknown_conversation_is_not_found(client, headers):
    response = client.get(
        "/conversations/6f1c9f0e-3c43-4a45-8a4e-0b6f2a3d9e11/context?agent=orchestrator",
        headers=headers(),
    )

    assert_error(response, 404, "NOT_FOUND")


def test_malformed_conversation_id_is_invalid(client, headers):
    response = client.get("/conversations/not-a-uuid/context?agent=orchestrator", headers=headers())

    assert_error(response, 400, "INVALID_INPUT")


def test_unexpected_failure_is_reported_without_detail(client, headers, conversation, monkeypatch):
    from context_service import slices

    async def broken(session, conversation_id):
        raise RuntimeError("database password is hunter2")

    monkeypatch.setattr(slices, "orchestrator_slice", broken)

    response = client.get(
        f"/conversations/{conversation}/context?agent=orchestrator", headers=headers()
    )

    assert_error(response, 500, "INTERNAL")
    assert response.json()["error"]["message"] == "The request could not be completed."
    assert "hunter2" not in response.text
