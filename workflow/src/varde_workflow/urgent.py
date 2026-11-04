"""Pure policy for urgent message sends."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
from typing import Any

from varde_data.records.addresses import AddressSlot
from varde_data.roles import role_for_address

URGENT_WINDOW = timedelta(minutes=10)
URGENT_RECIPIENT_LIMIT = 3
URGENT_GLOBAL_LIMIT = 10


def urgent_send_cause(
    sender: str,
    recipient: str,
    events: list[dict[str, Any]],
    now: datetime,
    slots: Iterable[AddressSlot] = (),
) -> str | None:
    """Return a cause when sender or rate policy rejects an urgent send."""
    if not _authorized(sender, recipient, tuple(slots)):
        return "unauthorized sender"
    recent = [
        event
        for event in events
        if event.get("event") == "urgent" and _recent(event.get("at"), now)
    ]
    if (
        sum(event.get("reader") == recipient for event in recent)
        >= URGENT_RECIPIENT_LIMIT
    ):
        return "recipient rate limit exceeded"
    if len(recent) >= URGENT_GLOBAL_LIMIT:
        return "global urgent rate limit exceeded"
    return None


def _authorized(sender: str, recipient: str, slots: tuple[AddressSlot, ...]) -> bool:
    if sender in {"main", "manager"}:
        return True
    role = role_for_address(sender)
    aliases: set[str] = set()
    for slot in slots:
        if sender == slot.slot or sender in slot.aliases:
            aliases.update(slot.aliases)
            if role is None:
                role = (
                    "orchestrator"
                    if slot.slot.startswith("orchestrator-")
                    else role_for_address(slot.slot)
                )
    if role not in {"orchestrator", "reviewer"}:
        return False
    qualifier = _qualifier(sender, role)
    recipient_role = role_for_address(recipient)
    recipient_qualifier = (
        _qualifier(recipient, recipient_role) if recipient_role else ""
    )
    if recipient_qualifier in aliases:
        return True
    return bool(qualifier and qualifier == recipient_qualifier)


def _qualifier(address: str, role: str | None) -> str:
    if not role:
        return ""
    prefix = f"{role}:"
    if address.startswith(prefix):
        return address[len(prefix) :]
    suffix = f"-{role}"
    return address[: -len(suffix)] if address.endswith(suffix) else ""


def _recent(value: Any, now: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        return False
    return now - URGENT_WINDOW <= at <= now
