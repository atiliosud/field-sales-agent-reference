import re
from pathlib import Path

import pytest
import yaml

import run
from checks import Observed, check_turn, normalise

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8"))
GROUPS = {"lookup", "stock", "write", "out-of-scope", "security"}
EXPECT_KEYS = {
    "tools",
    "no_tools",
    "failed_tools",
    "answer_all",
    "answer_any",
    "answer_none",
    "answer_none_regex",
    "pending",
}
WRITE_TOOLS = ["log_visit", "create_lead"]


def seen(answer="", pending=None, tools=(), failed=(), traced=True):
    return Observed(answer, pending, set(tools), set(failed), traced)


def test_thousands_separators_and_case_do_not_matter():
    assert normalise("About 18,500 EUR") == "about 18500 eur"
    assert normalise("P-104: 184 units") == "p-104: 184 units"
    assert normalise("40, 184") == "40, 184"


def test_answer_rules():
    expect = {
        "answer_all": ["18500"],
        "answer_any": ["quote", "demo"],
        "answer_none": ["24000"],
        "answer_none_regex": [r"\d+\s?%"],
    }

    assert check_turn(expect, seen("18,500 EUR, send a quote")) == []
    assert len(check_turn(expect, seen("nothing here"))) == 2
    assert check_turn(expect, seen("18,500 quote 24,000")) == ["the answer contains '24000'"]
    assert check_turn(expect, seen("18,500 quote, 10% off")) == [r"the answer matches /\d+\s?%/"]


def test_pending_rule():
    assert check_turn({"pending": "log_visit"}, seen(pending="log_visit")) == []
    assert check_turn({"pending": "none"}, seen()) == []
    assert check_turn({"pending": "none"}, seen(pending="log_visit"))
    assert check_turn({"pending": "log_visit"}, seen())


def test_tool_rules():
    expect = {"tools": ["check_stock"], "no_tools": ["log_visit"], "failed_tools": ["get_customer"]}

    assert (
        check_turn(expect, seen(tools=["check_stock", "get_customer"], failed=["get_customer"]))
        == []
    )
    assert len(check_turn(expect, seen(tools=["log_visit"]))) == 3
    assert check_turn({"tools": ["a"]}, seen(tools=["a"])) == []
    assert check_turn({"tools": ["a"]}, seen()) == ["a was not called"]
    assert check_turn({"no_tools": ["a"]}, seen(tools=["a"])) == ["a was called"]
    assert check_turn({"failed_tools": ["a"]}, seen(tools=["a"])) == ["a did not fail"]


def test_a_turn_without_a_trace_fails_its_tool_rules_but_not_its_answer_rules():
    assert check_turn({"answer_all": ["ok"]}, seen("ok", traced=False)) == []
    [problem] = check_turn({"no_tools": ["log_visit"]}, seen(traced=False))
    assert "no trace" in problem


def test_there_are_about_25_cases_in_the_five_groups():
    assert 24 <= len(CASES) <= 30
    assert {case["group"] for case in CASES} == GROUPS
    for group in GROUPS:
        assert sum(case["group"] == group for case in CASES) >= 4


def test_cases_are_well_formed():
    assert len({case["id"] for case in CASES}) == len(CASES)
    for case in CASES:
        assert case["as"] in {"sp-001", "sp-002"}
        assert case["turns"]
        for turn in case["turns"]:
            assert turn["say"]
            assert set(turn.get("expect", {})) <= EXPECT_KEYS, case["id"]


def test_identifiers_are_the_ones_of_the_contract():
    text = (ROOT / "evals" / "cases.yaml").read_text(encoding="utf-8")

    customers = set(re.findall(r"\bc-\d{3}\b", text))
    products = set(re.findall(r"\bP-\d{3}\b", text))

    assert customers <= {f"c-{n:03d}" for n in range(1, 11)}
    assert products <= {f"P-{n}" for n in range(101, 121)} | {"P-204"}


def test_no_case_expects_a_write_in_its_first_turn():
    for case in CASES:
        first = case["turns"][0].get("expect", {}).get("tools", [])
        assert not set(first) & set(WRITE_TOOLS), case["id"]


def test_the_security_cases_check_that_nothing_of_the_other_salesperson_is_said():
    for case in CASES:
        if case["group"] == "security":
            expects = [turn.get("expect", {}) for turn in case["turns"]]
            assert any("answer_none" in e or "failed_tools" in e for e in expects), case["id"]


def span(name, trace="t1", status="UNSET", session="s1", start="2026-01-01T10:00:00+00:00"):
    return {
        "name": name,
        "status_code": status,
        "start_time": start,
        "context": {"trace_id": trace},
        "attributes": {"session.id": session},
    }


def test_tools_of_a_turn_come_from_the_call_spans_of_its_trace():
    turn = run.TurnRun("hi", {}, answer="ok", session_trace="t1")
    by_trace = {
        "t1": [
            span("POST /chat"),
            span("call get_customer", status="ERROR"),
            span("call check_stock"),
            span("get_customer"),
        ],
        "t2": [span("call log_visit", trace="t2")],
    }

    observed = run.observe(turn, by_trace)

    assert observed.tools == {"get_customer", "check_stock"}
    assert observed.failed_tools == {"get_customer"}
    assert observed.traced


def test_a_turn_without_a_trace_is_not_traced():
    assert not run.observe(run.TurnRun("hi", {}, answer="ok"), {}).traced


def test_the_report_gives_the_rate_and_the_failures(tmp_path):
    good = run.CaseRun("a", "lookup", "sp-001", [run.TurnRun("q", {}, answer="fine")])
    bad = run.CaseRun("b", "stock", "sp-001", [run.TurnRun("q2", {}, answer="wrong")])
    bad.problems.append("turn 1: the answer does not contain '184'")
    report = tmp_path / "report.md"

    rate = run.write_report([good, bad], 0.85, report)

    text = report.read_text(encoding="utf-8")
    assert rate == 0.5
    assert "1/2 (50%)" in text and "FAILED" in text
    assert "### b (stock, sp-001)" in text and "'184'" in text
    assert "### a" not in text


def test_the_threshold_is_85_per_cent():
    assert run.THRESHOLD == 0.85


@pytest.mark.parametrize("passed, expected", [(22, True), (21, False)])
def test_22_of_25_cases_pass_the_gate_and_21_do_not(passed, expected, tmp_path):
    runs = [run.CaseRun(str(n), "lookup", "sp-001", []) for n in range(25)]
    for failing in runs[passed:]:
        failing.problems.append("x")

    rate = run.write_report(runs, run.THRESHOLD, tmp_path / "r.md")

    assert (rate >= run.THRESHOLD) is expected
