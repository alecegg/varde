"""Public administration operations for the plan queue store."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from varde_data.backends.sqlite.messages import SQLiteMessages
from varde_data.backends.sqlite.queue_backup import backup, restore
from varde_data.backends.sqlite.queue_schema import (
    QUEUE_MARKER_VERSION,
    SCHEMA_VERSION,
    configure_store,
)
from varde_data.errors import Invalid, WrongMode
from varde_data.locking import atomic_write
from varde_data.queue_mode_lock import operation, require_role_queue_ready
from varde_data.queue_paths import (
    LEGACY_QUEUE_DATABASE,
    QUEUE_DATABASE,
    QUEUE_VERSION_MARKER,
    read_queue_version,
)

QUEUE_MIGRATION_COMMAND = "varde plan queue merge-role-inbox"


def status(root: Path) -> dict[str, Any]:
    """Return the public store status report."""
    marker = read_queue_version(root)
    database = root / (
        QUEUE_DATABASE if marker >= QUEUE_MARKER_VERSION else LEGACY_QUEUE_DATABASE
    )
    migration_pending = marker < QUEUE_MARKER_VERSION and (
        marker > 0 or (root / LEGACY_QUEUE_DATABASE).is_file()
    )
    migration_message = (
        f"queue migration pending: run {QUEUE_MIGRATION_COMMAND}"
        if migration_pending
        else None
    )
    with operation(root) as mode:
        if not database.is_file():
            return {
                "mode": mode,
                "database": str(database),
                "exists": False,
                "migration_pending": migration_pending,
                "migration_message": migration_message,
            }
        with (
            closing(
                sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
            ) as db,
            db,
        ):
            merged = marker >= QUEUE_MARKER_VERSION
            version_query = (
                "SELECT value FROM queue_store_meta WHERE key='schema_version'"
                if merged
                else "SELECT value FROM meta WHERE key='schema_version'"
            )
            version_row = db.execute(version_query).fetchone()
            pragma_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            version = int(version_row[0]) if version_row else pragma_version
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            mode_query = (
                "SELECT value FROM queue_store_meta WHERE key='store_mode'"
                if merged
                else "SELECT value FROM meta WHERE key='store_mode'"
            )
            row = db.execute(mode_query).fetchone()
            queries = {
                "queue_items": "SELECT COUNT(*) FROM queue_items",
                "plan_state": "SELECT COUNT(*) FROM plan_state",
                "task_state": "SELECT COUNT(*) FROM task_state",
            }
            counts = {
                table: int(db.execute(query).fetchone()[0])
                for table, query in queries.items()
                if table in tables
            }
    return {
        "mode": str(row[0]) if row else mode,
        "database": str(database),
        "exists": True,
        "schema_version": version,
        "supported_schema_version": SCHEMA_VERSION,
        "migration_pending": migration_pending,
        "migration_message": migration_message,
        "counts": counts,
    }


def create_backup(root: Path) -> Path:
    """Create a verified backup of the queue database."""
    if read_queue_version(root) >= QUEUE_MARKER_VERSION:
        from varde_data.role_queue_merge import backup_role_queue

        return backup_role_queue(root)
    return backup(root)


def restore_backup(root: Path, source: Path) -> Path:
    """Restore a verified queue database backup."""
    if read_queue_version(root) >= QUEUE_MARKER_VERSION:
        from varde_data.role_queue_merge import restore_role_queue

        restore_role_queue(root, source)
        return root / QUEUE_DATABASE
    return restore(root, source)


def initialize(root: Path) -> None:
    """Initialize the queue store schema."""
    if (
        read_queue_version(root) < QUEUE_MARKER_VERSION
        and (root / LEGACY_QUEUE_DATABASE).is_file()
    ):
        raise Invalid(
            "legacy SQLite queue remains active; run `varde plan queue "
            "merge-role-inbox` before initializing the merged store"
        )
    database = root / QUEUE_DATABASE
    database.parent.mkdir(parents=True, exist_ok=True)
    SQLiteMessages(database)
    with closing(sqlite3.connect(database)) as db, db:
        configure_store(db)
        db.execute(
            "INSERT INTO queue_store_meta(key,value) VALUES('store_mode','markdown') "
            "ON CONFLICT(key) DO NOTHING"
        )
    atomic_write(
        root / QUEUE_VERSION_MARKER,
        f"{QUEUE_MARKER_VERSION}\n".encode("ascii"),
        mode=0o600,
    )


def export_metadata(root: Path) -> tuple[list[str], list[Path]]:
    """Return queue names and plan paths in stable export order."""
    database = root / QUEUE_DATABASE
    if not database.is_file():
        raise FileNotFoundError(database)
    require_role_queue_ready(root)
    with operation(root) as mode:
        if mode != "sqlite":
            raise WrongMode("queue store is not in sqlite mode")
        with (
            closing(
                sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
            ) as db,
            db,
        ):
            names = [
                str(row[0])
                for row in db.execute(
                    "SELECT queue_name FROM queue_meta ORDER BY queue_name"
                )
            ]
            plans = [
                Path(str(row[0]))
                for row in db.execute(
                    "SELECT plan_dir FROM plan_state ORDER BY plan_dir"
                )
            ]
    return names, plans
