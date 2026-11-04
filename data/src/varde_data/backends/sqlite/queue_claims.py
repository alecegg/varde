"""Atomic queue claims and lease operations for SQLite queue repositories."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.queue_mode_lock import callback_scope, operation
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import Fence, Ready

_ACTIVE = ("claimed", "building", "in_review")


def _time(value: str | None) -> datetime:
    result = datetime.now(UTC) if value is None else datetime.fromisoformat(value)
    if result.tzinfo is None:
        return result.replace(tzinfo=UTC)
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def claim(  # noqa: PLR0913 - mirrors the repository's claim API
    repo,
    queue_name: str,
    *,
    worker: str,
    role: str | None,
    lease_s: float,
    now: str | None,
    ready: Ready | None,
    fence: Fence | None,
    epoch: int | None,
) -> QueueItem | None:
    if lease_s <= 0:
        raise Invalid("lease_s must be positive")
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
            active_rows = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? "
                "AND state IN ('claimed','building','in_review')",
                (queue_name,),
            ).fetchall()
            in_flight = [repo._item(row) for row in active_rows]
            candidates = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND state='queued' "
                "AND (? IS NULL OR role=? OR role IS NULL) "
                "ORDER BY priority, row_order, id",
                (queue_name, role, role),
            ).fetchall()
            for row in candidates:
                item = repo._item(row)
                dependencies = item.depends_on
                if dependencies:
                    placeholders = ",".join("?" for _ in dependencies)
                    states = db.execute(
                        f"SELECT id, state FROM queue_items WHERE queue_name=? "  # noqa: S608 - placeholders are generated from count
                        f"AND id IN ({placeholders})",
                        (queue_name, *dependencies),
                    ).fetchall()
                    if {
                        state_row["id"]
                        for state_row in states
                        if state_row["state"] == "merged"
                    } != set(dependencies):
                        continue
                active_ids = {active.id for active in in_flight}
                if active_ids.intersection(item.serialize_with):
                    continue
                if ready is not None and not ready(item, in_flight):
                    continue
                expires = _iso(_time(now) + timedelta(seconds=lease_s))
                db.execute(
                    "UPDATE queue_items SET state='claimed', claimed_by=?, "
                    "claim_expires_at=?, claim_generation=claim_generation+1, "
                    "claim_epoch=? WHERE queue_name=? AND id=?",
                    (worker, expires, epoch, queue_name, item.id),
                )
                repo._event(db, item.id, worker, "claim", "queued", "claimed")
                return repo._item(
                    db.execute(
                        "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                        (queue_name, item.id),
                    ).fetchone()
                )
            return None


def _owned(
    db: sqlite3.Connection,
    repo,
    queue_name: str,
    item_id: str,
    worker: str,
    generation: int,
) -> QueueItem:
    row = db.execute(
        "SELECT * FROM queue_items WHERE queue_name=? AND id=?", (queue_name, item_id)
    ).fetchone()
    if row is None:
        raise NotFound(item_id)
    item = repo._item(row)
    if (
        item.claimed_by != worker
        or item.claim_generation != generation
        or item.state not in _ACTIVE
    ):
        raise Conflict("queue item lease was lost")
    return item


def _ensure_live(item: QueueItem, now: datetime) -> None:
    if item.claim_expires_at is None or _time(item.claim_expires_at) <= now:
        raise Conflict("queue item lease has expired")


def renew(  # noqa: PLR0913 - mirrors the repository's renew API
    repo,
    queue_name: str,
    item_id: str,
    *,
    worker: str,
    generation: int,
    lease_s: float,
    fence: Fence | None,
) -> QueueItem:
    return _renew(
        repo,
        queue_name,
        item_id,
        worker=worker,
        generation=generation,
        lease_s=lease_s,
        now=None,
        fence=fence,
    )


def _renew(  # noqa: PLR0913 - mirrors the repository's renew API
    repo,
    queue_name: str,
    item_id: str,
    *,
    worker: str,
    generation: int,
    lease_s: float,
    now: str | None,
    fence: Fence | None,
) -> QueueItem:
    if lease_s <= 0:
        raise Invalid("lease_s must be positive")
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
        current = _time(now)
        item = _owned(db, repo, queue_name, item_id, worker, generation)
        _ensure_live(item, current)
        expires = _iso(current + timedelta(seconds=lease_s))
        db.execute(
            "UPDATE queue_items SET claim_expires_at=? WHERE queue_name=? AND id=?",
            (expires, queue_name, item_id),
        )
        repo._event(db, item_id, worker, "renew", item.state, item.state)
        return repo._item(
            db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
        )


def renew_all(
    repo,
    queue_name: str | None,
    *,
    worker: str,
    lease_s: float,
    now: str | None,
    fence: Fence | None,
) -> list[QueueItem]:
    if lease_s <= 0:
        raise Invalid("lease_s must be positive")
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
        current = _time(now)
        if queue_name is None:
            rows = db.execute(
                "SELECT * FROM queue_items WHERE claimed_by=? "
                "AND state IN ('claimed','building','in_review') "
                "ORDER BY queue_name, priority, row_order, id",
                (worker,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND claimed_by=? "
                "AND state IN ('claimed','building','in_review') "
                "ORDER BY priority, row_order, id",
                (queue_name, worker),
            ).fetchall()
        items = [repo._item(row) for row in rows]
        for item in items:
            _ensure_live(item, current)
        expires = _iso(current + timedelta(seconds=lease_s))
        if queue_name is None:
            db.execute(
                "UPDATE queue_items SET claim_expires_at=? WHERE claimed_by=? "
                "AND state IN ('claimed','building','in_review')",
                (expires, worker),
            )
        else:
            db.execute(
                "UPDATE queue_items SET claim_expires_at=? WHERE queue_name=? "
                "AND claimed_by=? AND state IN ('claimed','building','in_review')",
                (expires, queue_name, worker),
            )
        for item in items:
            repo._event(db, item.id, worker, "renew", item.state, item.state)
        return [
            repo._item(
                db.execute(
                    "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                    (item.queue_name, item.id),
                ).fetchone()
            )
            for item in items
        ]


def release(  # noqa: PLR0913 - mirrors the repository's release API
    repo,
    queue_name: str,
    item_id: str,
    *,
    worker: str,
    generation: int,
    to_state: str,
    fence: Fence | None,
) -> QueueItem:
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
        item = _owned(db, repo, queue_name, item_id, worker, generation)
        db.execute(
            "UPDATE queue_items SET state=?, claimed_by=NULL, claim_expires_at=NULL "
            "WHERE queue_name=? AND id=?",
            (to_state, queue_name, item_id),
        )
        repo._event(db, item_id, worker, "release", item.state, to_state)
        return repo._item(
            db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
        )


def finish(  # noqa: PLR0913 - mirrors the slot-fenced completion contract
    repo,
    queue_name: str,
    item_id: str,
    *,
    worker: str,
    generation: int,
    to_state: str,
    follow_ups: tuple[QueueItemInput, ...] = (),
    fence: Fence | None,
) -> tuple[QueueItem, list[QueueItem]]:
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
        claimed_item = _owned(db, repo, queue_name, item_id, worker, generation)
        follow_up_items = []
        for follow_up in follow_ups:
            enqueued = _enqueue_in_transaction(repo, db, follow_up)
            if enqueued is not None:
                follow_up_items.append(enqueued)
        db.execute(
            "UPDATE queue_items SET state=?, claimed_by=NULL, claim_expires_at=NULL "
            "WHERE queue_name=? AND id=?",
            (to_state, queue_name, item_id),
        )
        repo._event(db, item_id, worker, "finish", claimed_item.state, to_state)
        finished = repo._item(
            db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
        )
        return finished, follow_up_items


def _enqueue_in_transaction(
    repo, db: sqlite3.Connection, item: QueueItemInput | None
) -> QueueItem | None:
    if item is None:
        return None
    db.execute(
        "INSERT OR IGNORE INTO queue_items "
        "(id, plan_dir, findings, owned_files, depends_cell, depends_on, "
        "serialize_with, priority, state, planned_at, plan_reviewed_at, "
        "build_started_at, build_done_at, merged_at, role, queue_name, "
        "row_order, extra, followup_depth) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
        "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item.id,
            item.plan_dir,
            item.findings,
            item.owned_files,
            item.depends_cell,
            json.dumps(item.depends_on),
            json.dumps(item.serialize_with),
            item.priority,
            item.state,
            item.planned_at,
            item.plan_reviewed_at,
            item.build_started_at,
            item.build_done_at,
            item.merged_at,
            item.role,
            item.queue_name,
            item.row_order,
            json.dumps(item.extra or {}, sort_keys=True),
            item.followup_depth,
        ),
    )
    row = db.execute(
        "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
        (item.queue_name, item.id),
    ).fetchone()
    if row is None:
        raise NotFound(item.id)
    stored = repo._item(row)
    if db.execute("SELECT changes()").fetchone()[0]:
        repo._event(db, stored.id, "system", "enqueue", None, stored.state)
    elif not _matches_input(stored, item):
        raise Conflict(f"follow-up item {item.id} already exists with different data")
    return stored


def _matches_input(stored: QueueItem, expected: QueueItemInput) -> bool:
    return (
        stored.plan_dir == expected.plan_dir
        and stored.role == expected.role
        and stored.queue_name == expected.queue_name
        and stored.owned_files == expected.owned_files
        and stored.depends_on == expected.depends_on
        and stored.serialize_with == expected.serialize_with
        and stored.extra == (expected.extra or {})
        and stored.followup_depth == expected.followup_depth
    )


def expire(
    repo, now: str | None, *, workers: Sequence[str] | None, fence: Fence | None
) -> list[QueueItem]:
    current = _iso(_time(now))
    with operation(repo._working_path()), repo._connection() as db:
        db.execute("BEGIN IMMEDIATE")
        with callback_scope():
            if fence is not None:
                fence(db)
        sql = (
            "SELECT * FROM queue_items WHERE state IN "
            "('claimed','building','in_review') AND claim_expires_at IS NOT NULL "
            "AND claim_expires_at<=?"
        )
        values: tuple[object, ...] = (current,)
        if workers is not None:
            if not workers:
                return []
            sql += " AND claimed_by IN (" + ",".join("?" for _ in workers) + ")"
            values += tuple(workers)
        rows = db.execute(
            sql + " ORDER BY queue_name, priority, row_order, id", values
        ).fetchall()
        items = [repo._item(row) for row in rows]
        for item in items:
            db.execute(
                "UPDATE queue_items SET state='queued', claimed_by=NULL, "
                "claim_expires_at=NULL, claim_generation=claim_generation+1 "
                "WHERE queue_name=? AND id=?",
                (item.queue_name, item.id),
            )
            repo._event(
                db,
                item.id,
                item.claimed_by or "system",
                "expire",
                item.state,
                "queued",
            )
        return [
            repo._item(
                db.execute(
                    "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                    (item.queue_name, item.id),
                ).fetchone()
            )
            for item in items
        ]
