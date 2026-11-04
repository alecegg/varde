"""Pure evaluator for native-cutover gate evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from varde_runner.plugins.paseo import HARNESS_TO_PASEO_PROVIDER

PASEO_BACKENDS = frozenset((*HARNESS_TO_PASEO_PROVIDER.values(), "paseo"))


def _time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_paseo_session(session: dict[str, Any]) -> bool:
    if session.get("backend") in PASEO_BACKENDS:
        return True
    try:
        reference = json.loads(session.get("ref", "{}"))
    except TypeError, ValueError:
        return False
    return isinstance(reference, dict) and reference.get("provider") == "paseo"


def check_gate(
    sessions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    bindings: list[dict[str, Any]],
    restart_at: datetime,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict[str, Any]:
    """Summarize Paseo residue and observed recovery after a runner restart."""
    restart = _time(restart_at)
    start = _time(since) if since is not None else restart
    end = _time(until) if until is not None else None
    if restart is None or start is None:
        raise ValueError("gate times must be valid timestamps")
    if end is not None and start > end:
        raise ValueError("--since must not be later than --until")

    session_by_id = {str(row.get("id", "")): row for row in sessions}
    paseo_ids = {
        session_id
        for session_id, row in session_by_id.items()
        if _is_paseo_session(row)
    }
    running_at_restart = {
        str(row.get("id", ""))
        for row in sessions
        if row.get("status") == "running"
        and (_time(row.get("created_at")) or datetime.max.replace(tzinfo=UTC))
        <= restart
    }

    resumes: set[str] = set()
    parked: set[str] = set()
    for event in events:
        timestamp = _time(event.get("created_at"))
        session_id = str(event.get("session_id", ""))
        if timestamp is None or timestamp <= restart:
            continue
        if start is not None and timestamp < start:
            continue
        if end is not None and timestamp > end:
            continue
        if event.get("kind") == "resume":
            resumes.add(session_id)
        elif event.get("kind") == "parked":
            parked.add(session_id)

    paseo_bindings = sum(
        str(binding.get("session_id", "")) in paseo_ids for binding in bindings
    )
    running_resumed = running_at_restart & resumes
    result = {
        "paseo_sessions": len(paseo_ids),
        "paseo_bindings": paseo_bindings,
        "running_at_restart": len(running_at_restart),
        "resumed_after_restart": len(resumes),
        "running_resumed_after_restart": len(running_resumed),
        "parked_after_restart": len(parked),
    }
    result["verdict_inputs_ok"] = (
        result["paseo_sessions"] == 0
        and result["paseo_bindings"] == 0
        and result["running_resumed_after_restart"] == result["running_at_restart"]
        and result["parked_after_restart"] == 0
    )
    return result
