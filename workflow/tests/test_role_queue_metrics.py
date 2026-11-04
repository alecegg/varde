from dataclasses import dataclass
from datetime import UTC, datetime

from varde_workflow.role_queue_metrics import lane_metrics


@dataclass(frozen=True)
class Item:
    id: str
    planned_at: str | None = None
    build_started_at: str | None = None
    build_done_at: str | None = None
    merged_at: str | None = None


@dataclass(frozen=True)
class Event:
    item_id: str
    at: str
    actor: str
    kind: str
    from_state: str | None = None
    to_state: str | None = None


def _at(seconds: int) -> str:
    return f"2026-01-01T00:00:{seconds:02d}+00:00"


def test_lane_metrics_reports_cycle_build_and_review_durations() -> None:
    metrics = lane_metrics(
        [Item("bundle", _at(0), _at(2), _at(5), _at(9))],
        [],
        datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert metrics.cycle_seconds == {"bundle": 9}
    assert metrics.build_seconds == {"bundle": 3}
    assert metrics.review_seconds == {"bundle": 4}


def test_idle_time_counts_only_gaps_with_ready_work() -> None:
    events = [
        Event("first", _at(0), "slot-a", "claim", "queued", "claimed"),
        Event("first", _at(10), "slot-a", "finish", "building", "merged"),
        Event("next", _at(12), "system", "enqueue", None, "queued"),
        Event("next", _at(20), "slot-a", "claim", "queued", "claimed"),
        Event("next", _at(30), "slot-a", "release", "claimed", "blocked"),
    ]

    metrics = lane_metrics(
        [Item("first"), Item("next")],
        events,
        datetime(2026, 1, 1, 0, 0, 40, tzinfo=UTC),
    )

    assert metrics.idle_seconds == {"slot-a": 8}
