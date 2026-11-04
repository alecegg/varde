"""Codex JSONL event normalization with stable byte anchors."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never

from ...errors import Diagnose
from ..model import (
    MAX_RECORD_BYTES,
    MAX_SOURCE_BYTES,
    EvidenceRecord,
    NormalizedRecordBudget,
    RecordAnchor,
    SourceSnapshot,
    rendered_length_bytes,
)
from .discovery import Header, parse_header

MAX_TEXT_EXCERPT = 512


def _raise(error: Exception) -> Never:
    raise error


def _object(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {key: item for key, item in value.items() if isinstance(key, str)}


@dataclass
class ParsedSource:
    header: Header
    source: SourceSnapshot
    records: list[EvidenceRecord]
    processed_records: int
    incomplete_tail: bool
    malformed_records: int
    omitted_records: int
    unknown_events: int
    inherited_events: int
    truncated: bool
    warnings: list[str]


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def event_kind(value: dict[str, Any]) -> str:
    top = value.get("type", "unknown")
    payload = _object(value.get("payload"))
    nested_value = payload.get("type")
    nested = nested_value if isinstance(nested_value, str) else None
    if top == "event_msg":
        if nested in {"item_completed", "item_started"}:
            item = _object(payload.get("item"))
            typ_value = item.get("type")
            typ = typ_value if isinstance(typ_value, str) else None
            if typ is None:
                return nested
            return {
                "function_call": "tool_call",
                "custom_tool_call": "tool_call",
                "function_call_output": "tool_result",
                "custom_tool_call_output": "tool_result",
                "message": "message",
            }.get(typ, nested)
        return nested or top
    if top == "response_item":
        if nested is None:
            return top
        return {
            "message": "message",
            "function_call": "tool_call",
            "custom_tool_call": "tool_call",
            "function_call_output": "tool_result",
            "custom_tool_call_output": "tool_result",
        }.get(nested, nested or top)
    return top


KNOWN_EVENT_KINDS = frozenset(
    {
        "message",
        "tool_call",
        "tool_result",
        "turn_context",
        "turn_failed",
        "turn_aborted",
        "turn_started",
        "task_started",
        "task_complete",
        "item_started",
        "item_completed",
        "token_count",
        "token_usage_record",
        "compacted",
        "warning",
        "error",
        "reasoning",
        "agent_message",
        "web_search_call",
        "mcp_tool_call",
        "custom_tool_call",
        "session_meta",
    }
)


def native_id(value: dict[str, Any]) -> str | None:
    payload = value.get("payload")
    if isinstance(payload, dict):
        for key in ("id", "response_id"):
            if isinstance(payload.get(key), str):
                return payload[key]
    return value.get("id") if isinstance(value.get("id"), str) else None


def _bounded(value: str, limit: int) -> str:
    return value[:limit] + ("…" if len(value) > limit else "")


def _content_text(value: Any) -> str | None:
    part = _object(value)
    text = part.get("text", part.get("input_text"))
    return text if isinstance(text, str) else None


def _usage(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    allowed = (
        "input_tokens",
        "cached_input_tokens",
        "cache_write_input_tokens",
        "output_tokens",
        "reasoning_output_tokens",
        "total_tokens",
    )
    result = {
        key: value[key]
        for key in allowed
        if isinstance(value.get(key), (int, float))
        and not isinstance(value.get(key), bool)
    }
    return result or None


def context_occupancy(record: dict[str, Any]) -> int | None:
    payload = _object(record.get("payload"))
    info = _object(payload.get("info"))
    usage = _usage(info.get("last_token_usage")) or {}
    value = usage.get("input_tokens")
    return value if isinstance(value, int) and value >= 0 else None


def _excerpt(value: Any, limit: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    text = (
        value
        if isinstance(value, str)
        else json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        )
    )
    return _bounded(text, limit), len(text) > limit


def normalize_record(
    value: dict[str, Any], anchor: RecordAnchor, thread_id: str
) -> EvidenceRecord:
    payload = _object(value.get("payload"))
    kind = event_kind(value)
    item = _object(payload.get("item")) or payload
    content = payload.get("content")
    excerpt = None
    if kind == "message" and isinstance(content, list):
        text = " ".join(
            text for part in content if (text := _content_text(part)) is not None
        )
        excerpt = _bounded(text, MAX_TEXT_EXCERPT) if text else None
    inp, input_cut = _excerpt(item.get("arguments", item.get("input")), 1024)
    out, output_cut = _excerpt(item.get("output", item.get("content")), 1024)
    output_length_bytes = rendered_length_bytes(item.get("output", item.get("content")))
    err, error_cut = _excerpt(item.get("error", payload.get("error")), 512)
    known = kind in KNOWN_EVENT_KINDS
    unknown, unknown_cut = _excerpt(payload, 512) if not known else (None, False)
    usage_record = None
    if value.get("type") == "token_usage_record":
        usage_record = {
            key: payload[key]
            for key in (
                "thread_id",
                "turn_id",
                "session_id",
                "root_turn_id",
                "response_id",
            )
            if isinstance(payload.get(key), str)
        }
        usage_record.update(
            {
                key: usage
                for key in ("usage", "turn_token_usage", "thread_token_usage")
                if (usage := _usage(payload.get(key)))
            }
        )
        usage_record = usage_record or None
    failure = (
        payload.get("reason", payload.get("message"))
        if kind == "turn_failed" or "error" in kind
        else None
    )
    tool_name = item.get("name", item.get("tool_name"))
    tool_status = item.get("status", payload.get("status"))
    return EvidenceRecord(
        session_thread_id=thread_id,
        anchor=anchor,
        timestamp=value.get("timestamp", payload.get("timestamp")),
        kind=kind,
        role=payload.get("role") if isinstance(payload.get("role"), str) else None,
        text_excerpt=excerpt,
        tool_name=_bounded(tool_name, 128) if isinstance(tool_name, str) else None,
        tool_input_excerpt=inp,
        tool_output_excerpt=out,
        tool_output_length_bytes=output_length_bytes,
        tool_status=_bounded(tool_status, 64) if isinstance(tool_status, str) else None,
        tool_error=err,
        detail_truncated=input_cut or output_cut or error_cut or unknown_cut,
        unknown_payload_excerpt=unknown,
        turn_id=payload.get("turn_id"),
        response_id=payload.get("response_id"),
        cwd=payload.get("cwd"),
        failure_reason=_bounded(failure, 256) if isinstance(failure, str) else None,
        compacted_before_tokens=payload.get("tokens_before")
        if isinstance(payload.get("tokens_before"), int)
        else None,
        usage_total=_usage(_object(payload.get("info")).get("total_token_usage")),
        usage_last=_usage(_object(payload.get("info")).get("last_token_usage")),
        usage_record=usage_record,
    )


def _prefix_count(header: Header) -> int:
    value = header.history_base
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, dict):
        for key in ("inherited_events", "event_count", "record_count"):
            if isinstance(value.get(key), int) and value[key] >= 0:
                return value[key]
    return 0


def parse_source(
    path: Path,
    byte_limit: int = MAX_SOURCE_BYTES,
    record_limit: int = 10_000,
    normalized_budget: NormalizedRecordBudget | None = None,
) -> ParsedSource:
    budget = normalized_budget or NormalizedRecordBudget()
    try:
        canonical = path.resolve(strict=True)
        with canonical.open("rb") as source_file:
            before = os.fstat(source_file.fileno())
            if not os.path.isfile(canonical):
                _raise(OSError("not a regular file"))
            limit = min(max(0, byte_limit), MAX_SOURCE_BYTES)
            data = source_file.read(limit)
            after = os.fstat(source_file.fileno())
            source_file.seek(0)
            verify = source_file.read(len(data))
    except OSError as cause:
        raise Diagnose(
            "diagnose_source_invalid", f"cannot read Codex rollout: {cause}"
        ) from cause
    if (
        (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        or after.st_size < before.st_size
        or (after.st_size == before.st_size and before.st_mtime_ns != after.st_mtime_ns)
        or verify != data
    ):
        raise Diagnose(
            "diagnose_source_changed",
            "Codex rollout changed while it was being inspected",
        )
    source = SourceSnapshot(
        source_id=str(canonical),
        canonical_path=str(canonical),
        device=before.st_dev,
        inode=before.st_ino,
        length=before.st_size,
        modified_ns=before.st_mtime_ns,
        digest=_sha(data),
    )
    lines = data.splitlines(keepends=True)
    if not lines or not lines[0].endswith(b"\n") or len(lines[0]) > MAX_RECORD_BYTES:
        raise Diagnose(
            "diagnose_source_invalid",
            "Codex session metadata record is incomplete or too large",
        )
    try:
        header = parse_header(json.loads(lines[0]))
    except (ValueError, json.JSONDecodeError) as cause:
        raise Diagnose(
            "diagnose_source_invalid", f"invalid Codex session metadata: {cause}"
        ) from cause
    header.session.source_id = str(canonical)
    records: list[EvidenceRecord] = []
    warnings: list[str] = []
    malformed = omitted = processed = unknown = inherited = 0
    truncated = before.st_size > limit
    incomplete_tail = bool(data and not data.endswith(b"\n"))
    if truncated:
        warnings.append(
            f"Codex rollout exceeded the {MAX_SOURCE_BYTES} byte source limit"
        )
    boundary = header.forked_from_id
    boundary_seen = boundary is None
    inherited_remaining = _prefix_count(header) if boundary is None else 0
    turn_cwd = None
    byte_start = len(lines[0])
    for index, line in enumerate(lines[1:], 1):
        if not line.endswith(b"\n"):
            omitted += 1
            break
        raw = line[:-1]
        start = byte_start
        byte_start += len(line)
        if len(raw) > MAX_RECORD_BYTES:
            malformed += 1
            omitted += 1
            truncated = True
            warnings.append(f"record {index} exceeded the per-record byte limit")
            continue
        if not raw:
            continue
        try:
            value = json.loads(raw)
        except ValueError, UnicodeDecodeError:
            malformed += 1
            omitted += 1
            warnings.append(f"record {index} was malformed JSON and was omitted")
            continue
        if not isinstance(value, dict):
            malformed += 1
            omitted += 1
            continue
        if value.get("type") == "session_meta":
            payload = value.get("payload") or {}
            if isinstance(payload, dict) and (
                "history_base" in payload or "forked_from_id" in payload
            ):
                warning = (
                    "rollout contains copied session metadata for an inherited "
                    "history prefix"
                )
                warnings.append(warning)
                truncated = True
            continue
        kind = event_kind(value)
        if not boundary_seen:
            inherited += 1
            boundary_seen = native_id(value) == boundary or boundary_seen
            continue
        if inherited_remaining:
            inherited_remaining -= 1
            inherited += 1
            continue
        payload = _object(value.get("payload"))
        if kind == "turn_context":
            turn_cwd = payload.get("cwd") or turn_cwd
        if processed >= record_limit:
            omitted += 1
            truncated = True
            warnings.append(
                f"Codex rollout exceeded the {record_limit} aggregate record limit"
            )
            break
        anchor = RecordAnchor(
            str(canonical), index, start, start + len(raw), _sha(raw), native_id(value)
        )
        record = normalize_record(value, anchor, header.session.thread_id)
        if record.cwd is None:
            record.cwd = turn_cwd
        elif kind == "turn_context":
            turn_cwd = record.cwd
        processed += 1
        if not budget.try_add(record):
            omitted += 1
            truncated = True
            warning = (
                "Codex normalized records exceeded the shared snapshot byte budget; "
                "records were omitted"
            )
            if warning not in warnings:
                warnings.append(warning)
            continue
        records.append(record)
        unknown += kind not in KNOWN_EVENT_KINDS
    if incomplete_tail:
        omitted += 1
        warnings.append(
            "an incomplete final JSONL record was excluded from the verified prefix"
        )
    if not boundary_seen:
        truncated = True
        warnings.append("forked Codex history boundary was not present in the rollout")
    if unknown:
        warnings.append(
            "unknown Codex event types were retained as bounded excerpts and counted"
        )
    return ParsedSource(
        header,
        source,
        records,
        processed,
        incomplete_tail,
        malformed,
        omitted,
        unknown,
        inherited,
        truncated,
        warnings,
    )
