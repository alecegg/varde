"""Friction handlers for ``varde learn store``: rows, migrate, verify, retire.

The store lock is held by the caller. ``migrate`` imports ``friction.jsonl``
into ``learn.sqlite3`` and leaves every source file untouched; ``retire``
removes them after a passing ``verify``.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from contextlib import closing, suppress
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.friction import META_HASH
from varde_data.backends.sqlite.learn_friction import (
    insert_event_rows,
    read_event_rows,
    read_mapping,
    replay_rows,
    write_mapping,
    write_transaction,
)
from varde_data.backends.sqlite.learn_schema import connect, count_rows
from varde_data.errors import DataError
from varde_data.friction_events import replay
from varde_data.learn_store_mode import read_learn_mode
from varde_data.records.friction import Event, LogReplay

LOG_NAME = "friction.jsonl"
LEGACY_INDEX = "learn.db"
RETIRED_FILES = (
    LOG_NAME,
    LEGACY_INDEX,
    f"{LEGACY_INDEX}-wal",
    f"{LEGACY_INDEX}-shm",
    f"{LEGACY_INDEX}.init.lock",
    f"{LEGACY_INDEX}.pre-log.map",
)
BACKUP_NAME = "learn.sqlite3.friction-backup"


def rows(root: Path) -> int:
    """Count the events in the store the marker names."""
    if read_learn_mode(root).friction == "sqlite":
        return count_rows(root, "friction_events")
    return len(_source(root).events)


def migrate(root: Path, *, dry_run: bool) -> dict[str, Any]:
    """Import the friction log idempotently; the caller flips the marker."""
    source = _source(root)
    present = _source_lines(source)
    legacy_map, legacy_problem = _read_legacy(root)
    if legacy_problem:
        return {"ok": False, "problems": [legacy_problem]}
    if dry_run:
        return {
            "ok": True,
            "would_import": len(present) - len(_stored_ids(root)),
            "events": len(source.events),
            "torn_tail": bool(source.torn_line),
        }
    imported = _import(root, source, present, legacy_map)
    result = verify(root)
    if result["ok"]:
        _backup(root)
    return {**result, "imported": imported}


def verify(root: Path) -> dict[str, Any]:
    """Check every source event is in sqlite with the same content and numeric ID."""
    source_path = root / LOG_NAME
    try:
        stored = _stored(root)
    except DataError as error:
        return {"ok": False, "problems": [f"sqlite log does not replay: {error}"]}
    if not source_path.is_file():
        return {"ok": True, "events": len(stored.events), "source": "absent"}
    try:
        source = replay(source_path)
    except DataError as error:
        return {"ok": False, "problems": [f"source log does not replay: {error}"]}
    problems = _differences(source, stored) + _map_problems(root)
    return {
        "ok": not problems,
        "events": len(source.events),
        "stored_events": len(stored.events),
        "items": _count_kind(stored.events, "item_added"),
        "torn_tail": bool(source.torn_line),
        "problems": problems,
    }


def retire(root: Path) -> dict[str, Any]:
    """Remove the friction log, the legacy index, its lock and its ID map."""
    removed = []
    for name in RETIRED_FILES:
        with suppress(FileNotFoundError):
            (root / name).unlink()
            removed.append(name)
    return {"removed": removed}


def _backup(root: Path) -> None:
    """Online-backup the imported database; the temp file never outlives a failure."""
    target = root / BACKUP_NAME
    temp = root / f"{BACKUP_NAME}.tmp"
    try:
        with closing(connect(root)) as source, closing(sqlite3.connect(temp)) as copy:
            source.backup(copy)
        os.replace(temp, target)
    finally:
        with suppress(FileNotFoundError):
            temp.unlink()


def _source(root: Path) -> LogReplay:
    return replay(root / LOG_NAME)


def _source_lines(source: LogReplay) -> list[tuple[str, str]]:
    """Return ``(event id, stored line)`` pairs in log order."""
    return [
        (event.id, line.removesuffix("\n"))
        for event, line in zip(source.events, source.lines, strict=True)
    ]


def _stored_ids(root: Path) -> set[str]:
    return {event.id for event in _stored(root).events} if _db_present(root) else set()


def _db_present(root: Path) -> bool:
    return (root / "learn.sqlite3").is_file()


def _stored(root: Path) -> LogReplay:
    if not _db_present(root):
        return LogReplay([])
    with closing(connect(root)) as db:
        return replay_rows(read_event_rows(db))


def _import(
    root: Path,
    source: LogReplay,
    present: list[tuple[str, str]],
    legacy_map: dict[str, dict[str, Any]],
) -> int:
    with closing(connect(root)) as db, write_transaction(db):
        have = {event.id for event in replay_rows(read_event_rows(db)).events}
        missing = [line for event_id, line in present if event_id not in have]
        insert_event_rows(db, missing)
        if legacy_map:
            write_mapping(db, legacy_map)
    return len(missing)


def _differences(source: LogReplay, stored: LogReplay) -> list[str]:
    """List source rows missing or altered in sqlite; later appended rows are fine."""
    count = len(source.events)
    head = stored.events[:count]
    problems: list[str] = []
    if [e.to_dict() for e in source.events] != [e.to_dict() for e in head]:
        problems.append("source events are missing or differ in sqlite")
    if tuple(line.removesuffix("\n") for line in source.lines) != tuple(
        line.removesuffix("\n") for line in stored.lines[:count]
    ):
        problems.append("stored lines differ from the source lines")
    if _numbers(source.events) != _numbers(head):
        problems.append("numeric IDs differ from the source log")
    return problems


def _map_problems(root: Path) -> list[str]:
    legacy, problem = _read_legacy(root)
    if problem:
        return [problem]
    if not legacy or not _db_present(root):
        return []
    with closing(connect(root)) as db:
        kept = read_mapping(db)
    missing = any(
        kept.get(section, {}).get(key) != value
        for section, values in legacy.items()
        for key, value in values.items()
    )
    return ["legacy ID map entries are missing from sqlite"] if missing else []


def _numbers(events: list[Event]) -> dict[str, dict[str, int]]:
    """Number each event kind by log order, as learn's ``EventNumbers`` does."""
    numbers: dict[str, dict[str, int]] = {}
    for event in events:
        kind = numbers.setdefault(event.kind, {})
        kind[event.id] = len(kind) + 1
    return numbers


