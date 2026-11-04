"""Epoch-fenced queue claim operations for durable slots."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Protocol

from varde_data.errors import Conflict, NotFound
from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import Fence, Ready


class SlotClaimQueue(Protocol):
    """Queue operations used by the SQLite slot claim adapter."""

    def claim(  # noqa: PLR0913 - mirrors the queue claim API
        self,
        queue_name: str,
        *,
        worker: str,
        lease_s: float,
        now: str | None = None,
        ready: Ready | None = None,
        fence: Fence | None = None,
        epoch: int | None = None,
    ) -> QueueItem | None: ...

    def get(self, queue_name: str, item_id: str) -> QueueItem: ...

    def release(
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str = "queued",
        fence: Fence | None = None,
    ) -> QueueItem: ...

    def finish_claim(  # noqa: PLR0913 - mirrors the queue completion contract
        self,
        queue_name: str,
        item_id: str,
        *,
        worker: str,
        generation: int,
        to_state: str,
        follow_ups: tuple[QueueItemInput, ...] = (),
        fence: Fence | None = None,
    ) -> tuple[QueueItem, list[QueueItem]]: ...

    def list(
        self,
        queue_name: str | None = None,
        state: str | None = None,
        plan_dir: str | None = None,
    ) -> list[QueueItem]: ...

    def renew_all(
        self,
        queue_name: str | None,
        *,
        worker: str,
        lease_s: float,
        now: str | None = None,
        fence: Fence | None = None,
    ) -> list[QueueItem]: ...


def slot_fence(
    slot_id: str,
    epoch: int,
    mutate: Callable[[sqlite3.Connection, sqlite3.Row], None] | None = None,
) -> Callable[[sqlite3.Connection | None], None]:
    """Return a queue transaction fence for one live slot epoch."""

    def fence(db: sqlite3.Connection | None) -> None:
        if db is None:
            raise Conflict("slot claim fence requires the SQLite transaction")
        row = db.execute("SELECT * FROM slots WHERE slot_id=?", (slot_id,)).fetchone()
        if row is None:
            raise NotFound(slot_id)
        if row["epoch"] != epoch or row["state"] == "dead":
            raise Conflict(f"slot {slot_id} epoch or state is stale")
        if mutate is not None:
            mutate(db, row)

    return fence


def claim(  # noqa: PLR0913 - mirrors the queue claim API
    queue: SlotClaimQueue,
    slot_id: str,
    *,
    epoch: int,
    queue_name: str,
    lease_s: float,
    now: str | None,
    ready: Ready | None,
) -> QueueItem | None:
    return queue.claim(
        queue_name,
        worker=slot_id,
        lease_s=lease_s,
        now=now,
        ready=ready,
        fence=slot_fence(slot_id, epoch),
        epoch=epoch,
    )


def release(
    queue: SlotClaimQueue,
    slot_id: str,
    *,
    epoch: int,
    queue_name: str,
    item_id: str,
    to_state: str,
) -> QueueItem:
    item = queue.get(queue_name, item_id)
    return queue.release(
        queue_name,
        item_id,
        worker=slot_id,
        generation=item.claim_generation,
        to_state=to_state,
        fence=slot_fence(slot_id, epoch),
    )


def finish(  # noqa: PLR0913 - mirrors the slot completion contract
    queue: SlotClaimQueue,
    slot_id: str,
    *,
    epoch: int,
    queue_name: str,
    item_id: str,
    generation: int,
    follow_ups: tuple[QueueItemInput, ...] = (),
) -> tuple[QueueItem, list[QueueItem]]:
    return queue.finish_claim(
        queue_name,
        item_id,
        worker=slot_id,
        generation=generation,
        to_state="done",
        follow_ups=follow_ups,
        fence=slot_fence(slot_id, epoch),
    )


def claimed(queue: SlotClaimQueue, slot_id: str) -> list[QueueItem]:
    return [
        item
        for item in queue.list()
        if item.claimed_by == slot_id
        and item.state in {"claimed", "building", "in_review"}
    ]


def renew_all(
    queue: SlotClaimQueue,
    slot_id: str,
    *,
    epoch: int,
    lease_s: float,
    now: str | None,
    mutate: Callable[[sqlite3.Connection, sqlite3.Row], None] | None = None,
) -> list[QueueItem]:
    """Atomically mutate a slot and renew its claims across all queues."""
    return queue.renew_all(
        None,
        worker=slot_id,
        lease_s=lease_s,
        now=now,
        fence=slot_fence(slot_id, epoch, mutate),
    )
