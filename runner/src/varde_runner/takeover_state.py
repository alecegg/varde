"""Pure takeover lease and sender policy."""

from __future__ import annotations

from datetime import UTC, datetime

HEARTBEAT_SECONDS = 20
LEASE_SECONDS = 90


def expired(heartbeat_at: str, now: datetime) -> bool:
    heartbeat = datetime.fromisoformat(heartbeat_at)
    if heartbeat.tzinfo is None:
        heartbeat = heartbeat.replace(tzinfo=UTC)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    return (current - heartbeat).total_seconds() >= LEASE_SECONDS


def should_queue(*, held: bool, lease_expired: bool, sender_class: str) -> bool:
    return held and not lease_expired and sender_class == "other"
