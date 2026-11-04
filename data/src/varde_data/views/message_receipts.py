"""Delivery state derived from message and delivery records."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

_DELIVERED_VIA = {"assumed", "hook", "receipt", "read", "cli"}
_READ_VIA = {"hook", "receipt", "read", "cli"}
UNDELIVERED_DEADLINE = timedelta(minutes=10)
NO_HOLDER_DEADLINE = timedelta(minutes=2)


def message_receipts(
    messages: list[dict[str, Any]], deliveries: list[dict[str, Any]], now: datetime
) -> dict[str, dict[str, Any]]:
    """Return each message's highest state, timestamps, and recipient age."""
    by_id = {str(row.get("id")): row for row in messages if row.get("id")}
    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for event in deliveries:
        history.setdefault(
            (str(event.get("message_id", "")), str(event.get("reader", ""))), []
        ).append(event)
    replies: dict[str, list[dict[str, Any]]] = {}
    for message in messages:
        reply_to = message.get("reply_to") or message.get("in_reply_to")
        if isinstance(reply_to, str):
            replies.setdefault(reply_to, []).append(message)

    result = {}
    for message_id, message in by_id.items():
        recipient = str(message.get("to", ""))
        sent = _time(message.get("ts"))
        timestamps: dict[str, str | None] = {
            "queued": str(message.get("ts")) if message.get("ts") else None,
            "pushed": None,
            "delivered": None,
            "read": None,
            "answered": None,
        }
        state = "queued"
        for event in history.get((message_id, recipient), []):
            kind = event.get("event")
            at = event.get("at")
            if not isinstance(at, str):
                continue
            via = event.get("via")
            if kind == "pushed":
                timestamps["pushed"] = at
                state = _later(state, "pushed")
            elif kind == "delivered" and via in _DELIVERED_VIA:
                timestamps["delivered"] = at
                state = _later(state, "delivered")
                if via in _READ_VIA:
                    timestamps["read"] = at
                    state = "read"
            elif kind == "acked":
                timestamps["read"] = at
                state = "read"
        answer = next(
            (
                reply
                for reply in replies.get(message_id, [])
                if sent is not None
                and reply.get("from") == recipient
                and (reply_at := _time(reply.get("ts"))) is not None
                and reply_at > sent
            ),
            None,
        )
        if answer is not None:
            timestamps["answered"] = str(answer.get("ts"))
            state = "answered"
        failures = [
            event
            for event in history.get((message_id, recipient), [])
            if event.get("event") in {"failed", "skipped-busy", "target-gone"}
            and isinstance(event.get("reason"), str)
        ]
        latest_failure = max(
            failures, key=lambda event: str(event.get("at", "")), default=None
        )
        delivered_as = next(
            (
                event.get("delivered_as", event.get("reason"))
                for event in reversed(history.get((message_id, recipient), []))
                if event.get("event") in {"pushed", "skipped-busy"}
                and event.get("delivered_as", event.get("reason"))
                in {"steer", "interrupt", "queued"}
            ),
            None,
        )
        result[message_id] = {
            "state": state,
            "last_reason": latest_failure.get("reason") if latest_failure else None,
            "delivered_as": delivered_as,
            "timestamps": timestamps,
            "recipients": {
                recipient: {
                    "state": state,
                    "undelivered_age_seconds": (
                        max(0.0, (now.astimezone(UTC) - sent).total_seconds())
                        if state in {"queued", "pushed"} and sent is not None
                        else None
                    ),
                }
            },
        }
    return result


def undelivered_deadlines(
    messages: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    now: datetime,
    *,
    excluded_addresses: set[str] | frozenset[str] = frozenset(),
    unbound_addresses: set[str] | frozenset[str] = frozenset(),
) -> dict[str, datetime]:
    """Return escalation deadlines for queued or pushed messages with valid times."""
    receipts = message_receipts(messages, deliveries, now)
    completed = {
        event.get("source_id") or event.get("message_id")
        for event in deliveries
        if event.get("event") in {"escalated", "dropped"}
    }
    deadlines: dict[str, datetime] = {}
    for message in messages:
        message_id = message.get("id")
        recipient = message.get("to")
        if (
            not isinstance(message_id, str)
            or message_id in completed
            or not isinstance(recipient, str)
            or recipient == "main"
            or recipient in excluded_addresses
        ):
            continue
        recipient_state = (
            receipts.get(message_id, {}).get("recipients", {}).get(recipient, {})
        )
        if recipient_state.get("state") not in {"queued", "pushed"}:
            continue
        sent = _time(message.get("ts"))
        if sent is not None:
            deadline = (
                NO_HOLDER_DEADLINE
                if recipient in unbound_addresses
                else UNDELIVERED_DEADLINE
            )
            deadlines[message_id] = sent + deadline
    return deadlines


def _later(current: str, new: str) -> str:
    order = {"queued": 0, "pushed": 1, "delivered": 2, "read": 3, "answered": 4}
    return new if order[new] > order[current] else current


def _time(value: object) -> datetime | None:
    if not isinstance(value, (str, datetime)) or not value:
        return None
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
