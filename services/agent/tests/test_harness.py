import asyncio

import pytest
from fakes.fake_model import FakeChatModel, call, say

from agent_service import turn
from agent_service.harness import Harness, HarnessLimit
from agent_service.prompts import load_prompt
from agent_service.turn import limit_message

READ_ONLY = "I couldn't finish this request; please try again or narrow it down."
VISIT = {"customer_id": "c-001", "summary": "Asked for a quote.", "outcome": "follow_up"}


def loop_forever(model: FakeChatModel) -> None:
    """A specialist that keeps asking for tools, so the model is called again and again."""
    model.script += [call("handoff", task="Look at c-001.")]
    model.script += [call("get_customer", customer_id="c-001") for _ in range(10)]


def start_visit(chat, model):
    model.script += [
        call("request_confirmation", tool="log_visit", arguments=VISIT, summary="Log it?")
    ]
    return chat("Log a visit").json()


def test_a_step_is_a_model_call_and_the_seventh_is_refused():
    harness = Harness(max_steps=6, tool_timeout_s=10, turn_timeout_s=60)

    for _ in range(6):
        harness.count_step()

    with pytest.raises(HarnessLimit) as stop:
        harness.count_step()
    assert stop.value.reason == "max_steps"
    assert harness.steps_used == 6


def test_max_steps_stops_a_turn_that_keeps_calling_the_model(chat, model, context):
    loop_forever(model)

    body = chat("Look at Nordic Tools").json()

    assert body["answer"] == READ_ONLY
    assert "pending_action" not in body
    assert len(model.prompts) == 6


def test_max_steps_comes_from_the_settings(make_client, model, token):
    client = make_client(max_steps=2)
    loop_forever(model)

    response = client.post(
        "/chat", json={"message": "Look"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.json()["answer"] == READ_ONLY
    assert len(model.prompts) == 2


def test_a_slow_read_tool_stops_the_turn(make_client, model, mcp, token):
    client = make_client(tool_timeout_s=0.1)
    mcp.delays["get_customer"] = 1
    model.script += [call("handoff", task="Get c-001."), call("get_customer", customer_id="c-001")]

    response = client.post(
        "/chat", json={"message": "Customer?"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.json()["answer"] == READ_ONLY
    assert len(model.prompts) == 2


def test_a_slow_model_stops_the_turn(make_client, model, token):
    client = make_client(turn_timeout_s=0.1)
    model.delay_s = 1
    model.script += [call("answer", text="Too late.")]

    response = client.post(
        "/chat", json={"message": "Hi"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.json()["answer"] == READ_ONLY


def test_the_turn_timeout_also_covers_loading_the_context(make_client, model, context, token):
    client = make_client(turn_timeout_s=0.1)
    model.script += [call("answer", text="Hello.")]
    headers = {"Authorization": f"Bearer {token}"}
    cid = client.post("/chat", json={"message": "Hi"}, headers=headers).json()["conversation_id"]
    context.delay_s = 0.3

    response = client.post("/chat", json={"message": "Hi", "conversation_id": cid}, headers=headers)

    assert response.json()["answer"] == READ_ONLY
    assert len(model.prompts) == 1  # only the first turn reached the model


def test_a_limit_saves_the_turn_and_no_new_facts(chat, model, context):
    first = chat_with_customer(chat, model)
    cid = first["conversation_id"]
    before = dict(context.conversations[cid].facts)
    loop_forever(model)

    chat("Look at the other one", conversation_id=cid)

    conversation = context.conversations[cid]
    assert [t["content"] for t in conversation.turns][-2:] == ["Look at the other one", READ_ONLY]
    assert conversation.facts == before


def chat_with_customer(chat, model):
    model.script += [
        call("handoff", task="Get c-001."),
        call("get_customer", customer_id="c-001"),
        say("It is Nordic Tools."),
        call("answer", text="Nordic Tools."),
    ]
    return chat("Who is c-001?").json()


def test_a_limit_always_clears_the_pending_action(chat, model, context):
    first = start_visit(chat, model)
    cid = first["conversation_id"]
    loop_forever(model)

    chat("Something else", conversation_id=cid)

    assert context.fact(cid, "pending_action")["value"] is None


def test_a_write_that_finished_before_the_limit_is_reported_as_done(
    make_client, model, mcp, context, token
):
    first = start_visit_with(make_client, model, token)
    client, cid = first
    client_slow = make_client(turn_timeout_s=0.2)
    model.delay_s = 1
    model.script += [call("answer", text="Done.")]

    response = client_slow.post(
        "/chat",
        json={"message": "yes", "conversation_id": cid, "confirm": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == (
        "The visit was logged, but I couldn't finish the rest of your request."
    )
    assert len(mcp.visits) == 1
    assert context.fact(cid, "pending_action")["value"] is None
    [artifact] = context.conversations[cid].artifacts
    assert artifact["type"] == "visit_summary"


def start_visit_with(make_client, model, token):
    client = make_client()
    model.script += [
        call("request_confirmation", tool="log_visit", arguments=VISIT, summary="Log it?")
    ]
    cid = client.post(
        "/chat", json={"message": "Log a visit"}, headers={"Authorization": f"Bearer {token}"}
    ).json()["conversation_id"]
    return client, cid


def test_a_write_cut_off_by_the_tool_limit_is_reported_as_unknown(
    make_client, model, mcp, context, token
):
    client, cid = start_visit_with(make_client, model, token)
    slow = make_client(tool_timeout_s=0.1)
    mcp.delays["log_visit"] = 1

    response = slow.post(
        "/chat",
        json={"message": "yes", "conversation_id": cid, "confirm": True},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.json()["answer"] == (
        "I'm not sure whether the visit was saved. Please check it before trying again."
    )
    assert context.fact(cid, "pending_action")["value"] is None


def test_a_write_refused_by_the_tool_is_not_unknown():
    from agent_service.harness import WriteState

    assert limit_message(WriteState("log_visit", "failed")) == READ_ONLY
    assert limit_message(None) == READ_ONLY


@pytest.mark.parametrize(
    ("tool", "status", "message"),
    [
        (
            "log_visit",
            "done",
            "The visit was logged, but I couldn't finish the rest of your request.",
        ),
        (
            "create_lead",
            "done",
            "The lead was created, but I couldn't finish the rest of your request.",
        ),
        (
            "log_visit",
            "unknown",
            "I'm not sure whether the visit was saved. Please check it before trying again.",
        ),
        (
            "create_lead",
            "unknown",
            "I'm not sure whether the lead was saved. Please check it before trying again.",
        ),
    ],
)
def test_the_limit_messages(tool, status, message):
    from agent_service.harness import WriteState

    assert limit_message(WriteState(tool, status)) == message


def test_the_turn_result_names_the_limit_and_the_steps_used(settings, model, mcp, context, token):
    loop_forever(model)
    prompts = {name: load_prompt(name) for name in ("orchestrator.v1", "specialist.v1")}
    service = turn.ChatService(
        settings, model, prompts["orchestrator.v1"], prompts["specialist.v1"]
    )

    result = asyncio.run(service.chat(token, None, "Look", False))

    assert result.limit == "max_steps"
    assert result.steps_used == 6
    assert result.answer == READ_ONLY
