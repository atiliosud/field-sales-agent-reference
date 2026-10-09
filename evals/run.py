"""Run the eval cases against a running stack and write evals/report.md.

The answer and the pending action come from the agent's API. The tools a turn called come
from its trace in Phoenix (the `call <tool>` spans of the agent), so the stack must be up
with Phoenix. Exits with an error when the pass rate is below the threshold.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from checks import Observed, check_turn

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from chat import YES, ChatError, post_chat  # noqa: E402
from make_token import make_token, read_secret  # noqa: E402

CASES = Path(__file__).resolve().parent / "cases.yaml"
REPORT = Path(__file__).resolve().parent / "report.md"
THRESHOLD = 0.85
TRACE_WAIT_S = 45


@dataclass
class TurnRun:
    say: str
    expect: dict[str, Any]
    answer: str = ""
    pending_tool: str | None = None
    error: str | None = None
    session_trace: str | None = None


@dataclass
class CaseRun:
    id: str
    group: str
    salesperson: str
    turns: list[TurnRun]
    conversation_id: str | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.problems


def run_conversation(url: str, secret: str, case: dict[str, Any]) -> CaseRun:
    run = CaseRun(
        case["id"],
        case["group"],
        case["as"],
        [TurnRun(t["say"], t.get("expect", {})) for t in case["turns"]],
    )
    token = make_token(case["as"], secret)
    pending = False
    for turn in run.turns:
        try:
            reply = post_chat(
                url, token, turn.say, run.conversation_id, pending and turn.say.lower() in YES
            )
        except ChatError as error:
            turn.error = str(error)
            break
        run.conversation_id = reply["conversation_id"]
        turn.answer = reply["answer"]
        turn.pending_tool = reply.get("pending_action", {}).get("tool")
        pending = turn.pending_tool is not None
    return run


def fetch_spans(phoenix: str, since: datetime) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    cursor = None
    for _ in range(50):
        query = {"limit": "1000", "start_time": since.isoformat()}
        if cursor:
            query["cursor"] = cursor
        with urllib.request.urlopen(
            f"{phoenix}/v1/projects/default/spans?{urllib.parse.urlencode(query)}", timeout=30
        ) as response:
            page = json.loads(response.read())
        spans += page["data"]
        cursor = page.get("next_cursor")
        if not cursor:
            break
    return spans


def attach_traces(runs: list[CaseRun], phoenix: str, since: datetime) -> dict[str, list[Any]]:
    """Wait for the `POST /chat` span of every answered turn; return the spans by trace."""
    wanted = {r.conversation_id: sum(1 for t in r.turns if t.answer) for r in runs}
    by_trace: dict[str, list[Any]] = defaultdict(list)
    deadline = time.monotonic() + TRACE_WAIT_S
    while True:
        by_trace.clear()
        roots: dict[str, list[Any]] = defaultdict(list)
        for span in fetch_spans(phoenix, since):
            by_trace[span["context"]["trace_id"]].append(span)
            session = span["attributes"].get("session.id")
            if span["name"] == "POST /chat" and session in wanted:
                roots[session].append(span)
        complete = all(len(roots[s]) >= n for s, n in wanted.items() if s)
        if complete or time.monotonic() > deadline:
            break
        time.sleep(3)
    for run in runs:
        answered = [t for t in run.turns if t.answer]
        ordered = sorted(roots.get(run.conversation_id, []), key=lambda s: s["start_time"])
        for turn, root in zip(answered, ordered, strict=False):
            turn.session_trace = root["context"]["trace_id"]
    return by_trace


def observe(turn: TurnRun, by_trace: dict[str, list[Any]]) -> Observed:
    seen = Observed(turn.answer, turn.pending_tool, traced=turn.session_trace is not None)
    for span in by_trace.get(turn.session_trace or "", []):
        if span["name"].startswith("call "):
            tool = span["name"].removeprefix("call ")
            seen.tools.add(tool)
            if span["status_code"] == "ERROR":
                seen.failed_tools.add(tool)
    return seen


def judge(runs: list[CaseRun], by_trace: dict[str, list[Any]]) -> None:
    for run in runs:
        for number, turn in enumerate(run.turns, 1):
            if turn.error:
                run.problems.append(f"turn {number}: {turn.error}")
                break
            for problem in check_turn(turn.expect, observe(turn, by_trace)):
                run.problems.append(f"turn {number}: {problem}")


def write_report(runs: list[CaseRun], threshold: float, path: Path) -> float:
    passed = sum(r.passed for r in runs)
    rate = passed / len(runs)
    groups: dict[str, list[CaseRun]] = defaultdict(list)
    for run in runs:
        groups[run.group].append(run)
    lines = [
        "# Eval report",
        "",
        f"Run at {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        f"**Pass rate: {passed}/{len(runs)} ({rate:.0%})**. "
        f"Threshold {threshold:.0%}: {'passed' if rate >= threshold else 'FAILED'}.",
        "",
        "| Group | Passed | Cases |",
        "| --- | --- | --- |",
    ]
    lines += [f"| {g} | {sum(r.passed for r in rs)} | {len(rs)} |" for g, rs in groups.items()]
    failed = [r for r in runs if not r.passed]
    if failed:
        lines += ["", "## Failures", ""]
        for run in failed:
            lines.append(f"### {run.id} ({run.group}, {run.salesperson})")
            lines += [f"- {problem}" for problem in run.problems]
            for number, turn in enumerate(run.turns, 1):
                if turn.answer:
                    lines.append(
                        f"- turn {number} said {turn.say!r}; the agent answered: {turn.answer!r}"
                    )
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return rate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--phoenix", default="http://localhost:6006")
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    parser.add_argument("--report", type=Path, default=REPORT)
    parser.add_argument("--only", help="run the cases whose id or group is this")
    args = parser.parse_args()

    cases = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    if args.only:
        cases = [c for c in cases if args.only in (c["id"], c["group"])]
    if not cases:
        print("No cases to run.")
        return 2
    secret = read_secret()
    since = datetime.now(UTC)
    runs = []
    for case in cases:
        runs.append(run_conversation(args.url, secret, case))
        print(f"ran {case['id']}", flush=True)
    try:
        by_trace = attach_traces(runs, args.phoenix, since)
    except (urllib.error.URLError, OSError) as error:
        print(f"Could not read the traces from Phoenix: {error}")
        return 2
    judge(runs, by_trace)
    rate = write_report(runs, args.threshold, args.report)
    for run in runs:
        print(("PASS " if run.passed else "FAIL ") + run.id)
        for problem in run.problems:
            print(f"     {problem}")
    print(f"Pass rate {rate:.0%} (threshold {args.threshold:.0%}). Report: {args.report}")
    return 0 if rate >= args.threshold else 1


if __name__ == "__main__":
    sys.exit(main())
