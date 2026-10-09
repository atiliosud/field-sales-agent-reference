import asyncio
import json

import pytest

from agent_service.config import Settings
from agent_service.graph import ROUTING_TOOLS
from agent_service.harness import Harness
from agent_service.mcp_client import ToolRunner
from agent_service.prompts import load_prompt


def runner(mcp_url, token, conversation_id="conv-1", harness=None):
    harness = harness or Harness(6, 10, 60)
    return ToolRunner(mcp_url, token, conversation_id, harness), harness


def test_a_write_tool_never_gets_confirmed_from_the_model(mcp_url, mcp, token):
    tools, _ = runner(mcp_url, token)
    arguments = {"customer_id": "c-001", "summary": "x", "outcome": "neutral", "confirmed": True}

    result = asyncio.run(tools.call("log_visit", arguments))

    assert not result.ok
    assert json.loads(result.text)["error"]["code"] == "CONFIRMATION_REQUIRED"
    assert mcp.visits == []


def test_a_write_tool_runs_when_the_orchestrator_confirms(mcp_url, mcp, token):
    tools, harness = runner(mcp_url, token)
    arguments = {"customer_id": "c-001", "summary": "x", "outcome": "neutral"}

    result = asyncio.run(tools.call("log_visit", arguments, confirmed=True))

    assert result.ok and len(mcp.visits) == 1
    assert harness.write.status == "done"
    assert tools.customer == {"id": "c-001"}
    assert tools.visit["outcome"] == "neutral"


def test_every_call_carries_the_token_and_the_conversation_id(mcp_url, mcp, token):
    tools, _ = runner(mcp_url, token, "conv-42")

    asyncio.run(tools.call("get_customer", {"customer_id": "c-001"}))

    [seen] = mcp.calls
    assert seen.authorization == f"Bearer {token}"
    assert seen.session_id == "conv-42"


def test_a_bad_token_is_reported_by_the_server_not_hidden(mcp_url, mcp):
    tools, _ = runner(mcp_url, "not-a-token")

    result = asyncio.run(tools.call("get_customer", {"customer_id": "c-001"}))

    assert not result.ok
    assert json.loads(result.text)["error"]["code"] == "UNAUTHENTICATED"


def test_the_customer_name_is_kept_from_get_customer(mcp_url, mcp, token):
    tools, _ = runner(mcp_url, token)

    asyncio.run(tools.call("get_customer", {"customer_id": "c-001"}))

    assert tools.customer == {"id": "c-001", "name": "Nordic Tools"}


def test_a_failed_read_does_not_change_the_customer(mcp_url, mcp, token):
    tools, _ = runner(mcp_url, token)

    asyncio.run(tools.call("get_customer", {"customer_id": "c-006"}))

    assert tools.customer is None


def test_a_tool_that_is_not_available_is_an_invalid_input(mcp_url, mcp, token):
    tools, _ = runner(mcp_url, token)

    result = asyncio.run(tools.call("delete_everything", {}))

    assert json.loads(result.text)["error"]["code"] == "INVALID_INPUT"


@pytest.mark.parametrize("name", ["orchestrator.v1", "orchestrator.v2", "specialist.v1"])
def test_prompts_are_loaded_by_version(name):
    prompt = load_prompt(name)

    assert (prompt.id, prompt.version) == tuple(name.split("."))
    assert prompt.system and prompt.input


@pytest.mark.parametrize("name", ["orchestrator.v1", "orchestrator.v2"])
def test_every_routing_tool_has_a_description_in_the_orchestrator_prompt(name):
    assert set(load_prompt(name).tools) == set(ROUTING_TOOLS)


def test_v2_names_every_field_of_the_write_tools():
    system = load_prompt("orchestrator.v2").system

    for field in ("customer_id", "summary", "outcome", "company_name", "contact", "notes"):
        assert field in system
    for outcome in ("positive", "neutral", "negative", "follow_up"):
        assert outcome in system


def test_an_unknown_prompt_version_is_an_error():
    with pytest.raises(FileNotFoundError):
        load_prompt("orchestrator.v9")


def test_settings_have_the_defaults_of_the_contract(monkeypatch):
    monkeypatch.setenv("MCP_URL", "http://mcp-sales:8001/mcp")
    monkeypatch.setenv("CONTEXT_URL", "http://context:8002")
    for name in ("HARNESS_MAX_STEPS", "HARNESS_TOOL_TIMEOUT_S", "HARNESS_TURN_TIMEOUT_S"):
        monkeypatch.delenv(name, raising=False)

    settings = Settings.from_env()

    assert (settings.max_steps, settings.tool_timeout_s, settings.turn_timeout_s) == (6, 10, 60)
    assert settings.prompt_orchestrator == "orchestrator.v2"
