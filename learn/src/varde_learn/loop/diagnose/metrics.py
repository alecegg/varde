"""Pure session metrics and explainable waste signals for normalized evidence."""

from __future__ import annotations

import json
import re
import shlex
from collections.abc import Iterable
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from typing import Any

from .model import EvidenceRecord

OVERSIZED_OUTPUT_BYTES = 4_096


@dataclass(frozen=True)
class Signal:
    kind: str
    count: int
    cost_tokens: int
    anchors: list[dict[str, Any]]


def value(record: EvidenceRecord | dict[str, Any], key: str) -> Any:
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def usage(record: EvidenceRecord | dict[str, Any]) -> dict[str, Any]:
    for key in ("usage_record", "usage_last", "usage_total"):
        record_usage = value(record, key)
        if isinstance(record_usage, dict) and record_usage:
            for usage_key in ("usage", "turn_token_usage", "thread_token_usage"):
                nested = record_usage.get(usage_key)
                if isinstance(nested, dict) and nested:
                    return nested
            return record_usage
    return {}


def number(usage: dict[str, Any], *keys: str) -> int | float:
    for key in keys:
        value = usage.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        ):
            return value
    return 0


def _tokens(
    record: EvidenceRecord | dict[str, Any],
) -> tuple[int | float, int | float, int | float]:
    usage_data = usage(record)
    input_tokens = number(usage_data, "input_tokens", "input")
    cached = number(
        usage_data,
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_read_tokens",
        "cacheRead",
    ) + number(usage_data, "cache_creation_input_tokens", "cache_write_input_tokens")
    output = number(usage_data, "output_tokens", "output")
    return input_tokens, cached, output


def usage_rows(rows):
    """One row per model call: per-call records, else per-event last usage,
    else the final total.
    """
    for key in ("usage_record", "usage_last"):
        found = [row for row in rows if value(row, key)]
        if found:
            return found
    totals = [row for row in rows if value(row, "usage_total")]
    return totals[-1:]


def _context_tokens(record: EvidenceRecord | dict[str, Any]) -> int | float:
    """Context size of one call; Codex cached input is already part of input."""
    input_tokens, cached, _ = _tokens(record)
    if "cached_input_tokens" in usage(record):
        return input_tokens
    return input_tokens + cached


def timestamp(record: EvidenceRecord | dict[str, Any]) -> datetime | None:
    raw = value(record, "timestamp")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def session_metrics(
    records: Iterable[EvidenceRecord | dict[str, Any]],
) -> dict[str, int | float]:
    """Aggregate usage fields when present; wall time spans valid record timestamps."""
    rows = paired_records(list(records))
    call_rows = usage_rows(rows)
    timestamps = [stamp for row in rows if (stamp := timestamp(row)) is not None]
    wall_seconds = (
        (max(timestamps) - min(timestamps)).total_seconds() if timestamps else 0
    )
    input_total = cached_total = output_total = peak_context = 0
    for row in call_rows:
        input_tokens, cached, output = _tokens(row)
        input_total += input_tokens
        cached_total += cached
        output_total += output
        peak_context = max(peak_context, _context_tokens(row))

    paired = paired_records(rows)
    return {
        "model_calls": len(call_rows),
        "wall_seconds": wall_seconds,
        "input_tokens": input_total,
        "cached_input_tokens": cached_total,
        "output_tokens": output_total,
        "peak_context": peak_context,
        "tool_calls": len([row for row in paired if _is_tool_call(row)]),
        "tool_errors": sum(
            1 for row in paired if _is_tool_call(row) and _is_tool_error(row)
        ),
    }


def _is_tool_call(record: EvidenceRecord | dict[str, Any]) -> bool:
    kind = str(value(record, "kind") or "").lower()
    return kind == "tool_call" or (
        bool(value(record, "tool_name")) and kind not in {"tool_result", "tool_error"}
    )


def _is_tool_error(record: EvidenceRecord | dict[str, Any]) -> bool:
    status = str(value(record, "tool_status") or "").lower()
    return bool(value(record, "tool_error")) or status in {
        "error",
        "failed",
        "failure",
    }


def _text(record: EvidenceRecord | dict[str, Any], key: str) -> str:
    found = value(record, key)
    if isinstance(found, str):
        return found
    if found is None:
        return ""
    return json.dumps(found, ensure_ascii=False, separators=(",", ":"))


