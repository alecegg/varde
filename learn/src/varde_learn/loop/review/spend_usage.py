"""Per-call token usage and relative spend for review evidence."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, NamedTuple

from ..diagnose.metrics import number, timestamp, usage, usage_rows, value


class Weights(NamedTuple):
    """Relative API price ratios, normalized to ordinary input tokens."""

    input: float = 1
    cache_read: float = 0.1
    cache_write: float = 2
    output: float = 5


WEIGHTS = Weights()


def _utc(stamp: datetime) -> datetime:
    return stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp.astimezone(UTC)


def _has_tokens(record: Any) -> bool:
    tokens = usage(record)
    return any(
        key in tokens
        for key in (
            "input_tokens",
            "input",
            "cached_input_tokens",
            "cache_read_input_tokens",
            "cache_read_tokens",
            "cacheRead",
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "cache_write_tokens",
            "cacheWrite",
            "output_tokens",
            "output",
        )
    )


def rows(
    records: Iterable[Any],
    start: datetime | None = None,
    end: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return per-call rows filtered inclusively by timestamp."""
    evidence = list(records)
    has_call_records = any(
        value(record, "usage_record") is not None
        or value(record, "usage_last") is not None
        for record in evidence
    )
    calls = (
        [record for record in usage_rows(evidence) if _has_tokens(record)]
        if has_call_records
        else []
    )

    positions: dict[tuple[str, str], int] = {}
    deduped: list[Any] = []
    for record in calls:
        message_id = value(record, "provider_message_id")
        if message_id:
            key = (str(value(record, "transcript_id") or ""), str(message_id))
            position = positions.get(key)
            if position is None:
                positions[key] = len(deduped)
                deduped.append(record)
            else:
                deduped[position] = record
        else:
            deduped.append(record)

    result = []
    for record in deduped:
        stamp = timestamp(record)
        if start is not None and (stamp is None or _utc(stamp) < _utc(start)):
            continue
        if end is not None and (stamp is None or _utc(stamp) > _utc(end)):
            continue
        counts = usage(record)
        input_tokens = number(counts, "input_tokens", "input")
        cache_read = number(
            counts, "cache_read_input_tokens", "cache_read_tokens", "cacheRead"
        )
        cache_write = number(
            counts,
            "cache_creation_input_tokens",
            "cache_write_input_tokens",
            "cache_write_tokens",
            "cacheWrite",
        )
        if "cached_input_tokens" in counts:
            cached = number(counts, "cached_input_tokens")
            input_tokens = max(0, input_tokens - cached)
            cache_read += cached
        result.append(
            {
                "input": input_tokens,
                "cache_read": cache_read,
                "cache_write": cache_write,
                "output": number(counts, "output_tokens", "output"),
                "model": value(record, "model"),
                "timestamp": value(record, "timestamp"),
                "context_size": input_tokens + cache_read + cache_write,
                "provider_message_id": value(record, "provider_message_id"),
            }
        )
    return result


def weighted(row: dict[str, Any]) -> float:
    return (
        row["input"] * WEIGHTS.input
        + row["cache_read"] * WEIGHTS.cache_read
        + row["cache_write"] * WEIGHTS.cache_write
        + row["output"] * WEIGHTS.output
    )


def aggregate(usage_rows_: Iterable[dict[str, Any]]) -> dict[str, int | float]:
    totals: dict[str, int | float] = {
        "input": 0,
        "cache_read": 0,
        "cache_write": 0,
        "output": 0,
        "weighted": 0,
        "calls": 0,
    }
    for row in usage_rows_:
        for key in ("input", "cache_read", "cache_write", "output"):
            totals[key] += row[key]
        totals["weighted"] += weighted(row)
        totals["calls"] += 1
    return totals


def coverage(harness: str, records: Iterable[Any]) -> dict[str, Any]:
    """Describe whether evidence provides per-call use, a session total, or none."""
    evidence = list(records)
    per_call = rows(evidence)
    has_per_call_data = any(
        value(item, "usage_record") is not None or value(item, "usage_last") is not None
        for item in evidence
    )
    if has_per_call_data:
        status = "per_call"
    elif any(value(item, "usage_total") for item in evidence):
        status = "session_total"
    else:
        status = "no_usage"
    return {
        "harness": harness,
        "status": status,
        "rows": per_call,
        "window_and_context_bands": status == "per_call",
    }
