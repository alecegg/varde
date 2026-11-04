"""Expiry rules: pure functions over entries and a date."""

from __future__ import annotations

from datetime import date

from varde_learn.memory.entry import Entry


def is_past(valid_until: str, today: date) -> bool:
    """True when `valid_until` is a valid ISO date before `today`."""
    if not valid_until:
        return False
    try:
        return date.fromisoformat(valid_until) < today
    except ValueError:
        return False


def is_expired(entry: Entry, today: date) -> bool:
    return is_past(entry.valid_until, today)


def expired_report(entries: list[Entry], today: date) -> list[Entry]:
    """Active entries past `valid_until`, oldest expiry first.

    Nothing is deleted: a human retires each one.
    """
    expired = [e for e in entries if e.status == "active" and is_expired(e, today)]
    return sorted(expired, key=lambda e: (e.valid_until, e.scope, e.id))
