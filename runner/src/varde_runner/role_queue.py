"""Pure data model and display rules for per-role work queues."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

QueueRowState = Literal["running", "waiting", "blocked", "done"]
RoleState = Literal["needs_you", "failed", "running", "idle", "done"]


@dataclass(frozen=True, slots=True)
class RoleQueueRow:
    id: str
    title: str
    plan_id: str | None
    state: QueueRowState


@dataclass(frozen=True, slots=True)
class RoleSummary:
    role: str
    agent_id: str | None
    state: RoleState
    current: RoleQueueRow | None
    queued: int
    needs_you: int


@dataclass(frozen=True, slots=True)
class RoleQueues:
    roles: list[RoleSummary]
    rows: dict[str, list[RoleQueueRow]]


RoleQueueRead = Callable[[], RoleQueues]

_NEEDS_YOU_LABEL_MAX = 9


def needs_you_count_text(count: int) -> str:
    """The label's count, capped so a large number cannot stretch the label."""
    return str(count) if count <= _NEEDS_YOU_LABEL_MAX else f"{_NEEDS_YOU_LABEL_MAX}+"


def _item_title(summary: RoleSummary) -> str:
    return summary.current.title[:40] if summary.current else "work"


def role_status_line(summary: RoleSummary) -> str:
    if summary.state == "needs_you":
        return f"Needs you: {needs_you_count_text(summary.needs_you)} approvals"
    if summary.state == "failed":
        return f"Failed on {_item_title(summary)}, {summary.queued} in queue"
    if summary.state == "running":
        return f"Working on {_item_title(summary)}, {summary.queued} in queue"
    if summary.state == "idle" and summary.queued:
        return f"Idle, {summary.queued} in queue"
    if summary.state == "idle":
        return "Idle"
    return "Done"


def home_sort(summaries: list[RoleSummary]) -> list[RoleSummary]:
    priority = {"needs_you": 0, "failed": 1, "running": 2, "idle": 3, "done": 4}
    return sorted(summaries, key=lambda summary: priority[summary.state])
