"""Bounded extraction of the latest usable context occupancy sample."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from .model import MAX_RECORD_BYTES

MAX_USAGE_BYTES = 1024 * 1024
MAX_USAGE_RECORDS = 2_000


class ContextUsageHarness(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    OPENCODE = "opencode"
    PI = "pi"


@dataclass(frozen=True)
class ContextUsage:
    current_tokens: int
    model: str | None = None
    context_window: int | None = None


def context_usage(
    harness: ContextUsageHarness | str,
    session_file: Path | str | None = None,
    direct_usage: dict[str, Any] | None = None,
) -> ContextUsage | None:
    harness = ContextUsageHarness(harness)
    direct = _parse_direct(harness, direct_usage) if direct_usage is not None else None
    if direct is not None:
        return direct
    if session_file is None:
        return None
    path = Path(session_file)
    if harness is ContextUsageHarness.OPENCODE and path.suffix == ".json":
        return _context_usage_from_export(path)
    if not _safe_usage_path(harness, path):
        return None
    records = _read_tail(path)
    return _parse_records(harness, records) if records is not None else None


def _parse_direct(
    harness: ContextUsageHarness, value: dict[str, Any]
) -> ContextUsage | None:
    if harness not in (ContextUsageHarness.OPENCODE, ContextUsageHarness.PI):
        return None
    usage = value.get("usage", value)
    keys = (
        ("input", "output", "reasoning", "cacheRead", "cacheWrite")
        if harness is ContextUsageHarness.OPENCODE
        else ("input", "output", "cacheRead", "cacheWrite")
    )
    total = _sum_fields(usage, keys)
    if total is None:
        return None
    model = value.get("model")
    model_id = (
        model.get("id", model.get("modelID")) if isinstance(model, dict) else None
    )
    model_id = model_id if isinstance(model_id, str) else value.get("modelID")
    window = model.get("contextWindow") if isinstance(model, dict) else None
    window = window if window is not None else value.get("contextWindow")
    return ContextUsage(
        total, model_id if isinstance(model_id, str) else None, _positive_int(window)
    )


def _parse_records(
    harness: ContextUsageHarness, records: list[Any]
) -> ContextUsage | None:
    latest = None
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("type") in {
            "compacted",
            "compaction",
            "compact_boundary",
            "session_reset",
        }:
            latest = None
            continue
        sample = _record_sample(harness, record)
        if sample is not None:
            latest = sample
    return latest


def _record_sample(harness: ContextUsageHarness, record: Any) -> ContextUsage | None:
    if not isinstance(record, dict):
        return None
    if harness is ContextUsageHarness.CODEX:
        payload = record.get("payload") or {}
        if payload.get("type") != "token_count":
            return None

        info = payload.get("info") or {}
        if "total_token_usage" in info:
            total = _sum_fields(
                info["total_token_usage"],
                (
                    "input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                    "cached_input_tokens",
                ),
            )
        else:
            total = _sum_fields(
                info.get("last_token_usage", {}),
                (
                    "input_tokens",
                    "output_tokens",
                    "reasoning_output_tokens",
                    "cached_input_tokens",
                ),
            )
        return (
            ContextUsage(
                total,
                info.get("model", payload.get("model")),
                _positive_int(info.get("model_context_window")),
            )
            if total is not None
            else None
        )
    if harness is ContextUsageHarness.CLAUDE:
        if record.get("type") not in {"assistant", "user"}:
            return None
        message = record.get("message") or {}
        usage = message.get("usage") or {}
        total = _sum_fields(
            usage,
            ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"),
        )
        return ContextUsage(total, message.get("model")) if total is not None else None
    if harness is ContextUsageHarness.OPENCODE:
        if record.get("type") != "message":
            return None
        message = record.get("message") or record
        tokens = message.get("tokens") or record.get("tokens") or {}
        total = _sum_fields(
            tokens,
            (
                "input",
                "output",
                "reasoning",
                "cache_read",
                "cacheRead",
                "cache_write",
                "cacheWrite",
            ),
        )
        return (
            ContextUsage(
                total,
                message.get("modelID", message.get("model_id")),
                _positive_int(message.get("model_context_window")),
            )
            if total is not None
            else None
        )
    if record.get("type") != "message":
        return None
    message = record.get("message") or {}
    if message.get("role") != "assistant":
        return None
    usage = message.get("usage") or {}
    total = _sum_fields(usage, ("input", "output", "cacheRead", "cacheWrite"))
    model = message.get("model") or {}
    return (
        ContextUsage(total, model.get("id"), _positive_int(model.get("contextWindow")))
        if total is not None
        else None
    )


def _context_usage_from_export(path: Path) -> ContextUsage | None:
    if not path.is_absolute():
        return None
    try:
        info = path.lstat()
        if (
            path.is_symlink()
            or not path.is_file()
            or info.st_size == 0
            or info.st_size > MAX_USAGE_BYTES
        ):
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    try:
        export = json.loads(raw)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None
    if not isinstance(export, dict) or not isinstance(export.get("info"), dict):
        return None
    session_id = export["info"].get("id")
    messages = export.get("messages")
    if (
        not isinstance(session_id, str)
        or not session_id
        or not isinstance(messages, list)
        or not 1 <= len(messages) <= MAX_USAGE_RECORDS
    ):
        return None
    latest = None
    for message in messages:
        if not isinstance(message, dict):
            continue
        if message.get("type") == "compaction":
            latest = None
            continue
        tokens = message.get("tokens")
        if not isinstance(tokens, dict):
            continue
        total = _sum_fields(tokens, ("input", "output", "reasoning"))
        cache_total = _sum_fields(tokens.get("cache"), ("read", "write"))
        if total is not None:
            total = min(2**64 - 1, total + (cache_total or 0))
            model = message.get("model")
            model_id = model.get("id") if isinstance(model, dict) else None
            latest = ContextUsage(
                total, model_id if isinstance(model_id, str) else None
            )
    return latest


def _sum_fields(value: Any, fields: tuple[str, ...]) -> int | None:
    if not isinstance(value, dict):
        return None
    present = [value[key] for key in fields if key in value]
    if not present or any(type(item) is not int or item < 0 for item in present):
        return None
    total = sum(present)
    return total if total <= 2**64 - 1 else None


def _positive_int(value: Any) -> int | None:
    return value if type(value) is int and 0 < value <= 2**64 - 1 else None


def _safe_usage_path(harness: ContextUsageHarness, path: Path) -> bool:
    try:
        if (
            not path.is_absolute()
            or path.name.endswith(".jsonl") is False
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size == 0
        ):
            return False
        parts = path.resolve(strict=True).parts
    except OSError:
        return False
    if harness is ContextUsageHarness.CODEX:
        return any(
            parts[index : index + 2] == (".codex", "sessions")
            for index in range(len(parts) - 1)
        )
    if harness is ContextUsageHarness.CLAUDE:
        return any(
            parts[index : index + 2] == (".claude", "projects")
            for index in range(len(parts) - 1)
        )
    if harness is ContextUsageHarness.OPENCODE:
        return ".opencode" in parts
    return any(
        parts[index : index + 3] == (".pi", "agent", "sessions")
        for index in range(len(parts) - 2)
    )


def _read_tail(path: Path) -> list[dict[str, Any]] | None:
    try:
        before = path.stat()
        with path.open("rb") as source:
            source.seek(max(0, before.st_size - MAX_USAGE_BYTES))
            data = source.read(MAX_USAGE_BYTES + 1)
        after = path.stat()
    except OSError:
        return None
    if (
        (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
        or len(data) != min(before.st_size, MAX_USAGE_BYTES)
        or len(data) > MAX_USAGE_BYTES
        or not data.endswith(b"\n")
    ):
        return None
    if before.st_size > MAX_USAGE_BYTES:
        boundary = data.find(b"\n")
        if boundary < 0:
            return None
        data = data[boundary + 1 :]
    records = []
    for line in data.splitlines():
        if not line:
            continue
        if len(line) > MAX_RECORD_BYTES or len(records) >= MAX_USAGE_RECORDS:
            return None
        try:
            item = json.loads(line)
        except UnicodeDecodeError, json.JSONDecodeError:
            return None
        records.append(item)
    return records or None
