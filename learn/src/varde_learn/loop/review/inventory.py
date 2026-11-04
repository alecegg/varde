"""Windowed, cross-harness inventory for daily session reviews."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from ..diagnose.list import discover_root
from ..diagnose.model import DiagnosticHarness, harness_adapter
from ..diagnose.pi import MAX_DISCOVERY_FILES, _read_header
from ..errors import Diagnose
from ..sources import Location, is_ignored


@dataclass
class Inventory:
    sessions: list[dict[str, Any]] = field(default_factory=list)
    statuses: list[dict[str, str]] = field(default_factory=list)
    locations: list[Location] = field(default_factory=list)


def in_window(row: dict[str, Any], window: tuple[datetime, datetime]) -> bool:
    """Return whether a session's activity interval overlaps [start, end]."""
    start, end = window
    first = _datetime(row.get("first_activity"))
    last = _datetime(row.get("last_activity"))
    return bool(first and last and first <= end and last >= start)


def _datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


_TIME_KEYS = ("timestamp", "time", "created_at", "updated_at")
_EDGE_BYTES = 256 * 1024


def _line_time(line: bytes) -> str | None:
    try:
        item = json.loads(line)
    except ValueError, UnicodeDecodeError:
        return None
    if not isinstance(item, dict):
        return None
    for key in _TIME_KEYS:
        value = item.get(key)
        if isinstance(value, str) and _datetime(value):
            return value
    return None


def _record_times(path: Path) -> tuple[str | None, str | None]:
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(_EDGE_BYTES)
            if size <= _EDGE_BYTES:
                tail = head
            else:
                stream.seek(max(0, size - _EDGE_BYTES))
                tail = stream.read(_EDGE_BYTES)
    except OSError:
        return None, None
    first = next(
        (value for line in head.splitlines() if (value := _line_time(line))), None
    )
    last = next(
        (value for line in reversed(tail.splitlines()) if (value := _line_time(line))),
        None,
    )
    return first, last


def _opencode_activity(
    found: list[dict[str, Any]],
) -> dict[str, tuple[str | None, str | None]]:
    grouped: dict[Path, list[str]] = {}
    for row in found:
        database, separator, session_id = str(row.get("path", "")).partition("#")
        if separator:
            grouped.setdefault(Path(database).resolve(), []).append(session_id)
    activities: dict[str, tuple[str | None, str | None]] = {}
    for database, session_ids in grouped.items():
        try:
            with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as db:
                columns = {
                    item[1] for item in db.execute("PRAGMA table_info(session_message)")
                }
                message_query = (
                    "SELECT max(time_updated) FROM session_message WHERE session_id=?"
                    if "time_updated" in columns
                    else (
                        "SELECT max(time_created) FROM session_message "
                        "WHERE session_id=?"
                    )
                )
                session_columns = {
                    item[1] for item in db.execute("PRAGMA table_info(session_v2)")
                }
                has_updated = "time_updated" in session_columns
                for session_id in session_ids:
                    updated = None
                    if has_updated:
                        session = db.execute(
                            "SELECT time_updated FROM session_v2 WHERE id=?",
                            (session_id,),
                        ).fetchone()
                        updated = session[0] if session else None
                    message = db.execute(message_query, (session_id,)).fetchone()
                    value = _millis(
                        updated
                        if updated is not None
                        else message[0]
                        if message
                        else None
                    )
                    activities[session_id] = (value, value)
        except sqlite3.Error:
            continue
    return activities


def _activity(
    row: dict[str, Any],
    path: Path,
    harness: str,
    window_start: datetime,
    opencode_times: dict[str, tuple[str | None, str | None]],
) -> tuple[str | None, str | None]:
    if harness == "opencode":
        _database, separator, session_id = str(row.get("path", "")).partition("#")
        if separator and session_id in opencode_times:
            return opencode_times[session_id]
        return row.get("started_at"), row.get("started_at")
    try:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime, UTC)
    except OSError:
        return None, None
    if modified_at < window_start:
        return modified_at.isoformat(), modified_at.isoformat()
    first, last = _record_times(path)
    modified = modified_at.isoformat()
    return first or modified, last or modified


def _millis(value: Any) -> str | None:
    if not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC).isoformat()
    except OSError, OverflowError, ValueError:
        return None


