"""Explicit, reversible migration of queue tables into the role inbox DB."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.sqlite.messages import SQLiteMessages, messages_db_path
from varde_data.backends.sqlite.queue_schema import (
    MESSAGE_SCHEMA_VERSION,
    QUEUE_MARKER_VERSION,
    SCHEMA_VERSION,
    configure_store,
)
from varde_data.errors import Conflict, Invalid
from varde_data.locking import atomic_write, file_lock
from varde_data.queue_mode_lock import barrier, operation
from varde_data.queue_paths import (
    LEGACY_QUEUE_DATABASE,
    QUEUE_DATABASE,
    QUEUE_VERSION_MARKER,
    read_queue_version,
)

LEGACY_QUEUE_SCHEMA_VERSION = 3
MESSAGE_MODE_LOCK = Path(".cache/inbox/store-mode.lock")
QUEUE_TABLES = (
    "queue_items",
    "queue_events",
    "queue_meta",
    "plan_state",
    "task_state",
    "slots",
    "slot_events",
)


@dataclass(frozen=True)
class MergeReport:
    verified: bool
    backup: Path | None
    already_merged: bool = False
    row_counts: dict[str, int] | None = None


def merge_role_queue(working: Path, *, timeout: float = 30) -> MergeReport:
    """Back up and copy the v3 queue into the message database, then flip marker."""
    root = working.resolve()
    with (
        barrier(root, timeout=timeout),
        file_lock(root / MESSAGE_MODE_LOCK, timeout=timeout),
    ):
        marker = read_queue_version(root)
        target = root / QUEUE_DATABASE
        if marker == QUEUE_MARKER_VERSION:
            _validate_merged_target(target)
            return MergeReport(
                True, None, already_merged=True, row_counts=_counts(target)
            )
        if marker != LEGACY_QUEUE_SCHEMA_VERSION:
            raise Invalid(
                f"queue marker is {marker}; expected {LEGACY_QUEUE_SCHEMA_VERSION} "
                f"before merge or {SCHEMA_VERSION} after merge"
            )
        source = root / LEGACY_QUEUE_DATABASE
        _validate_legacy_source(source)
        queue_backup = _snapshot(
            source,
            root / ".cache/data/backups",
            "queue-before-role-inbox",
            queue_marker=marker,
        )
        target_backup = None
        if target.is_file():
            target_backup = _snapshot(
                target,
                root / ".cache/inbox/backups",
                "inbox-before-queue-merge",
            )
        try:
            _prepare_target(target, root)
            _copy_queue_tables(source, target)
            _verify_equal(source, target)
            _checkpoint("after_copy")
            _write_queue_mode(target)
            _write_queue_version(root, QUEUE_MARKER_VERSION)
        except BaseException:
            _restore_target(target, target_backup)
            raise
        return MergeReport(True, queue_backup, row_counts=_counts(target))


def rollback_role_queue(working: Path, *, timeout: float = 30) -> MergeReport:
    """Copy current queue state back to the retained queue DB and restore v3 marker."""
    root = working.resolve()
    with (
        barrier(root, timeout=timeout),
        file_lock(root / MESSAGE_MODE_LOCK, timeout=timeout),
    ):
        marker = read_queue_version(root)
        if marker != SCHEMA_VERSION:
            raise Conflict(f"role queue is not merged (marker {marker})")
        target = root / QUEUE_DATABASE
        source = root / LEGACY_QUEUE_DATABASE
        _validate_merged_target(target)
        if not source.is_file():
            raise Invalid(f"retained legacy queue database is missing: {source}")
        backup = _snapshot(
            source,
            root / ".cache/data/backups",
            "queue-before-role-inbox-rollback",
            queue_marker=LEGACY_QUEUE_SCHEMA_VERSION,
        )
        _copy_queue_tables(target, source, reverse=True)
        _verify_equal(source, target)
        with closing(sqlite3.connect(source)) as db, db:
            db.execute(f"PRAGMA user_version={LEGACY_QUEUE_SCHEMA_VERSION}")
        _write_queue_version(root, LEGACY_QUEUE_SCHEMA_VERSION)
        _clear_merged_queue_rows(target)
        return MergeReport(True, backup, row_counts=_counts(source))


def backup_role_queue(working: Path) -> Path:
    """Back up the merged database without changing the active inbox."""
    with operation(working):
        return _snapshot(
            working / QUEUE_DATABASE,
            working / ".cache/inbox/backups",
            "queue-role-inbox",
            queue_marker=SCHEMA_VERSION,
        )


def restore_role_queue(working: Path, backup: Path) -> None:
    """Restore queue-owned tables from a merged backup, keeping current mail."""
    with barrier(working):
        target = working / QUEUE_DATABASE
        _validate_merged_target(target)
        _verify_snapshot_manifest(backup)
        _validate_merged_target(backup)
        _copy_merged_queue_tables(backup, target)
        _verify_equal_merged(backup, target)


def verify_merged_database(path: Path) -> None:
    """Verify that a merged role inbox contains both supported schemas."""
    _validate_merged_target(path)


def _clear_merged_queue_rows(database: Path) -> None:
    """Neutralize the inactive merged queue after rollback to the legacy DB."""
    with closing(sqlite3.connect(database)) as db:
        db.execute("BEGIN IMMEDIATE")
        try:
            for table in QUEUE_TABLES:
                db.execute(f'DELETE FROM "{table}"')  # noqa: S608
            db.execute(
                "DELETE FROM queue_store_meta WHERE key NOT IN "
                "('schema_version','store_mode')"
            )
            db.commit()
        except BaseException:
            db.rollback()
            raise


def _copy_merged_queue_tables(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row
        dst.execute("BEGIN IMMEDIATE")
        try:
            for table in QUEUE_TABLES:
                columns = _columns(src, table)
                quoted = ",".join(f'"{column}"' for column in columns)
                dst.execute(f'DELETE FROM "{table}"')  # noqa: S608
                rows = src.execute(f'SELECT {quoted} FROM "{table}"').fetchall()  # noqa: S608
                if rows:
                    dst.executemany(
                        f'INSERT INTO "{table}" ({quoted}) VALUES '  # noqa: S608
                        f"({','.join('?' for _ in columns)})",
                        [tuple(row) for row in rows],
                    )
            rows = src.execute(
                "SELECT key,value FROM queue_store_meta WHERE key NOT IN "
                "('schema_version','store_mode')"
            ).fetchall()
            dst.execute(
                "DELETE FROM queue_store_meta WHERE key NOT IN "
                "('schema_version','store_mode')"
            )
            dst.executemany("INSERT INTO queue_store_meta(key,value) VALUES(?,?)", rows)
            dst.commit()
        except BaseException:
            dst.rollback()
            raise


def _verify_equal_merged(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        for table in QUEUE_TABLES:
            if _ordered_rows(src, table) != _ordered_rows(dst, table):
                raise Conflict(f"queue restore parity mismatch in {table}")
        _integrity(dst, "role inbox database")


def _prepare_target(target: Path, root: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    SQLiteMessages(messages_db_path(root))
    with closing(sqlite3.connect(target)) as db:
        configure_store(db)
        db.execute(
            "INSERT INTO queue_store_meta(key,value) VALUES('store_mode','sqlite') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )


def _validate_legacy_source(path: Path) -> None:
    if not path.is_file():
        raise Invalid(f"legacy SQLite queue is missing: {path}")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if version != LEGACY_QUEUE_SCHEMA_VERSION:
            raise Invalid(
                f"legacy queue schema is {version}; expected "
                f"{LEGACY_QUEUE_SCHEMA_VERSION}"
            )
        mode = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()
        if mode is None or mode[0] != "sqlite":
            raise Invalid("legacy queue must be in sqlite mode before merge")
        for table in (*QUEUE_TABLES, "meta"):
            if not _table_exists(db, table):
                raise Invalid(f"legacy queue is missing table {table}")
        _integrity(db, "legacy queue")


def _validate_merged_target(path: Path) -> None:
    if not path.is_file():
        raise Invalid(f"role inbox database is missing: {path}")
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
        message_version = int(db.execute("PRAGMA user_version").fetchone()[0])
        if message_version != MESSAGE_SCHEMA_VERSION:
            raise Invalid(
                f"role inbox message schema is {message_version}; expected "
                f"{MESSAGE_SCHEMA_VERSION}"
            )
        row = db.execute(
            "SELECT value FROM queue_store_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None or int(row[0]) != SCHEMA_VERSION:
            raise Invalid("role inbox queue schema marker is missing or mismatched")
        for table in (*QUEUE_TABLES, "queue_store_meta"):
            if not _table_exists(db, table):
                raise Invalid(f"role inbox database is missing table {table}")
        _integrity(db, "role inbox database")


def _copy_queue_tables(source: Path, target: Path, *, reverse: bool = False) -> None:
    source_meta = "queue_store_meta" if reverse else "meta"
    target_meta = "meta" if reverse else "queue_store_meta"
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        src.row_factory = sqlite3.Row
        dst.row_factory = sqlite3.Row
        dst.execute("BEGIN IMMEDIATE")
        try:
            for table in QUEUE_TABLES:
                columns = _columns(src, table)
                if set(columns) != set(_columns(dst, table)):
                    raise Invalid(  # noqa: TRY301 - abort transaction on schema drift.
                        f"queue table columns differ for {table}"
                    )
                quoted = ",".join(f'"{column}"' for column in columns)
                dst.execute(f'DELETE FROM "{table}"')  # noqa: S608
                rows = src.execute(f'SELECT {quoted} FROM "{table}"').fetchall()  # noqa: S608
                if rows:
                    dst.executemany(
                        f'INSERT INTO "{table}" ({quoted}) VALUES '  # noqa: S608
                        f"({','.join('?' for _ in columns)})",
                        [tuple(row) for row in rows],
                    )
            columns = _columns(src, source_meta)
            dst.execute(f'DELETE FROM "{target_meta}"')  # noqa: S608
            rows = src.execute(f'SELECT * FROM "{source_meta}"').fetchall()  # noqa: S608
            if rows:
                dst.executemany(
                    f'INSERT INTO "{target_meta}" '  # noqa: S608
                    f"({','.join(f'"{column}"' for column in columns)}) "
                    f"VALUES ({','.join('?' for _ in columns)})",
                    [tuple(row) for row in rows if row[0] != "schema_version"],
                )
            if not reverse:
                dst.execute(
                    "INSERT INTO queue_store_meta(key,value) "
                    "VALUES('schema_version',?)",
                    (str(SCHEMA_VERSION),),
                )
            dst.commit()
        except BaseException:
            dst.rollback()
            raise


def _verify_equal(source: Path, target: Path) -> None:
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(target)) as dst,
    ):
        for table in QUEUE_TABLES:
            left = _ordered_rows(src, table)
            right = _ordered_rows(dst, table)
            if left != right:
                raise Conflict(f"queue migration parity mismatch in {table}")
        source_meta = _metadata_rows(src, "meta")
        target_meta = _metadata_rows(dst, "queue_store_meta")
        target_meta.pop("schema_version", None)
        source_meta.pop("schema_version", None)
        if source_meta != target_meta:
            raise Conflict("queue migration parity mismatch in metadata")
        _integrity(dst, "role inbox database")


def _ordered_rows(db: sqlite3.Connection, table: str) -> list[tuple[object, ...]]:
    columns = _columns(db, table)
    return [
        tuple(row)
        for row in db.execute(
            f'SELECT * FROM "{table}" ORDER BY {",".join(f'"{c}"' for c in columns)}'  # noqa: S608
        )
    ]


def _metadata_rows(db: sqlite3.Connection, table: str) -> dict[str, str]:
    if not _table_exists(db, table):
        return {}
    rows = db.execute(f'SELECT * FROM "{table}"')  # noqa: S608
    return {str(key): str(value) for key, value in rows}


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in db.execute(f'PRAGMA table_info("{table}")')]


def _table_exists(db: sqlite3.Connection, table: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        is not None
    )


def _integrity(db: sqlite3.Connection, name: str) -> None:
    result = db.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise Invalid(f"{name} integrity check failed: {result}")


def _snapshot(
    source: Path,
    directory: Path,
    prefix: str,
    *,
    queue_marker: int | None = None,
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = directory / f"{prefix}-{stamp}.sqlite3"
    with (
        closing(sqlite3.connect(source)) as src,
        closing(sqlite3.connect(destination)) as dst,
    ):
        src.backup(dst)
        _integrity(dst, f"backup {destination}")
        counts = _counts_connection(dst)
    checksum = _checksum(destination)
    manifest = {
        "source": str(source),
        "sha256": checksum,
        "row_counts": counts,
        "queue_marker": queue_marker,
    }
    destination.with_suffix(".sqlite3.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    return destination


def _restore_target(target: Path, backup: Path | None) -> None:
    if backup is None:
        for suffix in ("", "-wal", "-shm"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        return
    replacement = Path(f"{target}.restore")
    for suffix in ("-wal", "-shm"):
        Path(f"{replacement}{suffix}").unlink(missing_ok=True)
    with (
        closing(sqlite3.connect(backup)) as src,
        closing(sqlite3.connect(replacement)) as dst,
    ):
        src.backup(dst)
    for suffix in ("-wal", "-shm"):
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    replacement.replace(target)


def _checkpoint(step: str) -> None:
    """Crash injection point used by migration tests."""


def _write_queue_version(root: Path, version: int) -> None:
    atomic_write(
        root / QUEUE_VERSION_MARKER,
        f"{version}\n".encode("ascii"),
        mode=0o600,
    )


def _write_queue_mode(database: Path) -> None:
    with closing(sqlite3.connect(database)) as db, db:
        db.execute(
            "INSERT INTO queue_store_meta(key,value) VALUES('store_mode','sqlite') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
        )


def _counts(path: Path) -> dict[str, int]:
    with closing(sqlite3.connect(path)) as db:
        return _counts_connection(db)


def _counts_connection(db: sqlite3.Connection) -> dict[str, int]:
    tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {
        str(table): int(
            db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]  # noqa: S608
        )
        for (table,) in tables
    }


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_snapshot_manifest(path: Path) -> None:
    try:
        manifest = json.loads(
            path.with_suffix(path.suffix + ".json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise Invalid(f"queue backup manifest is missing or invalid: {exc}") from exc
    if manifest.get("sha256") != _checksum(path):
        raise Invalid("queue backup checksum does not match its manifest")
