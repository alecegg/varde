from varde_data.queue_metrics import queue_metrics
from varde_data.records.queue import QueueItem


def _item(
    item_id: str,
    *,
    queue_name: str = "default",
    planned_at: str | None = None,
    build_started_at: str | None = None,
    build_done_at: str | None = None,
    merged_at: str | None = None,
) -> QueueItem:
    return QueueItem(
        id=item_id,
        plan_dir="plan",
        queue_name=queue_name,
        planned_at=planned_at,
        build_started_at=build_started_at,
        build_done_at=build_done_at,
        merged_at=merged_at,
    )


def test_queue_metrics_calculates_medians_and_skipped_counts() -> None:
    items = [
        _item(
            "one",
            queue_name="alpha",
            planned_at="2026-01-01T00:00:00+00:00",
            build_started_at="2026-01-01T00:01:00+00:00",
            build_done_at="2026-01-01T00:03:00+00:00",
            merged_at="2026-01-01T00:08:00+00:00",
        ),
        _item(
            "two",
            queue_name="alpha",
            planned_at="2026-01-01T00:00:00+00:00",
            build_started_at="2026-01-01T00:02:00+00:00",
            build_done_at="2026-01-01T00:06:00+00:00",
            merged_at="2026-01-01T00:10:00+00:00",
        ),
        _item("incomplete", queue_name="beta", planned_at="2026-01-01T00:00:00+00:00"),
    ]

    metrics = queue_metrics(items)

    assert metrics["alpha"].cycle_time.median_seconds == 540
    assert metrics["alpha"].cycle_time.skipped == 0
    assert metrics["alpha"].build_time.median_seconds == 180
    assert metrics["alpha"].review_wait.median_seconds == 270
    assert metrics["beta"].cycle_time.median_seconds is None
    assert metrics["beta"].cycle_time.skipped == 1
    assert metrics["beta"].build_time.skipped == 1
    assert metrics["beta"].review_wait.skipped == 1
