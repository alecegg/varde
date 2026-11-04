"""Pure measurements for delegated work in a queue wave."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

RouteTier = Literal["self", "builder", "orchestrator"]


class _Item(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def depends_on(self) -> tuple[str, ...]: ...

    @property
    def build_started_at(self) -> str | None: ...

    @property
    def build_done_at(self) -> str | None: ...


class _Event(Protocol):
    @property
    def item_id(self) -> str: ...

    @property
    def at(self) -> str: ...

    @property
    def kind(self) -> str: ...

    @property
    def to_state(self) -> str | None: ...


@dataclass(frozen=True)
class QueueTelemetry:
    """Per-item queue/build durations and aggregate wave measurements."""

    queue_wait_seconds: dict[str, float | None]
    run_seconds: dict[str, float | None]
    critical_path_seconds: float | None
    delegated_count: int
    coordinator_count: int
    route_counts: dict[RouteTier, int]


def _seconds(start: str | None, end: str | None) -> float | None:
    if start is None or end is None:
        return None
    try:
        seconds = datetime.fromisoformat(end) - datetime.fromisoformat(start)
        result = seconds.total_seconds()
    except TypeError, ValueError:
        return None
    return result if result >= 0 else None


def _queue_wait(item_id: str, events: list[_Event]) -> float | None:
    try:
        ordered = sorted(
            (event for event in events if event.item_id == item_id),
            key=lambda event: datetime.fromisoformat(event.at),
        )
    except TypeError, ValueError:
        return None
    queued_at: str | None = None
    for event in ordered:
        if event.kind == "enqueue" or event.to_state == "queued":
            queued_at = event.at
        elif event.kind == "claim" and queued_at is not None:
            return _seconds(queued_at, event.at)
    return None


def _critical_path(
    items: list[_Item], durations: dict[str, float | None]
) -> float | None:
    by_id = {item.id: item for item in items}
    visiting: set[str] = set()
    memo: dict[str, float] = {}

    def path(item_id: str) -> float:
        if item_id in memo:
            return memo[item_id]
        if item_id in visiting:
            raise ValueError("queue wave dependencies contain a cycle")
        visiting.add(item_id)
        item = by_id[item_id]
        parents = [dependency for dependency in item.depends_on if dependency in by_id]
        parent_duration = max((path(parent) for parent in parents), default=0.0)
        duration = durations[item_id] or 0.0
        visiting.remove(item_id)
        memo[item_id] = parent_duration + duration
        return memo[item_id]

    if not items or all(duration is None for duration in durations.values()):
        return None
    try:
        return max(path(item_id) for item_id in by_id)
    except ValueError:
        return None


def queue_telemetry(
    items: Iterable[_Item],
    events: Iterable[_Event],
    *,
    self_count: int,
    builder_count: int,
    orchestrator_count: int,
    delegated_count: int | None = None,
) -> QueueTelemetry:
    """Measure queue wait, run duration, and dependency critical path."""
    item_rows = list(items)
    event_rows = list(events)
    queue_wait = {item.id: _queue_wait(item.id, event_rows) for item in item_rows}
    run = {
        item.id: _seconds(item.build_started_at, item.build_done_at)
        for item in item_rows
    }
    route_counts: dict[RouteTier, int] = {
        "self": self_count,
        "builder": builder_count,
        "orchestrator": orchestrator_count,
    }
    return QueueTelemetry(
        queue_wait,
        run,
        _critical_path(item_rows, run),
        delegated_count
        if delegated_count is not None
        else builder_count + orchestrator_count,
        self_count,
        route_counts,
    )
