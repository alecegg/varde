"""Bounded inspection and discovery of Pi coding-agent JSONL sessions."""

from __future__ import annotations

import hashlib
import heapq
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import (
    MAX_DISCOVERY_FILES,
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    SNAPSHOT_SCHEMA_VERSION,
    Coverage,
    CurrentOverlap,
    DiagnosticHarness,
    EvidenceRecord,
    Inspection,
    InspectionSnapshot,
    NormalizedRecordBudget,
    RecordAnchor,
    SessionMetadata,
    SnapshotIdentity,
    SourceSnapshot,
    register_harness,
)

MAX_TEXT_EXCERPT = 4096


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _bounded(text: str, limit: int) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _excerpt(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    )
    return _bounded(rendered, limit)


def _text(content: Any) -> str | None:
    if isinstance(content, str):
        return _bounded(content, MAX_TEXT_EXCERPT)
    if isinstance(content, list):
        values: list[str] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            value = block.get("text")
            if not isinstance(value, str):
                value = block.get("thinking")
            if isinstance(value, str):
                values.append(value)
        if values:
            return _bounded(" ".join(values), MAX_TEXT_EXCERPT)
    return None


def _parent_id(parent_path: str) -> str:
    stem = Path(parent_path).stem
    _timestamp, separator, session_id = stem.partition("_")
    return session_id if separator else stem


def _read_header(path: Path) -> dict[str, Any] | None:
    if path.is_symlink() or not path.is_file():
        return None
    try:
        with path.open("rb") as stream:
            raw = stream.readline(MAX_RECORD_BYTES + 1)
        if len(raw) > MAX_RECORD_BYTES or not raw.endswith(b"\n"):
            return None
        value = json.loads(raw)
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) and value.get("type") == "session" else None


def _read_bounded(path: Path) -> tuple[bytes, bool, int | None, int | None]:
    size = path.stat().st_size
    with path.open("rb") as stream:
        if size <= MAX_SOURCE_BYTES:
            return stream.read(MAX_SOURCE_BYTES), False, None, None
        edge = MAX_SOURCE_BYTES // 2
        head = stream.read(edge)
        stream.seek(size - edge)
        tail = stream.read(edge)
    # Drop partial edge records and retain the tail's real source offset.
    first_end = head.rfind(b"\n") + 1
    last_start = tail.find(b"\n") + 1
    head = head[:first_end]
    return head + tail[last_start:], True, len(head), size - edge + last_start


def _parse_records(
    path: Path,
    lines: list[bytes],
    session_id: str,
    cwd: str | None,
    tail_offset: int | None,
    tail_source_offset: int | None,
) -> tuple[list[EvidenceRecord], int, int, int]:
    records: list[EvidenceRecord] = []
    malformed = omitted = parsed = skipped = 0
    budget = NormalizedRecordBudget()
    offset = len(lines[0])
    thread = f"pi:{session_id}"
    for index, raw_line in enumerate(lines[1:], start=1):
        start = offset
        if tail_offset is not None and offset >= tail_offset:
            start = (tail_source_offset or 0) + offset - tail_offset
        offset += len(raw_line)
        if not raw_line.endswith(b"\n") or len(raw_line) - 1 > MAX_RECORD_BYTES:
            malformed += 1
            skipped += 1
            continue
        try:
            item = json.loads(raw_line)
        except UnicodeDecodeError, json.JSONDecodeError:
            malformed += 1
            skipped += 1
            continue
        if not isinstance(item, dict):
            malformed += 1
            skipped += 1
            continue
        if parsed >= MAX_RECORDS:
            omitted += 1
            skipped += 1
            continue
        anchor = RecordAnchor(
            str(path),
            index,
            start,
            start + len(raw_line) - 1,
            _digest(raw_line[:-1]),
            item.get("id"),
            session_id,
        )
        record = _normalize(item, anchor, thread, cwd)
        parsed += 1
        if not budget.try_add(record):
            omitted += 1
            skipped += 1
            continue
        records.append(record)
    return records, malformed, omitted, skipped


