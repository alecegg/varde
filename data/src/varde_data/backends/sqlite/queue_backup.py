"""Verified backup and restore operations for the plan queue database."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.sqlite.queue_schema import SCHEMA_VERSION
from varde_data.errors import Invalid
from varde_data.locking import file_lock
from varde_data.queue_mode_lock import barrier

_DATABASE = ".cache/data/queue.sqlite3"
_BACKUPS = ".cache/data/backups"
_LOCK = ".cache/data/queue.lock"
_REQUIRED_COLUMNS = {
    "queue_items": {
        "id",
        "plan_dir",
        "findings",
        "owned_files",
        "depends_cell",
        "depends_on",
        "serialize_with",
        "priority",
        "state",
        "planned_at",
        "plan_reviewed_at",
        "build_started_at",
        "build_done_at",
        "merged_at",
        "role",
        "claimed_by",
        "claim_expires_at",
        "claim_generation",
        "claim_epoch",
        "queue_name",
        "row_order",
        "extra",
    },
    "queue_events": {
        "seq",
        "item_id",
        "at",
        "actor",
        "kind",
        "from_state",
        "to_state",
        "source",
    },
    "plan_state": {
        "plan_dir",
        "status",
        "status_at",
        "owner",
        "assigned_to",
        "merge_approved_at",
        "last_export_hash",
    },
    "task_state": {"plan_dir", "task_id", "status", "status_at", "last_export_hash"},
    "queue_meta": {"queue_name", "last_export_hash", "header"},
    "meta": {"key", "value"},
}


def backup(root: Path, *, keep: int = 10) -> Path:
    """Create and verify an online backup, retaining the newest ``keep`` copies."""
    if keep < 1:
        raise ValueError("keep must be at least one")
    database = root / _DATABASE
    if not database.is_file():
        raise FileNotFoundError(database)
    directory = root / _BACKUPS
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = directory / f"queue-{timestamp}.sqlite3"
    with file_lock(root / _LOCK, timeout=30):
        with (
            sqlite3.connect(database) as source,
            sqlite3.connect(destination) as target,
        ):
            source.backup(target)
            _verify(target)
            _validate_schema(target)
            counts = _row_counts(target)
        checksum = _checksum(destination)
        _write_manifest(destination, checksum, counts)
        _retain(directory, keep, destination)
    return destination


def restore(root: Path, backup_path: Path) -> Path:
    """Restore a verified backup, preserving the displaced database beside it."""
    database = root / _DATABASE
    source = backup_path.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    database.parent.mkdir(parents=True, exist_ok=True)
    if database.resolve() == source:
        raise Invalid("restore source must be a separate backup file")
    with barrier(root, timeout=30):
        _verify_manifest(source)
        with closing(
            sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
        ) as connection:
            _verify(connection)
            _validate_schema(connection)
            counts = _row_counts(connection)
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise Invalid(
                f"queue backup version {version} does not match supported version "
                f"{SCHEMA_VERSION}"
            )
        if counts != _read_manifest(source)["row_counts"]:
            raise Invalid("queue backup row counts do not match its manifest")
        if database.exists():
            displaced = _unused_name(database.with_name(database.name + ".pre-restore"))
            with (
                closing(sqlite3.connect(database)) as current,
                closing(sqlite3.connect(displaced)) as saved,
            ):
                current.backup(saved)
                _verify(saved)
                _validate_schema(saved)
                saved_counts = _row_counts(saved)
                current.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            _write_manifest(displaced, _checksum(displaced), saved_counts)
            _verify_manifest(displaced)
        else:
            displaced = None
        temporary = database.with_name(f".{database.name}.restore-{os.getpid()}")
        try:
            with (
                closing(sqlite3.connect(source)) as source_db,
                closing(sqlite3.connect(temporary)) as target,
            ):
                source_db.backup(target)
                _verify(target)
                _validate_schema(target)
                if _row_counts(target) != counts:
                    raise Invalid(  # noqa: TRY301 - aborts replacement on mismatch
                        "restored queue row counts do not match the backup"
                    )
                target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                target.execute("PRAGMA journal_mode=DELETE")
            Path(f"{temporary}-wal").unlink(missing_ok=True)
            Path(f"{temporary}-shm").unlink(missing_ok=True)
            Path(f"{database}-wal").unlink(missing_ok=True)
            Path(f"{database}-shm").unlink(missing_ok=True)
            temporary.replace(database)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    return displaced if displaced is not None else database


def _verify(connection: sqlite3.Connection) -> None:
    result = connection.execute("PRAGMA integrity_check").fetchone()
    if result is None or result[0] != "ok":
        raise Invalid(f"queue database integrity check failed: {result}")


def _validate_schema(connection: sqlite3.Connection) -> None:
    for table, required in _REQUIRED_COLUMNS.items():
        columns = {
            str(row[1]) for row in connection.execute(f'PRAGMA table_info("{table}")')
        }
        missing = required - columns
        if missing:
            raise Invalid(
                f"queue database table {table} is missing columns: "
                f"{', '.join(sorted(missing))}"
            )


def _row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    counts: dict[str, int] = {}
    for (table,) in tables:
        quoted = '"' + str(table).replace('"', '""') + '"'
        counts[str(table)] = int(
            connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]  # noqa: S608
        )
    if not counts:
        raise Invalid("queue database contains no tables")
    return counts


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _manifest(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".json")


def _write_manifest(path: Path, checksum: str, counts: dict[str, int]) -> None:
    _manifest(path).write_text(
        json.dumps({"sha256": checksum, "row_counts": counts}, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(_manifest(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Invalid(f"queue backup manifest is missing or invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise Invalid("queue backup manifest is invalid")
    return value


def _verify_manifest(path: Path) -> None:
    manifest = _read_manifest(path)
    if manifest.get("sha256") != _checksum(path):
        raise Invalid("queue backup checksum does not match its manifest")
    if not isinstance(manifest.get("row_counts"), dict):
        raise Invalid("queue backup row counts are missing from its manifest")


def _retain(directory: Path, keep: int, newest: Path) -> None:
    backups = sorted(
        directory.glob("queue-*.sqlite3"), key=lambda path: path.name, reverse=True
    )
    for old in backups[keep:]:
        if old != newest:
            old.unlink()
            _manifest(old).unlink(missing_ok=True)


def _unused_name(path: Path) -> Path:
    candidate = path
    suffix = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.{suffix}")
        suffix += 1
    return candidate