def _anchor(index: int, record: EvidenceRecord | dict[str, Any]) -> dict[str, Any]:
    return {"index": index, "timestamp": value(record, "timestamp")}


def _as_row(row: Any) -> Any:
    if isinstance(row, dict):
        return dict(row)
    if is_dataclass(row) and not isinstance(row, type):
        return asdict(row)
    return row


def paired_records(records):
    """Attach split tool result fields to their call row for waste heuristics."""
    rows = [_as_row(row) for row in records]
    calls = {}
    ordered = []
    for index, row in enumerate(rows):
        kind = str(value(row, "kind") or "").lower()
        if kind == "tool_call":
            ordered.append(index)
            tool_id = value(row, "tool_use_id")
            if tool_id:
                calls[str(tool_id)] = index
        elif kind in {"tool_result", "tool_error"}:
            tool_id = value(row, "tool_use_id")
            call_index = (
                calls.pop(str(tool_id), None)
                if tool_id
                else (ordered.pop(0) if ordered else None)
            )
            if call_index is not None and isinstance(rows[call_index], dict):
                for key in (
                    "tool_output_excerpt",
                    "tool_output_length_bytes",
                    "tool_status",
                    "tool_error",
                ):
                    found = value(row, key)
                    if found is not None:
                        rows[call_index][key] = found
                rows[call_index]["result_timestamp"] = value(row, "timestamp")
    return rows


_paired_records = paired_records


def _cost(text: str) -> int:
    """Estimate output-token cost as UTF-8 byte length divided by four."""
    return len(text.encode("utf-8")) // 4


def _signal(kind: str, indexes: list[int], records: list[Any], cost: int) -> Signal:
    return Signal(
        kind, len(indexes), max(0, cost), [_anchor(i, records[i]) for i in indexes]
    )


def _command(record: Any) -> list[str]:
    raw = _text(record, "tool_input_excerpt")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        raw = " ".join(
            str(item) for item in parsed.values() if isinstance(item, (str, int))
        )
    try:
        return shlex.split(raw)
    except ValueError:
        return raw.split()


def _family(command: list[str]) -> str:
    return command[0].rsplit("/", 1)[-1] if command else ""


def _fail(record: Any) -> bool:
    status = str(value(record, "tool_status") or "").lower()
    return _is_tool_error(record) or status in {"failed", "failure", "error"}


def _tool_observation_text(record: Any) -> tuple[str, bool]:
    output = _text(record, "tool_output_excerpt")
    return output, _has_capture_marker(output)


def _has_capture_marker(output: str) -> bool:
    return bool(re.search(r"(?i)(capture handle|captured as|\bhandle[:=])", output))


def _repeat_read(records: list[Any]) -> Signal | None:
    reads: dict[str, list[int]] = {}
    for index, row in enumerate(records):
        if not _is_tool_call(row):
            continue
        command = _command(row)
        tool = str(value(row, "tool_name") or "").lower()
        if (
            tool not in {"read", "cat", "sed", "head", "tail", "grep", "rg"}
            and not command
        ):
            continue
        path = next(
            (part for part in command if part.startswith("/") or "." in part), ""
        )
        if (
            not path
            and command
            and command[0].rsplit("/", 1)[-1] in {"cat", "sed", "head", "tail"}
        ):
            path = next((part for part in command[1:] if not part.startswith("-")), "")
        if path:
            reads.setdefault(path, []).append(index)
    repeated = [
        index
        for indexes in reads.values()
        if len(indexes) >= 3
        for index in indexes[1:]
    ]
    if not repeated:
        return None
    cost = sum(
        _cost(_text(records[index], "tool_output_excerpt")) for index in repeated
    )
    return _signal("repeat_read", repeated, records, cost)