def _normalize(
    item: dict[str, Any],
    anchor: RecordAnchor,
    thread: str,
    cwd: str | None,
) -> EvidenceRecord:
    entry_type = item.get("type", "unknown")
    message_value = item.get("message")
    message: dict[str, Any] = {}
    if isinstance(message_value, dict):
        message = message_value
    role_value = message.get("role")
    role = role_value if isinstance(role_value, str) else None
    content = (
        message.get("content")
        if entry_type == "message"
        else item.get("summary", item.get("content"))
    )
    blocks = content if isinstance(content, list) else []
    tool_call: dict[str, Any] | None = None
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "toolCall":
            tool_call = block
            break
    tool_result = role == "toolResult"
    tool_name = message.get("toolName") if tool_result else None
    tool_id = message.get("toolCallId") if tool_result else None
    tool_input = None
    if tool_call is not None:
        tool_name = tool_call.get("name")
        tool_id = tool_call.get("id")
        tool_input = tool_call.get("arguments")
    tool_output = message.get("content") if tool_result else None
    is_error = bool(message.get("isError")) if tool_result else False
    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = None
    if entry_type == "message" and tool_call is not None:
        kind = "tool_call"
    elif entry_type == "message" and tool_result:
        kind = "tool_result"
    else:
        kind = str(entry_type)
    text = _text(content)
    if not text and role == "bashExecution":
        text = _text(
            "\n".join(str(message.get(key, "")) for key in ("command", "output"))
        )
    if not text and isinstance(item.get("data"), (dict, list, str)):
        text = _excerpt(item["data"], MAX_TEXT_EXCERPT)
    return EvidenceRecord(
        session_thread_id=thread,
        anchor=anchor,
        timestamp=item.get("timestamp"),
        kind=kind,
        role=role or ("system" if entry_type != "message" else None),
        text_excerpt=text,
        tool_name=tool_name if isinstance(tool_name, str) else None,
        tool_use_id=tool_id if isinstance(tool_id, str) else None,
        tool_input_excerpt=_excerpt(tool_input, 1024),
        tool_output_excerpt=_excerpt(tool_output, 1024),
        tool_status=("error" if is_error else "success") if tool_result else None,
        tool_error=_excerpt(tool_output, 1024) if is_error else None,
        parent_native_id=item.get("parentId"),
        branch_from_id=item.get("fromId") if entry_type == "branch_summary" else None,
        usage_record=usage,
        cwd=cwd,
        transcript_id=thread,
        provider_message_id=item.get("id"),
    )


