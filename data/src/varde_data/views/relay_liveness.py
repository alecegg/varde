"""Pure relay liveness calculations over a repository snapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

HEARTBEAT_SECONDS = 30
RUNNER_WAITING_STALE_SECONDS = HEARTBEAT_SECONDS * 4


def elapsed(
    start: datetime, end: datetime, events: Sequence[Mapping[str, object]]
) -> timedelta:
    """Return elapsed time after subtracting sleep gaps within the interval."""
    slept = timedelta()
    for event in events:
        if event.get("event") != "slept":
            continue
        try:
            at = datetime.fromisoformat(str(event["at"]))
            raw_gap = event.get("gap_seconds", 0)
            gap = max(0.0, float(raw_gap)) if isinstance(raw_gap, (int, float)) else 0.0
        except KeyError, TypeError, ValueError:
            continue
        if start < at <= end:
            slept += timedelta(seconds=gap)
    return max(timedelta(), end - start - slept)


def mailman_alive(
    token_id: str, now: datetime, events: Sequence[Mapping[str, object]]
) -> bool:
    """Apply the workflow's waiting and returned age windows to one token."""
    latest = next(
        (event for event in reversed(events) if event.get("token_id") == token_id),
        None,
    )
    if latest is None or latest.get("event") == "ended":
        return False
    try:
        at = datetime.fromisoformat(str(latest["at"]))
    except KeyError, ValueError:
        return False
    age = elapsed(at, now, events)
    return (latest.get("event") == "waiting" and age < timedelta(seconds=90)) or (
        latest.get("event") == "returned" and age < timedelta(minutes=5)
    )
