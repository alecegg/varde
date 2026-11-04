from varde_data.records.queue import QueueEvent, QueueItem
from varde_workflow.queue_telemetry import queue_telemetry


def _at(seconds: int) -> str:
    return f"2026-01-01T00:00:{seconds:02d}+00:00"


def test_delegation_telemetry_reports_caller_supplied_work_counts() -> None:
    telemetry = queue_telemetry(
        [QueueItem("task", "plan")],
        [],
        self_count=2,
        builder_count=2,
        orchestrator_count=1,
    )

    assert telemetry.delegated_count == 3
    assert telemetry.coordinator_count == 2
    assert telemetry.route_counts == {"self": 2, "builder": 2, "orchestrator": 1}


def test_wave_telemetry_reports_wait_run_and_dependency_critical_path() -> None:
    items = [
        QueueItem("first", "plan", build_started_at=_at(5), build_done_at=_at(10)),
        QueueItem(
            "second",
            "plan",
            depends_on=("first",),
            build_started_at=_at(12),
            build_done_at=_at(20),
        ),
        QueueItem(
            "independent", "plan", build_started_at=_at(4), build_done_at=_at(11)
        ),
    ]
    events = [
        QueueEvent(1, "first", _at(1), "system", "enqueue", None, "queued"),
        QueueEvent(2, "first", _at(5), "builder", "claim", "queued", "claimed"),
        QueueEvent(3, "second", _at(8), "system", "enqueue", None, "queued"),
        QueueEvent(4, "second", _at(12), "builder", "claim", "queued", "claimed"),
    ]

    telemetry = queue_telemetry(
        items,
        events,
        self_count=1,
        builder_count=2,
        orchestrator_count=0,
    )

    assert telemetry.queue_wait_seconds == {
        "first": 4,
        "second": 4,
        "independent": None,
    }
    assert telemetry.run_seconds == {"first": 5, "second": 8, "independent": 7}
    assert telemetry.critical_path_seconds == 13
    assert telemetry.route_counts == {"self": 1, "builder": 2, "orchestrator": 0}


def test_mixed_timezone_timestamps_are_ignored() -> None:
    item = QueueItem(
        "mixed", "plan", build_started_at="2030-01-01T00:00:00", build_done_at=_at(5)
    )
    events = [
        QueueEvent(
            1, "mixed", "2030-01-01T00:00:00", "system", "enqueue", None, "queued"
        ),
        QueueEvent(2, "mixed", _at(5), "builder", "claim", "queued", "claimed"),
    ]
    telemetry = queue_telemetry(
        [item], events, self_count=1, builder_count=1, orchestrator_count=0
    )
    assert telemetry.queue_wait_seconds["mixed"] is None
    assert telemetry.run_seconds["mixed"] is None
