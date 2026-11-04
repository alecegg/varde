"""Bounded inspection and discovery of Claude Code JSONL sessions."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .model import (
    MAX_DISCOVERY_FILES,
    MAX_FAMILY,
    MAX_FAMILY_SOURCE_BYTES,
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    MAX_SNAPSHOT_BYTES,
    MAX_SOURCE_BYTES,
    NORMALIZED_RECORD_BUDGET_BYTES,
    SNAPSHOT_SCHEMA_VERSION,
    ChildSession,
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
    ToolObservation,
    register_harness,
    rendered_length_bytes,
)

MAX_WARNINGS = 100
MAX_TEXT_EXCERPT = 4096
MAX_USAGE_FALLBACK_BYTES = MAX_SNAPSHOT_BYTES - NORMALIZED_RECORD_BUDGET_BYTES
MAX_USAGE_RECORD_BUDGET_BYTES = NORMALIZED_RECORD_BUDGET_BYTES // 4
MAX_USAGE_SCAN_BYTES = MAX_SOURCE_BYTES * MAX_FAMILY


class _ClaudeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class _Sidecar:
    tool_use_id: str
    parent_agent_id: str | None


@dataclass
class _Parsed:
    source: SourceSnapshot
    started_at: str | None
    cwd: str | None
    records: list[EvidenceRecord]
    usage_supplements: list[EvidenceRecord]
    processed: int
    incomplete_tail: bool
    malformed: int
    omitted: int
    truncated: bool
    warnings: list[str]
    unknown: bool
    identity_incomplete: bool


def _fail(code: str, message: str) -> ValueError:
    return _ClaudeError(code, message)


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _bounded(text: str, limit: int) -> str:
    return text[:limit] + ("…" if len(text) > limit else "")


def _parse_source_record(
    raw: bytes,
    index: int,
    offset: int,
    path: Path,
    identity: tuple[str, str, str, str | None, str | None, str | None],
) -> tuple[EvidenceRecord | None, bool, bool]:
    if len(raw) > MAX_RECORD_BYTES:
        return None, True, True
    try:
        item = json.loads(raw)
    except UnicodeDecodeError, json.JSONDecodeError:
        return None, True, False
    session, thread, transcript, agent, parent_agent, parent_tool = identity
    if item.get("sessionId") not in (None, session):
        raise _fail(
            "diagnose_source_invalid",
            "Claude transcript contains a conflicting sessionId",
        )
    canonical = path.resolve(strict=True)
    anchor = RecordAnchor(
        str(canonical),
        index,
        offset,
        offset + len(raw),
        _digest(raw),
        item.get("uuid"),
        session,
    )
    return (
        normalize_record(
            item, anchor, thread, transcript, agent, parent_agent, parent_tool
        ),
        False,
        False,
    )


def _excerpt(value: Any, limit: int) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, separators=(",", ":"), ensure_ascii=False)
    )
    return _bounded(rendered, limit), len(rendered) > limit


def normalize_record(
    value: dict[str, Any],
    anchor: RecordAnchor,
    thread_id: str,
    transcript_id: str | None = None,
    agent_id: str | None = None,
    parent_agent_id: str | None = None,
    parent_tool_use_id: str | None = None,
) -> EvidenceRecord:
    type_value = value.get("type")
    top_type = type_value if isinstance(type_value, str) else "unknown"
    message_value = value.get("message")
    message = message_value if isinstance(message_value, dict) else {}
    role = message.get("role") if isinstance(message.get("role"), str) else None
    content = message.get("content")
    blocks: list[Any] = content if isinstance(content, list) else []
    use = next(
        (b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_use"), None
    )
    result = next(
        (b for b in blocks if isinstance(b, dict) and b.get("type") == "tool_result"),
        None,
    )
    kind: str = (
        "tool_result"
        if result
        else "tool_call"
        if use
        else "progress"
        if top_type == "progress"
        else "message"
        if top_type in {"assistant", "user", "system"}
        else top_type
    )
    texts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        text_value = block.get("text", block.get("content"))
        if isinstance(text_value, str):
            texts.append(text_value)
    if isinstance(content, str):
        text = _bounded(content, MAX_TEXT_EXCERPT)
    elif texts:
        text = _bounded(" ".join(texts), MAX_TEXT_EXCERPT)
    elif top_type == "progress":
        text, _ = _excerpt(
            (value.get("data") or {}).get("message", value.get("data")),
            MAX_TEXT_EXCERPT,
        )
    else:
        text = None
    tool_id = (use or {}).get("id") or (result or {}).get("tool_use_id")
    name = use.get("name") if use and isinstance(use.get("name"), str) else None
    inp, input_cut = _excerpt(use.get("input") if use else None, 1024)
    out, output_cut = _excerpt(result.get("content") if result else None, 1024)
    output_length_bytes = rendered_length_bytes(
        result.get("content") if result else None
    )
    failed = bool(result and result.get("is_error") is True)
    observations = []
    for block in blocks:
        if not isinstance(block, dict) or block.get("type") not in {
            "tool_use",
            "tool_result",
        }:
            continue
        is_result = block["type"] == "tool_result"
        obs_input, cut_in = _excerpt(block.get("input"), 1024)
        obs_output, cut_out = _excerpt(
            block.get("content") if is_result else None, 1024
        )
        is_error = is_result and block.get("is_error") is True
        observations.append(
            ToolObservation(
                block_type=block["type"],
                tool_use_id=block.get("tool_use_id") if is_result else block.get("id"),
                tool_name=_bounded(block["name"], 128)
                if isinstance(block.get("name"), str)
                else None,
                input_excerpt=obs_input,
                output_excerpt=obs_output,
                status=("error" if is_error else "success") if is_result else None,
                error=obs_output if is_error else None,
                detail_truncated=cut_in or cut_out,
            )
        )
    usage = message.get("usage")
    usage = (
        {
            key: val
            for key, val in usage.items()
            if key
            in {
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            }
            and type(val) in (int, float)
        }
        if isinstance(usage, dict)
        else None
    )
    known_blocks = all(
        isinstance(b, dict)
        and b.get("type")
        in {
            "text",
            "tool_use",
            "tool_result",
            "thinking",
            "redacted_thinking",
            "image",
            "document",
        }
        for b in blocks
    )
    known = top_type in {"assistant", "user", "system", "progress"} and (
        top_type == "progress" or known_blocks
    )
    unknown, unknown_cut = (None, False) if known else _excerpt(value, 512)
    return EvidenceRecord(
        session_thread_id=thread_id,
        anchor=anchor,
        timestamp=value.get("timestamp"),
        kind=kind,
        role=role,
        text_excerpt=text,
        tool_name=_bounded(name, 128) if name else None,
        tool_input_excerpt=inp,
        tool_output_excerpt=out,
        tool_output_length_bytes=output_length_bytes,
        tool_status=("error" if failed else "success") if result else None,
        tool_error=out if failed else None,
        tool_observations=observations,
        detail_truncated=input_cut
        or output_cut
        or unknown_cut
        or any(o.detail_truncated for o in observations),
        unknown_payload_excerpt=unknown,
        response_id=message.get("id"),
        cwd=value.get("cwd"),
        usage_record=usage,
        transcript_id=transcript_id,
        provider_message_id=message.get("id"),
        agent_id=value.get("agentId") or agent_id,
        parent_agent_id=parent_agent_id,
        parent_native_id=value.get("parentUuid"),
        tool_use_id=tool_id,
        parent_tool_use_id=parent_tool_use_id,
        is_sidechain=value.get("isSidechain"),
        is_meta=value.get("isMeta"),
        is_compact_summary=value.get("isCompactSummary"),
        timestamp_raw=value.get("timestamp"),
    )


def _read_source(
    path: Path,
    limit: int,
    identity: tuple[str, str, str, str | None, str | None, str | None],
    budget: NormalizedRecordBudget,
    record_limit: int,
) -> _Parsed:
    if path.is_symlink() or not path.is_file():
        raise _fail(
            "diagnose_source_invalid", "Claude transcript is not a regular file"
        )
    before = path.stat()
    with path.open("rb") as source_file:
        data = source_file.read(limit + 1)
    initially_truncated = len(data) > limit
    data = data[:limit]
    after = path.stat()
    if (
        (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        or after.st_size < before.st_size
        or (after.st_size == before.st_size and before.st_mtime_ns != after.st_mtime_ns)
    ):
        raise _fail(
            "diagnose_source_changed",
            "Claude transcript changed while it was being inspected",
        )
    lines = data.splitlines(keepends=True)
    if (
        not lines
        or not lines[0].endswith(b"\n")
        or len(lines[0]) - 1 > MAX_RECORD_BYTES
    ):
        raise _fail(
            "diagnose_source_invalid",
            "Claude transcript header is incomplete or too large",
        )
    try:
        header = json.loads(lines[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(
            "diagnose_source_invalid", f"invalid Claude transcript header: {exc}"
        ) from exc
    session, thread, transcript, agent, _, _ = identity
    if header.get("sessionId") != session:
        raise _fail(
            "diagnose_source_invalid",
            "Claude transcript sessionId conflicts with its selected filename",
        )
    canonical = path.resolve(strict=True)
    st = canonical.stat()
    source = SourceSnapshot(
        str(canonical),
        str(canonical),
        st.st_dev,
        st.st_ino,
        st.st_size,
        st.st_mtime_ns,
        _digest(data),
        session_thread_id=thread,
        transcript_id=transcript,
    )
    records, warnings = [], []
    usage_supplements: dict[str, EvidenceRecord] = {}
    malformed = omitted = processed = 0
    truncated = initially_truncated
    unknown = identity_incomplete = False
    offset = 0
    budget_warned = False
    usage_fallback_bytes = MAX_USAGE_FALLBACK_BYTES
    for index, line in enumerate(lines):
        if not line.endswith(b"\n"):
            omitted += 1
            break
        raw = line[:-1]
        start = offset
        offset += len(line)
        record, malformed_record, oversized_record = _parse_source_record(
            raw, index, start, path, identity
        )
        if malformed_record:
            malformed += 1
            omitted += 1
            truncated |= oversized_record
            continue
        if record is None:
            malformed += 1
            omitted += 1
            continue
        if processed >= record_limit:
            omitted += 1
            truncated = True
            compact = _compact_usage_record(record)
            if compact is not None and not _retain_usage_record(
                usage_supplements, compact
            ):
                warnings.append("Claude usage supplements reached their record limit")
                truncated = True
            continue
        record_unknown, record_identity_incomplete = _record_completeness(
            record, index, agent, warnings
        )
        unknown |= record_unknown
        identity_incomplete |= record_identity_incomplete
        processed += 1
        content_limit = NORMALIZED_RECORD_BUDGET_BYTES - MAX_USAGE_RECORD_BUDGET_BYTES
        action, retained, usage_fallback_bytes = _fit_record(
            record, budget, content_limit, usage_fallback_bytes
        )
        if retained is not None and action != "supplement":
            records.append(retained)
        elif (
            action == "supplement"
            and retained is not None
            and not _retain_usage_record(usage_supplements, retained)
        ):
            warnings.append("Claude usage supplements reached their record limit")
            truncated = True
        if action in {"record", "compact", "supplement"}:
            if action != "record":
                omitted += 1
                truncated = True
            continue
        omitted += 1
        truncated = True
        if not budget_warned:
            warnings.append(
                (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                    "Claude normalized records exceeded the shared snapshot "
                    "byte budget; records were omitted"
                )
            )
            budget_warned = True
    incomplete = bool(data and not data.endswith(b"\n"))
    if incomplete:
        warnings.append("Claude transcript ends with an incomplete JSONL record")
    if initially_truncated:
        warnings.append(f"Claude transcript exceeded the {limit} byte source limit")
    return _Parsed(
        source,
        header.get("timestamp"),
        header.get("cwd"),
        records,
        list(usage_supplements.values()),
        processed,
        incomplete,
        malformed,
        omitted,
        truncated,
        warnings,
        unknown,
        identity_incomplete,
    )


def _compact_usage_record(record: EvidenceRecord) -> EvidenceRecord | None:
    if record.usage_record is None:
        return None
    return replace(
        record,
        text_excerpt=None,
        tool_input_excerpt=None,
        tool_output_excerpt=None,
        tool_output_length_bytes=None,
        tool_observations=[],
        tool_error=None,
        unknown_payload_excerpt=None,
        detail_truncated=True,
    )


def _record_completeness(
    record: EvidenceRecord, index: int, agent: str | None, warnings: list[str]
) -> tuple[bool, bool]:
    identity_incomplete = False
    if record.anchor.native_id is None:
        identity_incomplete = True
        warnings.append(f"Claude record {index} has no native UUID identity")
    if agent and record.agent_id and record.agent_id != agent:
        identity_incomplete = True
        warnings.append(
            f"Claude child `{agent}` record {index} has a conflicting native agent ID"
        )
    return record.unknown_payload_excerpt is not None, identity_incomplete


def _fit_record(
    record: EvidenceRecord,
    budget: NormalizedRecordBudget,
    content_limit: int,
    fallback_bytes: int,
) -> tuple[str, EvidenceRecord | None, int]:
    size = _serialized_record_size(record)
    if budget.used_bytes + size <= content_limit and budget.try_add(record):
        return "record", record, fallback_bytes
    compact = _compact_usage_record(record)
    if compact is None:
        return "omit", None, fallback_bytes
    if budget.try_add(compact):
        return "compact", compact, fallback_bytes
    compact_size = _serialized_record_size(compact)
    if compact_size <= fallback_bytes:
        return "compact", compact, fallback_bytes - compact_size
    return "supplement", compact, fallback_bytes


def _usage_key(record: EvidenceRecord) -> str:
    identity = record.provider_message_id or record.anchor.native_id
    return identity or f"@{record.anchor.source_id}:{record.anchor.byte_start}"


def _retain_usage_record(
    records: dict[str, EvidenceRecord], record: EvidenceRecord
) -> bool:
    key = _usage_key(record)
    previous = records.get(key)
    if previous is None and len(records) >= MAX_RECORDS:
        return False
    if previous is None or (record.usage_record or {}).get("output_tokens", 0) >= (
        previous.usage_record or {}
    ).get("output_tokens", 0):
        records[key] = record
    return True


def _serialized_record_size(record: EvidenceRecord) -> int:
    return len(json.dumps(asdict(record), separators=(",", ":"), default=str))


def _read_usage_line(
    source: Any, read_bytes: int, limit: int
) -> tuple[bytes, int, str]:
    """Read one line; status is ok, oversized (skipped), over_limit, or eof."""
    line = source.readline(MAX_RECORD_BYTES + 2)
    if not line:
        return line, read_bytes, "eof"
    read_bytes += len(line)
    if read_bytes > limit:
        return line, read_bytes, "over_limit"
    if len(line.rstrip(b"\r\n")) <= MAX_RECORD_BYTES:
        return line.rstrip(b"\r\n"), read_bytes, "ok"
    while line and not line.endswith(b"\n") and read_bytes <= limit:
        line = source.readline(64 * 1024)
        read_bytes += len(line)
    return b"", read_bytes, "over_limit" if read_bytes > limit else "oversized"


def _is_usage_item(item: Any) -> bool:
    if not isinstance(item, dict) or item.get("type") != "assistant":
        return False
    message = item.get("message")
    return isinstance(message, dict) and isinstance(message.get("usage"), dict)


def _keep_max_output(
    records: dict[str, EvidenceRecord], compact: EvidenceRecord
) -> bool:
    """Keep the max-output snapshot per id; True when dropped at the record cap."""
    key = _usage_key(compact)
    previous = records.get(key)
    output = (compact.usage_record or {}).get("output_tokens", 0)
    if previous is not None and output < (previous.usage_record or {}).get(
        "output_tokens", 0
    ):
        return False
    if previous is None and len(records) >= MAX_RECORDS:
        return True
    records[key] = compact
    return False


def _read_usage_records(
    path: Path,
    identity: tuple[str, str, str, str | None, str | None, str | None],
    limit: int,
) -> tuple[list[EvidenceRecord], int, bool]:
    session, thread, transcript, agent, parent_agent, parent_tool = identity
    canonical = path.resolve(strict=True)
    records: dict[str, EvidenceRecord] = {}
    read_bytes = 0
    truncated = False
    with canonical.open("rb") as source:
        index = -1
        while True:
            offset = read_bytes
            raw, read_bytes, status = _read_usage_line(source, read_bytes, limit)
            if status in ("eof", "over_limit"):
                truncated = truncated or status == "over_limit"
                break
            index += 1
            if status == "oversized":
                truncated = True
                continue
            try:
                item = json.loads(raw)
            except UnicodeDecodeError, json.JSONDecodeError:
                continue
            if not _is_usage_item(item):
                continue
            anchor = RecordAnchor(
                str(canonical),
                index,
                offset,
                offset + len(raw),
                _digest(raw),
                item.get("uuid"),
                session,
            )
            record = normalize_record(
                item, anchor, thread, transcript, agent, parent_agent, parent_tool
            )
            compact = _compact_usage_record(record)
            if compact is not None:
                truncated = _keep_max_output(records, compact) or truncated
    return list(records.values()), read_bytes, truncated


def _scan_large_main_usage(
    path: Path,
    parsed: _Parsed,
    identity: tuple[str, str, str, str | None, str | None, str | None],
) -> tuple[list[EvidenceRecord], int]:
    if (parsed.source.length or 0) <= MAX_SOURCE_BYTES:
        return list(parsed.usage_supplements), 0
    records, read_bytes, truncated = _read_usage_records(
        path, identity, MAX_USAGE_SCAN_BYTES
    )
    parsed.records = [
        replace(record, usage_record=None)
        if record.usage_record is not None
        else record
        for record in parsed.records
    ]
    if truncated:
        parsed.warnings.append("Claude usage scan reached its byte or record limit")
        parsed.truncated = True
    return records or list(parsed.usage_supplements), read_bytes


def _sidecar(path: Path) -> _Sidecar | None:
    try:
        value = json.loads(path.read_text())
    except OSError, UnicodeDecodeError, json.JSONDecodeError:
        return None
    tool_id = value.get("toolUseId")
    if not isinstance(tool_id, str) or not tool_id:
        return None
    parent = value.get("parentAgentId")
    return _Sidecar(tool_id, parent if isinstance(parent, str) else None)


def _child_files(root: Path) -> tuple[list[tuple[Path, str, _Sidecar | None]], bool]:
    if not root.exists():
        return [], False
    found, uncertain = [], False
    try:
        for path in sorted(root.iterdir()):
            if path.name.endswith(".meta.json") or path.name.startswith(".DS_Store"):
                continue
            if (
                path.is_symlink()
                or not path.is_file()
                or not path.name.startswith("agent-")
                or path.suffix != ".jsonl"
            ):
                uncertain = True
                continue
            agent = path.stem[6:]
            if not agent:
                uncertain = True
                continue
            found.append((path, agent, _sidecar(path.with_suffix(".meta.json"))))
    except OSError:
        return [], True
    return found, uncertain


def _snapshot(root: Path, main_path: Path, session_id: str) -> InspectionSnapshot:
    root = root.resolve(strict=True)
    main_path = main_path.resolve(strict=True)
    project = main_path.parent
    if project.parent != root or main_path.name != f"{session_id}.jsonl":
        raise _fail(
            "diagnose_source_invalid",
            "Claude main transcript identity does not match its project path",
        )
    namespace = project.name
    thread = f"claude:{namespace}:{session_id}"
    transcript = f"{thread}:main"
    budget = NormalizedRecordBudget()
    main = _read_source(
        main_path,
        MAX_SOURCE_BYTES,
        (session_id, thread, transcript, None, None, None),
        budget,
        MAX_RECORDS,
    )
    usage_supplements, usage_scan_bytes = _scan_large_main_usage(
        main_path, main, (session_id, thread, transcript, None, None, None)
    )
    files, uncertain = _child_files(project / session_id / "subagents")
    family_truncated = len(files) > MAX_FAMILY
    files = files[:MAX_FAMILY]
    children, sources, records = [], [main.source], list(main.records)
    warnings = list(main.warnings)
    complete = not (
        main.truncated
        or main.incomplete_tail
        or main.malformed
        or main.identity_incomplete
    )
    if main.unknown:
        complete = False
        warnings.append(
            (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                "unknown Claude event types were retained as bounded excerpts; "
                "event semantics are incomplete"
            )
        )
    if uncertain:
        complete = False
        warnings.append("Claude subagent discovery or sidecar linkage is incomplete")
    if family_truncated:
        complete = False
        warnings.append(
            f"Claude child family exceeded the {MAX_FAMILY} transcript limit"
        )
    total_bytes, processed, malformed, omitted = (
        main.source.length or 0,
        main.processed,
        main.malformed,
        main.omitted,
    )
    incomplete, truncated = main.incomplete_tail, main.truncated or family_truncated
    for path, agent, sidecar in files:
        remaining = MAX_FAMILY_SOURCE_BYTES - total_bytes
        rel = path.relative_to(project / session_id).as_posix()
        child_transcript = f"{thread}:agent:{agent}:{rel}"
        child_identity = (
            session_id,
            child_transcript,
            child_transcript,
            agent,
            sidecar.parent_agent_id if sidecar else None,
            sidecar.tool_use_id if sidecar else None,
        )
        if remaining <= 0:
            complete = False
            truncated = True
            warnings.append(
                "Claude child family reached its aggregate source-byte limit"
            )
            usage_remaining = MAX_USAGE_SCAN_BYTES - usage_scan_bytes
            if usage_remaining > 0:
                child_usage, scanned, usage_limited = _read_usage_records(
                    path, child_identity, usage_remaining
                )
                usage_supplements.extend(child_usage)
                usage_scan_bytes += scanned
                if usage_limited:
                    warnings.append(
                        "Claude usage scan reached its byte or record limit"
                    )
                    truncated = True
            continue
        child = _read_source(
            path,
            min(remaining, MAX_SOURCE_BYTES),
            child_identity,
            budget,
            MAX_RECORDS - processed,
        )
        total_bytes += child.source.length or 0
        child_usage = child.usage_supplements
        if (child.source.length or 0) > min(remaining, MAX_SOURCE_BYTES):
            usage_remaining = MAX_USAGE_SCAN_BYTES - usage_scan_bytes
            if usage_remaining > 0:
                child_usage, scanned, usage_limited = _read_usage_records(
                    path, child_identity, usage_remaining
                )
                usage_scan_bytes += scanned
                if usage_limited:
                    warnings.append(
                        "Claude usage scan reached its byte or record limit"
                    )
                    truncated = True
            child.records = [
                replace(record, usage_record=None)
                if record.usage_record is not None
                else record
                for record in child.records
            ]
        if not sidecar:
            complete = False
            warnings.append(
                f"Claude child `{agent}` has missing or invalid .meta.json linkage"
            )
        if (
            child.truncated
            or child.incomplete_tail
            or child.malformed
            or child.unknown
            or child.identity_incomplete
        ):
            complete = False
        children.append(
            ChildSession(
                child_transcript,
                child.source.source_id,
                None,
                child.started_at,
                "Claude .meta.json toolUseId"
                if sidecar
                else "unverified Claude child sidecar",
                child_transcript,
                agent,
                sidecar.parent_agent_id if sidecar else None,
                sidecar.tool_use_id if sidecar else None,
            )
        )
        sources.append(child.source)
        records.extend(child.records)
        usage_supplements.extend(child_usage)
        processed += child.processed
        incomplete |= child.incomplete_tail
        malformed += child.malformed
        omitted += child.omitted
        truncated |= child.truncated
        warnings.extend(child.warnings)
    agent_threads: dict[str, list[str]] = {}
    for child in children:
        agent_threads.setdefault(child.agent_id or "", []).append(child.thread_id)
    tool_calls = {
        (r.session_thread_id, r.tool_use_id) for r in records if r.tool_use_id
    }
    for child in children:
        if not child.parent_tool_use_id:
            complete = False
            child.relationship_evidence = "Claude child parent link is missing"
            continue
        parent = (
            thread
            if not child.parent_agent_id
            else (
                agent_threads.get(child.parent_agent_id, [None])[0]
                if len(agent_threads.get(child.parent_agent_id, [])) == 1
                else None
            )
        )
        if parent and (parent, child.parent_tool_use_id) in tool_calls:
            child.parent_thread_id = parent
            child.relationship_evidence = (
                "Claude sidecar toolUseId matched the parent transcript"
            )
        else:
            complete = False
            child.relationship_evidence = (
                "Claude sidecar toolUseId did not match a parent tool call"
            )
            warnings.append(
                (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                    f"Claude child `{child.agent_id or 'unknown'}` toolUseId "
                    "could not be verified in its parent transcript"
                )
            )
    _deduplicate_usage([*records, *usage_supplements], warnings, lambda: None)
    usage_supplements = [item for item in usage_supplements if item.usage_record]
    warnings = warnings[:MAX_WARNINGS]
    coverage = Coverage(
        complete,
        complete,
        False,
        False,
        None,
        incomplete,
        truncated,
        len(records),
        malformed,
        omitted,
        warnings=warnings,
    )
    session = SessionMetadata(
        "claude",
        thread,
        session_id,
        None,
        None,
        main.started_at,
        main.cwd,
        None,
        None,
        None,
        sources[0].source_id,
        transcript,
        project_namespace=namespace,
    )
    payload = {
        "session": asdict(session),
        "children": [asdict(c) for c in children],
        "sources": [asdict(s) for s in sources],
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
        children,
        sources,
        records,
        CurrentOverlap.UNKNOWN,
        coverage,
        usage_records=usage_supplements,
    )


def _deduplicate_usage(
    records: list[EvidenceRecord], warnings: list[str], unused: Any
) -> None:
    latest: dict[tuple[str, str], int] = {}
    for index, record in enumerate(records):
        if record.usage_record is None:
            continue
        message_id = record.provider_message_id or record.anchor.native_id
        if not message_id:
            warnings.append(
                (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                    "Claude usage snapshot has no provider message ID; duplicate "
                    "accounting cannot be verified"
                )
            )
            continue
        key = (record.transcript_id or "", message_id or "")
        previous = latest.get(key)
        if previous is not None:
            old = records[previous].usage_record or {}
            current = record.usage_record or {}
            old_output = old.get("output_tokens", 0)
            current_output = current.get("output_tokens", 0)
            if current_output >= old_output:
                records[previous].usage_record = None
                latest[key] = index
            else:
                records[index].usage_record = None
            warnings.append(
                (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                    "repeated Claude provider message snapshots were retained "
                    "but only the latest usage snapshot is counted"
                )
            )
        else:
            latest[key] = index


def inspect_path(projects_root: Path | str, path: Path | str) -> InspectionSnapshot:
    root = Path(projects_root).resolve(strict=True)
    source = Path(path)
    if source.is_symlink():
        raise _fail(
            "diagnose_source_invalid", "Claude transcript path cannot be a symlink"
        )
    source = source.resolve(strict=True)
    try:
        rel = source.relative_to(root)
    except ValueError as exc:
        raise _fail(
            "diagnose_source_outside_root",
            "Claude transcript is outside the configured projects root",
        ) from exc
    if len(rel.parts) == 2:
        session = rel.name.removesuffix(".jsonl")
        if not rel.name.endswith(".jsonl"):
            raise _fail(
                "diagnose_source_invalid",
                "Claude transcript must have a .jsonl extension",
            )
        main = source
    elif len(rel.parts) >= 4 and rel.parts[2] == "subagents":
        session = rel.parts[1]
        main = root / rel.parts[0] / f"{session}.jsonl"
    else:
        raise _fail(
            "diagnose_source_invalid",
            "Claude transcript path must be within a project namespace",
        )
    return _snapshot(root, main, session)


def inspect_id(projects_root: Path | str, session_id: str) -> InspectionSnapshot:
    root = Path(projects_root).resolve(strict=True)
    matches = []
    for project in sorted(root.iterdir()):
        candidate = project / f"{session_id}.jsonl"
        if candidate.is_file() and not candidate.is_symlink():
            try:
                header = json.loads(candidate.open("rb").readline())
                if header.get("sessionId") == session_id:
                    matches.append(candidate)
            except OSError, UnicodeDecodeError, json.JSONDecodeError:
                pass
    if not matches:
        raise _fail(
            "diagnose_session_not_found",
            (
                f"Claude session `{session_id}` was not found under the "
                "configured projects root"
            ),
        )
    if len(matches) > 1:
        raise _fail(
            "diagnose_session_ambiguous",
            (
                f"Claude session `{session_id}` appears in multiple project "
                "namespaces; use --path"
            ),
        )
    return _snapshot(root, matches[0], session_id)


def _claude_discovery_row(
    path: Path, project_name: str, parent_id: str | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        with path.open("rb") as source:
            header_line = source.readline(MAX_RECORD_BYTES + 1)
            if len(header_line) > MAX_RECORD_BYTES:
                return None, "transcript header exceeds the record byte limit"
            first = json.loads(header_line)
            if not isinstance(first, dict):
                return None, "transcript header is not an object"
            header = first
            user = _first_user_record(first, source, parent_id)
        if not header_line:
            return None, "file contains no transcript records"
        subagent = parent_id is not None
        session_id = (
            path.stem
            if not subagent
            else str(header.get("agentId") or path.stem.removeprefix("agent-"))
        )
        header_id = header.get("sessionId")
        if not subagent and header_id != session_id:
            return None, "transcript sessionId does not match its filename"
        if user is None:
            return None, "transcript contains no user record"
        row = {
            "harness": "claude",
            "identity": f"claude:{project_name}:{session_id}",
            "session_id": session_id,
            "aliases": [session_id],
            "parent_identity": f"claude:{project_name}:{parent_id}"
            if parent_id
            else None,
            "parent_known": parent_id is None,
            "started_at": user.get("timestamp"),
            "cwd": user.get("cwd"),
            "retro_analyst": False,
            "source": str(path),
            "path": str(path),
        }
        if subagent:
            row.update(kind="subagent", parent_id=parent_id)
    except OSError:
        return None, "file could not be read"
    except ValueError, UnicodeDecodeError, json.JSONDecodeError:
        return None, "transcript contains malformed JSON"
    else:
        return row, None


def _first_user_record(
    first: dict[str, Any], source: Any, parent_id: str | None
) -> dict[str, Any] | None:
    is_user = first.get("type") == "user"
    message = first.get("message")
    if is_user or (isinstance(message, dict) and message.get("role") == "user"):
        return first
    if parent_id:
        return None
    for line in source:
        if len(line) > MAX_RECORD_BYTES:
            raise ValueError("transcript record exceeds the record byte limit")
        item = json.loads(line)
        if not isinstance(item, dict):
            continue
        message = item.get("message")
        if item.get("type") == "user" or (
            isinstance(message, dict) and message.get("role") == "user"
        ):
            return item
    return None


def _mtime_before(path: Path, window_start: datetime) -> bool:
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, UTC) < window_start
    except OSError:
        # The normal discovery row reports the file as unreadable.
        return False


def _old_discovery_row(path: Path, project_name: str) -> Any:
    return SimpleNamespace(
        harness="claude",
        identity=f"claude:{project_name}:{path.stem}",
        session_id=path.stem,
        aliases=[path.stem],
        parent_identity=None,
        parent_known=False,
        started_at=None,
        cwd=None,
        retro_analyst=False,
        source=str(path),
        path=str(path),
        status="out_of_window",
        reason="activity is outside the requested window",
    )


class ClaudeHarness:
    harness = DiagnosticHarness.CLAUDE

    def discover_root(
        self,
        root: Path,
        limit: int = MAX_DISCOVERY_FILES,
        window_start: datetime | None = None,
        pending_paths: set[str] | None = None,
        include_skipped: bool = False,
    ) -> tuple[list[Any], list[str]]:
        """List Claude project sessions and their subagents without repo filtering."""
        rows: list[Any] = []
        warnings: list[str] = []
        if not root.is_dir():
            return rows, warnings
        candidates: list[tuple[Path, str, str | None]] = []
        truncated = False
        projects = sorted(itertools.islice(root.iterdir(), MAX_DISCOVERY_FILES + 1))
        if len(projects) > MAX_DISCOVERY_FILES:
            truncated = True
            projects = projects[:MAX_DISCOVERY_FILES]
        for project in projects:
            if not project.is_dir():
                continue
            files = sorted(
                itertools.islice(project.glob("*.jsonl"), MAX_DISCOVERY_FILES + 1)
            )
            if len(files) > MAX_DISCOVERY_FILES:
                truncated = True
                files = files[:MAX_DISCOVERY_FILES]
            for path in files:
                candidates.append((path, project.name, None))
                child_dir = project / path.stem / "subagents"
                children = sorted(
                    itertools.islice(
                        child_dir.glob("agent-*.jsonl"), MAX_DISCOVERY_FILES + 1
                    )
                )
                if len(children) > MAX_DISCOVERY_FILES:
                    truncated = True
                candidates.extend(
                    (child, project.name, path.stem)
                    for child in children[:MAX_DISCOVERY_FILES]
                )
                if len(candidates) > MAX_DISCOVERY_FILES:
                    truncated = True
                    candidates = candidates[:MAX_DISCOVERY_FILES]
                    break
            if len(candidates) >= MAX_DISCOVERY_FILES:
                break
        for path, project_name, parent_id in candidates:
            if window_start is not None and _mtime_before(path, window_start):
                rows.append(_old_discovery_row(path, project_name))
                continue
            if len(rows) >= limit:
                warnings.append(
                    "Claude session discovery reached its requested row limit"
                )
                break
            row, reason = _claude_discovery_row(path, project_name, parent_id)
            if row:
                rows.append(row)
            elif reason:
                warnings.append(f"Skipped {path}: {reason}")
                if include_skipped:
                    rows.append(
                        SimpleNamespace(
                            harness="claude",
                            identity=f"claude:{project_name}:{path.stem}",
                            session_id=path.stem,
                            aliases=[path.stem],
                            parent_identity=None,
                            parent_known=False,
                            started_at=None,
                            cwd=None,
                            retro_analyst=False,
                            source=str(path),
                            path=str(path),
                            status="skipped",
                            reason=reason,
                        )
                    )
        if truncated:
            warnings.append("Claude session discovery reached its entry limit")
        return rows, warnings

    def discover(self, *, repo: Path, roots: dict[str, Any], limit: int) -> list[Any]:
        projects = roots.get("claude")
        if not projects or not Path(projects).is_dir():
            return []
        found = []
        for project in sorted(Path(projects).iterdir()):
            if not project.is_dir():
                continue
            for path in sorted(project.glob("*.jsonl")):
                try:
                    with path.open("rb") as f:
                        header = json.loads(f.readline())
                    user = None
                    with path.open("rb") as f:
                        for line in f:
                            item = json.loads(line)
                            if (
                                item.get("type") == "user"
                                or (item.get("message") or {}).get("role") == "user"
                            ):
                                user = item
                                break
                    sid = path.stem
                    if (
                        not user
                        or header.get("sessionId") != sid
                        or not user.get("cwd")
                    ):
                        continue
                    cwd = Path(user["cwd"]).resolve()
                    if os.path.commonpath((str(cwd), str(repo.resolve()))) != str(
                        repo.resolve()
                    ):
                        continue
                    found.append(
                        {
                            "harness": "claude",
                            "identity": f"claude:{project.name}:{sid}",
                            "session_id": sid,
                            "aliases": [sid],
                            "parent_identity": None,
                            "parent_known": True,
                            "started_at": user.get("timestamp"),
                            "cwd": user.get("cwd"),
                            "retro_analyst": False,
                            "source": str(path),
                        }
                    )
                except OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError:
                    continue
                if len(found) >= limit:
                    return found
        return found

    def inspect(self, request: Any) -> Inspection:
        if isinstance(request, dict):
            snapshot = (
                inspect_path(request["projects_root"], request["path"])
                if request.get("path")
                else inspect_id(request["projects_root"], request["session_id"])
            )
        else:
            snapshot = (
                inspect_path(request.projects_root, request.path)
                if getattr(request, "path", None)
                else inspect_id(request.projects_root, request.session_id)
            )
        if getattr(request, "is_current", False):
            snapshot.overlap = CurrentOverlap.CURRENT
            snapshot.coverage.complete = False
            snapshot.coverage.analysis_ready = False
            warning = (
                "current Claude session overlaps this evidence family; provide "
                "a verified pre-orchestration cutoff"
            )
            if warning not in snapshot.coverage.warnings:
                snapshot.coverage.warnings.append(warning)
        return Inspection(
            snapshot.session,
            snapshot.children,
            snapshot.sources,
            snapshot.records,
            snapshot.overlap,
            snapshot.coverage,
            SnapshotIdentity(snapshot.digest),
            usage_records=snapshot.usage_records,
        )


adapter = ClaudeHarness()
register_harness(adapter)
