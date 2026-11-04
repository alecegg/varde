"""Pure helpers for rendering and summarizing permission guard audit data."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

_SECRET_FIELD_NAME = re.compile(
    r"(?:token|secret|password|passwd|credential|api.?key)", re.IGNORECASE
)
_SECRET_ASSIGNMENT = re.compile(
    r"\\?[\"']?[A-Za-z0-9_]*(?:token|secret|password|passwd|credential|api.?key)"
    r"[A-Za-z0-9_]*\\?[\"']?\s*[:=]\s*"
    r"(?:\\?\"[^\"\\]*\\?\"|'[^']*'|[^\s,;}]+)",
    re.IGNORECASE,
)
_SECRET_OPTION = re.compile(
    r"--(?:token|secret|password|passwd|credential|api.?key)"
    r"(?:\s*=\s*|\s+)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
    re.IGNORECASE,
)
_SECRET_PATTERNS = (
    re.compile(r"(?i)authorization\s*:\s*(?:bearer|basic)\s+\S+"),
    re.compile(r"(?i)sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)github_pat_[A-Za-z0-9_]+"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]+"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)(?<!\S)-p\s*(?:\"[^\"]*\"|'[^']*'|\S+)"),
    re.compile(r"(?i)([^:/@\s]+):([^/@\s]+)@"),
)


def redact_prompt(payload: Any) -> str:
    """Serialize a prompt payload while removing secret-like values."""
    if isinstance(payload, str):
        text = payload
    else:
        text = json.dumps(_redact(payload), ensure_ascii=False, sort_keys=True)
    text = _SECRET_ASSIGNMENT.sub("[redacted]", text)
    text = _SECRET_OPTION.sub("[redacted]", text)
    for pattern in _SECRET_PATTERNS[:-1]:
        text = pattern.sub("[redacted]", text)
    text = _SECRET_PATTERNS[-1].sub(r"\1:[redacted]@", text)
    return text[:2000]


def _redact(value: Any, field: str = "") -> Any:
    if _SECRET_FIELD_NAME.search(field):
        return "[redacted]"
    if isinstance(value, dict):
        return {key: _redact(item, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return value
    return value


def approvals_by_pattern(
    rows: list[dict[str, Any]], revoked: frozenset[str]
) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = row.get("request_key")
        if key and row.get("verdict") == "approve":
            grouped[str(key)].append(row)
    result = []
    for key, approvals in grouped.items():
        result.append(
            {
                "request_key": key,
                "count": len(approvals),
                "last_ts": max(str(row.get("ts", "")) for row in approvals),
                "revoked": key in revoked,
            }
        )
    return sorted(result, key=lambda item: item["request_key"])
