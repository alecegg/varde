"""Reclaim stale durable slots and their expired queue claims."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Conflict, NotFound, WrongMode
from varde_data.queue_mode_lock import operation
from varde_data.records.queue import QueueItem
from varde_data.repos.slots import ReclaimReport

PARK_LEASE_S = 4 * 60 * 60


def _timestamp(value: str | None) -> datetime:
    parsed = datetime.fromisoformat(value) if value else datetime.now(UTC)
    return (
        parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
    )


def _stale(db: sqlite3.Connection, slot: sqlite3.Row, now: str) -> bool:
    if slot["state"] == "dead":
        return False
    current = datetime.fromisoformat(now)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if slot["state"] == "parked":
        updated = _timestamp(slot["updated_at"])
        return (current - updated).total_seconds() >= PARK_LEASE_S
    claims = db.execute(
        "SELECT 1 FROM queue_items WHERE claimed_by=? AND state IN "
        "('claimed','building','in_review') LIMIT 1",
        (slot["slot_id"],),
    ).fetchone()
    if claims is not None:
        return (
            db.execute(
                "SELECT 1 FROM queue_items WHERE claimed_by=? AND state IN "
                "('claimed','building','in_review') AND claim_expires_at<=? LIMIT 1",
                (slot["slot_id"], now),
            ).fetchone()
            is not None
        )
    last_progress = _timestamp(slot["last_progress_at"] or slot["updated_at"])
    return (current - last_progress).total_seconds() >= slot["lease_s"]


def reclaim_stale(
    path: Path, working_dir: Path, *, now: str | None = None, busy_timeout: float = 30
) -> ReclaimReport:
    """Atomically mark stale slots dead and expire their lapsed claims."""
    current = _timestamp(now).isoformat()
    reclaimed: list[str] = []
    skipped: list[str] = []
    expired: list[QueueItem] = []
    with operation(working_dir) as mode:
        if mode != "sqlite":
            raise WrongMode("slot repository requires SQLite store mode")
        with closing(sqlite3.connect(path, timeout=busy_timeout)) as db, db:
            db.row_factory = sqlite3.Row
            configure_store(db)
            candidates = [
                row["slot_id"]
                for row in db.execute("SELECT * FROM slots ORDER BY slot_id")
                if _stale(db, row, current)
            ]

    queue = SQLiteQueue(path, busy_timeout=busy_timeout)
    for slot_id in candidates:

        def fence(db: sqlite3.Connection | None, *, slot_id: str = slot_id) -> None:
            if db is None:
                raise Conflict("slot reclaim fence requires the SQLite transaction")
            row = db.execute(
                "SELECT * FROM slots WHERE slot_id=?", (slot_id,)
            ).fetchone()
            if row is None:
                raise NotFound(slot_id)
            if not _stale(db, row, current):
                raise Conflict(f"slot {slot_id} became live before reclaim")
            db.execute(
                "UPDATE slots SET state='dead', updated_at=? WHERE slot_id=?",
                (current, slot_id),
            )
            detail = '{"reason":"stale lease"}'
            for kind in ("dead", "reclaim"):
                db.execute(
                    "INSERT INTO slot_events (slot_id, at, actor, kind, epoch, detail) "
                    "VALUES (?, ?, 'system', ?, ?, ?)",
                    (slot_id, current, kind, row["epoch"], detail),
                )

        try:
            expired.extend(queue.expire(current, workers=[slot_id], fence=fence))
        except Conflict as exc:
            if "became live" not in str(exc):
                raise
            skipped.append(slot_id)
        else:
            reclaimed.append(slot_id)
    return ReclaimReport(tuple(reclaimed), tuple(skipped), tuple(expired))
