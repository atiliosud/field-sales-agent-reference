import json

from fakes.fake_model import call, say

TASK = "List the opportunities of customer c-001."


def lookup_script(model, final="Nordic Tools has two open opportunities."):
    model.script += [
        call("handoff", task=TASK),
        call("list_opportunities", customer_id="c-001"),
        say("c-001 has o-001 and o-002 open."),
        call("answer", text=final),
    ]


def test_lookup_goes_through_the_specialist_and_back(chat, model, mcp, context, token):
    lookup_script(model)

    response = chat("What's open with Nordic Tools?")

    assert response.status_code == 200
    body = response.json()
    assert list(body) == ["conversation_id", "answer"]
    assert body["answer"] == "Nordic Tools has two open opportunities."
    assert [c.tool for c in mcp.calls] == ["list_opportunities"]
    assert len(model.prompts) == 4


def test_mcp_receives_the_token_of_the_user_and_the_conversation_id(chat, model, mcp, token):
    lookup_script(model)

    body = chat("What's open with Nordic Tools?").json()

    [seen] = mcp.calls
    assert seen.authorization == f"Bearer {token}"
    assert seen.session_id == body["conversation_id"]


def test_the_turn_and_the_current_customer_are_saved(chat, model, context):
    lookup_script(model)

    body = chat("What's open with Nordic Tools?").json()

    conversation = context.conversations[body["conversation_id"]]
    assert [(t["role"], t["content"]) for t in conversation.turns] == [
        ("user", "What's open with Nordic Tools?"),
        ("orchestrator", "Nordic Tools has two open opportunities."),
    ]
    assert conversation.facts["current_customer"]["value"] == {"id": "c-001"}


def test_the_orchestrator_can_answer_without_the_specialist(chat, model, mcp):
    model.script += [call("answer", text="Hello! How can I help?")]

    body = chat("Hi").json()

    assert body["answer"] == "Hello! How can I help?"
    assert mcp.calls == []
    assert len(model.prompts) == 1


def test_a_plain_reply_from_the_model_is_taken_as_the_answer(chat, model):
    model.script += [say("Plain text answer.")]

    assert chat("Hi").json()["answer"] == "Plain text answer."


def test_the_orchestrator_has_no_data_tools_and_the_specialist_no_write_tools(chat, model):
    lookup_script(model)

    chat("What's open with Nordic Tools?")

    assert model.bound[0] == ["answer", "handoff", "request_confirmation"]
    assert model.bound[1] == ["get_customer", "find_customer", "list_opportunities", "check_stock"]


def test_the_specialist_gets_the_task_and_not_the_conversation(chat, model, context):
    lookup_script(model)
    first = chat("What's open with Nordic Tools?").json()
    model.script.clear()
    lookup_script(model)
    model.prompts.clear()

    chat("And now?", conversation_id=first["conversation_id"])

    specialist_prompt = model.prompts[1][1].content
    assert TASK in specialist_prompt
    assert '"id": "c-001"' in specialist_prompt
    assert "What's open with Nordic Tools?" not in specialist_prompt
    roles = [role for _, _, role in context.requests if role == "specialist"]
    assert roles


def test_the_orchestrator_prompt_carries_the_history(chat, model):
    lookup_script(model)
    first = chat("What's open with Nordic Tools?").json()
    model.script += [call("answer", text="Same customer.")]
    model.prompts.clear()

    chat("And the stock?", conversation_id=first["conversation_id"])

    prompt = model.prompts[0][1].content
    assert "user: What's open with Nordic Tools?" in prompt
    assert "orchestrator: Nordic Tools has two open opportunities." in prompt


def test_a_customer_of_another_salesperson_is_reported_by_the_tool(chat, model, mcp):
    model.script += [
        call("handoff", task="Get customer c-006."),
        call("get_customer", customer_id="c-006"),
        say("The tool said FORBIDDEN."),
        call("answer", text="That customer is not assigned to you."),
    ]

    body = chat("Tell me about c-006").json()

    assert body["answer"] == "That customer is not assigned to you."
    tool_message = model.prompts[2][-1].content
    assert json.loads(tool_message)["error"]["code"] == "FORBIDDEN"
    assert "Sunvale" not in tool_message


def test_the_specialist_cannot_call_a_write_tool(chat, model, mcp):
    model.script += [
        call("handoff", task="Log a visit."),
        call("log_visit", customer_id="c-001", summary="x", outcome="neutral", confirmed=True),
        say("Not allowed."),
        call("answer", text="I need your confirmation first."),
    ]

    chat("Log a visit")

    assert mcp.calls == []
    assert json.loads(model.prompts[2][-1].content)["error"]["code"] == "FORBIDDEN"


def test_a_tool_error_is_given_to_the_specialist_as_it_is(chat, model, mcp):
    mcp.broken.add("check_stock")
    model.script += [
        call("handoff", task="Stock of P-104."),
        call("check_stock", product_code="P-104"),
        say("The stock tool failed."),
        call("answer", text="I couldn't check the stock."),
    ]

    chat("Stock of P-104?")

    assert json.loads(model.prompts[2][-1].content)["error"]["code"] == "INTERNAL"


def test_the_sales_tools_being_down_does_not_break_the_turn(make_client, model, mcp, token):
    client = make_client(mcp_url="http://127.0.0.1:1/mcp")
    model.script += [
        call("handoff", task="Get customer c-001."),
        call("answer", text="The sales data is unavailable right now."),
    ]

    response = client.post(
        "/chat", json={"message": "Customer c-001?"}, headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    assert "unavailable" in response.json()["answer"]
    assert "sales tools are unavailable" in model.prompts[1][1].content


def test_the_conversation_id_is_kept_between_turns(chat, model):
    model.script += [call("answer", text="One."), call("answer", text="Two.")]

    first = chat("First").json()
    second = chat("Second", conversation_id=first["conversation_id"]).json()

    assert second["conversation_id"] == first["conversation_id"]
