"""Pure grouping for mailbox decisions into dashboard threads."""

from __future__ import annotations

import re
from typing import Any

_PLAN_IN_WATCH_BODY = re.compile(
    r"\b(?:needs-decision|needs-user|blocked)\s+([\w./-]+)", re.IGNORECASE
)
_NEEDS_USER_KINDS = frozenset(
    {"needs-user", "needs-decision", "permission", "merge-ready"}
)


def is_user_facing_message(message: dict[str, Any]) -> bool:
    """Keep actionable requests and messages addressed to the Runner user."""
    kind = message.get("kind")
    recipient = str(message.get("to", "")).lower()
    sender = str(message.get("from", message.get("sender", ""))).lower()
    return (
        kind in _NEEDS_USER_KINDS
        or message.get("type") == "approval"
        or recipient == "user"
        or sender == "user"
        or bool(message.get("reply"))
    )


def group_threads(
    decisions: list[dict[str, Any]], open_ids: set[str] | None = None
) -> list[dict[str, Any]]:
    open_ids = open_ids or set()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for decision in decisions:
        thread_id = _thread_id(decision)
        grouped.setdefault(thread_id, []).append(decision)

    threads = []
    for thread_id, rows in grouped.items():
        latest = max(rows, key=_timestamp)
        plan_id = _plan_id(latest)
        sender = latest.get("source_agent") or latest.get("sender") or ""
        open_rows = [row for row in rows if _decision_id(row) in open_ids]
        threads.append(
            {
                "thread_id": thread_id,
                "plan_id": plan_id,
                "sender": sender,
                "title": latest.get("title") or latest.get("asked") or "",
                "open_count": len(open_rows),
                "stale_count": sum(
                    row.get("state") == "pending" and _decision_id(row) not in open_ids
                    for row in rows
                ),
                "last_open_ts": max((_timestamp(row) for row in open_rows), default=""),
                "last_ts": _timestamp(latest),
                "last_preview": _preview(latest),
                "user_message": any(
                    str(row.get("to", "")).lower() == "user"
                    or str(row.get("from", row.get("sender", ""))).lower() == "user"
                    or bool(row.get("reply"))
                    for row in rows
                ),
                "decision_ids": [
                    _decision_id(row) for row in sorted(rows, key=_timestamp)
                ],
            }
        )
    return sorted(threads, key=lambda thread: thread["last_ts"], reverse=True)


def open_needs_you_count(threads: list[dict[str, Any]]) -> int:
    """Count open user-facing items, excluding stale or resolved rows."""
    count = 0
    for thread in threads:
        open_count = thread.get("open_count")
        if isinstance(open_count, int) and open_count > 0:
            count += open_count
    return count


def _thread_id(decision: dict[str, Any]) -> str:
    plan_id = _plan_id(decision)
    if plan_id:
        return f"plan:{plan_id}"
    sender = decision.get("source_agent") or decision.get("sender")
    if sender:
        return f"sender:{sender}"
    message_id = decision.get("msg_id") or decision.get("decision_id") or id(decision)
    return f"message:{message_id}"


def _plan_id(decision: dict[str, Any]) -> str | None:
    plan_id = decision.get("plan_id")
    if plan_id:
        return str(plan_id)
    if (decision.get("source_agent") or decision.get("sender")) == "varde-watch":
        match = _PLAN_IN_WATCH_BODY.search(_preview(decision))
        if match:
            return match.group(1)
    return None


def _decision_id(decision: dict[str, Any]) -> str:
    return str(decision.get("decision_id") or decision.get("msg_id") or "")


def _timestamp(decision: dict[str, Any]) -> str:
    value = decision.get("updated_at") or decision.get("ts") or ""
    return value if isinstance(value, str) else str(value)


def _preview(decision: dict[str, Any]) -> str:
    value = (
        decision.get("latest_answer_body")
        or decision.get("answer_body")
        or decision.get("reply")
        or decision.get("body")
        or ""
    )
    return value if isinstance(value, str) else str(value)
