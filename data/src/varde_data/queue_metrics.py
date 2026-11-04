"""Pure calculations for queue cycle, build, and review durations."""

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from statistics import median

from varde_data.records.queue import QueueItem


@dataclass(frozen=True)
class DurationSummary:
    """Median duration in seconds and the number of incomplete items."""

    median_seconds: float | None
    skipped: int


@dataclass(frozen=True)
class QueueDurationMetrics:
    """Duration summaries for one queue."""

    cycle_time: DurationSummary
    build_time: DurationSummary
    review_wait: DurationSummary


def _seconds(start: str | None, end: str | None) -> float | None:
    if start is None or end is None:
        return None
    try:
        elapsed = datetime.fromisoformat(end) - datetime.fromisoformat(start)
    except ValueError:
        return None
    return elapsed.total_seconds()


def _summary(values: Iterable[float | None]) -> DurationSummary:
    values = list(values)
    durations = [value for value in values if value is not None]
    skipped = sum(value is None for value in values)
    return DurationSummary(median(durations) if durations else None, skipped)


def queue_metrics(items: Iterable[QueueItem]) -> dict[str, QueueDurationMetrics]:
    """Calculate per-queue medians; incomplete timestamp pairs count as skipped."""
    grouped: dict[str, list[QueueItem]] = defaultdict(list)
    for item in items:
        grouped[item.queue_name].append(item)

    result: dict[str, QueueDurationMetrics] = {}
    for queue_name, queue_items in grouped.items():
        cycle = [_seconds(item.planned_at, item.merged_at) for item in queue_items]
        build = [
            _seconds(item.build_started_at, item.build_done_at) for item in queue_items
        ]
        review = [_seconds(item.build_done_at, item.merged_at) for item in queue_items]
        result[queue_name] = QueueDurationMetrics(
            _summary(cycle), _summary(build), _summary(review)
        )
    return result
