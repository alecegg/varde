"""Pure cycle, phase, and ready-work idle metrics for role queues."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


class _Item(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def planned_at(self) -> str | None: ...

    @property
    def build_started_at(self) -> str | None: ...

    @property
    def build_done_at(self) -> str | None: ...

    @property
    def merged_at(self) -> str | None: ...


class _Event(Protocol):
    @property
    def item_id(self) -> str: ...

    @property
    def at(self) -> str: ...

    @property
    def actor(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def from_state(self) -> str | None: ...

    @property
    def to_state(self) -> str | None: ...


@dataclass(frozen=True)
class LaneMetrics:
    """Per-item durations and ready-work idle seconds per worker slot."""

    cycle_seconds: dict[str, float | None]
    build_seconds: dict[str, float | None]
    review_seconds: dict[str, float | None]
    idle_seconds: dict[str, float]


def _seconds(start: str | None, end: str | None) -> float | None:
    if start is None or end is None:
        return None
    try:
        elapsed = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        return elapsed.total_seconds()
    except ValueError:
        return None


def lane_metrics(
    items: Iterable[_Item], events: Iterable[_Event], now: datetime
) -> LaneMetrics:
    """Calculate durations and slot idle time while queued work was available."""
    item_rows = list(items)
    cycle = {item.id: _seconds(item.planned_at, item.merged_at) for item in item_rows}
    build = {
        item.id: _seconds(item.build_started_at, item.build_done_at)
        for item in item_rows
    }
    review = {
        item.id: _seconds(item.build_done_at, item.merged_at) for item in item_rows
    }
    idle = _ready_work_idle(events, now)
    return LaneMetrics(cycle, build, review, idle)


def _ready_work_idle(events: Iterable[_Event], now: datetime) -> dict[str, float]:
    ordered = sorted(
        events, key=lambda event: (datetime.fromisoformat(event.at), event.item_id)
    )
    queued: set[str] = set()
    idle_since: dict[str, datetime] = {}
    total: dict[str, float] = defaultdict(float)
    previous: datetime | None = None

    for event in ordered:
        at = datetime.fromisoformat(event.at)
        _accrue_idle(total, idle_since, previous, at, bool(queued))
        if event.kind == "claim":
            idle_since.pop(event.actor, None)
            queued.discard(event.item_id)
        else:
            if event.kind == "enqueue" or event.to_state == "queued":
                queued.add(event.item_id)
            elif event.from_state == "queued" or event.kind == "claim":
                queued.discard(event.item_id)
            if _releases_slot(event) and event.actor not in {"", "system"}:
                idle_since[event.actor] = at
        previous = at

    _accrue_idle(total, idle_since, previous, now, bool(queued))
    return dict(total)


def _accrue_idle(
    total: dict[str, float],
    idle_since: dict[str, datetime],
    start: datetime | None,
    end: datetime,
    work_ready: bool,
) -> None:
    if start is None or not work_ready:
        return
    seconds = (end - start).total_seconds()
    if seconds <= 0:
        return
    for slot in idle_since:
        total[slot] += seconds


def _releases_slot(event: _Event) -> bool:
    if event.kind == "release":
        return True
    return event.kind in {"finish", "transition"} and event.to_state in {
        "merged",
        "blocked",
        "cancelled",
        "queued",
    }
