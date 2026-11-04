"""One-way in-place upgrade of ``cli_calls`` from the JSON-blob layout (v1)."""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.learn_calls import typed_row
from varde_data.errors import LearnStoreIo

LOG = logging.getLogger(__name__)
BACKUP_SUFFIX = ".calls-v1-backup"
SKIPPED_NAME = "cli_calls.skipped.jsonl"
CALLS_LAYOUT_KEY = "calls_layout"
CALLS_LAYOUT = "2"
_NEW_TABLE = """
CREATE TABLE cli_calls_v2 (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failure', 'blocked')),
    duration_s REAL NOT NULL,
    session TEXT,
    guardrail TEXT,
    arg TEXT
)
"""
_INSERT_V2 = (
    "INSERT INTO cli_calls_v2 (id, ts, command, status, duration_s, session, "
    "guardrail, arg) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)
_SELECT_V2 = (
    "SELECT id, ts, command, status, duration_s, session, guardrail, arg "
    "FROM cli_calls_v2 ORDER BY id"
)
_INDEXES = (
    "CREATE INDEX cli_calls_ts ON cli_calls(ts)",
    "CREATE INDEX cli_calls_session ON cli_calls(session)",
    "CREATE INDEX cli_calls_command ON cli_calls(command)",
)


def has_blob_layout(connection: sqlite3.Connection) -> bool:
    """Whether ``cli_calls`` still has the v1 ``row`` JSON column."""
    columns = connection.execute("PRAGMA table_info(cli_calls)").fetchall()
    return any(column[1] == "row" for column in columns)


def upgrade_calls_layout(connection: sqlite3.Connection) -> None:
    """Upgrade a v1 ``cli_calls`` table in place; do nothing for the typed layout."""
    if not has_blob_layout(connection):
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        if not has_blob_layout(connection):  # another opener finished first
            connection.rollback()
            return
        skipped = _upgrade_locked(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    # after the commit: a rolled-back upgrade must not append the same lines twice
    _write_skipped(_database_path(connection).parent / SKIPPED_NAME, skipped)
    _vacuum(connection)


def _upgrade_locked(connection: sqlite3.Connection) -> list[str]:
    _backup(_database_path(connection))
    expected, skipped = _copy_valid_rows(connection)
    problem = _verify_copy(connection, expected, len(skipped))
    if problem:
        raise LearnStoreIo(
            "upgrade CLI calls layout", _database_path(connection), OSError(problem)
        )
    connection.execute("DROP TABLE cli_calls")
    connection.execute("ALTER TABLE cli_calls_v2 RENAME TO cli_calls")
    for statement in _INDEXES:
        connection.execute(statement)
    connection.execute(
        "INSERT INTO meta (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (CALLS_LAYOUT_KEY, CALLS_LAYOUT),
    )
    return skipped


def _database_path(connection: sqlite3.Connection) -> Path:
    return Path(connection.execute("PRAGMA database_list").fetchone()[2])


def _backup(database: Path) -> None:
    """Copy the database through a second reader: a connection that holds the
    write lock cannot be a backup source (the copy would wait forever)."""
    target = database.with_name(database.name + BACKUP_SUFFIX)
    os.close(os.open(target, os.O_WRONLY | os.O_CREAT, 0o600))
    target.chmod(0o600)
    with (
        closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(target)) as copy,
    ):
        source.backup(copy)


def _copy_valid_rows(
    connection: sqlite3.Connection,
) -> tuple[list[tuple[Any, ...]], list[str]]:
    """Copy valid rows into ``cli_calls_v2``; return them and the skipped texts."""
    connection.execute("DROP TABLE IF EXISTS cli_calls_v2")
    connection.execute(_NEW_TABLE)
    copied: list[tuple[Any, ...]] = []
    skipped: list[str] = []
    for row_id, text in connection.execute(
        "SELECT id, row FROM cli_calls ORDER BY id"
    ).fetchall():
        values = typed_row(_loads(text))
        if values is None:
            skipped.append(text)
            continue
        copied.append((row_id, *values))
    connection.executemany(_INSERT_V2, copied)
    return copied, skipped


def _loads(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return None


def _verify_copy(
    connection: sqlite3.Connection, expected: list[tuple[Any, ...]], skipped: int
) -> str | None:
    """Return a mismatch description, or ``None`` when the copy is exact."""
    old_count = connection.execute("SELECT COUNT(*) FROM cli_calls").fetchone()[0]
    if len(expected) + skipped != old_count:
        return f"copied {len(expected)} plus skipped {skipped} is not {old_count}"
    stored = connection.execute(_SELECT_V2).fetchall()
    if len(stored) != len(expected):
        return f"new table holds {len(stored)} rows, expected {len(expected)}"
    for want, got in zip(expected, stored, strict=True):
        if tuple(got) != want:
            return f"row id {want[0]} differs after copy"
    return None


def _write_skipped(path: Path, skipped: list[str]) -> None:
    if not skipped:
        return
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(descriptor, ("\n".join(skipped) + "\n").encode())
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _vacuum(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("VACUUM")
    except sqlite3.Error as error:
        LOG.warning("VACUUM after the calls layout upgrade failed: %s", error)
