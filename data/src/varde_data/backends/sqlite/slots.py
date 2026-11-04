"""SQLite implementation of the durable slot repository."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.backends.sqlite.slot_claims import (
    SlotClaimQueue,
    renew_all,
)
from varde_data.backends.sqlite.slot_claims import (
    claim as claim_slot,
)
from varde_data.backends.sqlite.slot_claims import (
    claimed as claimed_items,
)
from varde_data.backends.sqlite.slot_claims import finish as finish_claim
from varde_data.backends.sqlite.slot_claims import (
    release as release_slot,
)
from varde_data.backends.sqlite.slot_reclaim import (
    PARK_LEASE_S,
    ReclaimReport,
    reclaim_stale,
)
from varde_data.errors import Conflict, Invalid, NotFound, WrongMode
from varde_data.queue_mode_lock import operation
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import Ready
from varde_data.slot_handoff import build_handoff_record
from varde_data.slot_model import Slot, SlotEvent


class SQLiteSlots:
    """Persist slot state and lifecycle events in the queue database."""

    def __init__(
        self, path: Path, working_dir: Path, *, busy_timeout: float = 30
    ) -> None:
        self.path = path
        self.working_dir = working_dir
        self.busy_timeout = busy_timeout
        with operation(self.working_dir) as mode:
            if mode != "sqlite":
                raise WrongMode("slot repository requires SQLite store mode")
            with self._connection() as db:
                configure_store(db)

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

    @contextmanager
    def _store(self) -> Iterator[None]:
        with operation(self.working_dir) as mode:
            if mode != "sqlite":
                raise WrongMode("slot repository requires SQLite store mode")
            yield

    @staticmethod
    def _now(now: str | None) -> str:
        return now or datetime.now(UTC).isoformat()

    @staticmethod
    def _slot(row: sqlite3.Row) -> Slot:
        return Slot(
            slot_id=row["slot_id"],
            plan_id=row["plan_id"],
            role=row["role"],
            lease_s=row["lease_s"],
            agent_ref=row["agent_ref"],
            session_id=row["session_id"],
            state=row["state"],
            epoch=row["epoch"],
            last_progress_at=row["last_progress_at"],
            last_progress_note=row["last_progress_note"],
            context_tokens=row["context_tokens"],
            turn_count=row["turn_count"],
            checkpoint=row["checkpoint"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _event(  # noqa: PLR0913, PLR0917
        db: sqlite3.Connection,
        slot_id: str,
        at: str,
        actor: str,
        kind: str,
        epoch: int,
        detail: dict[str, object] | None = None,
    ) -> None:
        db.execute(
            "INSERT INTO slot_events (slot_id, at, actor, kind, epoch, detail) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (slot_id, at, actor, kind, epoch, json.dumps(detail, sort_keys=True)),
        )

    def _get(self, db: sqlite3.Connection, slot_id: str) -> Slot:
        row = db.execute("SELECT * FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
        if row is None:
            raise NotFound(slot_id)
        return self._slot(row)

    def _queue(self) -> SlotClaimQueue:
        return cast("SlotClaimQueue", SQLiteQueue(self.path))

    def _renew_claims(
        self,
        slot_id: str,
        *,
        epoch: int,
        lease_s: int,
        now: str | None,
        mutate: Callable[[sqlite3.Connection, sqlite3.Row], None],
    ) -> None:
        renew_all(
            self._queue(),
            slot_id,
            epoch=epoch,
            lease_s=lease_s,
            now=now,
            mutate=mutate,
        )

    def claim(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        lease_s: int,
        now: str | None = None,
        ready: Ready | None = None,
    ) -> QueueItem | None:
        return claim_slot(
            self._queue(),
            slot_id,
            epoch=epoch,
            queue_name=queue_name,
            lease_s=lease_s,
            now=now,
            ready=ready,
        )

    def release(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        item_id: str,
        to_state: str = "queued",
    ) -> QueueItem:
        return release_slot(
            self._queue(),
            slot_id,
            epoch=epoch,
            queue_name=queue_name,
            item_id=item_id,
            to_state=to_state,
        )

    def finish(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        item_id: str,
        generation: int,
        follow_ups: tuple[QueueItemInput, ...] = (),
    ) -> tuple[QueueItem, list[QueueItem]]:
        return finish_claim(
            self._queue(),
            slot_id,
            epoch=epoch,
            queue_name=queue_name,
            item_id=item_id,
            generation=generation,
            follow_ups=follow_ups,
        )

    def claimed(self, slot_id: str) -> list[QueueItem]:
        return claimed_items(self._queue(), slot_id)

    def reclaim_stale(self, now: str | None = None) -> ReclaimReport:
        """Mark stale slots dead and release their expired claims."""
        return reclaim_stale(
            self.path,
            self.working_dir,
            now=now,
            busy_timeout=self.busy_timeout,
        )

    def _check_epoch(self, slot: Slot, epoch: int) -> None:
        if slot.epoch != epoch or slot.state == "dead":
            raise Conflict(f"slot {slot.slot_id} epoch or state is stale")

    def register(
        self,
        slot_id: str,
        *,
        plan_id: str,
        role: str,
        agent_ref: str,
        session_id: str | None = None,
        lease_s: int = 300,
    ) -> Slot:
        if lease_s <= 0:
            raise Invalid("slot lease_s must be positive")
        now = self._now(None)
        with self._store(), self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT * FROM slots WHERE slot_id=?", (slot_id,)
            ).fetchone()
            if existing is not None:
                slot = self._slot(existing)
                if (
                    slot.plan_id == plan_id
                    and slot.role == role
                    and slot.agent_ref == agent_ref
                    and slot.state != "dead"
                ):
                    return slot
                raise Conflict(f"slot {slot_id} already belongs to another agent")
            db.execute(
                "INSERT INTO slots (slot_id, plan_id, role, lease_s, agent_ref, "
                "session_id, state, epoch, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'active', 1, ?)",
                (slot_id, plan_id, role, lease_s, agent_ref, session_id, now),
            )
            self._event(db, slot_id, now, agent_ref, "register", 1)
            return self._get(db, slot_id)

    def heartbeat(  # noqa: PLR0913 - mirrors the slot heartbeat contract
        self,
        slot_id: str,
        *,
        epoch: int,
        progress_note: str | None = None,
        context_tokens: int | None = None,
        turn_count: int | None = None,
        lease_s: int | None = None,
        now: str | None = None,
    ) -> Slot:
        at = self._now(now)
        if lease_s is not None and lease_s <= 0:
            raise Invalid("lease_s must be positive")
        slot = self.show(slot_id)
        self._check_epoch(slot, epoch)
        effective_lease_s = slot.lease_s if lease_s is None else lease_s
        updated: list[Slot] = []

        def mutate(db: sqlite3.Connection, row: sqlite3.Row) -> None:
            db.execute(
                "UPDATE slots SET last_progress_at=?, last_progress_note=?, "
                "context_tokens=COALESCE(?, context_tokens), "
                "turn_count=COALESCE(?, turn_count), lease_s=?, updated_at=? "
                "WHERE slot_id=?",
                (
                    at,
                    progress_note,
                    context_tokens,
                    turn_count,
                    effective_lease_s,
                    at,
                    slot_id,
                ),
            )
            self._event(
                db,
                slot_id,
                at,
                row["agent_ref"] or "system",
                "heartbeat",
                epoch,
            )
            updated.append(self._get(db, slot_id))

        self._renew_claims(
            slot_id,
            epoch=epoch,
            lease_s=effective_lease_s,
            now=at,
            mutate=mutate,
        )
        return updated[0]

    def park(self, slot_id: str, *, epoch: int, now: str | None = None) -> Slot:
        at = self._now(now)
        slot = self.show(slot_id)
        self._check_epoch(slot, epoch)
        if slot.state == "parked":
            return slot
        if slot.state != "active":
            raise Conflict(f"cannot park slot in {slot.state} state")
        updated: list[Slot] = []

        def mutate(db: sqlite3.Connection, row: sqlite3.Row) -> None:
            if row["state"] != "active":
                raise Conflict(f"cannot park slot in {row['state']} state")
            db.execute(
                "UPDATE slots SET state='parked', updated_at=? WHERE slot_id=?",
                (at, slot_id),
            )
            self._event(db, slot_id, at, row["agent_ref"] or "system", "park", epoch)
            updated.append(self._get(db, slot_id))

        self._renew_claims(
            slot_id, epoch=epoch, lease_s=PARK_LEASE_S, now=at, mutate=mutate
        )
        return updated[0]

    def unpark(
        self,
        slot_id: str,
        *,
        epoch: int,
        lease_s: int | None = None,
        now: str | None = None,
    ) -> Slot:
        if lease_s is not None and lease_s <= 0:
            raise Invalid("lease_s must be positive")
        at = self._now(now)
        slot = self.show(slot_id)
        self._check_epoch(slot, epoch)
        effective_lease_s = slot.lease_s if lease_s is None else lease_s
        updated: list[Slot] = []

        def mutate(db: sqlite3.Connection, row: sqlite3.Row) -> None:
            if row["state"] not in {"active", "parked"}:
                raise Conflict(f"cannot unpark slot in {row['state']} state")
            db.execute(
                "UPDATE slots SET state='active', lease_s=?, updated_at=? "
                "WHERE slot_id=?",
                (effective_lease_s, at, slot_id),
            )
            if row["state"] == "parked":
                self._event(
                    db, slot_id, at, row["agent_ref"] or "system", "unpark", epoch
                )
            updated.append(self._get(db, slot_id))

        self._renew_claims(
            slot_id,
            epoch=epoch,
            lease_s=effective_lease_s,
            now=at,
            mutate=mutate,
        )
        return updated[0]

    def by_session(self, session_id: str) -> Slot | None:
        with self._store(), self._connection() as db:
            row = db.execute(
                "SELECT * FROM slots WHERE session_id=? "
                "ORDER BY CASE state WHEN 'active' THEN 0 WHEN 'parked' THEN 1 "
                "WHEN 'handed_off' THEN 2 ELSE 3 END, "
                "updated_at DESC, slot_id LIMIT 1",
                (session_id,),
            ).fetchone()
            return None if row is None else self._slot(row)

    def handoff(
        self,
        slot_id: str,
        *,
        epoch: int,
        checkpoint: str,
        now: str | None = None,
    ) -> Slot:
        """Store the checkpoint and hand the slot off in one fenced transaction."""
        at = self._now(now)
        with self._store(), self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            slot = self._get(db, slot_id)
            self._check_epoch(slot, epoch)
            db.execute(
                "UPDATE slots SET checkpoint=?, state='handed_off', updated_at=? "
                "WHERE slot_id=?",
                (checkpoint, at, slot_id),
            )
            self._event(
                db,
                slot_id,
                at,
                slot.agent_ref or "system",
                "handoff",
                epoch,
                {"checkpoint": True},
            )
            return self._get(db, slot_id)

    def replace(
        self,
        slot_id: str,
        *,
        new_agent_ref: str,
        new_session_id: str | None = None,
        lease_s: int | None = None,
        actor: str = "system",
        now: str | None = None,
    ) -> Slot:
        at = self._now(now)
        if lease_s is not None and lease_s <= 0:
            raise Invalid("lease_s must be positive")
        slot = self.show(slot_id)
        if slot.state == "dead":
            raise Conflict(f"cannot replace dead slot {slot_id}")
        expected_epoch = slot.epoch
        epoch = expected_epoch + 1
        effective_lease_s = slot.lease_s if lease_s is None else lease_s
        updated: list[Slot] = []

        def mutate(db: sqlite3.Connection, row: sqlite3.Row) -> None:
            db.execute(
                "UPDATE slots SET agent_ref=?, session_id=?, state='active', epoch=?, "
                "lease_s=?, last_progress_at=?, updated_at=? WHERE slot_id=?",
                (
                    new_agent_ref,
                    new_session_id,
                    epoch,
                    effective_lease_s,
                    at,
                    at,
                    slot_id,
                ),
            )
            db.execute(
                "UPDATE queue_items SET claim_epoch=? WHERE claimed_by=? "
                "AND state IN ('claimed','building','in_review')",
                (epoch, slot_id),
            )
            self._event(
                db,
                slot_id,
                at,
                actor,
                "replace",
                epoch,
                {"old_agent_ref": row["agent_ref"], "new_agent_ref": new_agent_ref},
            )
            updated.append(self._get(db, slot_id))

        self._renew_claims(
            slot_id,
            epoch=expected_epoch,
            lease_s=effective_lease_s,
            now=at,
            mutate=mutate,
        )
        return updated[0]

    def show(self, slot_id: str) -> Slot:
        with self._store(), self._connection() as db:
            return self._get(db, slot_id)

    def events(self, slot_id: str) -> list[SlotEvent]:
        with self._store(), self._connection() as db:
            rows = db.execute(
                "SELECT * FROM slot_events WHERE slot_id=? ORDER BY seq", (slot_id,)
            ).fetchall()
            return [
                SlotEvent(
                    seq=row["seq"],
                    slot_id=row["slot_id"],
                    at=row["at"],
                    actor=row["actor"],
                    kind=row["kind"],
                    epoch=row["epoch"],
                    detail=json.loads(row["detail"]) if row["detail"] else None,
                )
                for row in rows
            ]

    def handoff_record(self, slot_id: str) -> dict[str, object]:
        with self._store(), self._connection() as db:
            slot = self._get(db, slot_id)
            rows = (
                db.execute(
                    "SELECT * FROM slots WHERE plan_id=? AND slot_id<>? "
                    "ORDER BY slot_id",
                    (slot.plan_id, slot_id),
                ).fetchall()
                if slot.role == "orchestrator"
                else []
            )
            children = [self._slot(row) for row in rows]
        items = self.claimed(slot_id)
        child_items = [
            item for child in children for item in self.claimed(child.slot_id)
        ]
        events = self.events(slot_id)
        task_states = SQLitePlanState(self.path).task_states(slot.plan_id)
        return build_handoff_record(
            slot, items, events, task_states, children, child_items
        )
