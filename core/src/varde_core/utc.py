"""Small, dependency-free UTC datetime helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any


def as_utc(value: datetime) -> datetime:
    """Attach UTC to a naive datetime or convert an aware one to UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def parse_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp, returning None for unsupported or invalid input."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def utc_day(value: datetime) -> date:
    """Return the calendar date after converting the datetime to UTC."""
    return as_utc(value).date()


def window_start(value: datetime, *, days: int = 0, hours: int = 0) -> datetime:
    """Return the UTC-normalized start of a look-back window."""
    return as_utc(value) - timedelta(days=days, hours=hours)


def in_window(value: datetime, start: datetime, end: datetime) -> bool:
    """Whether a datetime falls within an inclusive UTC-normalized window."""
    timestamp = as_utc(value)
    return as_utc(start) <= timestamp <= as_utc(end)
