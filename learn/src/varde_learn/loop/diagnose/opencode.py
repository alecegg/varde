"""Read-only OpenCode 2.0.12 session and export inspection."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Never
from urllib.parse import quote

from ..errors import Diagnose
from .model import (
    MAX_DISCOVERY_FILES,
    MAX_FAMILY,
    MAX_RECORD_BYTES,
    MAX_RECORDS,
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
    SourceCompanion,
    SourceSnapshot,
    ToolObservation,
    register_harness,
    rendered_length_bytes,
)

OPENCODE_VERSION = "2.0.12"
SESSION_COLUMNS = {
    "id",
    "project_id",
    "workspace_id",
    "parent_id",
    "fork_session_id",
    "fork_boundary",
    "slug",
    "directory",
    "path",
    "title",
    "version",
    "share_url",
    "summary_additions",
    "summary_deletions",
    "summary_files",
    "summary_diffs",
    "metadata",
    "cost",
    "tokens_input",
    "tokens_output",
    "tokens_reasoning",
    "tokens_cache_read",
    "tokens_cache_write",
    "revert",
    "permission",
    "agent",
    "model",
    "time_created",
    "time_updated",
    "time_idle",
    "time_viewed",
    "idle_outcome",
    "time_compacting",
    "time_archived",
    "time_suspended",
    "resume_attempts",
}
MESSAGE_COLUMNS = {
    "id",
    "session_id",
    "type",
    "seq",
    "time_created",
    "time_updated",
    "data",
}


def _raise(error: Exception) -> Never:
    raise error


@dataclass
class InspectRequest:
    root: Path
    session_id: str | None = None
    path: Path | None = None


@dataclass
class DiscoveredSession:
    harness: str
    identity: str
    session_id: str
    aliases: list[str]
    parent_identity: str | None
    parent_known: bool
    started_at: str | None
    cwd: str | None
    retro_analyst: bool


class OpenCodeAdapter:
    harness = DiagnosticHarness.OPENCODE

    def discover_root(
        self,
        root: Path,
        limit: int = MAX_DISCOVERY_FILES,
        window_start: datetime | None = None,
        pending_paths: set[str] | None = None,
        include_skipped: bool = False,
    ) -> tuple[list[Any], list[str]]:
        try:
            database = root if root.is_file() else _database_path(root)
        except Diagnose as error:
            return [], [str(error)]
        if not database.exists():
            return [], []
        db = _connect(database)
        warnings: list[str] = []
        try:
            _validate_schema(db)
            rows = db.execute(
                "SELECT id,parent_id,directory,version,time_created "
                "FROM session_v2 ORDER BY time_updated DESC,id LIMIT ?",
                (min(limit, MAX_DISCOVERY_FILES) + 1,),
            ).fetchall()
            if len(rows) > min(limit, MAX_DISCOVERY_FILES):
                warnings.append("OpenCode session discovery reached its entry limit")
            result: list[Any] = []
            skipped_versions: list[str] = []
            for sid, parent, cwd, version, created in rows[:limit]:
                if version != OPENCODE_VERSION:
                    skipped_versions.append(str(sid))
                    continue
                first = db.execute(
                    "SELECT data FROM session_message WHERE session_id=? "
                    "AND type='user' ORDER BY seq LIMIT 1",
                    (sid,),
                ).fetchone()
                retro = False
                if first:
                    raw = first[0]
                    if len(raw.encode()) > MAX_RECORD_BYTES:
                        warnings.append(
                            f"Skipped OpenCode session {sid}: first user message "
                            "exceeds the byte limit"
                        )
                        continue
                    try:
                        message = json.loads(raw)
                    except ValueError, TypeError:
                        warnings.append(
                            f"Skipped OpenCode session {sid}: first user message "
                            "is malformed"
                        )
                        continue
                    text = message.get("text", "") if isinstance(message, dict) else ""
                    retro = "retro analyst" in text.lower()
                result.append(
                    {
                        "harness": "opencode",
                        "identity": f"opencode:{sid}",
                        "session_id": sid,
                        "parent_identity": f"opencode:{parent}" if parent else None,
                        "parent_known": True,
                        "parent_id": parent,
                        "started_at": _timestamp_ms(created),
                        "cwd": cwd,
                        "retro_analyst": retro,
                        "kind": "session",
                        "path": f"{database}#{sid}",
                    }
                )
            if skipped_versions:
                examples = ", ".join(skipped_versions[:5])
                warnings.append(
                    f"Skipped {len(skipped_versions)} OpenCode sessions with "
                    f"version mismatch (examples: {examples})"
                )
            return result, warnings
        finally:
            db.close()

    def discover(
        self, *, repo: Any, roots: dict[str, Any], limit: int
    ) -> list[DiscoveredSession]:
        return discover_sessions(Path(roots["opencode"]), Path(repo), limit)

    def inspect(self, request: Any) -> Inspection:
        root = Path(request.path or request.root)
        database = root if request.path else _database_path(root)
        snapshot = (
            inspect_path(database, request.session_id)
            if request.path
            else inspect_id(database, request.session_id)
            if request.session_id
            else inspect_path(database)
        )
        return Inspection(
            snapshot.session,
            snapshot.children,
            snapshot.sources,
            snapshot.records,
            snapshot.overlap,
            snapshot.coverage,
            SnapshotIdentity(snapshot.digest),
            snapshot.redacted,
        )


def _fail(code: str, message: str) -> Diagnose:
    return Diagnose(code, message)


def _database_path(root: Path) -> Path:
    if root.is_file():
        return root.resolve(strict=True)
    configured = os.environ.get("OPENCODE_DB")
    path = Path(configured) if configured else root / "opencode.db"
    if not path.is_absolute():
        path = root / path
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise _fail(
            "diagnose_session_not_found", f"cannot resolve OpenCode database: {exc}"
        ) from exc


def _connect(path: Path) -> sqlite3.Connection:
    uri = "file:" + quote(str(path), safe="/") + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=0.25)
        connection.row_factory = sqlite3.Row
    except sqlite3.Error as exc:
        raise _fail(
            "diagnose_store_read_failed",
            f"cannot open OpenCode database read-only: {exc}",
        ) from exc
    else:
        return connection


def _validate_schema(db: sqlite3.Connection) -> None:
    for table, expected in (
        ("session_v2", SESSION_COLUMNS),
        ("session_message", MESSAGE_COLUMNS),
    ):
        try:
            actual = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error as exc:
            raise _fail(
                "diagnose_store_schema", f"cannot inspect OpenCode schema: {exc}"
            ) from exc
        missing = sorted(expected - actual)
        if missing:
            raise _fail(
                "diagnose_store_schema",
                f"OpenCode store is missing required {table} columns: "
                f"{', '.join(missing)}",
            )
        if actual != expected:
            raise _fail(
                "diagnose_store_schema",
                f"OpenCode {table} schema differs from the supported 2.0.12 format",
            )


def _source(path: Path, data: bytes | None) -> SourceSnapshot:
    stat = path.stat()
    hasher = hashlib.sha256()
    if data is None:
        # Hash SQLite incrementally to bound memory; sweep may repeat this per session.
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
    else:
        hasher.update(data)
    companions = []
    for suffix in ("-wal", "-shm"):
        companion_path = Path(str(path) + suffix)
        try:
            companion_stat = companion_path.lstat()
            if (
                companion_path.is_symlink()
                or not companion_path.is_file()
                or companion_stat.st_size == 0
                or companion_stat.st_size > MAX_SOURCE_BYTES
            ):
                companions.append(SourceCompanion(str(companion_path), False))
                continue
            companion_data = companion_path.read_bytes()
            companions.append(
                SourceCompanion(
                    str(companion_path),
                    True,
                    companion_stat.st_dev,
                    companion_stat.st_ino,
                    len(companion_data),
                    companion_stat.st_mtime_ns,
                    "sha256:" + hashlib.sha256(companion_data).hexdigest(),
                )
            )
        except OSError:
            companions.append(SourceCompanion(str(companion_path), False))
    return SourceSnapshot(
        str(path),
        str(path),
        stat.st_dev,
        stat.st_ino,
        stat.st_size,
        stat.st_mtime_ns,
        "sha256:" + hasher.hexdigest(),
        companions=companions,
    )


def _timestamp_ms(value: Any) -> str | None:
    if type(value) is not int:
        return None
    try:
        return (
            datetime.fromtimestamp(value / 1000, UTC)
            .isoformat(timespec="seconds")
            .replace("+00:00", "Z")
        )
    except OverflowError, OSError, ValueError:
        return None


def _digest(value: Any) -> str:
    raw = json.dumps(
        value, separators=(",", ":"), ensure_ascii=False, sort_keys=True
    ).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _excerpt(value: Any, limit: int = 4096) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    text = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    )
    return text[:limit] or None, len(text) > limit


def _normalize_message(
    data: dict[str, Any], anchor: RecordAnchor, session_id: str
) -> EvidenceRecord:
    kind = data.get("type")
    role = kind if kind in {"user", "assistant"} else None
    text_parts: list[str] = []
    observations: list[ToolObservation] = []
    content = data.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
            elif item.get("type") == "tool":
                state_value = item.get("state")
                state = state_value if isinstance(state_value, dict) else {}
                output, output_cut = _excerpt(state.get("content"))
                inp, input_cut = _excerpt(state.get("input"))
                error, error_cut = _excerpt(state.get("error"))
                observations.append(
                    ToolObservation(
                        "tool",
                        str(item.get("id")) if item.get("id") is not None else None,
                        str(item.get("name")) if item.get("name") is not None else None,
                        inp,
                        output,
                        state.get("status"),
                        error,
                        input_cut or output_cut or error_cut,
                        rendered_length_bytes(state.get("content")),
                    )
                )
    if isinstance(data.get("text"), str):
        text_parts.append(data["text"])
    text, text_cut = _excerpt("\n".join(text_parts) if text_parts else None)
    time_data = data.get("time")
    timestamp_raw = time_data.get("created") if isinstance(time_data, dict) else None
    timestamp = _timestamp_ms(timestamp_raw)
    if timestamp is None and isinstance(timestamp_raw, str):
        with contextlib.suppress(ValueError, OverflowError):
            timestamp = (
                datetime.fromisoformat(timestamp_raw)
                .astimezone(UTC)
                .isoformat()
                .replace("+00:00", "Z")
            )
    tokens_value = data.get("tokens")
    tokens = tokens_value if isinstance(tokens_value, dict) else {}
    cache_value = tokens.get("cache")
    cache: dict[str, Any] = cache_value if isinstance(cache_value, dict) else {}
    usage = {
        "input_tokens": tokens.get("input"),
        "output_tokens": tokens.get("output"),
        "reasoning_tokens": tokens.get("reasoning"),
        "cache_read_tokens": cache.get("read"),
        "cache_write_tokens": cache.get("write"),
    }
    usage = {
        key: value for key, value in usage.items() if type(value) is int and value >= 0
    }
    if usage:
        usage["total_tokens"] = sum(usage.values())
    return EvidenceRecord(
        session_thread_id=session_id,
        anchor=anchor,
        timestamp=timestamp,
        kind=str(kind or "unknown"),
        role=role,
        text_excerpt=text,
        tool_observations=observations,
        detail_truncated=text_cut,
        usage_record=usage or None,
        provider_message_id=str(data.get("id")) if data.get("id") else None,
        timestamp_raw=timestamp_raw,
    )


def _snapshot(
    path: Path, data: bytes | None, db: sqlite3.Connection, selected_id: str | None
) -> InspectionSnapshot:
    _validate_schema(db)
    if selected_id:
        row = db.execute(
            "SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,"
            "version,time_created FROM session_v2 WHERE id=?",
            (selected_id,),
        ).fetchone()
        if row is None:
            raise _fail(
                "diagnose_session_not_found",
                f"OpenCode session `{selected_id}` was not found",
            )
    else:
        rows = db.execute(
            "SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,"
            "version,time_created FROM session_v2 ORDER BY time_created DESC,id LIMIT 2"
        ).fetchall()
        if not rows:
            raise _fail(
                "diagnose_session_not_found", "OpenCode database contains no sessions"
            )
        if len(rows) > 1:
            raise _fail(
                "diagnose_session_ambiguous",
                "OpenCode database path contains multiple sessions; use --session",
            )
        row = rows[0]
    if row[6] != OPENCODE_VERSION:
        raise _fail(
            "diagnose_store_version", f"unsupported OpenCode version `{row[6]}`"
        )
    session_id, _project, parent, fork, _boundary, directory, version, created = row
    warnings: list[str] = []
    partial = False
    if parent:
        warnings.append(
            "selected OpenCode session has a parent_id; parent history was not "
            "prepended"
        )
    if fork:
        warnings.append(
            "OpenCode fork rows are materialized; inherited incident provenance is not "
            "established, so coverage is partial"
        )
        partial = True
    children: list[ChildSession] = []
    sessions = [row]
    visited = {session_id}
    queue = [session_id]
    while queue:
        p = queue.pop()
        for child in db.execute(
            "SELECT id,project_id,parent_id,fork_session_id,fork_boundary,directory,"
            "version,time_created FROM session_v2 WHERE parent_id=? "
            "ORDER BY time_created,id",
            (p,),
        ):
            if len(sessions) >= MAX_FAMILY:
                partial = True
                warnings.append(
                    f"OpenCode child family exceeded the {MAX_FAMILY}-session bound"
                )
                break
            if child[0] in visited:
                partial = True
                warnings.append(
                    "OpenCode parent_id cycle or duplicate child relationship "
                    "was detected"
                )
                continue
            visited.add(child[0])
            if child[6] != OPENCODE_VERSION:
                partial = True
                warnings.append(
                    f"linked OpenCode child `{child[0]}` uses an unsupported format "
                    "version"
                )
                continue
            children.append(
                ChildSession(
                    child[0],
                    str(path),
                    child[2],
                    _timestamp_ms(child[7]),
                    "OpenCode session_v2.parent_id",
                    fork_session_id=child[3],
                    fork_boundary=_json_value(child[4]),
                )
            )
            sessions.append(child)
            queue.append(child[0])
    records: list[EvidenceRecord] = []
    malformed = omitted = 0
    budget = NormalizedRecordBudget()
    processed = 0
    truncated = False
    for session in sessions:
        last_sequence = 0
        location = None
        saw_switch = False
        context_complete = True
        context_digest = (
            "sha256:" + hashlib.sha256(b"opencode-location-context-v1").hexdigest()
        )
        for message in db.execute(
            "SELECT id,session_id,type,seq,data FROM session_message "
            "WHERE session_id=? ORDER BY seq LIMIT ?",
            (session[0], min(MAX_RECORDS - processed + 1, MAX_RECORDS + 1)),
        ):
            processed += 1
            sequence = message[3]
            record_index = max(sequence - 1, 0) if type(sequence) is int else 0
            if processed > MAX_RECORDS:
                partial = True
                break
            try:
                msg = json.loads(message[4])
                if not isinstance(msg, dict):
                    _raise(TypeError("message is not an object"))
                if sequence != last_sequence + 1:
                    context_digest = _extend_context_digest(
                        context_digest,
                        {
                            "kind": "sequence-gap",
                            "expected": last_sequence + 1,
                            "observed": sequence,
                        },
                    )
                    context_complete = False
                    location = None
                last_sequence = sequence
                is_switch = message[2] == "location-switched"
                if is_switch:
                    previous = _nested_directory(msg, "previous")
                    next_location = _nested_directory(msg, "location")
                    if not saw_switch and context_complete:
                        if previous is not None:
                            for prior_index, prior in enumerate(records):
                                if prior.session_location is not None:
                                    continue
                                updated = replace(
                                    prior,
                                    session_location=previous,
                                    location_provenance=(
                                        "first location-switched.previous.location"
                                    ),
                                )
                                if not budget.try_replace(prior, updated):
                                    partial = True
                                    truncated = True
                                    warnings.append(
                                        "OpenCode location history could not be "
                                        "backfilled within the normalized record byte "
                                        "budget; some earlier locations remain unknown"
                                    )
                                    break
                                records[prior_index] = updated
                        else:
                            warnings.append(
                                "first OpenCode location switch omitted "
                                "previous.location; earlier session locations remain "
                                "unknown"
                            )
                    elif (
                        location is not None
                        and previous is not None
                        and location != previous
                    ):
                        context_complete = False
                        warnings.append(
                            "OpenCode location-switch history has conflicting "
                            "previous.location evidence"
                        )
                    location = next_location
                    saw_switch = True
                anchor = RecordAnchor(
                    str(path),
                    record_index,
                    0,
                    0,
                    _digest(msg),
                    message[0],
                    message[1],
                    message[3],
                )
                record = _normalize_message(msg, anchor, session[0])
                if record is None:
                    continue
                record.provider_message_id = None
                record.anchor.context_digest = context_digest
                record.session_location = location
                if is_switch and location is not None:
                    record.location_provenance = "location-switched.location"
                elif location is not None:
                    record.location_provenance = (
                        "latest prior location-switched.location"
                        if saw_switch
                        else "unknown"
                    )
                size = len(
                    json.dumps(
                        asdict(record), separators=(",", ":"), ensure_ascii=False
                    ).encode()
                )
                if (
                    size > MAX_RECORD_BYTES
                    or budget.used_bytes + size > NORMALIZED_RECORD_BUDGET_BYTES
                ):
                    omitted += 1
                    partial = True
                    truncated = True
                    continue
                budget.used_bytes += size
                records.append(record)
                if is_switch:
                    context_digest = _extend_context_digest(
                        context_digest,
                        {
                            "kind": "location-switched",
                            "id": message[0],
                            "sequence": sequence,
                            "record_digest": anchor.record_digest,
                        },
                    )
            except ValueError, TypeError, json.JSONDecodeError:
                malformed += 1
                partial = True
    if malformed or omitted:
        warnings.append(
            "OpenCode history contains malformed or omitted records; coverage is "
            "partial"
        )
    if partial:
        warnings.append(
            "OpenCode native history has gaps, inherited rows, unknown records, or "
            "bounded discovery limits"
        )
    warnings = warnings[:32]
    metadata = SessionMetadata(
        harness="opencode",
        thread_id=session_id,
        session_id=session_id,
        parent_thread_id=parent,
        parent_provenance="OpenCode session_v2.parent_id" if parent else None,
        started_at=_timestamp_ms(created),
        cwd=None,
        cli_version=version,
        history_mode="forked_materialized_rows" if fork else None,
        git=None,
        source_id=str(path),
        project_namespace=str(_project) if _project is not None else None,
        current_directory=directory,
    )
    identity_data = {
        "session": asdict(metadata),
        "records": [asdict(r) for r in records],
    }
    snapshot_digest = _digest(identity_data)
    return InspectionSnapshot(
        SNAPSHOT_SCHEMA_VERSION,
        snapshot_digest,
        metadata,
        children,
        [_source(path, data)],
        records,
        CurrentOverlap.UNKNOWN,
        Coverage(
            not partial,
            not partial,
            not partial,
            False,
            None,
            False,
            truncated or processed >= MAX_RECORDS,
            len(records),
            malformed,
            omitted,
            warnings=warnings,
        ),
    )


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _nested_directory(value: dict[str, Any], key: str) -> str | None:
    relation = value.get(key)
    location = (
        relation.get("location")
        if key == "previous" and isinstance(relation, dict)
        else relation
    )
    directory = location.get("directory") if isinstance(location, dict) else None
    return directory if isinstance(directory, str) else None


def _extend_context_digest(previous: str, evidence: dict[str, Any]) -> str:
    return _digest({"previous": previous, "evidence": evidence})


def inspect_id(root: Path, session_id: str) -> InspectionSnapshot:
    if not session_id or any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
        for ch in session_id
    ):
        raise _fail("diagnose_session_not_found", "invalid OpenCode session ID")
    return inspect_path(root, session_id)


def _incomplete_export(path: Path, sample: bytes) -> InspectionSnapshot:
    metadata = SessionMetadata(
        "opencode",
        path.stem,
        path.stem,
        None,
        None,
        None,
        None,
        None,
        "export",
        None,
        str(path),
    )
    warning = (
        "OpenCode export exceeded the source byte bound; only its head and tail "
        "were read"
    )
    source = _source(path, sample)
    sampled_identity = (
        f"{source.digest}:{source.length}:{source.modified_ns}"
    ).encode()
    source.digest = "sha256:" + hashlib.sha256(sampled_identity).hexdigest()
    return InspectionSnapshot(
        SNAPSHOT_SCHEMA_VERSION,
        _digest({"session": asdict(metadata), "source": "incomplete"}),
        metadata,
        [],
        [source],
        [],
        CurrentOverlap.UNKNOWN,
        Coverage(
            complete=False,
            source_complete=False,
            analysis_ready=False,
            cutoff_verified=False,
            cutoff_anchor=None,
            incomplete_tail=True,
            truncated=True,
            record_count=0,
            malformed_records=0,
            omitted_records=0,
            warnings=[warning],
        ),
    )


def inspect_path(path: Path, session_id: str | None = None) -> InspectionSnapshot:
    path = Path(path)
    try:
        canonical = path.resolve(strict=True)
        if not canonical.is_file():
            raise _fail(
                "diagnose_source_invalid", "OpenCode path must be a regular file"
            )
        with canonical.open("rb") as source:
            prefix = source.read(16)
        source_size = canonical.stat().st_size
    except OSError as exc:
        raise _fail(
            "diagnose_source_invalid", f"cannot read OpenCode path: {exc}"
        ) from exc
    if prefix.startswith(b"SQLite format 3\x00"):
        db = _connect(canonical)
        try:
            return _snapshot(canonical, None, db, session_id)
        except sqlite3.Error as exc:
            raise _fail(
                "diagnose_store_read_failed", f"cannot read OpenCode database: {exc}"
            ) from exc
        finally:
            db.close()
    try:
        if source_size > MAX_SOURCE_BYTES:
            half = MAX_SOURCE_BYTES // 2
            with canonical.open("rb") as source:
                head = source.read(half)
                source.seek(-half, os.SEEK_END)
                tail = source.read(half)
            return _incomplete_export(canonical, head + tail)
        data = canonical.read_bytes()
    except OSError as exc:
        raise _fail(
            "diagnose_source_invalid", f"cannot read OpenCode path: {exc}"
        ) from exc
    try:
        export = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _fail(
            "diagnose_source_invalid", f"cannot parse OpenCode export: {exc}"
        ) from exc
    return _inspect_export(canonical, data, export)


def _inspect_export(path: Path, data: bytes, export: Any) -> InspectionSnapshot:
    if not isinstance(export, dict) or not isinstance(export.get("messages"), list):
        raise _fail(
            "diagnose_source_invalid", "OpenCode export must contain a messages array"
        )
    info_value = export.get("info")
    info = info_value if isinstance(info_value, dict) else {}
    session_id = str(info.get("id") or path.stem)
    records: list[EvidenceRecord] = []
    omitted = malformed = 0
    budget = NormalizedRecordBudget()
    for index, message in enumerate(export["messages"][:MAX_RECORDS]):
        if not isinstance(message, dict):
            malformed += 1
            continue
        anchor = RecordAnchor(
            str(path),
            index,
            0,
            0,
            _digest(message),
            str(message.get("id") or ""),
            session_id,
            index,
        )
        record = _normalize_message(message, anchor, session_id)
        size = len(
            json.dumps(
                asdict(record), separators=(",", ":"), ensure_ascii=False
            ).encode()
        )
        if (
            size > MAX_RECORD_BYTES
            or budget.used_bytes + size > NORMALIZED_RECORD_BUDGET_BYTES
        ):
            omitted += 1
            continue
        budget.used_bytes += size
        records.append(record)
    truncated = len(export["messages"]) > MAX_RECORDS or omitted > 0
    warnings = (
        ["OpenCode export history exceeded a bounded record limit"] if truncated else []
    )
    metadata = SessionMetadata(
        "opencode",
        session_id,
        session_id,
        None,
        None,
        None,
        None,
        None,
        "export",
        None,
        str(path),
    )
    return InspectionSnapshot(
        SNAPSHOT_SCHEMA_VERSION,
        _digest({"session": asdict(metadata), "records": [asdict(r) for r in records]}),
        metadata,
        [],
        [_source(path, data)],
        records,
        CurrentOverlap.UNKNOWN,
        Coverage(
            not truncated and malformed == 0,
            not truncated and malformed == 0,
            not truncated and malformed == 0,
            False,
            None,
            False,
            truncated,
            len(records),
            malformed,
            omitted,
            warnings=warnings,
        ),
    )


def discover_sessions(
    root: Path, repo: Path, limit: int = MAX_DISCOVERY_FILES
) -> list[DiscoveredSession]:
    path = _database_path(root)
    if not path.exists():
        return []
    db = _connect(path)
    try:
        _validate_schema(db)
        rows = db.execute(
            "SELECT id,parent_id,directory,version,time_created FROM session_v2 "
            "ORDER BY time_created DESC,id LIMIT ?",
            (min(limit, MAX_DISCOVERY_FILES) + 1,),
        ).fetchall()
        if len(rows) > min(limit, MAX_DISCOVERY_FILES):
            raise _fail(
                "diagnose_discovery_incomplete",
                "OpenCode session discovery exceeded its entry bound",
            )
        result = []
        for sid, parent, cwd, version, created in rows:
            if version != OPENCODE_VERSION or not _in_repo(cwd, repo):
                continue
            first = db.execute(
                "SELECT data FROM session_message WHERE session_id=? "
                "AND type='user' ORDER BY seq LIMIT 1",
                (sid,),
            ).fetchone()
            retro = False
            if first:
                raw = first[0]
                if len(raw.encode()) > MAX_RECORD_BYTES:
                    continue
                try:
                    obj = json.loads(raw)
                    text = obj.get("text", "") if isinstance(obj, dict) else ""
                    retro = "retro analyst" in text.lower()
                except ValueError, TypeError:
                    continue
            result.append(
                DiscoveredSession(
                    "opencode",
                    f"opencode:{sid}",
                    sid,
                    [sid],
                    f"opencode:{parent}" if parent else None,
                    True,
                    _timestamp_ms(created),
                    cwd,
                    retro,
                )
            )
    except sqlite3.Error as exc:
        raise _fail(
            "diagnose_store_read_failed", f"cannot list OpenCode sessions: {exc}"
        ) from exc
    else:
        return result
    finally:
        db.close()


def _in_repo(cwd: str | None, repo: Path) -> bool:
    if not cwd:
        return False
    try:
        Path(cwd).resolve().relative_to(repo.resolve())
    except OSError, ValueError:
        return False
    else:
        return True


adapter = OpenCodeAdapter()
register_harness(adapter)
