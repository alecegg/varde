"""Pure slot records and lifecycle rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

SlotState = Literal["active", "parked", "handed_off", "dead"]
SLOT_STATES: frozenset[SlotState] = frozenset(
    {"active", "parked", "handed_off", "dead"}
)

_TRANSITIONS: dict[SlotState, frozenset[SlotState]] = {
    "active": frozenset({"parked", "handed_off", "dead"}),
    "parked": frozenset({"active", "handed_off", "dead"}),
    "handed_off": frozenset({"active", "dead"}),
    "dead": frozenset(),
}


@dataclass(frozen=True)
class Slot:
    slot_id: str
    plan_id: str
    role: str
    lease_s: int
    agent_ref: str | None = None
    session_id: str | None = None
    state: SlotState = "active"
    epoch: int = 1
    last_progress_at: str | None = None
    last_progress_note: str | None = None
    context_tokens: int | None = None
    turn_count: int = 0
    checkpoint: str | None = None
    updated_at: str | None = None


@dataclass(frozen=True)
class SlotEvent:
    seq: int
    slot_id: str
    at: str
    actor: str
    kind: str
    epoch: int
    detail: dict[str, object] | None = None


def epoch_matches(slot: Slot, epoch: int) -> bool:
    """Return whether an operation's epoch is current for this slot."""
    return slot.epoch == epoch


def is_stale(slot: Slot, now: datetime, lease_s: int) -> bool:
    """Return whether progress has exceeded the lease; parked slots stay resumable."""
    if slot.state == "parked":
        return False
    last_progress_at = slot.last_progress_at or slot.updated_at
    if last_progress_at is None:
        return False
    progress_at = datetime.fromisoformat(last_progress_at)
    current = now if now.tzinfo is not None else now.replace(tzinfo=UTC)
    if progress_at.tzinfo is None:
        progress_at = progress_at.replace(tzinfo=UTC)
    return (current - progress_at).total_seconds() >= lease_s


def next_state(current: SlotState, target: SlotState) -> SlotState:
    """Validate and return a slot lifecycle transition."""
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"invalid slot state transition: {current} -> {target}")
    return target