def _count_kind(events: list[Event], kind: str) -> int:
    return sum(1 for event in events if event.kind == kind)


def _read_legacy(root: Path) -> tuple[dict[str, dict[str, Any]], str | None]:
    """Read the legacy index's ID map; refuse an unreadable or stale index.

    Without ``learn.db`` the map is empty: IDs and slugs derive from the event
    order, exactly as the files backend rebuilds them.
    """
    path = root / LEGACY_INDEX
    if not path.is_file():
        return {}, None
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            stored_hash = db.execute(
                "SELECT value FROM meta WHERE key = ?", (META_HASH,)
            ).fetchone()
            mapping = read_mapping(db)
    except sqlite3.Error as error:
        return {}, f"learn.db is unreadable ({error}); its ID map would be lost"
    if stored_hash is None or stored_hash[0] != _log_hash(root):
        return {}, (
            "learn.db is out of date with friction.jsonl; run "
            "`varde learn friction list` to refresh it, then migrate again"
        )
    return mapping, None


def _log_hash(root: Path) -> str:
    """Hash the complete lines of the log the way the legacy index does."""
    path = root / LOG_NAME
    raw = path.read_bytes() if path.exists() else b""
    complete = raw if not raw or raw.endswith(b"\n") else raw[: raw.rfind(b"\n") + 1]
    return hashlib.sha256(complete).hexdigest()
