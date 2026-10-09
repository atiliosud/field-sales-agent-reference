"""The rules of an eval case. Plain string and set checks, so a result is repeatable."""

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Observed:
    """What happened in one turn."""

    answer: str
    pending_tool: str | None
    tools: set[str] = field(default_factory=set)
    failed_tools: set[str] = field(default_factory=set)
    traced: bool = True


def normalise(text: str) -> str:
    """Lower case, without thousands separators, so 18,500 matches 18500."""
    return re.sub(r"(?<=\d)[, ](?=\d{3}\b)", "", text).lower()


def check_turn(expect: dict[str, Any], seen: Observed) -> list[str]:
    """Return what went wrong in the turn; an empty list means it passed."""
    problems: list[str] = []
    answer = normalise(seen.answer)

    def mentions(text: str) -> bool:
        return normalise(text) in answer

    for text in expect.get("answer_all", []):
        if not mentions(text):
            problems.append(f"the answer does not contain {text!r}")
    any_of = expect.get("answer_any", [])
    if any_of and not any(mentions(text) for text in any_of):
        problems.append(f"the answer contains none of {any_of}")
    for text in expect.get("answer_none", []):
        if mentions(text):
            problems.append(f"the answer contains {text!r}")
    for pattern in expect.get("answer_none_regex", []):
        if re.search(pattern, seen.answer, re.IGNORECASE):
            problems.append(f"the answer matches /{pattern}/")

    if "pending" in expect:
        wanted = None if expect["pending"] == "none" else expect["pending"]
        if seen.pending_tool != wanted:
            problems.append(f"pending action is {seen.pending_tool!r}, expected {wanted!r}")

    if any(key in expect for key in ("tools", "no_tools", "failed_tools")) and not seen.traced:
        problems.append("the turn has no trace in Phoenix, so its tool calls are unknown")
        return problems
    for tool in expect.get("tools", []):
        if tool not in seen.tools:
            problems.append(f"{tool} was not called")
    for tool in expect.get("no_tools", []):
        if tool in seen.tools:
            problems.append(f"{tool} was called")
    for tool in expect.get("failed_tools", []):
        if tool not in seen.failed_tools:
            problems.append(f"{tool} did not fail")
    return problems
