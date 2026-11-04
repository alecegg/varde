"""Schema for the learn store database ``learn.sqlite3``."""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from varde_core.sqlite import configure_connection
from varde_data.errors import Invalid
from varde_data.learn_store_mode import DB_NAME, learn_db_path

SCHEMA_VERSION = 1

_SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS friction_events (
    seq INTEGER PRIMARY KEY,
    event TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS analyzed (
    harness TEXT NOT NULL,
    session TEXT NOT NULL,
    row TEXT NOT NULL,
    PRIMARY KEY (harness, session)
);

CREATE TABLE IF NOT EXISTS digests (
    run_date TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    candidates TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cli_calls (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    command TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('success', 'failure', 'blocked')),
    duration_s REAL NOT NULL,
    session TEXT,
    guardrail TEXT,
    arg TEXT
);

CREATE INDEX IF NOT EXISTS cli_calls_ts ON cli_calls(ts);
CREATE INDEX IF NOT EXISTS cli_calls_session ON cli_calls(session);
CREATE INDEX IF NOT EXISTS cli_calls_command ON cli_calls(command);
"""


def connect(root: Path) -> sqlite3.Connection:
    """Open the learn database, creating or upgrading its schema."""
    root.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(learn_db_path(root), timeout=30)
    try:
        _retry_while_locked(lambda: configure_connection(connection))
        _retry_while_locked(lambda: ensure_schema(connection))
    except BaseException:
        connection.close()
        raise
    return connection


_BUSY_CODES = {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}


def _is_busy(error: sqlite3.OperationalError) -> bool:
    """Whether the error is SQLITE_BUSY or SQLITE_LOCKED, extended codes included."""
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and code & 0xFF in _BUSY_CODES


def _retry_while_locked(step: Callable[[], None], *, timeout: float = 30) -> None:
    """Retry a setup step that races other first openers (WAL switch, schema)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            step()
        except sqlite3.OperationalError as error:
            if not _is_busy(error) or time.monotonic() >= deadline:
                raise
            time.sleep(0.02)
        else:
            return


def ensure_schema(connection: sqlite3.Connection) -> None:
    """Create the current schema, rejecting a database from newer code."""
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise Invalid(  # noqa: TRY003, RUF100
            f"learn database schema {version} is newer than supported "
            f"version {SCHEMA_VERSION}"
        )
    if version < SCHEMA_VERSION:
        with connection:
            connection.executescript(_SCHEMA_V1)
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES ('calls_layout', '2')"
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    from varde_data.backends.sqlite.learn_calls_upgrade import (
        upgrade_calls_layout,
    )

    upgrade_calls_layout(connection)


def count_rows(root: Path, table: str) -> int:
    """Count rows in one known table; zero when the database is absent."""
    if table not in {"friction_events", "analyzed", "cli_calls"}:
        raise ValueError(f"unknown learn table: {table}")
    path = learn_db_path(root)
    if not path.is_file():
        return 0
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
        try:
            return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])  # noqa: S608
        except sqlite3.OperationalError:
            return 0


__all__ = [
    "DB_NAME",
    "SCHEMA_VERSION",
    "connect",
    "count_rows",
    "ensure_schema",
    "learn_db_path",
]
