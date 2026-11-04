"""SQLite implementation of the queue repository's item operations."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Conflict, Invalid, NotFound
from varde_data.queue_mode_lock import operation
from varde_data.records.queue import QueueEvent, QueueItem, QueueItemInput
from varde_data.repos.queue import Fence, Ready
from varde_data.version import Version


class SQLiteQueue:
    """Persist queue items and their state-transition history in SQLite."""

    def __init__(self, path: Path, *, busy_timeout: float = 30) -> None:
        self.path = path
        self.busy_timeout = busy_timeout
        if path.is_file() and path.stat().st_size == 0:
            raise _invalid_database("queue database is empty")
        wal_path = Path(f"{path}-wal")
        shm_path = Path(f"{path}-shm")
        if path.is_file() and shm_path.exists() and not wal_path.exists():
            raise _invalid_database("queue database WAL file is missing")
        with self._connection() as db:
            try:
                configure_store(db)
            except sqlite3.DatabaseError as exc:
                message = "queue database is corrupt"
                if "disk i/o" in str(exc).lower() or "malformed" in str(exc).lower():
                    message = f"queue database is corrupt: {exc}"
                raise _invalid_database(message) from exc

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=self.busy_timeout)
        db.row_factory = sqlite3.Row
        try:
            with closing(db), db:
                yield db
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                from varde_data.errors import Locked

                raise Locked("queue database is busy; retry the operation") from exc
            raise

    def _working_path(self) -> Path:
        if self.path.name == "queue.sqlite3" and self.path.parent.name == "data":
            return self.path.parent.parent.parent
        if self.path.name == "messages.sqlite3" and self.path.parent.name == "inbox":
            return self.path.parent.parent.parent
        return self.path.parent

    def version(self) -> Version:
        """Return a token for the complete queue, plan, and task state."""
        with operation(self._working_path()), self._connection() as db:
            snapshot = tuple(
                tuple(tuple(row) for row in db.execute(query).fetchall())
                for query in (
                    "SELECT * FROM queue_items ORDER BY queue_name, id",
                    "SELECT * FROM queue_events ORDER BY seq",
                    "SELECT * FROM plan_state ORDER BY plan_dir",
                    "SELECT * FROM task_state ORDER BY plan_dir, task_id",
                )
            )
        return Version(snapshot)

    @staticmethod
    def _item(row: sqlite3.Row) -> QueueItem:
        return QueueItem(
            id=row["id"],
            plan_dir=row["plan_dir"],
            findings=row["findings"],
            owned_files=row["owned_files"],
            depends_cell=row["depends_cell"],
            depends_on=tuple(json.loads(row["depends_on"])),
            serialize_with=tuple(json.loads(row["serialize_with"])),
            priority=row["priority"],
            state=row["state"],
            planned_at=row["planned_at"],
            plan_reviewed_at=row["plan_reviewed_at"],
            build_started_at=row["build_started_at"],
            build_done_at=row["build_done_at"],
            merged_at=row["merged_at"],
            role=row["role"],
            queue_name=row["queue_name"],
            row_order=row["row_order"],
            extra=json.loads(row["extra"]),
            followup_depth=row["followup_depth"],
            claimed_by=row["claimed_by"],
            claim_expires_at=row["claim_expires_at"],
            claim_generation=row["claim_generation"],
            claim_epoch=row["claim_epoch"],
        )

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        item_id: str,
        actor: str,
        kind: str,
        old: str | None,
        new: str | None,
    ) -> None:
        db.execute(
            "INSERT INTO queue_events "
            "(item_id, at, actor, kind, from_state, to_state, source) "
            "VALUES (?, ?, ?, ?, ?, ?, 'cli')",
            (item_id, datetime.now(UTC).isoformat(), actor, kind, old, new),
        )

    def enqueue(self, item: QueueItemInput) -> QueueItem:
        with operation(self._working_path()), self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO queue_items "
                "(id, plan_dir, findings, owned_files, depends_cell, depends_on, "
                "serialize_with, priority, state, planned_at, plan_reviewed_at, "
                "build_started_at, build_done_at, merged_at, role, queue_name, "
                "row_order, extra, followup_depth) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
            stored = self._item(row)
            if db.execute("SELECT changes()").fetchone()[0]:
                self._event(db, stored.id, "system", "enqueue", None, stored.state)
            return stored

    def list(
        self,
        queue_name: str | None = None,
        state: str | None = None,
        plan_dir: str | None = None,
    ) -> list[QueueItem]:
        with operation(self._working_path()), self._connection() as db:
            rows = db.execute(
                "SELECT * FROM queue_items "
                "WHERE (? IS NULL OR queue_name=?) "
                "AND (? IS NULL OR state=?) "
                "AND (? IS NULL OR plan_dir=?) "
                "ORDER BY priority, row_order, id",
                (queue_name, queue_name, state, state, plan_dir, plan_dir),
            )
            return [self._item(row) for row in rows]

    def get(self, queue_name: str, item_id: str) -> QueueItem:
        with operation(self._working_path()), self._connection() as db:
            row = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
        if row is None:
            raise NotFound(item_id)
        return self._item(row)

    def transition(
        self,
        queue_name: str,
        item_id: str,
        to_state: str,
        *,
        actor: str,
        expect_state: str | None = None,
        expect_generation: int | None = None,
    ) -> QueueItem:
        with operation(self._working_path()), self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
            if row is None:
                raise NotFound(item_id)
            current = self._item(row)
            if (expect_state is not None and current.state != expect_state) or (
                expect_generation is not None
                and current.claim_generation != expect_generation
            ):
                raise Conflict("queue item changed")
            now = datetime.now(UTC).isoformat()
            timestamps = {
                "in_review": (
                    ("plan_reviewed_at", current.plan_reviewed_at),
                    ("build_done_at", current.build_done_at),
                ),
                "building": (("build_started_at", current.build_started_at),),
                "merged": (("merged_at", current.merged_at),),
            }
            updates = {
                name: now for name, old in timestamps.get(to_state, ()) if old is None
            }
            clear_claim = to_state in {"merged", "blocked", "cancelled", "queued"}
            db.execute(
                "UPDATE queue_items SET state=?, "
                "plan_reviewed_at=COALESCE(plan_reviewed_at, ?), "
                "build_started_at=COALESCE(build_started_at, ?), "
                "build_done_at=COALESCE(build_done_at, ?), "
                "merged_at=COALESCE(merged_at, ?), "
                "claimed_by=CASE WHEN ? THEN NULL ELSE claimed_by END, "
                "claim_expires_at=CASE WHEN ? THEN NULL ELSE claim_expires_at END "
                "WHERE queue_name=? AND id=?",
                (
                    to_state,
                    updates.get("plan_reviewed_at"),
                    updates.get("build_started_at"),
                    updates.get("build_done_at"),
                    updates.get("merged_at"),
                    clear_claim,
                    clear_claim,
                    queue_name,
                    item_id,
                ),
            )
            self._event(db, item_id, actor, "transition", current.state, to_state)
            changed = db.execute(
                "SELECT * FROM queue_items WHERE queue_name=? AND id=?",
                (queue_name, item_id),
            ).fetchone()
            if changed is None:
                raise NotFound(item_id)
            return self._item(changed)

    def claim(  # noqa: PLR0913 - mirrors the queue repository contract
        self,
        queue_name: str,
        *,
        worker: str,
        role: str | None = None,
        lease_s: float,
        now: str | None = None,
        ready: Ready | None = None,
        fence: Fence | None = None,
        epoch: int | None = None,
    ) -> QueueItem | None:
        from varde_data.backends.sqlite.queue_claims import claim

        return claim(
            self,
            queue_name,
            worker=worker,
            role=role,
            lease_s=lease_s,
            now=now,
            ready=ready,
            fence=fence,
            epoch=epoch,
        )

    def renew(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        lease_s: float,
        fence: Fence | None = None,
    ) -> QueueItem:
        from varde_data.backends.sqlite.queue_claims import renew

        return renew(
            self,
            queue_name,
            item_id,
            worker=worker,
            generation=generation,
            lease_s=lease_s,
            fence=fence,
        )

    def renew_all(
        self,
        queue_name: str | None,
        *,
        worker: str,
        lease_s: float,
        now: str | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]:
        from varde_data.backends.sqlite.queue_claims import renew_all

        return renew_all(
            self, queue_name, worker=worker, lease_s=lease_s, now=now, fence=fence
        )

    def release(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str = "queued",
        fence: Fence | None = None,
    ) -> QueueItem:
        from varde_data.backends.sqlite.queue_claims import release

        return release(
            self,
            queue_name,
            item_id,
            worker=worker,
            generation=generation,
            to_state=to_state,
            fence=fence,
        )

    def finish_claim(  # noqa: PLR0913 - mirrors the slot-fenced completion contract
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str,
        follow_ups: tuple[QueueItemInput, ...] = (),
        fence: Fence | None = None,
    ) -> tuple[QueueItem, list[QueueItem]]:
        from varde_data.backends.sqlite.queue_claims import finish

        return finish(
            self,
            queue_name,
            item_id,
            worker=worker,
            generation=generation,
            to_state=to_state,
            follow_ups=follow_ups,
            fence=fence,
        )

    def expire(
        self,
        now: str | None = None,
        *,
        workers: Sequence[str] | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]:
        from varde_data.backends.sqlite.queue_claims import expire

        return expire(self, now, workers=workers, fence=fence)

    def events(self, item_id: str) -> list[QueueEvent]:
        with operation(self._working_path()), self._connection() as db:
            rows = db.execute(
                "SELECT * FROM queue_events WHERE item_id=? ORDER BY seq", (item_id,)
            )
            return [
                QueueEvent(
                    r["seq"],
                    r["item_id"],
                    r["at"],
                    r["actor"],
                    r["kind"],
                    r["from_state"],
                    r["to_state"],
                    r["source"],
                )
                for r in rows
            ]


def _invalid_database(message: str) -> Invalid:
    return Invalid(
        f"{message}; recover with `varde plan store restore` from a backup or "
        "`varde plan store import` from the markdown export"
    )
