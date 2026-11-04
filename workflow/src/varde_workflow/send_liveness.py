"""Pure helpers for mailman send-liveness telemetry."""

from datetime import datetime
from typing import Any


def _token_age_s(
    events: list[dict[str, Any]], token: str | None, now: datetime
) -> int | None:
    """Return the age of the latest event for a token, clamped at zero."""
    if not token:
        return None
    latest = next(
        (event for event in reversed(events) if event.get("token_id") == token), None
    )
    if latest is None:
        return None
    timestamp = datetime.fromisoformat(str(latest["at"]))
    return max(0, int((now - timestamp).total_seconds()))
