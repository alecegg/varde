"""SQLite schema creation and migrations for the plan queue store."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid

SCHEMA_VERSION = 4
MESSAGE_SCHEMA_VERSION = 5
QUEUE_MARKER_VERSION = 4

_SCHEMA_V1 = (
    """CREATE TABLE IF NOT EXISTS queue_items (
        id TEXT PRIMARY KEY,
        plan_dir TEXT NOT NULL,
        findings TEXT NOT NULL,
        owned_files TEXT NOT NULL,
        depends_cell TEXT NOT NULL DEFAULT '',
        depends_on TEXT NOT NULL DEFAULT '[]',
        serialize_with TEXT NOT NULL DEFAULT '[]',
        priority INTEGER NOT NULL DEFAULT 0,
        state TEXT NOT NULL,
        planned_at TEXT,
        plan_reviewed_at TEXT,
        build_started_at TEXT,
        build_done_at TEXT,
        merged_at TEXT,
        role TEXT,
        claimed_by TEXT,
        claim_expires_at TEXT,
        claim_generation INTEGER NOT NULL DEFAULT 0,
        claim_epoch INTEGER,
        queue_name TEXT NOT NULL,
        row_order INTEGER,
        extra TEXT NOT NULL DEFAULT '{}',
        UNIQUE(queue_name, id)
    )""",
    """CREATE TABLE IF NOT EXISTS queue_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id TEXT NOT NULL,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        kind TEXT NOT NULL,
        from_state TEXT,
        to_state TEXT,
        source TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS plan_state (
        plan_dir TEXT PRIMARY KEY,
        status TEXT NOT NULL,
        status_at TEXT,
        owner TEXT,
        assigned_to TEXT,
        merge_approved_at TEXT,
        last_export_hash TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS task_state (
        plan_dir TEXT NOT NULL,
        task_id TEXT NOT NULL,
        status TEXT NOT NULL,
        status_at TEXT,
        last_export_hash TEXT,
        PRIMARY KEY(plan_dir, task_id)
    )""",
    """CREATE TABLE IF NOT EXISTS queue_meta (
        queue_name TEXT PRIMARY KEY,
        last_export_hash TEXT,
        header TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS queue_store_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )""",
)

_SCHEMA_V2 = (
    """CREATE TABLE IF NOT EXISTS slots (
        slot_id TEXT PRIMARY KEY,
        plan_id TEXT NOT NULL,
        role TEXT NOT NULL,
        lease_s INTEGER NOT NULL,
        agent_ref TEXT,
        session_id TEXT,
        state TEXT NOT NULL,
        epoch INTEGER NOT NULL DEFAULT 1,
        last_progress_at TEXT,
        last_progress_note TEXT,
        context_tokens INTEGER,
        turn_count INTEGER NOT NULL DEFAULT 0,
        checkpoint TEXT,
        updated_at TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS slot_events (
        seq INTEGER PRIMARY KEY AUTOINCREMENT,
        slot_id TEXT NOT NULL,
        at TEXT NOT NULL,
        actor TEXT NOT NULL,
        kind TEXT NOT NULL,
        epoch INTEGER NOT NULL,
        detail TEXT
    )""",
)


def migrate(connection: sqlite3.Connection) -> None:
    """Apply queue schema migrations atomically, refusing newer databases."""
    if _is_unified_database(connection):
        _migrate_unified(connection)
        return
    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.DatabaseError as exc:
        raise _invalid_database(f"cannot read queue database version: {exc}") from exc
    if current > SCHEMA_VERSION:
        raise Invalid(
            f"queue database version {current} is newer than supported version "
            f"{SCHEMA_VERSION}; recover with `varde plan store restore` from a "
            "backup or `varde plan store import` from the markdown export"
        )
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchone()
    except sqlite3.DatabaseError as exc:
        message = f"queue database integrity check failed: {exc}"
        raise _invalid_database(message) from exc
    if integrity is None or integrity[0] != "ok":
        raise _invalid_database(f"queue database integrity check failed: {integrity}")
    configure_connection(connection)
    if current == SCHEMA_VERSION:
        return

    connection.execute("BEGIN IMMEDIATE")
    try:
        current = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current > SCHEMA_VERSION:
            raise Invalid(  # noqa: TRY301 - the schema version is the validation
                f"queue database version {current} is newer than supported version "
                f"{SCHEMA_VERSION}"
            )
        if current < 1:
            for statement in _SCHEMA_V1:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 1")
            current = 1
        if current < 2:
            for statement in _SCHEMA_V2:
                connection.execute(statement)
            connection.execute("PRAGMA user_version = 2")
            current = 2
        if current < 3:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(queue_items)")
            }
            if "followup_depth" not in columns:
                connection.execute(
                    "ALTER TABLE queue_items ADD COLUMN followup_depth "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute("PRAGMA user_version = 3")
            current = 3
        if current < 4:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS queue_store_meta "
                "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO queue_store_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )
            connection.execute("PRAGMA user_version = 4")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def configure_store(connection: sqlite3.Connection) -> None:
    """Configure WAL and bring the database to the supported schema version."""
    migrate(connection)


def _is_unified_database(connection: sqlite3.Connection) -> bool:
    path = str(connection.execute("PRAGMA database_list").fetchone()[2])
    return Path(path).name == "messages.sqlite3" and Path(path).parent.name == "inbox"


def _migrate_unified(connection: sqlite3.Connection) -> None:
    message_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if message_version != MESSAGE_SCHEMA_VERSION:
        raise Invalid(
            f"role inbox message schema is {message_version}; expected "
            f"{MESSAGE_SCHEMA_VERSION}. Initialize or restore the message store "
            "before merging the queue."
        )
    configure_connection(connection)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS queue_store_meta "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    row = connection.execute(
        "SELECT value FROM queue_store_meta WHERE key='schema_version'"
    ).fetchone()
    current = int(row[0]) if row else 0
    if current > SCHEMA_VERSION:
        raise Invalid(
            f"role queue schema {current} is newer than supported {SCHEMA_VERSION}"
        )
    if current == SCHEMA_VERSION:
        return
    connection.execute("BEGIN IMMEDIATE")
    try:
        for statement in _SCHEMA_V1:
            connection.execute(statement)
        for statement in _SCHEMA_V2:
            connection.execute(statement)
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(queue_items)")
        }
        if "followup_depth" not in columns:
            connection.execute(
                "ALTER TABLE queue_items ADD COLUMN followup_depth "
                "INTEGER NOT NULL DEFAULT 0"
            )
        connection.execute(
            "INSERT INTO queue_store_meta(key,value) VALUES('schema_version',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(SCHEMA_VERSION),),
        )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def _invalid_database(message: str) -> Invalid:
    return Invalid(
        f"{message}; recover with `varde plan store restore` from a backup or "
        "`varde plan store import` from the markdown export"
    )
