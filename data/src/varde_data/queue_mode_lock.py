"""Mode locks for the queue store.

Every queue, plan, or task state read or write must run inside ``operation``.
Migrations hold ``barrier`` while changing the store and flipping its mode.
"""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Literal

from varde_data.backends.sqlite.queue_schema import (
    MESSAGE_SCHEMA_VERSION,
    QUEUE_MARKER_VERSION,
    SCHEMA_VERSION,
)
from varde_data.errors import Invalid, Locked
from varde_data.locking import file_lock, shared_file_lock
from varde_data.queue_paths import (
    LEGACY_QUEUE_DATABASE,
    QUEUE_DATABASE,
    read_queue_version,
)

StoreMode = Literal["markdown", "sqlite"]
_LOCK = Path(".queue.mode.lock")
_DATABASE = QUEUE_DATABASE
_DEFAULT_TIMEOUT = 30.0
_local = threading.local()


def _callback_depth() -> int:
    return getattr(_local, "callback_depth", 0)


def _active_operations() -> dict[Path, tuple[StoreMode, int]]:
    operations = getattr(_local, "operations", None)
    if operations is None:
        operations = {}
        _local.operations = operations
    return operations


def _owned_barriers() -> dict[Path, int]:
    barriers = getattr(_local, "barriers", None)
    if barriers is None:
        barriers = {}
        _local.barriers = barriers
    return barriers


@contextmanager
def callback_scope() -> Iterator[None]:
    """Mark execution of a queue fence or ready callback as reentry unsafe."""
    _local.callback_depth = _callback_depth() + 1
    try:
        yield
    finally:
        _local.callback_depth -= 1


def _read_mode(working: Path) -> StoreMode:
    database = _database_for_mode(working)
    if not database.exists():
        return "markdown"
    try:
        with closing(
            sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        ) as db:
            is_unified = database == working / _DATABASE
            meta_table = "queue_store_meta" if is_unified else "meta"
            tables = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (meta_table,),
            ).fetchone()
            if tables is None:
                return "markdown"
            query = (
                "SELECT value FROM queue_store_meta WHERE key='store_mode'"
                if is_unified
                else "SELECT value FROM meta WHERE key='store_mode'"
            )
            row = db.execute(query).fetchone()
    except sqlite3.Error as error:
        raise Invalid(f"cannot read queue store mode: {error}") from error
    mode = row[0] if row is not None else "markdown"
    if mode not in ("markdown", "sqlite"):
        raise Invalid(f"invalid queue store mode: {mode!r}")
    return mode


def _database_for_mode(working: Path) -> Path:
    version = read_queue_version(working)
    if version >= QUEUE_MARKER_VERSION:
        return working / _DATABASE
    legacy = working / LEGACY_QUEUE_DATABASE
    unified = working / _DATABASE
    return legacy if legacy.is_file() else unified


def require_role_queue_ready(working: Path) -> None:
    """Reject queue opens until the explicit physical merge is verified."""
    version = read_queue_version(working)
    if version != QUEUE_MARKER_VERSION:
        raise Invalid(
            f"role queue marker is {version}, expected {QUEUE_MARKER_VERSION}; run "
            "`varde plan queue merge-role-inbox` with the runner stopped"
        )
    database = working / _DATABASE
    if not database.is_file():
        raise Invalid(
            "role inbox database is missing; run `varde plan queue "
            "merge-role-inbox` with the runner stopped"
        )
    try:
        with closing(
            sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
        ) as db:
            message_version = int(db.execute("PRAGMA user_version").fetchone()[0])
            row = db.execute(
                "SELECT value FROM queue_store_meta WHERE key='schema_version'"
            ).fetchone()
            queue_version = int(row[0]) if row else 0
            mode_row = db.execute(
                "SELECT value FROM queue_store_meta WHERE key='store_mode'"
            ).fetchone()
            required_tables = {
                "queue_items",
                "queue_events",
                "queue_meta",
                "plan_state",
                "task_state",
                "slots",
                "slot_events",
            }
            tables = {
                str(row[0])
                for row in db.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise Locked(f"role inbox queue schema check is busy: {exc}") from exc
        raise Invalid(f"role inbox queue schema is unavailable: {exc}") from exc
    except (sqlite3.Error, ValueError) as exc:
        raise Invalid(f"role inbox queue schema is unavailable: {exc}") from exc
    if (
        message_version != MESSAGE_SCHEMA_VERSION
        or queue_version != SCHEMA_VERSION
        or mode_row is None
        or not required_tables <= tables
    ):
        raise Invalid(
            "role inbox queue schema markers disagree; run `varde plan queue "
            "merge-role-inbox` or restore the queue backup"
        )


@contextmanager
def operation(
    working: Path, *, timeout: float = _DEFAULT_TIMEOUT
) -> Iterator[StoreMode]:
    """Hold a shared mode lock while a state operation selects its backend."""
    if _callback_depth():
        raise Invalid("queue callbacks cannot re-enter operation()")
    lock_path = (working / _LOCK).resolve()
    if lock_path in _owned_barriers():
        yield _read_mode(working)
        return
    active = _active_operations()
    current = active.get(lock_path)
    if current is not None:
        mode, depth = current
        active[lock_path] = (mode, depth + 1)
        try:
            yield mode
        finally:
            _leave_operation(active, lock_path, mode, depth + 1)
        return

    with shared_file_lock(lock_path, timeout=timeout):
        mode = _read_mode(working)
        active[lock_path] = (mode, 1)
        try:
            yield mode
        finally:
            _leave_operation(active, lock_path, mode, 1)


def _leave_operation(
    active: dict[Path, tuple[StoreMode, int]],
    lock_path: Path,
    mode: StoreMode,
    depth: int,
) -> None:
    if depth == 1:
        del active[lock_path]
        return
    active[lock_path] = (mode, depth - 1)


@contextmanager
def barrier(working: Path, timeout: float = _DEFAULT_TIMEOUT) -> Iterator[None]:
    """Hold the exclusive mode lock across migration and mode verification."""
    if _callback_depth():
        raise Invalid("queue callbacks cannot enter barrier()")
    lock_path = (working / _LOCK).resolve()
    barriers = _owned_barriers()
    depth = barriers.get(lock_path)
    if depth is not None:
        barriers[lock_path] = depth + 1
        try:
            yield
        finally:
            barriers[lock_path] = depth
        return
    if lock_path in _active_operations():
        raise Invalid("barrier() cannot be entered from operation()")
    with file_lock(lock_path, timeout=timeout):
        barriers[lock_path] = 1
        try:
            yield
        finally:
            del barriers[lock_path]
