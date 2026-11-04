"""Pure planning for the one-time migration of legacy inbox messages."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

URGENT = {"needs-user", "blocked", "merge-ready"}
FINISHED = {"completed", "cancelled"}
MARKER_ID = "legacy-migration-v1"


def plan_migration(
    messages: list[dict[str, Any]],
    deliveries: list[dict[str, str]],
    plans: dict[str, str],
    now: datetime,
) -> list[dict[str, Any]]:
    """Return append and delivery-log records for a single migration pass."""
    if any(event.get("message_id") == MARKER_ID for event in deliveries):
        return []
    cutoff = now - timedelta(hours=48)
    replay: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    for message in reversed(messages):
        try:
            timestamp = datetime.fromisoformat(str(message["ts"]))
        except KeyError, ValueError:
            timestamp = datetime.min.replace(tzinfo=UTC)
        message_id = str(message.get("id", ""))
        delivered = any(
            event.get("message_id") == message_id
            and event.get("reader") == str(message.get("to", ""))
            and event.get("event") in {"delivered", "acked", "dropped", "legacy"}
            for event in deliveries
        )
        if (
            message.get("kind") in URGENT
            and cutoff <= timestamp <= now
            and not delivered
        ):
            replay.append(message)
            continue
        if (
            message.get("kind") == "info"
            and plans.get(str(message.get("to", ""))) in FINISHED
        ):
            marks.append(
                _mark(message_id, "dropped", now, str(message.get("to", "main")))
            )
        elif timestamp < cutoff:
            marks.append(
                _mark(message_id, "legacy", now, str(message.get("to", "main")))
            )
    replay.sort(key=lambda item: str(item.get("ts", "")), reverse=True)
    copies = [
        {
            **message,
            "id": _new_id(str(message.get("id", "")), now),
            "to": "main",
            "legacy": True,
        }
        for message in replay[:30]
    ]
    marks.append(_mark(MARKER_ID, "legacy", now))
    return [{"append": copies, "marks": marks}]


def _new_id(message_id: str, now: datetime) -> str:
    seed = f"{message_id}:{now.astimezone(UTC).isoformat()}".encode()
    return "m-" + hashlib.sha256(seed).hexdigest()[:8]


def _mark(
    message_id: str, event: str, now: datetime, reader: str = "main"
) -> dict[str, Any]:
    return {
        "message_id": message_id,
        "reader": reader,
        "session": "",
        "via": "migration",
        "event": event,
        "at": now.astimezone(UTC).isoformat().replace("+00:00", "Z"),
    }
