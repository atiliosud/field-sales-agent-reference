import json

from fakes.fake_model import call

VISIT = {
    "customer_id": "c-001",
    "summary": "Asked for a quote on anchor kits.",
    "outcome": "follow_up",
}
QUESTION = "I'll log a follow-up visit to Nordic Tools: asked for a quote. Shall I go ahead?"


def ask_for_visit(model):
    model.script += [
        call("request_confirmation", tool="log_visit", arguments=VISIT, summary=QUESTION)
    ]


def confirm_visit_script(model, text="Done: the visit is logged."):
    model.script += [call("answer", text=text)]


def start(chat, model):
    ask_for_visit(model)
    return chat("Log a visit to Nordic Tools, they asked for a quote").json()


def test_a_write_is_not_run_but_asked_for_confirmation(chat, model, mcp, context):
    body = start(chat, model)

    assert body["answer"] == QUESTION
    assert body["pending_action"] == {"tool": "log_visit", "summary": QUESTION}
    assert mcp.calls == [] and mcp.visits == []
    fact = context.fact(body["conversation_id"], "pending_action")
    assert fact["value"] == {"tool": "log_visit", "arguments": VISIT, "summary": QUESTION}


def test_confirm_runs_the_tool_with_confirmed_true_and_clears_the_fact(chat, model, mcp, context):
    first = start(chat, model)
    confirm_visit_script(model)

    body = chat("yes", conversation_id=first["conversation_id"], confirm=True).json()

    assert body["answer"] == "Done: the visit is logged."
    assert "pending_action" not in body
    [seen] = mcp.calls
    assert seen.tool == "log_visit" and seen.arguments["confirmed"] is True
    assert [v["customer_id"] for v in mcp.visits] == ["c-001"]
    cleared = context.fact(first["conversation_id"], "pending_action")
    assert cleared["value"] is None and cleared["version"] == 2


def test_confirm_saves_the_visit_summary_and_the_current_customer(chat, model, context):
    first = start(chat, model)
    confirm_visit_script(model)

    chat("yes", conversation_id=first["conversation_id"], confirm=True)

    conversation = context.conversations[first["conversation_id"]]
    [artifact] = conversation.artifacts
    assert artifact["type"] == "visit_summary"
    assert artifact["payload"]["customer_id"] == "c-001"
    assert conversation.facts["current_customer"]["value"] == {"id": "c-001"}


def test_after_confirming_the_orchestrator_can_only_answer(chat, model):
    first = start(chat, model)
    confirm_visit_script(model)
    model.bound.clear()

    chat("yes", conversation_id=first["conversation_id"], confirm=True)

    assert model.bound == [["answer"]]


def test_a_clear_yes_in_words_confirms_too(chat, model, mcp):
    first = start(chat, model)
    model.script += [call("confirm_pending"), call("answer", text="Done.")]

    body = chat("yes, please", conversation_id=first["conversation_id"]).json()

    assert body["answer"] == "Done."
    assert len(mcp.visits) == 1


def test_confirm_without_a_pending_action_runs_nothing(chat, model, mcp):
    first = chat_answer(chat, model)
    model.prompts.clear()

    body = chat("yes", conversation_id=first["conversation_id"], confirm=True).json()

    assert body["answer"] == "There is no pending action to confirm."
    assert model.prompts == [] and mcp.calls == []


def chat_answer(chat, model):
    model.script += [call("answer", text="Hello.")]
    return chat("Hi").json()


def test_the_model_cannot_confirm_when_nothing_is_pending(chat, model, mcp):
    first = chat_answer(chat, model)
    model.script += [call("confirm_pending"), call("answer", text="Nothing to confirm.")]
    model.bound.clear()

    chat("yes", conversation_id=first["conversation_id"])

    assert "confirm_pending" not in model.bound[0]
    assert mcp.calls == []


def test_the_pending_action_is_dropped_by_the_next_turn(chat, model, context):
    first = start(chat, model)
    model.script += [call("answer", text="Stock is fine.")]

    body = chat("What about stock?", conversation_id=first["conversation_id"]).json()

    assert "pending_action" not in body
    assert context.fact(first["conversation_id"], "pending_action")["value"] is None


def test_a_new_question_after_a_cleared_one_is_saved(chat, model, context):
    first = start(chat, model)
    cid = first["conversation_id"]
    confirm_visit_script(model)
    chat("yes", conversation_id=cid, confirm=True)
    ask_for_visit(model)

    body = chat("Log another visit", conversation_id=cid).json()

    assert body["pending_action"]["tool"] == "log_visit"
    fact = context.fact(cid, "pending_action")
    assert fact["value"]["summary"] == QUESTION and fact["version"] == 3


def test_the_model_cannot_choose_a_write_tool_that_does_not_exist(chat, model, context):
    model.script += [
        call("request_confirmation", tool="delete_everything", arguments={}, summary="x")
    ]

    body = chat("Do it").json()

    assert "pending_action" not in body
    assert context.fact(body["conversation_id"], "pending_action") is None


def test_a_lead_follows_the_same_flow(chat, model, mcp):
    lead = {"company_name": "Harbour Fixings", "contact": "Anna Berg", "notes": "Trade fair"}
    model.script += [
        call("request_confirmation", tool="create_lead", arguments=lead, summary="Create it?")
    ]
    first = chat("New lead").json()
    model.script += [call("answer", text="Lead created.")]

    chat("yes", conversation_id=first["conversation_id"], confirm=True)

    assert [lead_["company_name"] for lead_ in mcp.leads] == ["Harbour Fixings"]


def test_a_refused_write_is_reported_and_the_question_is_dropped(chat, model, mcp, context):
    refused = {**VISIT, "customer_id": "c-006"}
    model.script += [
        call("request_confirmation", tool="log_visit", arguments=refused, summary="Log it?")
    ]
    first = chat("Log a visit to c-006").json()
    model.script += [call("answer", text="That customer is not assigned to you.")]

    body = chat("yes", conversation_id=first["conversation_id"], confirm=True).json()

    assert body["answer"] == "That customer is not assigned to you."
    assert mcp.visits == []
    assert (
        json.loads(model.prompts[-1][1].content.split("so far:\n")[1])["error"]["code"]
        == "FORBIDDEN"
    )
    assert context.fact(first["conversation_id"], "pending_action")["value"] is None
