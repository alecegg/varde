"""SQLite backend for the CLI call log (``cli_calls`` in ``learn.sqlite3``)."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.learn_schema import connect
from varde_data.errors import LearnStoreIo
from varde_data.learn_store_mode import (
    StaleGeneration,
    learn_db_path,
    read_learn_mode,
    writer_target,
)
from varde_data.repos.calls import CallRecord, parse_ts, rows_since

APPEND_LOCK_TIMEOUT = 0.5
APPEND_BUSY_MS = 500
COLUMNS = ("ts", "command", "status", "duration_s", "session", "guardrail", "arg")
INSERT = (
    "INSERT INTO cli_calls (ts, command, status, duration_s, session, guardrail, arg) "
    "VALUES (?, ?, ?, ?, ?, ?, ?)"
)
SELECT = (
    "SELECT ts, command, status, duration_s, session, guardrail, arg FROM cli_calls"
)
STATUSES = ("success", "failure", "blocked")
CallTuple = tuple[str, str, str, float, "str | None", "str | None", "str | None"]


def typed_row(row: object) -> CallTuple | None:
    """Return the column values for a valid call row, or ``None`` when invalid.

    Mirrors the reader's row rules (``varde_learn.loop.calls._valid_row``): non-empty
    string ``ts`` and ``command``, a known ``status``, a finite non-negative
    non-bool number ``duration_s``, string-or-null ``session``, string
    ``guardrail`` and ``arg`` when present, and a ``ts`` that parses as ISO.
    """
    if not isinstance(row, Mapping):
        return None
    ts, command, status = row.get("ts"), row.get("command"), row.get("status")
    if not (isinstance(ts, str) and ts and isinstance(command, str) and command):
        return None
    if status not in STATUSES or parse_ts(ts) is None:
        return None
    duration = _duration(row.get("duration_s"))
    session, guardrail, arg = (row.get(key) for key in ("session", "guardrail", "arg"))
    present = [row[key] for key in ("guardrail", "arg") if key in row]
    names_ok = all(isinstance(item, str) for item in present)
    if (
        duration is None
        or not names_ok
        or not (session is None or isinstance(session, str))
    ):
        return None
    return (ts, command, status, duration, session, guardrail, arg)


def _duration(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) and number >= 0 else None


def record_from_columns(values: tuple[Any, ...]) -> CallRecord:
    """Rebuild a call dict from column values; NULL guardrail and arg are omitted."""
    row = dict(zip(COLUMNS, values, strict=True))
    return {
        key: value
        for key, value in row.items()
        if value is not None or key == "session"
    }


def coarse_cutoff(since: datetime) -> str:
    """Date text a day before ``since``: a safe lower bound for ``ts`` text."""
    return (since.astimezone(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")


class SqliteCalls:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.generation = read_learn_mode(root).generation

    def append(self, row: Mapping[str, Any]) -> None:
        values = typed_row(row)
        if values is None:
            raise ValueError("call row fails the typed layout rules")
        with writer_target(
            self.root,
            "calls",
            held_generation=self.generation,
            timeout=APPEND_LOCK_TIMEOUT,
        ) as (backend, generation):
            if backend != "sqlite":
                raise StaleGeneration(
                    f"calls moved to {backend} at generation {generation}; "
                    "reopen the store"
                )
            with closing(connect(self.root)) as db:
                db.execute(f"PRAGMA busy_timeout = {APPEND_BUSY_MS}")
                with db:
                    db.execute(INSERT, values)

    def read(self) -> list[CallRecord]:
        try:
            return self.read_strict()
        except LearnStoreIo:
            return []

    def read_strict(self, since: datetime | None = None) -> list[CallRecord]:
        path = learn_db_path(self.root)
        if not path.is_file():
            return []
        query, params = SELECT, ()
        if since is not None:
            query, params = f"{SELECT} WHERE ts >= ?", (coarse_cutoff(since),)
        try:
            with closing(connect(self.root)) as db:
                rows = [
                    record_from_columns(values)
                    for values in db.execute(f"{query} ORDER BY id", params)
                ]
        except sqlite3.Error as error:
            raise LearnStoreIo("read CLI calls", path, OSError(str(error))) from error
        return rows_since(rows, since)
