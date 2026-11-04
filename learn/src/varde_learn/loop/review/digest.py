"""Build bounded, deterministic, redacted daily review context."""

from collections.abc import Sequence

from varde_learn.loop.diagnose.model import EvidenceRecord

from .redact import redact

_FIELD_LIMIT = 480


def build_digest(records: Sequence[EvidenceRecord], max_chars: int) -> str:
    """Render normalized records with record-index anchors within a character budget."""
    if max_chars <= 0:
        return ""
    lines: list[str] = []
    size = 0
    for fallback_index, record in enumerate(records):
        line = _render_record(record, record.anchor.record_index or fallback_index)
        separator_size = int(bool(lines))
        if size + separator_size + len(line) > max_chars:
            break
        lines.append(line)
        size += separator_size + len(line)
    return "\n".join(lines)


def _render_record(record: EvidenceRecord, index: int) -> str:
    parts = [f"[{index}]"]
    text = record.text_excerpt
    if record.role == "user" and text:
        parts.append("user: " + _bounded(text))
    elif record.role == "assistant" and text:
        parts.append("assistant: " + _bounded(text))
    if record.tool_name:
        parts.append(_tool_part(record))
    return redact(" ".join(parts))


def _tool_part(record: EvidenceRecord) -> str:
    parts = ["tool: " + _bounded(record.tool_name or "", 128) + _tool_markers(record)]
    output = record.tool_output_excerpt
    if not output:
        return " ".join(parts)
    output = redact(output)
    length = record.tool_output_length_bytes
    is_oversized = record.detail_truncated or (
        length is not None and length > len(output.encode("utf-8"))
    )
    if is_oversized:
        parts.append(f"output: [oversized output, {length or 'unknown'} bytes]")
    else:
        parts.append("output: " + _bounded(output))
    return " ".join(parts)


def _tool_markers(record: EvidenceRecord) -> str:
    status = (record.tool_status or "").lower().replace("_", " ")
    error = (record.tool_error or "").lower()
    reason = (record.failure_reason or "").lower()
    markers = []
    if status in {"error", "failed", "failure"} or error:
        markers.append("failure")
    if "retry" in reason or "retry" in status:
        markers.append("retry")
    timed_out = "timeout" in status or "timed out" in status
    timed_out = timed_out or "timeout" in error or "timed out" in error
    if timed_out:
        markers.append("timeout")
    return f" ({','.join(markers)})" if markers else ""


def _bounded(value: str, limit: int = _FIELD_LIMIT) -> str:
    safe = redact(value).replace("\n", " ").replace("\r", " ")
    return safe if len(safe) <= limit else safe[:limit] + "…"
