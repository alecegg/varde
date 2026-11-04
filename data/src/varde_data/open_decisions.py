"""The one definition of an open decision, shared by the mailbox and threads."""

from __future__ import annotations

from typing import Any

OPEN_DECISION_KINDS = frozenset({"needs-user", "needs-decision", "merge-ready"})


def open_decision_items(
    items: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    acknowledged_ids: set[str],
    bound_addresses: set[str],
    concluded_addresses: set[str],
) -> list[dict[str, Any]]:
    """Return unanswered needs-user messages for current, unconcluded senders."""
    latest_replies: dict[str, str] = {}
    for message in messages:
        if message.get("from") != "main":
            continue
        recipient = message.get("to")
        timestamp = message.get("ts")
        if isinstance(recipient, str) and isinstance(timestamp, str):
            latest_replies[recipient] = max(
                timestamp, latest_replies.get(recipient, "")
            )

    open_items = []
    for item in items:
        sender = item.get("sender")
        timestamp = item.get("ts")
        if (
            item.get("kind") not in OPEN_DECISION_KINDS
            or item.get("state") != "pending"
            or not isinstance(sender, str)
            or sender not in bound_addresses
            or sender in concluded_addresses
            or str(item.get("msg_id", "")) in acknowledged_ids
        ):
            continue
        reply_at = latest_replies.get(sender)
        if reply_at and isinstance(timestamp, str) and reply_at > timestamp:
            continue
        open_items.append(item)
    return open_items
