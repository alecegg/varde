"""Backend-neutral slot repository contract."""

from dataclasses import dataclass
from typing import Any, Protocol

from varde_data.records.queue import QueueItem, QueueItemInput
from varde_data.repos.queue import Ready
from varde_data.slot_model import Slot, SlotEvent


@dataclass(frozen=True)
class ReclaimReport:
    """Outcome of one stale-slot reclamation pass."""

    reclaimed: tuple[str, ...]
    skipped: tuple[str, ...]
    expired_items: tuple[QueueItem, ...]


class SlotRepository(Protocol):
    """Operations supported by the durable slot store."""

    def register(
        self,
        slot_id: str,
        *,
        plan_id: str,
        role: str,
        agent_ref: str,
        session_id: str | None = None,
        lease_s: int = 300,
    ) -> Slot: ...

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
    ) -> Slot: ...

    def claim(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        lease_s: int,
        now: str | None = None,
        ready: Ready | None = None,
    ) -> QueueItem | None: ...

    def release(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        item_id: str,
        to_state: str = "queued",
    ) -> QueueItem: ...

    def finish(
        self,
        slot_id: str,
        *,
        epoch: int,
        queue_name: str,
        item_id: str,
        generation: int,
        follow_ups: tuple[QueueItemInput, ...] = (),
    ) -> tuple[QueueItem, list[QueueItem]]: ...

    def claimed(self, slot_id: str) -> list[QueueItem]: ...

    def reclaim_stale(self, now: str | None = None) -> ReclaimReport: ...

    def park(self, slot_id: str, *, epoch: int, now: str | None = None) -> Slot: ...
    def unpark(
        self,
        slot_id: str,
        *,
        epoch: int,
        lease_s: int | None = None,
        now: str | None = None,
    ) -> Slot: ...

    def handoff(
        self,
        slot_id: str,
        *,
        epoch: int,
        checkpoint: str,
        now: str | None = None,
    ) -> Slot: ...

    def replace(
        self,
        slot_id: str,
        *,
        new_agent_ref: str,
        new_session_id: str | None = None,
        lease_s: int | None = None,
        actor: str = "system",
        now: str | None = None,
    ) -> Slot: ...

    def by_session(self, session_id: str) -> Slot | None: ...

    def show(self, slot_id: str) -> Slot: ...
    def events(self, slot_id: str) -> list[SlotEvent]: ...
    def handoff_record(self, slot_id: str) -> dict[str, Any]: ...
