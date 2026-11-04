"""Retention for the CLI call log: a used-through watermark and pruning."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.learn_schema import connect
from varde_data.errors import LearnStoreIo
from varde_data.learn_store_mode import learn_db_path
from varde_data.repos.calls import parse_ts

WATERMARK_KEY = "calls_used_through"
BATCH = 5000
_COARSE_FORMAT = "%Y-%m-%dT%H:%M:%S"


def mark_used(root: Path, ts: str) -> None:
    """Raise the watermark to ``ts`` (UTC ISO text); it never lowers."""
    when = parse_ts(ts)
    if when is None:
        raise ValueError(f"watermark is not an ISO timestamp: {ts!r}")
    # a future-dated ts must not lift the watermark past unread rows
    when = min(when, datetime.now(UTC))
    with closing(connect(root)) as db, db:
        db.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = MAX(value, excluded.value)",
            (WATERMARK_KEY, when.isoformat()),
        )


def usage(root: Path) -> dict[str, Any]:
    """Return the watermark and the oldest stored ``ts`` (``None`` when absent)."""
    with closing(connect(root)) as db:
        return {
            "watermark": _watermark(db),
            "oldest_ts": _oldest_ts(db),
        }


def prune(
    root: Path, days: int, now: datetime, *, dry_run: bool = False
) -> dict[str, Any]:
    """Delete rows older than ``days`` and older than the watermark.

    SQL picks a coarse superset of candidates; each is then checked by its
    parsed ``ts``. Deletes run in batches, each committed on its own.
    """
    cutoff = now.astimezone(UTC) - timedelta(days=days)
    with closing(connect(root)) as db:
        mark = _watermark(db)
        limit = _limit(cutoff, mark)
        ids = _prunable_ids(db, limit) if limit is not None else []
        if not dry_run:
            _delete_batches(db, ids)
        free = db.execute("PRAGMA freelist_count").fetchone()[0]
    return {
        "deleted": 0 if dry_run else len(ids),
        "would_delete": len(ids) if dry_run else None,
        "cutoff": cutoff.isoformat(),
        "watermark": mark,
        "free_pages": free,
        "dry_run": dry_run,
    }


def vacuum(root: Path) -> dict[str, int]:
    """Rebuild the database file to return free pages; report its size change."""
    path = learn_db_path(root)
    before = path.stat().st_size
    try:
        with closing(connect(root)) as db:
            db.execute("VACUUM")
    except sqlite3.Error as error:
        raise LearnStoreIo(
            "vacuum learn database", path, OSError(str(error))
        ) from error
    return {"bytes_before": before, "bytes_after": path.stat().st_size}


def _watermark(db: sqlite3.Connection) -> str | None:
    found = db.execute("SELECT value FROM meta WHERE key = ?", (WATERMARK_KEY,))
    row = found.fetchone()
    return None if row is None else str(row[0])


def _oldest_ts(db: sqlite3.Connection) -> str | None:
    """The smallest ``ts`` text (a coarse order when formats are mixed)."""
    found = db.execute("SELECT MIN(ts) FROM cli_calls").fetchone()
    return None if found is None or found[0] is None else str(found[0])


def _limit(cutoff: datetime, mark: str | None) -> datetime | None:
    """Rows strictly older than this are prunable; ``None`` deletes nothing."""
    used = parse_ts(mark) if mark is not None else None
    return None if used is None else min(cutoff, used)


def _prunable_ids(db: sqlite3.Connection, limit: datetime) -> list[int]:
    coarse = (limit + timedelta(days=1)).strftime(_COARSE_FORMAT)
    candidates = db.execute("SELECT id, ts FROM cli_calls WHERE ts < ?", (coarse,))
    return [
        row_id
        for row_id, text in candidates
        if (when := parse_ts(text)) is not None and when < limit
    ]


def _delete_batches(db: sqlite3.Connection, ids: list[int]) -> None:
    for start in range(0, len(ids), BATCH):
        batch = json.dumps(ids[start : start + BATCH])
        with db:
            db.execute(
                "DELETE FROM cli_calls WHERE id IN (SELECT value FROM json_each(?))",
                (batch,),
            )
