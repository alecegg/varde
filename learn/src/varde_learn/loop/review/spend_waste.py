"""Measure token-spend patterns from plain per-session records.

Each record has ``session_id`` and ``rows`` (the per-call dictionaries returned
by :func:`spend_usage.rows`). Optional fields are ``tool_names`` (one tool name
or ``None`` per row, describing that call; recognized standalone names include
poll/watch tools and ``msg-send``), ``role``, ``target``, and
``first_call_context`` (context-token count for the first call in the review
window). Review rounds count reviewer sessions after the first
for a target. Startup spend uses the first row's measured usage; the optional
first-call context supplies its context size. Context and cache measures cover
all supplied sessions, and first calls means first call in the supplied
window. Missing optional metadata makes its detector return ``None``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

SessionRecord = dict[str, Any]
Row = dict[str, Any]


def _row_weight(row: Row) -> float:
    """Return established spend weighting while tolerating partial usage rows."""
    return (
        _number(row.get("input"))
        + 0.1 * _number(row.get("cache_read"))
        + 2 * _number(row.get("cache_write"))
        + 5 * _number(row.get("output"))
    )


def _number(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def _share(
    name: str, matching: list[Row], total: float, thresholds: dict[str, Any]
) -> dict[str, Any]:
    return {
        "name": name,
        "weighted_share": sum(_row_weight(row) for row in matching) / total
        if total
        else 0.0,
        "count": len(matching),
        "thresholds": thresholds,
    }


def _timestamp(row: Row) -> datetime | None:
    value = row.get("timestamp")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _session_rows(records: list[SessionRecord]) -> list[Row]:
    rows = []
    for record in records:
        session_id = record.get("session_id")
        calls = record.get("rows")
        if session_id is None or not isinstance(calls, list):
            continue
        tool_names = record.get("tool_names")
        for index, call in enumerate(calls):
            if not isinstance(call, dict):
                continue
            row = {**call, "session_id": session_id}
            for key in ("role", "target"):
                if key in record:
                    row[key] = record[key]
            if isinstance(tool_names, list) and index < len(tool_names):
                row["tool_name"] = tool_names[index]
            rows.append(row)
    return rows


def _tool_category(row: Row) -> str | None:
    name = row.get("tool_name")
    if not isinstance(name, str) or not name:
        return None
    lowered = name.lower()
    if lowered in {"monitor", "taskoutput", "schedulewakeup", "croncreate", "sleep"}:
        return "poll"
    if lowered in {"msg-send", "msg_send", "varde_msg_send"}:
        return "msg_send"
    if lowered in {"bash", "shell"}:
        return None
    if "poll" in lowered or "watch" in lowered or "sleep" in lowered:
        return "poll"
    return "other"


def _context_rows(rows: list[Row], threshold: int) -> list[Row]:
    return [
        row
        for row in rows
        if isinstance(row.get("context_size"), (int, float))
        and row["context_size"] >= threshold
    ]


def _startup_rows(records: list[SessionRecord]) -> list[Row] | None:
    first_rows = []
    for record in records:
        if "first_call_context" not in record:
            continue
        calls = record.get("rows")
        if not isinstance(calls, list) or not calls:
            continue
        valid_calls = [call for call in calls if isinstance(call, dict)]
        if not valid_calls:
            continue
        first_call = min(
            enumerate(valid_calls),
            key=lambda pair: (
                _timestamp(pair[1]) is None,
                _timestamp(pair[1]) or datetime.max.replace(tzinfo=UTC),
                pair[0],
            ),
        )[1]
        row = dict(first_call)
        if not isinstance(record["first_call_context"], (int, float)):
            continue
        row["context_size"] = record["first_call_context"]
        first_rows.append(row)
    return first_rows or None


def _review_repeat_rows(rows: list[Row]) -> tuple[list[Row], int] | None:
    sessions_by_target: dict[str, dict[Any, list[Row]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in rows:
        target = row.get("target")
        session = row.get("session_id")
        if (
            row.get("role") == "reviewer/checker"
            and isinstance(target, str)
            and target
            and session is not None
        ):
            sessions_by_target[target][session].append(row)
    if not sessions_by_target:
        return None
    repeated_rows = []
    repeated_sessions_count = 0
    for sessions in sessions_by_target.values():
        ordered_sessions = sorted(
            sessions,
            key=lambda session: min(
                (_timestamp(row) or datetime.max.replace(tzinfo=UTC))
                for row in sessions[session]
            ),
        )
        later_sessions = ordered_sessions[1:]
        repeated_sessions_count += len(later_sessions)
        repeated_rows.extend(
            row for session in later_sessions for row in sessions[session]
        )
    return repeated_rows, repeated_sessions_count


def _cache_rebuild_rows(
    rows: list[Row], idle_seconds: int, cache_tokens: int
) -> list[Row] | None:
    rows_by_session: dict[Any, list[Row]] = defaultdict(list)
    for row in rows:
        if row.get("session_id") is not None and _timestamp(row) is not None:
            rows_by_session[row["session_id"]].append(row)
    if not any(len(calls) > 1 for calls in rows_by_session.values()):
        return None
    rebuilds = []
    for calls in rows_by_session.values():
        calls.sort(key=lambda row: _timestamp(row) or datetime.max.replace(tzinfo=UTC))
        previous: datetime | None = None
        for row in calls:
            current = _timestamp(row)
            cache_write = row.get("cache_write", 0)
            if (
                current is not None
                and previous is not None
                and (current - previous).total_seconds() > idle_seconds
                and isinstance(cache_write, (int, float))
                and cache_write > cache_tokens
            ):
                rebuilds.append(row)
            previous = current
    return rebuilds


def analyze(
    session_records: Iterable[SessionRecord],
    context_thresholds: tuple[int, ...] = (200_000, 400_000),
    idle_seconds: int = 3600,
    cache_write_threshold: int = 60_000,
) -> dict[str, dict[str, Any] | None]:
    """Measure weighted-spend shares from per-session usage records."""
    records = list(session_records)
    rows = _session_rows(records)
    total = sum(_row_weight(row) for row in rows)
    contexts = [
        row["context_size"]
        for row in rows
        if isinstance(row.get("context_size"), (int, float))
    ]
    peak = max(contexts) if contexts else None
    result: dict[str, dict[str, Any] | None] = {}
    for threshold in context_thresholds:
        if not contexts:
            result[f"context_over_{threshold // 1000}k"] = None
            continue
        name = f"context_over_{threshold // 1000}k"
        result[name] = _share(
            name,
            _context_rows(rows, threshold),
            total,
            {"context_tokens": threshold, "peak_context_tokens": peak},
        )

    categories = [_tool_category(row) for row in rows]
    if all(category is None for category in categories):
        result["poll_watch_msg_read_sleep"] = None
        result["msg_send"] = None
    else:
        for key, category in (
            ("poll_watch_msg_read_sleep", "poll"),
            ("msg_send", "msg_send"),
        ):
            matching = [
                row
                for row, actual in zip(rows, categories, strict=True)
                if actual == category
            ]
            result[key] = (
                _share(key, matching, total, {"categorization": "per-call tool name"})
                if category in categories
                else None
            )

    startup = _startup_rows(records)
    result["startup_prompt"] = (
        None
        if startup is None
        else _share("startup_prompt", startup, total, {"calls_per_session": 1})
    )
    repeated = _review_repeat_rows(rows)
    if repeated is None:
        result["repeated_review_rounds"] = None
    else:
        repeated_rows, repeated_count = repeated
        result["repeated_review_rounds"] = _share(
            "repeated_review_rounds", repeated_rows, total, {}
        )
        result["repeated_review_rounds"]["count"] = repeated_count

    subagents = [row for row in rows if "subagent" in str(row.get("role", "")).lower()]
    has_role = any("role" in record for record in records)
    result["subagent"] = (
        _share("subagent", subagents, total, {"role": "subagent"}) if has_role else None
    )

    rebuilds = _cache_rebuild_rows(rows, idle_seconds, cache_write_threshold)
    result["cache_rebuild_after_idle"] = (
        None
        if rebuilds is None
        else _share(
            "cache_rebuild_after_idle",
            rebuilds,
            total,
            {"idle_seconds": idle_seconds, "cache_write_tokens": cache_write_threshold},
        )
    )
    return result
