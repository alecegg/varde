"""Heuristic role and plan attribution for session spend rows."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

_PLAN = re.compile(
    r"(?:plan[s]?[ /`]+(?:id )?`?|plans/)"
    r"(20\d\d-\d\d-\d\d-[a-z0-9-]+|[a-z][a-z0-9]+(?:-[a-z0-9]+)+)"
)


def role(first_prompt: str, is_subagent: bool) -> str:
    """Classify a session from its opening prompt, using lightweight clues."""
    prompt = first_prompt.lower()
    head = prompt[:260]
    if is_subagent:
        return "in-session subagent"
    if "orchestrator" in head:
        return "orchestrator"
    if "probe" in head[:60] or "wake-drill" in head[:60]:
        return "probe"
    if re.search(r"review|fact-check|re-check|re-checker", head):
        return "reviewer/checker"
    if "planner" in head or "varde-plan " in head[:200]:
        return "planner"
    if "friction cycle" in head or "varde-learn" in head:
        return "learn"
    if (
        "builder" in head
        or "developer_instructions" in head
        or "ui-craft" in head
        or head[:30].startswith("fixes")
        or head.startswith("fix mode")
    ):
        return "builder"
    return "main/interactive/other"


def plan(first_prompt: str) -> str | None:
    """Extract the first recognizable plan identifier from an opening prompt."""
    match = _PLAN.search(first_prompt[:1500])
    return match.group(1) if match else None


def attribute(sessions: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Enrich sessions with role/plan, inheriting both for linked subagents.

    Rows may use either the descriptive fields or the shorter field names from
    the source analysis: ``first_prompt``/``first``, ``is_subagent``/``sub``,
    and ``session_id``/``sid``. Subagents link to their parent through
    ``parent_session_id`` or the shared ``session_id`` used by Claude traces.
    """
    rows = [dict(item) for item in sessions]
    parents: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not _is_subagent(item):
            session_id = _session_id(item)
            if session_id:
                parents[session_id] = item
            item["role"] = role(_first_prompt(item), False)
            item["plan"] = plan(_first_prompt(item))

    for item in rows:
        if not _is_subagent(item):
            continue
        item["role"] = role(_first_prompt(item), True)
        parent_id = str(item.get("parent_session_id") or _session_id(item))
        parent = parents.get(parent_id) if parent_id else None
        item["plan"] = (parent.get("plan") if parent else None) or plan(
            _first_prompt(item)
        )
        item["parent_role"] = parent.get("role") if parent else None
    unclassified_rows = [
        item
        for item in rows
        if item["role"] == "main/interactive/other"
        or (
            _is_subagent(item)
            and item["parent_role"] in (None, "main/interactive/other")
        )
    ]
    return {
        "sessions": rows,
        "unclassified": len(unclassified_rows),
        "unclassified_rows": unclassified_rows,
    }


def _first_prompt(item: dict[str, Any]) -> str:
    value = item.get("first_prompt", item.get("first", ""))
    return value if isinstance(value, str) else ""


def _is_subagent(item: dict[str, Any]) -> bool:
    return bool(item.get("is_subagent", item.get("sub", False)))


def _session_id(item: dict[str, Any]) -> str:
    return str(item.get("session_id", item.get("sid", "")))
