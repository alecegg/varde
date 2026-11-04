"""SQLite schema creation and migrations for the friction store."""

from __future__ import annotations

import sqlite3

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid

SCHEMA_VERSION = 5

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    repo_root TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'promoted', 'archived')),
    target TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS occurrences (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    cwd TEXT NOT NULL,
    repo_root TEXT,
    head_sha TEXT,
    evidence TEXT NOT NULL,
    cost TEXT
);

CREATE TABLE IF NOT EXISTS status_changes (
    id INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    from_status TEXT NOT NULL CHECK (
        from_status IN ('open', 'resolved', 'promoted', 'archived')
    ),
    to_status TEXT NOT NULL CHECK (
        to_status IN ('open', 'resolved', 'promoted', 'archived')
    ),
    reason TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS occurrences_item_id ON occurrences(item_id, id);
CREATE INDEX IF NOT EXISTS status_changes_item_id ON status_changes(item_id, id);
"""

_SCHEMA_V2 = """
CREATE TABLE IF NOT EXISTS adoptions (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    summary TEXT NOT NULL,
    target_files TEXT NOT NULL,
    commit_sha TEXT,
    eval_before TEXT,
    eval_after TEXT
);

CREATE TABLE IF NOT EXISTS adoption_items (
    adoption_id INTEGER NOT NULL REFERENCES adoptions(id) ON DELETE CASCADE,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    PRIMARY KEY (adoption_id, item_id)
);
"""

_SCHEMA_V3 = """
CREATE TABLE IF NOT EXISTS incident_provenance (
    incident_key TEXT PRIMARY KEY,
    occurrence_id INTEGER NOT NULL UNIQUE REFERENCES occurrences(id) ON DELETE CASCADE,
    identity_version INTEGER NOT NULL CHECK (identity_version = 1),
    harness TEXT NOT NULL,
    thread_id TEXT NOT NULL,
    incident_kind TEXT NOT NULL,
    witness_id TEXT,
    source_id TEXT NOT NULL,
    record_index INTEGER NOT NULL CHECK (record_index >= 0),
    byte_start INTEGER NOT NULL CHECK (byte_start >= 0),
    byte_end INTEGER NOT NULL CHECK (byte_end >= byte_start),
    record_digest TEXT NOT NULL,
    payload_digest TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS incident_provenance_witness
    ON incident_provenance(harness, thread_id, witness_id);
"""

_SCHEMA_V5 = """
CREATE TABLE IF NOT EXISTS item_tags (
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    PRIMARY KEY (item_id, tag)
);
CREATE INDEX IF NOT EXISTS item_tags_tag ON item_tags(tag, item_id);
"""


def schema_version(connection: sqlite3.Connection) -> int:
    row = connection.execute(
        "SELECT value FROM meta WHERE key = 'schema_version'"
    ).fetchone()
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError) as error:
        raise Invalid(f"invalid friction schema version {row[0]!r}") from error


def table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return (
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        is not None
    )


def database_has_rows(connection: sqlite3.Connection) -> bool:
    for table in ("items", "occurrences", "status_changes", "adoptions"):
        if (
            table_exists(connection, table)
            and connection.execute(
                f'SELECT 1 FROM "{table}" LIMIT 1'  # noqa: S608 - allowlisted table name
            ).fetchone()
        ):
            return True
    return False


def read_schema_version(connection: sqlite3.Connection) -> int:
    return schema_version(connection) if table_exists(connection, "meta") else 0


def migrate(connection: sqlite3.Connection) -> None:
    configure_connection(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        current = read_schema_version(connection)
        if current > SCHEMA_VERSION:
            raise Invalid(  # noqa: TRY301 - the schema version is the validation
                f"friction database version {current} is newer than supported version "
                f"{SCHEMA_VERSION}"
            )
        if current < 1:
            _execute_batch(connection, _SCHEMA_V1)
            _write_schema_version(connection, 1)
        if current < 2:
            _execute_batch(connection, _SCHEMA_V2)
            _write_schema_version(connection, 2)
        if current < 4:
            _execute_batch(connection, _SCHEMA_V3)
            _write_schema_version(connection, 4)
        if current < 5:
            _execute_batch(connection, _SCHEMA_V5)
            _write_schema_version(connection, 5)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


def configure_store(connection: sqlite3.Connection) -> None:
    configure_connection(connection)
    migrate(connection)


def _write_schema_version(connection: sqlite3.Connection, version: int) -> None:
    connection.execute(
        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(version),),
    )


def _execute_batch(connection: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if statement.strip():
            connection.execute(statement)