def inspect_path(path: Path | str) -> InspectionSnapshot:
    source_path = Path(path)
    if source_path.is_symlink() or not source_path.is_file():
        raise ValueError("Pi transcript is not a regular file")
    canonical = source_path.resolve(strict=True)
    data, truncated, tail_offset, tail_source_offset = _read_bounded(canonical)
    lines = data.splitlines(keepends=True)
    header = {}
    if lines and lines[0].endswith(b"\n") and len(lines[0]) <= MAX_RECORD_BYTES:
        try:
            candidate = json.loads(lines[0])
            if isinstance(candidate, dict) and candidate.get("type") == "session":
                header = candidate
        except UnicodeDecodeError, json.JSONDecodeError:
            pass
    version = header.get("version", 1)
    supported = version == 3
    stat = canonical.stat()
    source = SourceSnapshot(
        str(canonical),
        str(canonical),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        None if truncated else _digest(data),
    )
    sid = str(header.get("id") or canonical.stem.rsplit("_", 1)[-1])
    thread = f"pi:{sid}"
    warnings: list[str] = []
    if not supported:
        skipped = max(0, len(lines) - 1)
        parsed = malformed = omitted = 0
        records = []
        warnings.append("skipped: unsupported session version")
    else:
        records, malformed, omitted, skipped = _parse_records(
            canonical, lines, sid, header.get("cwd"), tail_offset, tail_source_offset
        )
        parsed = len(records)
    parent_path = header.get("parentSession")
    parent = _parent_id(parent_path) if isinstance(parent_path, str) else None
    warnings.append(f"Pi parse stats: parsed {parsed}, skipped {skipped} records")
    if truncated:
        warnings.append(
            "Pi transcript exceeded the source byte limit; head and tail were read"
        )
    complete = not truncated and not malformed and not omitted and supported
    coverage = Coverage(
        complete=complete,
        source_complete=complete,
        analysis_ready=False,
        cutoff_verified=False,
        cutoff_anchor=None,
        incomplete_tail=False,
        truncated=truncated or bool(omitted),
        record_count=len(records),
        malformed_records=malformed,
        omitted_records=omitted,
        warnings=warnings,
        skipped_records=skipped,
    )
    session = SessionMetadata(
        "pi",
        thread,
        sid,
        f"pi:{parent}" if parent else None,
        f"Pi parentSession: {parent_path}" if parent else None,
        header.get("timestamp"),
        header.get("cwd"),
        None,
        None,
        None,
        source.source_id,
        thread,
    )
    payload = {
        "session": asdict(session),
        "records": [asdict(r) for r in records],
        "coverage": asdict(coverage),
    }
    digest = _digest(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    )
    return InspectionSnapshot(
        SNAPSHOT_SCHEMA_VERSION,
        digest,
        session,
        [],
        [source],
        records,
        CurrentOverlap.UNKNOWN,
        coverage,
    )


def _in_repo(cwd: str, repo: Path) -> bool:
    try:
        return os.path.commonpath(
            (str(Path(cwd).resolve()), str(repo.resolve()))
        ) == str(repo.resolve())
    except OSError, ValueError:
        return False


class PiHarness:
    harness = DiagnosticHarness.PI

    def discover(self, *, repo: Path, roots: dict[str, Any], limit: int) -> list[Any]:
        root = roots.get("pi")
        if limit <= 0 or not root or not Path(root).is_dir():
            return []
        found = []
        candidates = heapq.nsmallest(
            MAX_DISCOVERY_FILES,
            Path(root).glob("--*--/*.jsonl"),
            key=str,
        )
        for path in candidates:
            header = _read_header(path)
            if not header or header.get("version") != 3:
                continue
            cwd = header.get("cwd")
            if not isinstance(cwd, str) or not _in_repo(cwd, repo):
                continue
            session_id = header.get("id")
            if not isinstance(session_id, str) or not session_id:
                session_id = path.stem.rsplit("_", 1)[-1]
            parent_path = header.get("parentSession")
            parent = _parent_id(parent_path) if isinstance(parent_path, str) else None
            found.append(
                {
                    "harness": "pi",
                    "identity": f"pi:{session_id}",
                    "session_id": session_id,
                    "aliases": [session_id],
                    "parent_identity": f"pi:{parent}" if parent else None,
                    "parent_known": True,
                    "kind": "main",
                    "started_at": header.get("timestamp"),
                    "cwd": cwd,
                    "retro_analyst": False,
                    "source": str(path),
                }
            )
            if len(found) >= limit:
                break
        return found

    def inspect(self, request: Any) -> Inspection:
        path = (
            request.get("path")
            if isinstance(request, dict)
            else getattr(request, "path", None)
        )
        if not path:
            raise ValueError("Pi transcript path was not specified")
        snapshot = inspect_path(path)
        return Inspection(
            snapshot.session,
            snapshot.children,
            snapshot.sources,
            snapshot.records,
            snapshot.overlap,
            snapshot.coverage,
            SnapshotIdentity(snapshot.digest),
        )


register_harness(PiHarness())
