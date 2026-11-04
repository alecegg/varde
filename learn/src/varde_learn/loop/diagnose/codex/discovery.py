"""Bounded discovery and identity verification for Codex rollout JSONL files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ...errors import Diagnose
from ..model import MAX_DISCOVERY_FILES, MAX_RECORD_BYTES, GitMetadata, SessionMetadata

MAX_LIST_METADATA_BYTES = 96 * 1024 * 1024
MAX_DISCOVERY_FILE_BYTES = 16 * 1024 * 1024
VERIFIED_CLI_VERSIONS = {"0.155.1", "0.162.1", "0.162.0-alpha.17.2", "0.165.0"}
SUFFIXABLE_CLI_VERSIONS = {"0.155.1", "0.165.0"}


def _is_verified_version(version: str) -> bool:
    exact = version.split("+")[0]
    return (
        exact in VERIFIED_CLI_VERSIONS or exact.split("-")[0] in SUFFIXABLE_CLI_VERSIONS
    )


@dataclass
class Header:
    session: SessionMetadata
    forked_from_id: str | None = None
    history_base: Any = None
    parent_link_known: bool = False


@dataclass
class Discovery:
    sessions: list[tuple[Path, Header]]
    truncated: bool = False
    uncertain: bool = False
    limit: str | None = None
    skipped_headers: int = 0
    skipped_entries: int = 0
    unverified_versions: set[str] = field(default_factory=set)
    skipped_sessions: list[tuple[Path, str]] = field(default_factory=list)


def _error(code: str, message: str) -> Diagnose:
    return Diagnose(code, message)


def parse_header(value: dict[str, Any], require_known_version: bool = True) -> Header:
    if value.get("type") != "session_meta":
        raise _error(
            "diagnose_source_unsupported",
            "first Codex rollout record is not session_meta",
        )
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise _error(
            "diagnose_source_invalid", "Codex session metadata payload is missing"
        )
    thread_id = payload.get("id")
    if not isinstance(thread_id, str) or not thread_id.strip():
        raise _error("diagnose_source_invalid", "Codex canonical thread ID is missing")
    version = payload.get("cli_version")
    if (
        not isinstance(version, str)
        or not version.strip()
        or (require_known_version and not _is_verified_version(version))
    ):
        raise _error(
            "diagnose_codex_version_unsupported",
            (
                f"Codex session file version {version!r} is not supported yet; "
                "Varde cannot read this file"
            ),
        )
    source = payload.get("source") or {}
    source_parent = (
        (
            ((source.get("subagent") or {}).get("thread_spawn") or {}).get(
                "parent_thread_id"
            )
        )
        if isinstance(source, dict)
        else None
    )
    direct_parent = payload.get("parent_thread_id")
    source_present = (
        isinstance(source, dict)
        and isinstance(source.get("subagent"), dict)
        and isinstance(source["subagent"].get("thread_spawn"), dict)
        and isinstance(
            source["subagent"]["thread_spawn"].get("parent_thread_id"),
            (str, type(None)),
        )
    )
    if (
        isinstance(direct_parent, str)
        and isinstance(source_parent, str)
        and direct_parent != source_parent
    ):
        raise _error(
            "diagnose_source_invalid",
            "Codex parent thread metadata conflicts between session_meta fields",
        )
    parent = (
        direct_parent
        if isinstance(direct_parent, str)
        else source_parent
        if isinstance(source_parent, str)
        else None
    )
    provenance = (
        "session_meta.parent_thread_id+source.subagent.thread_spawn.parent_thread_id"
        if isinstance(direct_parent, str) and isinstance(source_parent, str)
        else "session_meta.parent_thread_id"
        if isinstance(direct_parent, str)
        else "session_meta.source.subagent.thread_spawn.parent_thread_id"
        if isinstance(source_parent, str)
        else None
    )
    git_value = payload.get("git")
    git = (
        GitMetadata(
            **{
                key: git_value.get(key)
                for key in ("commit_hash", "branch", "repository_url")
            }
        )
        if isinstance(git_value, dict)
        else None
    )
    session = SessionMetadata(
        harness="codex",
        thread_id=thread_id,
        session_id=payload.get("session_id")
        if isinstance(payload.get("session_id"), str)
        else None,
        parent_thread_id=parent,
        parent_provenance=provenance,
        started_at=payload.get("timestamp", value.get("timestamp")),
        cwd=payload.get("cwd"),
        cli_version=version,
        history_mode=payload.get("history_mode"),
        git=git,
        source_id="",
    )
    parent_known = (
        isinstance(direct_parent, (str, type(None)))
        and "parent_thread_id" in payload
        or source_present
    )
    return Header(
        session,
        payload.get("forked_from_id")
        if isinstance(payload.get("forked_from_id"), str)
        else None,
        payload.get("history_base"),
        parent_known,
    )


def verified_header_identity(value: dict[str, Any]) -> tuple[str, str | None, bool]:
    header = parse_header(value)
    inherited = bool(
        header.forked_from_id
        or header.history_base is not None
        or (header.session.history_mode and header.session.history_mode != "full")
    )
    return header.session.thread_id, header.session.parent_thread_id, inherited


def read_header(
    path: Path,
    byte_limit: int = MAX_RECORD_BYTES + 1,
    require_known_version: bool = True,
) -> tuple[Header, int]:
    try:
        with path.open("rb") as source:
            line = source.readline(min(byte_limit, MAX_RECORD_BYTES + 1) + 1)
    except OSError as cause:
        raise _error(
            "diagnose_source_invalid", f"cannot read rollout header: {cause}"
        ) from cause
    if len(line) > MAX_RECORD_BYTES or not line.endswith(b"\n"):
        raise _error(
            "diagnose_source_invalid",
            (
                "Codex session metadata exceeds the header limit or remaining "
                "discovery byte budget"
            ),
        )
    try:
        header = parse_header(json.loads(line), require_known_version)
    except (ValueError, json.JSONDecodeError) as cause:
        raise _error(
            "diagnose_source_invalid", f"invalid Codex session metadata: {cause}"
        ) from cause
    return header, len(line)


def _rejected_header_details(
    path: Path, error: Diagnose
) -> tuple[int, bool, str | None]:
    try:
        with path.open("rb") as source:
            line = source.readline(MAX_RECORD_BYTES + 1)
    except OSError:
        return 0, False, None
    header_too_large = len(line) > MAX_RECORD_BYTES
    if header_too_large or error.code != "diagnose_codex_version_unsupported":
        return len(line), header_too_large, None
    try:
        payload = json.loads(line).get("payload", {})
    except AttributeError, json.JSONDecodeError, TypeError:
        return len(line), False, None
    version = payload.get("cli_version")
    return len(line), False, version if isinstance(version, str) else None


def _is_empty_file(path: Path) -> bool:
    return path.stat().st_size == 0


def _skip_for_window(
    path: Path, window_start: datetime | None, pending_paths: set[str] | None
) -> bool:
    if window_start is None:
        return False
    try:
        too_old = datetime.fromtimestamp(path.stat().st_mtime, UTC) < window_start
    except OSError:
        return False
    return too_old and str(path.resolve(strict=False)) not in (pending_paths or set())


def scan_sessions(
    home: Path,
    *,
    for_list: bool = False,
    window_start: datetime | None = None,
    pending_paths: set[str] | None = None,
) -> Discovery:
    root = home / "sessions"
    try:
        if root.is_symlink():
            raise _error(
                "diagnose_discovery_invalid",
                "Codex sessions path is not a real directory",
            )
        if not root.is_dir():
            return Discovery([])
    except OSError:
        return Discovery([])
    output: list[tuple[Path, Header]] = []
    skipped_sessions: list[tuple[Path, str]] = []
    unverified_versions: set[str] = set()
    scanned = metadata_bytes = skipped_headers = skipped_entries = 0
    uncertain = False
    stack = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        if depth > 8:
            uncertain = True
            skipped_entries += 1
            continue
        try:
            entries = list(directory.iterdir())
        except OSError as cause:
            raise _error(
                "diagnose_discovery_failed", f"cannot scan Codex sessions: {cause}"
            ) from cause
        for path in entries:
            scanned += 1
            if scanned > MAX_DISCOVERY_FILES:
                return Discovery(
                    output, True, uncertain, "entries", skipped_headers, skipped_entries
                )
            try:
                if path.is_symlink():
                    uncertain = True
                    skipped_entries += 1
                    continue
                if path.is_dir():
                    stack.append((path, depth + 1))
                    continue
                if not path.is_file():
                    uncertain = True
                    skipped_entries += 1
                    continue
                if (
                    path.suffix != ".jsonl"
                    or not path.name.startswith("rollout-")
                    or _is_empty_file(path)
                ):
                    continue
            except OSError:
                uncertain = True
                skipped_entries += 1
                continue
            if _skip_for_window(path, window_start, pending_paths):
                continue
            budget = MAX_RECORD_BYTES + 1
            try:
                header, size = read_header(
                    path, min(budget, MAX_RECORD_BYTES + 1), not for_list
                )
                output.append((path, header))
            except Diagnose as error:
                skipped_headers += 1
                uncertain = True
                skipped_sessions.append((path, error.message))
                size, header_too_large, unverified_version = _rejected_header_details(
                    path, error
                )
                if not for_list and header_too_large:
                    return Discovery(
                        output,
                        True,
                        True,
                        "record_bytes",
                        skipped_headers,
                        skipped_entries,
                    )
                if unverified_version is not None:
                    unverified_versions.add(unverified_version)
            metadata_bytes += size if for_list else 0
    return Discovery(
        output,
        False,
        uncertain,
        None,
        skipped_headers,
        skipped_entries,
        unverified_versions,
        skipped_sessions,
    )


def discover_descendants(
    root_thread: str, sessions: list[tuple[Path, Header]]
) -> tuple[list[tuple[Path, Header, str]], bool]:
    by_parent: dict[str, list[tuple[Path, Header]]] = {}
    counts: dict[str, int] = {}
    for path, header in sessions:
        ident = header.session.thread_id
        counts[ident] = counts.get(ident, 0) + 1
        if header.session.parent_thread_id:
            by_parent.setdefault(header.session.parent_thread_id, []).append(
                (path, header)
            )
    result: list[tuple[Path, Header, str]] = []
    ambiguous = False
    pending, visited = [root_thread], {root_thread}
    while pending:
        parent = pending.pop()
        for path, child in by_parent.get(parent, []):
            ident = child.session.thread_id
            if ident in visited:
                continue
            if counts[ident] > 1:
                ambiguous = True
                continue
            visited.add(ident)
            result.append((path, child, parent))
            pending.append(ident)
            if len(result) >= MAX_DISCOVERY_FILES:
                return result, ambiguous
    return result, ambiguous


def child_header_matches(
    parsed: Header, discovered: Header, expected_parent: str
) -> bool:
    return (
        parsed.session.thread_id == discovered.session.thread_id
        and parsed.session.parent_thread_id == expected_parent
        and discovered.session.parent_thread_id == expected_parent
    )
