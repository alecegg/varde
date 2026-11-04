"""Codex native rollout discovery and inspection."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ...errors import Diagnose
from ..model import (
    HARNESS_ADAPTERS,
    MAX_DISCOVERY_FILES,
    MAX_FAMILY,
    MAX_FAMILY_SOURCE_BYTES,
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    SNAPSHOT_SCHEMA_VERSION,
    ChildSession,
    Coverage,
    CurrentOverlap,
    DiagnosticHarness,
    Inspection,
    InspectionSnapshot,
    NormalizedRecordBudget,
    SnapshotIdentity,
)
from .discovery import (
    MAX_DISCOVERY_FILE_BYTES,
    MAX_LIST_METADATA_BYTES,
    Header,
    child_header_matches,
    discover_descendants,
    parse_header,
    read_header,
    scan_sessions,
    verified_header_identity,
)
from .events import (
    ParsedSource,
    context_occupancy,
    event_kind,
    native_id,
    normalize_record,
    parse_source,
)

MAX_WARNINGS = 128


def _snapshot(
    session, children, sources, records, overlap, coverage
) -> InspectionSnapshot:
    import hashlib
    from dataclasses import asdict

    payload = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "session": asdict(session),
        "children": [asdict(item) for item in children],
        "sources": [asdict(item) for item in sources],
        "records": [asdict(item) for item in records],
        "overlap": overlap.value,
        "coverage": asdict(coverage),
        "redacted": 0,
    }
    data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        default=lambda item: item.value if hasattr(item, "value") else asdict(item),
    ).encode()
    return InspectionSnapshot(
        SNAPSHOT_SCHEMA_VERSION,
        "sha256:" + hashlib.sha256(data).hexdigest(),
        session,
        children,
        sources,
        records,
        overlap,
        coverage,
    )


def inspect_path(home: Path, path: Path) -> InspectionSnapshot:
    try:
        discovery = scan_sessions(home)
    except Diagnose:
        from .discovery import Discovery

        discovery = Discovery([], True, True)
    selected = parse_source(
        path, MAX_SOURCE_BYTES, MAX_RECORDS, NormalizedRecordBudget()
    )
    return _inspect_selected(home, selected, discovery)


def inspect_id(home: Path, thread_id: str) -> InspectionSnapshot:
    discovery = scan_sessions(home)
    if discovery.truncated or discovery.uncertain:
        if discovery.unverified_versions:
            versions = ", ".join(sorted(discovery.unverified_versions))
            raise Diagnose(
                "diagnose_codex_version_unsupported",
                (
                    "Codex session discovery found unverified cli_version(s): "
                    f"{versions}; verify the version against the reader first"
                ),
            )
        reason = {
            "bytes": "Codex session listing exhausted its 96 MiB metadata budget",
            "entries": (
                "Codex session discovery exceeded the "
                f"{MAX_DISCOVERY_FILES} entry scan limit; use --path"
            ),
            "record_bytes": (
                "Codex session discovery reached its "
                f"{MAX_RECORD_BYTES // 1024} KiB per-file header read limit; "
                "use --path"
            ),
        }.get(
            discovery.limit or "",
            (
                "Codex session metadata was incomplete or could not be "
                "verified; use --path"
            ),
        )
        raise Diagnose("diagnose_discovery_incomplete", reason)
    matches = [
        path
        for path, header in discovery.sessions
        if header.session.thread_id == thread_id
    ]
    if not matches:
        raise Diagnose(
            "diagnose_session_not_found", f"Codex thread `{thread_id}` was not found"
        )
    if len(matches) != 1:
        raise Diagnose(
            "diagnose_session_ambiguous",
            f"multiple Codex rollouts identify thread `{thread_id}`; use --path",
        )
    return inspect_path(home, matches[0])


def _inspect_selected(
    home: Path, selected: ParsedSource, discovery
) -> InspectionSnapshot:
    thread_id = selected.header.session.thread_id
    descendants, ambiguous = discover_descendants(thread_id, discovery.sessions)
    family_truncated = len(descendants) > MAX_FAMILY
    descendants = descendants[:MAX_FAMILY]
    children: list[ChildSession] = []
    sources = [selected.source]
    records = list(selected.records)
    warnings = list(selected.warnings)
    incomplete = selected.incomplete_tail
    malformed, omitted = selected.malformed_records, selected.omitted_records
    unknown, inherited, processed = (
        selected.unknown_events,
        selected.inherited_events,
        selected.processed_records,
    )
    truncated = selected.truncated
    complete = not incomplete and malformed == 0 and not truncated
    discovery_truncated = discovery.truncated or discovery.uncertain
    linkage_uncertain = discovery_truncated or ambiguous
    family_bytes = selected.source.length or 0
    if ambiguous:
        complete = False
        warnings.append(
            (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                "multiple Codex rollouts identify a linked child thread; "
                "ambiguous child branches were omitted"
            )
        )
    if selected.inherited_events == 0 and (
        selected.header.forked_from_id is not None
        or selected.header.history_base is not None
        or (
            selected.header.session.history_mode
            and selected.header.session.history_mode != "full"
        )
    ):
        complete = False
        warnings.append(
            (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                "Codex rollout has inherited or forked history metadata; "
                "physical records may not represent a complete independent "
                "history"
            )
        )
    if family_truncated:
        complete = False
        truncated = True
        linkage_uncertain = True
        warnings.append(f"linked child family exceeded the {MAX_FAMILY} child limit")
    if discovery_truncated:
        complete = False
        truncated = True
        linkage_uncertain = True
        warnings.append(
            (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                "Codex metadata discovery omitted or could not verify one or "
                "more entries; linked-child coverage is partial"
            )
        )
    budget = NormalizedRecordBudget(
        sum(
            len(
                json.dumps(
                    record.__dict__, default=lambda x: x.__dict__, separators=(",", ":")
                ).encode()
            )
            for record in records
        )
    )
    for child_path, discovered, expected_parent in descendants:
        remaining_bytes = MAX_FAMILY_SOURCE_BYTES - family_bytes
        remaining_records = MAX_RECORDS - processed
        if remaining_bytes <= 0 or remaining_records <= 0:
            complete = truncated = False
            warnings.append(
                "linked-child family reached its aggregate byte or record limit"
            )
            continue
        child_limit = min(remaining_bytes, MAX_SOURCE_BYTES)
        try:
            child = parse_source(child_path, child_limit, remaining_records, budget)
        except Diagnose:
            complete = False
            linkage_uncertain = True
            warnings.append("a linked child rollout could not be read")
            continue
        if not child_header_matches(child.header, discovered, expected_parent):
            complete = False
            linkage_uncertain = True
            warnings.append(
                (  # noqa: UP034 - keep the wrapped warning explicitly grouped
                    "a linked child rollout changed identity or parent "
                    "relationship during inspection"
                )
            )
            continue
        child_session = child.header.session
        children.append(
            ChildSession(
                child_session.thread_id,
                child.source.source_id,
                child_session.parent_thread_id,
                child_session.started_at,
                child_session.parent_provenance or "session_meta.parent_thread_id",
            )
        )
        sources.append(child.source)
        records.extend(child.records)
        family_bytes += child.source.length or 0
        incomplete |= child.incomplete_tail
        malformed += child.malformed_records
        omitted += child.omitted_records
        unknown += child.unknown_events
        inherited += child.inherited_events
        processed += child.processed_records
        truncated |= child.truncated
        if child.incomplete_tail or child.malformed_records or child.truncated:
            complete = False
        warnings.extend(child.warnings)
    if unknown:
        warnings.append(
            "unknown Codex event types were retained as bounded excerpts and counted"
        )
    if not (home / "sessions").is_dir():
        complete = False
        linkage_uncertain = True
        warnings.append(
            "Codex session directory was unavailable; linked-child coverage is unknown"
        )
    if len(warnings) > MAX_WARNINGS:
        warnings = warnings[: MAX_WARNINGS - 1] + [
            "additional coverage warnings were omitted at the warning limit"
        ]
    current = os.environ.get("CODEX_THREAD_ID")
    family_ids = {thread_id, *(child.thread_id for child in children)}
    overlap = (
        CurrentOverlap.CURRENT
        if current in family_ids
        else CurrentOverlap.UNKNOWN
        if not current or linkage_uncertain
        else CurrentOverlap.NOT_CURRENT
    )
    coverage = Coverage(
        complete,
        complete,
        complete and overlap is CurrentOverlap.NOT_CURRENT,
        False,
        None,
        incomplete,
        truncated,
        len(records),
        malformed,
        omitted,
        unknown,
        inherited,
        warnings,
    )
    return _snapshot(
        selected.header.session, children, sources, records, overlap, coverage
    )


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
    source: str
    retro_analyst: bool = False
    tool_call_results: tuple[str, ...] = ()
    listing_source: str = "active"
    status: str = "ok"
    reason: str | None = None


class CodexHarness:
    harness = DiagnosticHarness.CODEX

    def discover_root(
        self,
        root: Path,
        limit: int = MAX_DISCOVERY_FILES,
        window_start: datetime | None = None,
        pending_paths: set[str] | None = None,
        include_skipped: bool = False,
    ) -> tuple[list[DiscoveredSession], list[str]]:
        discovery = scan_sessions(
            root,
            for_list=True,
            window_start=window_start,
            pending_paths=pending_paths,
        )
        rows: list[DiscoveredSession] = []
        warnings: list[str] = []
        for path, header in discovery.sessions:
            session = header.session
            first = _first_user(path)
            if first is None:
                warnings.append(
                    f"Skipped Codex rollout {path}: first user message "
                    "could not be read"
                )
                continue
            rows.append(
                DiscoveredSession(
                    "codex",
                    f"codex:{session.thread_id}",
                    session.thread_id,
                    [session.thread_id],
                    f"codex:{session.parent_thread_id}"
                    if session.parent_thread_id
                    else None,
                    header.parent_link_known,
                    session.started_at,
                    session.cwd,
                    str(path),
                    first.startswith("varde-retro-analyst"),
                    (),
                    "archived"
                    if path.is_relative_to(root / "sessions/archived")
                    else "active",
                )
            )
        for path, reason in discovery.skipped_sessions:
            if include_skipped:
                session_id = path.stem.removeprefix("rollout-")
                rows.append(
                    DiscoveredSession(
                        "codex",
                        f"codex:{session_id}",
                        session_id,
                        [session_id],
                        None,
                        False,
                        None,
                        None,
                        str(path),
                        status="skipped",
                        reason=reason,
                    )
                )
        if discovery.truncated:
            warnings.append("Codex session discovery reached its entry limit")
        if (
            discovery.uncertain
            or discovery.skipped_headers
            or discovery.skipped_entries
        ):
            warnings.append(
                "Codex discovery was incomplete "
                f"(skipped headers: {discovery.skipped_headers}, "
                f"skipped entries: {discovery.skipped_entries})"
            )
        if discovery.unverified_versions:
            versions = ", ".join(sorted(discovery.unverified_versions))
            warnings.append(
                f"Codex sessions with unsupported CLI versions were skipped: {versions}"
            )
        if len(rows) > limit:
            warnings.append("Codex session discovery reached its requested row limit")
        return rows[:limit], warnings

    def discover(
        self, *, repo: Any, roots: dict[str, Any], limit: int
    ) -> list[DiscoveredSession]:
        home = Path(roots["codex"])
        discovery = scan_sessions(home, for_list=True)
        result = []
        result_bytes = 0
        for path, header in discovery.sessions:
            session = header.session
            if not session.cwd or not _in_repo(session.cwd, Path(repo)):
                continue
            first = _first_user(path)
            if first is None:
                continue
            identity = f"codex:{session.thread_id}"
            aliases = [session.thread_id]
            if session.session_id and session.session_id not in aliases:
                aliases.append(session.session_id)
            tool_results, bytes_read = _tool_call_results(
                path, MAX_LIST_METADATA_BYTES - result_bytes
            )
            result_bytes += bytes_read
            result.append(
                DiscoveredSession(
                    "codex",
                    identity,
                    session.thread_id,
                    aliases,
                    f"codex:{session.parent_thread_id}"
                    if session.parent_thread_id
                    else None,
                    header.parent_link_known,
                    session.started_at,
                    session.cwd,
                    str(path),
                    first.startswith("varde-retro-analyst"),
                    tool_results,
                    "archived"
                    if path.is_relative_to(home / "sessions/archived")
                    else "active",
                )
            )
        return result[:limit]

    def inspect(self, request: Any) -> Inspection:
        home = Path(
            getattr(
                request,
                "source_root",
                getattr(request, "codex_home", Path.home() / ".codex"),
            )
        )
        path = getattr(request, "path", None)
        thread_id = getattr(request, "session_id", None)
        if path is not None:
            snapshot = inspect_path(home, Path(path))
        elif isinstance(thread_id, str):
            snapshot = inspect_id(home, thread_id)
        else:
            raise Diagnose(
                "diagnose_session_not_found", "Codex thread was not specified"
            )
        return Inspection(
            snapshot.session,
            snapshot.children,
            snapshot.sources,
            snapshot.records,
            snapshot.overlap,
            snapshot.coverage,
            SnapshotIdentity(snapshot.digest),
        )


def _in_repo(cwd: str, repo: Path) -> bool:
    try:
        return os.path.commonpath(
            (str(Path(cwd).resolve()), str(repo.resolve()))
        ) == str(repo.resolve())
    except OSError, ValueError:
        return False


def _first_user(path: Path) -> str | None:
    try:
        with path.open("rb") as source:
            source.readline(MAX_RECORD_BYTES + 1)
            for line in source:
                if len(line) > MAX_RECORD_BYTES:
                    return None
                value = json.loads(line)
                payload = value.get("payload", {})
                if payload.get("type") == "message" and payload.get("role") == "user":
                    content = payload.get("content", "")
                    if isinstance(content, list):
                        return next(
                            (
                                part.get("text", "")
                                for part in content
                                if isinstance(part, dict)
                                and isinstance(part.get("text"), str)
                            ),
                            "",
                        )
                    return content if isinstance(content, str) else ""
    except OSError, ValueError, AttributeError:
        return None
    return ""


def _tool_call_results(path: Path, byte_limit: int) -> tuple[tuple[str, ...], int]:
    if byte_limit <= 0:
        return (), 0
    results = []
    try:
        with path.open("rb") as source:
            data = source.read(min(byte_limit, MAX_DISCOVERY_FILE_BYTES))
            for line in data.splitlines():
                if len(line) > MAX_RECORD_BYTES:
                    continue
                try:
                    value = json.loads(line)
                except UnicodeDecodeError, json.JSONDecodeError:
                    continue
                if not isinstance(value, dict):
                    continue
                payload = value.get("payload", value)
                if not isinstance(payload, dict) or payload.get("type") not in {
                    "function_call_output",
                    "custom_tool_call_output",
                }:
                    continue
                output = payload.get("output", payload.get("content"))
                if output is not None:
                    results.append(
                        output
                        if isinstance(output, str)
                        else json.dumps(output, separators=(",", ":"), sort_keys=True)
                    )
    except OSError:
        return (), 0
    return tuple(results), len(data)


if DiagnosticHarness.CODEX not in HARNESS_ADAPTERS:
    from ..model import register_harness

    register_harness(CodexHarness())

__all__ = [
    "CodexHarness",
    "Header",
    "context_occupancy",
    "discover_descendants",
    "event_kind",
    "inspect_id",
    "inspect_path",
    "native_id",
    "normalize_record",
    "parse_header",
    "parse_source",
    "read_header",
    "scan_sessions",
    "verified_header_identity",
]