def _project(cwd: Any) -> str:
    if not isinstance(cwd, str) or not cwd:
        return "outside any repo"
    current = Path(cwd)
    for candidate in (current, *current.parents):
        try:
            if (candidate / ".git").exists():
                return candidate.name
        except OSError:
            continue
    return "outside any repo"


def _pi_discovery(root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    adapter = harness_adapter(DiagnosticHarness.PI)
    candidates = sorted(islice(root.glob("--*--/*.jsonl"), MAX_DISCOVERY_FILES + 1))
    warnings = []
    if len(candidates) > MAX_DISCOVERY_FILES:
        warnings.append("Pi session discovery reached its 5000-file limit")
    rows = adapter.discover(
        repo=Path("/"), roots={"pi": root}, limit=MAX_DISCOVERY_FILES
    )
    discovered_paths = {str(row.get("source", "")) for row in rows}
    versions = [
        path
        for path in candidates[:MAX_DISCOVERY_FILES]
        if str(path) not in discovered_paths
        and (header := _read_header(path))
        and header.get("version") != 3
    ]
    if versions:
        warnings.append(
            f"Pi skipped {len(versions)} sessions with unsupported versions"
        )
    return [dict(row) for row in rows], warnings


def build_inventory(
    locations: list[Location],
    window: tuple[datetime, datetime],
    pending_paths: set[str] | None = None,
) -> Inventory:
    """Discover each configured root once and retain sessions active in window."""
    result = Inventory(locations=list(locations))
    seen: set[Path] = set()
    for location in locations:
        if location.status != "ok":
            result.statuses.append(
                {
                    "root": str(location.path),
                    "status": location.status,
                    "reason": location.reason,
                }
            )
            continue
        try:
            if location.harness == "pi":
                found, warnings = _pi_discovery(location.path)
            else:
                discovered = discover_root(
                    location.harness,
                    location.path,
                    window_start=window[0],
                    pending_paths=pending_paths,
                    include_skipped=True,
                )
                found = [vars(row) for row in discovered.sessions]
                warnings = discovered.warnings
        except (OSError, ValueError, sqlite3.Error, Diagnose) as error:
            result.statuses.append(
                {"root": str(location.path), "status": "error", "reason": str(error)}
            )
            continue
        for warning in warnings:
            result.statuses.append(
                {"root": str(location.path), "status": "discovery", "reason": warning}
            )
        opencode_times = (
            _opencode_activity(found) if location.harness == "opencode" else {}
        )
        for source in found:
            source_path = source.get("path") or source.get("source") or ""
            raw_path = str(source_path)
            path = Path(raw_path.partition("#")[0])
            canonical = path.resolve(strict=False)
            if location.harness == "opencode" and "#" in raw_path:
                canonical = Path(f"{canonical}#{raw_path.partition('#')[2]}")
            if canonical in seen:
                existing = next(
                    (
                        item
                        for item in result.sessions
                        if Path(item["path"]).resolve(strict=False) == canonical
                    ),
                    None,
                )
                if existing:
                    existing.setdefault("also_in", []).append(str(location.path))
                continue
            seen.add(canonical)
            row = dict(source)
            row.update(root=str(location.path), path=raw_path, harness=location.harness)
            if location.harness == "codex" and row.get("parent_id"):
                row["kind"] = "subagent"
            discovery_status = row.get("status")
            first, last = (
                (None, None)
                if discovery_status in {"skipped", "out_of_window"}
                else _activity(row, path, location.harness, window[0], opencode_times)
            )
            row.update(first_activity=first, last_activity=last)
            row["project"] = _project(row.get("cwd"))
            if discovery_status == "out_of_window":
                row.update(status="skipped: out of window", reason=row.get("reason"))
            elif discovery_status == "skipped":
                row.update(status="skipped", reason=row.get("reason") or "unreadable")
            elif is_ignored(path, location.ignored_paths):
                row.update(status="skipped: ignored", reason="path is ignored")
            elif first is None or last is None:
                row.update(
                    status="skipped: activity unknown",
                    reason="could not determine activity time",
                )
            elif not in_window(row, window):
                row.update(
                    status="skipped: out of window",
                    reason="activity is outside the requested window",
                )
            else:
                row.update(
                    status="analyzable", reason="activity overlaps the requested window"
                )
            result.sessions.append(row)
    return result
