"""Calls domain: count, migrate, verify and retire ``cli_calls.jsonl``."""

from __future__ import annotations

import itertools
import os
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

from varde_data.backends.files.calls import iter_rows, parse_line
from varde_data.backends.sqlite.learn_calls import INSERT, SELECT, typed_row
from varde_data.backends.sqlite.learn_calls_upgrade import (
    BACKUP_SUFFIX as V1_BACKUP_SUFFIX,
)
from varde_data.backends.sqlite.learn_calls_upgrade import (
    CALLS_LAYOUT,
    CALLS_LAYOUT_KEY,
    SKIPPED_NAME,
    has_blob_layout,
)
from varde_data.backends.sqlite.learn_schema import connect, count_rows
from varde_data.learn_store_mode import backend_for, learn_db_path
from varde_data.repos.calls import CALLS_NAME, CallRecord

BATCH = 10_000
BACKUP_SUFFIX = ".calls-backup"


def importable(row: CallRecord) -> bool:
    """A row the typed table can hold: it satisfies ``typed_row``."""
    return typed_row(row) is not None


def _file_rows(root: Path) -> Iterator[CallRecord]:
    try:
        yield from (row for row in iter_rows(root / CALLS_NAME) if importable(row))
    except FileNotFoundError:
        return


def skipped_lines(root: Path) -> Iterator[bytes]:
    """Yield raw non-blank file lines that migrate does not import."""
    try:
        with (root / CALLS_NAME).open("rb") as handle:
            for line in handle:
                row = parse_line(line)
                if line.strip() and (row is None or not importable(row)):
                    yield line.rstrip(b"\n")
    except FileNotFoundError:
        return


def rows(root: Path) -> int:
    """Rows the active backend holds."""
    if backend_for(root, "calls") == "sqlite":
        return count_rows(root, "cli_calls")
    return sum(1 for _ in _file_rows(root))


def migrate(root: Path, *, dry_run: bool) -> dict[str, Any]:
    """Import the call log into sqlite, back up the database, then verify.

    The caller holds the exclusive store lock and flips the marker on success.
    Re-running before the flip replaces the imported table. After the flip it
    does nothing, so rows appended to sqlite are never deleted.
    """
    if backend_for(root, "calls") == "sqlite":
        return {"ok": True, "already_migrated": True, "rows": rows(root)}
    expected = sum(1 for _ in _file_rows(root))
    skipped = sum(1 for _ in skipped_lines(root))
    if dry_run:
        return {"ok": True, "rows": expected, "skipped_lines": skipped}
    with closing(connect(root)) as db:
        with db:
            db.execute("DELETE FROM cli_calls")
            for batch in _batches(_file_rows(root)):
                db.executemany(
                    INSERT, [values for row in batch if (values := typed_row(row))]
                )
        backup = learn_db_path(root).with_name(learn_db_path(root).name + BACKUP_SUFFIX)
        with closing(sqlite3.connect(backup)) as target:
            db.backup(target)
    backup.chmod(0o600)
    result = verify(root)
    return {**result, "rows": expected, "skipped_lines": skipped, "backup": str(backup)}


def _batches(items: Iterable[CallRecord]) -> Iterator[list[CallRecord]]:
    iterator = iter(items)
    while batch := list(itertools.islice(iterator, BATCH)):
        yield batch


def verify(root: Path) -> dict[str, Any]:
    """Check the typed layout and, when the file exists, the prefix rule.

    Rows appended to sqlite after the flip follow the file's rows, so the file
    must equal a prefix of the table in count and content.
    """
    file_count = sum(1 for _ in _file_rows(root))
    sqlite_count = count_rows(root, "cli_calls")
    result: dict[str, Any] = {
        "files_rows": file_count,
        "sqlite_rows": sqlite_count,
        "mismatch_at": None,
        "skipped_lines": sum(1 for _ in skipped_lines(root)),
    }
    if not layout_ok(root):
        return {**result, "ok": False, "layout": "not typed"}
    if sqlite_count < file_count:
        return {**result, "ok": False}
    if file_count == 0:
        return {**result, "ok": True}
    with closing(connect(root)) as db:
        stored = db.execute(f"{SELECT} ORDER BY id")
        for index, (expected, actual) in enumerate(
            zip(_file_rows(root), stored, strict=False)
        ):
            if typed_row(expected) != tuple(actual):
                return {**result, "ok": False, "mismatch_at": index}
    return {**result, "ok": True}


def layout_ok(root: Path) -> bool:
    """Whether the calls table has the typed layout (meta ``calls_layout`` is 2)."""
    with closing(connect(root)) as db:
        if has_blob_layout(db):
            return False
        found = db.execute(
            "SELECT value FROM meta WHERE key = ?", (CALLS_LAYOUT_KEY,)
        ).fetchone()
    return found is not None and found[0] == CALLS_LAYOUT


def retire(root: Path) -> dict[str, Any]:
    """Remove the call log file and the migration backups after a passing verify.

    Lines that were never imported are first saved to ``cli_calls.skipped.jsonl``.
    """
    if backend_for(root, "calls") != "sqlite":
        raise ValueError("calls is not on sqlite; migrate it first")
    if not verify(root)["ok"]:
        raise ValueError("calls verify failed; nothing was retired")
    saved = _save_skipped(root)
    removed = []
    database = learn_db_path(root)
    for path in (
        root / CALLS_NAME,
        database.with_name(database.name + BACKUP_SUFFIX),
        database.with_name(database.name + V1_BACKUP_SUFFIX),
    ):
        if path.is_file():
            path.unlink()
            removed.append(path.name)
    return {"removed": removed, "skipped_saved": saved}


def _save_skipped(root: Path) -> int:
    lines = list(skipped_lines(root))
    if not lines:
        return 0
    path = root / SKIPPED_NAME
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, b"\n".join(lines) + b"\n")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    return len(lines)
