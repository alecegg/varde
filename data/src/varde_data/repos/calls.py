"""Backend-neutral API for the CLI call log."""

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol

CALLS_NAME = "cli_calls.jsonl"
CallRecord = dict[str, Any]


class CallsRepository(Protocol):
    """Append and read CLI call rows as JSON objects.

    Rows are stored as given; callers validate them. ``append`` raises on any
    failure so the caller decides how to account for a dropped call.
    """

    def append(self, row: Mapping[str, Any]) -> None: ...

    def read(self) -> list[CallRecord]:
        """Return stored rows in append order; unreadable storage yields none."""
        ...

    def read_strict(self, since: datetime | None = None) -> list[CallRecord]:
        """Return stored rows in append order; raise ``LearnStoreIo`` on failure.

        With ``since``, return only rows whose parsed ``ts`` is at or after it.
        """
        ...


def parse_ts(value: object) -> datetime | None:
    """Parse an ISO timestamp as aware UTC; a naive value is read as UTC."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def rows_since(rows: Iterable[CallRecord], since: datetime | None) -> list[CallRecord]:
    """Keep rows whose parsed ``ts`` is at or after ``since``; all when ``None``."""
    if since is None:
        return list(rows)
    return [row for row in rows if (when := parse_ts(row.get("ts"))) and when >= since]


class MemoryCalls:
    """In-memory calls backend used by repository contract tests."""

    def __init__(self) -> None:
        self._rows: list[CallRecord] = []

    def append(self, row: Mapping[str, Any]) -> None:
        self._rows.append(dict(row))

    def read(self) -> list[CallRecord]:
        return [dict(row) for row in self._rows]

    def read_strict(self, since: datetime | None = None) -> list[CallRecord]:
        return rows_since(self.read(), since)