def _oversized_output(records: list[Any]) -> Signal | None:
    indexes = []
    cost = 0
    for index, row in enumerate(records):
        observations = value(row, "tool_observations")
        if isinstance(observations, list):
            known_lengths = [
                observation
                for observation in observations
                if isinstance(observation, dict)
                and isinstance(observation.get("output_length_bytes"), int)
            ]
            if known_lengths:
                for observation in known_lengths:
                    output = _text(observation, "output_excerpt")
                    length = observation["output_length_bytes"]
                    if length >= OVERSIZED_OUTPUT_BYTES and not _has_capture_marker(
                        output
                    ):
                        indexes.append(index)
                        cost += _cost(output)
                continue
        if not _is_tool_call(row):
            continue
        output, captured = _tool_observation_text(row)
        original_length = value(row, "tool_output_length_bytes")
        # Legacy snapshots have unknown original lengths, so they do not fire.
        if (
            isinstance(original_length, int)
            and original_length >= OVERSIZED_OUTPUT_BYTES
            and not captured
        ):
            indexes.append(index)
            cost += _cost(output)
    return _signal("oversized_output", indexes, records, cost) if indexes else None


def _rerun_for_detail(records: list[Any]) -> Signal | None:
    filter_commands: dict[str, list[tuple[int, str]]] = {}
    filters = {"head", "tail", "grep", "rg", "jq"}
    for index, row in enumerate(records):
        if not _is_tool_call(row):
            continue
        command = _command(row)
        filter_index = next(
            (i for i, part in enumerate(command) if part in filters), None
        )
        if filter_index is None:
            continue
        base = " ".join(command[:filter_index])
        filter_commands.setdefault(base, []).append(
            (index, " ".join(command[filter_index:]))
        )
    reruns = [
        index
        for calls in filter_commands.values()
        if len({filter_text for _, filter_text in calls}) > 1
        for index, _ in calls[1:]
    ]
    if not reruns:
        return None
    cost = sum(_cost(_text(records[i], "tool_output_excerpt")) for i in reruns)
    return _signal("rerun_for_detail", reruns, records, cost)


def _retry_loop(records: list[Any]) -> Signal | None:
    retries = []
    streak: list[int] = []
    streak_family = ""
    for index, row in enumerate(records):
        command = _command(row)
        family = _family(command)
        if _is_tool_call(row) and _fail(row) and family and family == streak_family:
            streak.append(index)
        elif _is_tool_call(row) and _fail(row) and family:
            if len(streak) >= 3:
                retries.extend(streak)
            streak, streak_family = [index], family
        else:
            if len(streak) >= 3:
                retries.extend(streak)
            streak, streak_family = [], ""
    if len(streak) >= 3:
        retries.extend(streak)
    if not retries:
        return None
    cost = sum(_cost(_text(records[i], "tool_output_excerpt")) for i in retries)
    return _signal("retry_loop", retries, records, cost)


def _slow_command(records: list[Any]) -> Signal | None:
    slow = []
    slow_cost = 0
    pending: dict[str, tuple[int, datetime]] = {}
    for index, row in enumerate(records):
        kind = str(value(row, "kind") or "").lower()
        stamp = timestamp(row)
        result_stamp = value(row, "result_timestamp")
        if kind == "tool_call" and stamp and isinstance(result_stamp, str):
            try:
                end = datetime.fromisoformat(result_stamp)
            except ValueError:
                continue
            if (end - stamp).total_seconds() > 20:
                slow.append(index)
                slow_cost += _cost(_text(row, "tool_output_excerpt"))
            continue
        if stamp is None:
            continue
        tool_id = str(value(row, "tool_use_id") or value(row, "tool_name") or "")
        if kind == "tool_call":
            pending[tool_id] = (index, stamp)
        elif kind == "tool_result" and tool_id in pending:
            start_index, start = pending.pop(tool_id)
            if (stamp - start).total_seconds() > 20:
                slow.append(start_index)
                slow_cost += _cost(_text(row, "tool_output_excerpt"))
    return _signal("slow_command", slow, records, slow_cost) if slow else None


def waste_signals(records: Iterable[EvidenceRecord | dict[str, Any]]) -> list[Signal]:
    """Find five deterministic patterns using 1 KiB output and 20 s thresholds.

    Costs estimate repeated or oversized output tokens as UTF-8 bytes / 4.
    Anchors point to the evidence records that triggered each signal.
    """
    rows = _paired_records(list(records))
    candidates = (
        _repeat_read(rows),
        _oversized_output(rows),
        _rerun_for_detail(rows),
        _retry_loop(rows),
        _slow_command(rows),
    )
    return [signal for signal in candidates if signal is not None]
