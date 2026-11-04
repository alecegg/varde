"""Slot-fenced services for pulling work from a role queue."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from varde_data.records.queue import QueueItem
from varde_data.repos.queue import QueueRepository
from varde_data.repos.slots import SlotRepository

from varde_workflow.role_queue_budget import (
    BudgetLimits,
    ResourceSnapshot,
    may_start,
)
from varde_workflow.role_queue_flow import follow_up
from varde_workflow.role_queue_independence import ready as independent_ready


@dataclass(frozen=True)
class PullResult:
    item: QueueItem | None
    reason: str


def pull(  # noqa: PLR0913 - mirrors the role pull contract
    repo: QueueRepository,
    slots: SlotRepository,
    *,
    queue_name: str,
    role: str,
    slot_id: str,
    epoch: int,
    lease_s: int,
    snapshot: ResourceSnapshot | None,
    limits: BudgetLimits,
    now: datetime,
) -> PullResult:
    """Claim one eligible item after checking the global start budget."""
    decision = may_start(snapshot, limits, now)
    if not decision.ok:
        return PullResult(None, decision.reason)

    def eligible(candidate: QueueItem, in_flight: Sequence[QueueItem]) -> bool:
        return candidate.role == role and independent_ready(candidate, in_flight)

    item = slots.claim(
        slot_id,
        epoch=epoch,
        queue_name=queue_name,
        lease_s=lease_s,
        now=now.isoformat(),
        ready=eligible,
    )
    if item is None:
        return PullResult(None, "no independent item ready")
    return PullResult(item, "claimed")


def finish(
    slots: SlotRepository,
    item: QueueItem,
    *,
    slot_id: str,
    epoch: int,
    outcome: str = "done",
) -> list[QueueItem]:
    """Atomically complete a claim and enqueue its follow-up under the slot fence."""
    next_items = follow_up(item, outcome)
    _, enqueued = slots.finish(
        slot_id,
        epoch=epoch,
        queue_name=item.queue_name,
        item_id=item.id,
        generation=item.claim_generation,
        follow_ups=next_items,
    )
    return enqueued


def release(
    slots: SlotRepository,
    *,
    queue_name: str,
    item_id: str,
    slot_id: str,
    epoch: int,
) -> QueueItem:
    """Return an item's claim to the queue through its slot fence."""
    return slots.release(
        slot_id,
        epoch=epoch,
        queue_name=queue_name,
        item_id=item_id,
    )


def renew(
    slots: SlotRepository,
    *,
    slot_id: str,
    epoch: int,
    lease_s: int | None = None,
    now: datetime | None = None,
) -> object:
    """Renew all claims held by this slot using its current epoch."""
    return slots.heartbeat(
        slot_id,
        epoch=epoch,
        lease_s=lease_s,
        now=now.isoformat() if now else None,
    )
