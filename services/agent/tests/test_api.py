from fakes.fake_model import call


def post(client, body, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/chat", json=body, headers=headers)


def assert_error(response, status, code):
    assert response.status_code == status
    body = response.json()
    assert list(body) == ["error"]
    assert list(body["error"]) == ["code", "message"]
    assert body["error"]["code"] == code


def test_health_needs_no_token(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_no_token_is_unauthenticated(client):
    assert_error(post(client, {"message": "Hi"}), 401, "UNAUTHENTICATED")


def test_expired_token_is_unauthenticated(client, make_token):
    from datetime import timedelta

    token = make_token(expires_in=timedelta(hours=-1))

    assert_error(post(client, {"message": "Hi"}, token), 401, "UNAUTHENTICATED")


def test_empty_or_missing_message_is_invalid(client, token):
    assert_error(post(client, {"message": ""}, token), 400, "INVALID_INPUT")
    assert_error(post(client, {}, token), 400, "INVALID_INPUT")


def test_a_conversation_of_another_salesperson_is_forbidden(chat, model, make_token):
    model.script.append(call("answer", text="Hello."))
    mine = chat("Hi").json()

    other = chat(
        "Hi", conversation_id=mine["conversation_id"], bearer=make_token("sp-002", "South")
    )

    assert_error(other, 403, "FORBIDDEN")


def test_an_unknown_conversation_is_not_found(chat):
    response = chat("Hi", conversation_id="6f1c9f0e-3c43-4a45-8a4e-0b6f2a3d9e11")

    assert_error(response, 404, "NOT_FOUND")


def test_an_unexpected_failure_is_reported_without_detail(chat, model, monkeypatch):
    from agent_service import turn

    async def broken(*args, **kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(turn, "build_graph", lambda deps: type("G", (), {"ainvoke": broken})())

    response = chat("Hi")

    assert_error(response, 500, "INTERNAL")
    assert "secret" not in response.text
