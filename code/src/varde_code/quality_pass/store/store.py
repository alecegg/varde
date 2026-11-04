"""SQLite and in-memory stores for scan-time quality cache rows."""

from __future__ import annotations

import contextlib

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Never, Self

from varde_code.index.paths import repo_db_path

SCHEMA_VERSION = 1
FILE_NAME = f"quality-v{SCHEMA_VERSION}.sqlite"
KINDS = ("facts", "edges", "measures", "scores")
LAYERS = (*KINDS, "path_classes")
BATCH_ORDER = ("facts", "edges", "measures", "path_classes", "scores")
SQLITE_VARIABLE_LIMIT = 900


def quality_store_path(repo_root: str | Path) -> Path:
    """Return the default quality database path beside this repo's fast index."""
    return repo_db_path(Path(repo_root)).parent / FILE_NAME


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.blake2b(value.encode("utf-8"), digest_size=32).hexdigest()


def _readonly_directory(path: Path) -> bool:
    try:
        mode = path.stat().st_mode
    except OSError:
        return False
    has_write_bit = mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    return not has_write_bit or not os.access(path, os.W_OK)


def _versioned_paths(directory: Path) -> list[tuple[int, Path]]:
    paths = []
    for path in directory.glob("quality-v*.sqlite"):
        match = re.fullmatch(r"quality-v(\d+)\.sqlite", path.name)
        if match:
            paths.append((int(match.group(1)), path))
    return sorted(paths, reverse=True)


def _schema_state(connection: sqlite3.Connection) -> str:
    """Classify a database as current, incomplete quality schema, or foreign."""
    try:
        tables = {
            item[0]
            for item in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        foreign_tables = tables - {"meta", "cache_keys", *LAYERS}
        if foreign_tables:
            return "foreign"
        if "meta" not in tables:
            return "incomplete"
        meta_columns = {
            item[1] for item in connection.execute("PRAGMA table_info(meta)")
        }
        if not {"key", "value"} <= meta_columns:
            return "foreign"
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'schema_version'"
        ).fetchone()
        if row is not None and row[0] != str(SCHEMA_VERSION):
            return "foreign"
        for table in tables - {"meta"}:
            columns = {
                item[1] for item in connection.execute(f"PRAGMA table_info({table})")
            }
            expected = (
                {"layer", "path", "cache_key"}
                if table == "cache_keys"
                else {"path", "cache_key", "value", "digest"}
            )
            if not expected <= columns:
                return "foreign"
        if row is None or not {"meta", "cache_keys", *LAYERS} <= tables:
            return "incomplete"
    except sqlite3.DatabaseError:
        return "foreign"
    else:
        return "current"


def _create_schema(connection: sqlite3.Connection) -> None:
    for table in LAYERS:
        connection.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            "path TEXT NOT NULL, cache_key TEXT NOT NULL, value TEXT NOT NULL, "
            "digest TEXT NOT NULL, PRIMARY KEY(path, cache_key))"
        )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS cache_keys ("
        "layer TEXT NOT NULL, path TEXT NOT NULL, cache_key TEXT NOT NULL, "
        "PRIMARY KEY(layer, path, cache_key))"
    )
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),),
    )


def _begin_immediate(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN IMMEDIATE")


@contextlib.contextmanager
def _startup_lock(directory: Path):
    """Serialize only database discovery and initialization, never repository work."""
    if fcntl is None:
        connection = sqlite3.connect(
            directory / ".quality-store-init.sqlite", timeout=30, isolation_level=None
        )
        try:
            _begin_immediate(connection)
            yield
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()
        return

    lock_path = directory / ".quality-store-init.lock"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _inspect_database(path: Path) -> tuple[sqlite3.Connection, str]:
    connection = sqlite3.connect(
        path, timeout=30, check_same_thread=False, isolation_level=None
    )
    try:
        _begin_immediate(connection)
        state = _schema_state(connection)
        if state == "incomplete":
            _create_schema(connection)
            state = _schema_state(connection)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
        raise
    else:
        return connection, state


def _raise_incompatible_schema(path: Path) -> Never:
    raise sqlite3.DatabaseError(f"cannot initialize incompatible schema: {path}")


def _initialize_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path, timeout=30, check_same_thread=False, isolation_level=None
    )
    try:
        _begin_immediate(connection)
        state = _schema_state(connection)
        if state == "incomplete":
            _create_schema(connection)
        elif state != "current":
            _raise_incompatible_schema(path)
        connection.execute("COMMIT")
    except BaseException:
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        connection.close()
        raise
    else:
        return connection


def _open_database(directory: Path) -> tuple[sqlite3.Connection, Path]:
    candidates = _versioned_paths(directory)
    for _, path in candidates:
        connection, state = _inspect_database(path)
        if state == "current":
            return connection, path
        connection.close()
        if state == "incomplete":
            return _initialize_database(path), path

    highest = max((number for number, _ in candidates), default=0)
    version = max(SCHEMA_VERSION, highest + 1)
    path = directory / f"quality-v{version}.sqlite"
    return _initialize_database(path), path


class Store:
    """A disposable cache with atomic, file-scoped writes."""

    def __init__(
        self, connection: sqlite3.Connection | None, path: Path | None
    ) -> None:
        self._connection = connection
        self.path = path
        self._memory: dict[str, dict[tuple[str, str], tuple[str, str]]] = {
            layer: {} for layer in LAYERS
        }
        self._meta: dict[str, str] = {"schema_version": str(SCHEMA_VERSION)}

    @property
    def meta(self) -> dict[str, str]:
        if self._connection is None:
            return dict(self._meta)
        try:
            return dict(self._connection.execute("SELECT key, value FROM meta"))
        except sqlite3.DatabaseError:
            return dict(self._meta)

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def get_facts(self, path: str, key: str) -> Any | None:
        return self._get("facts", path, key)

    def put_facts(self, path: str, key: str, facts: Any) -> None:
        self.put_batch(path, {"facts": (key, facts)})

    def get_edges(self, path: str, key: str) -> Any | None:
        return self._get("edges", path, key)

    def put_edges(self, path: str, key: str, edges: Any) -> None:
        self.put_batch(path, {"edges": (key, edges)})

    def get_measures(self, path: str, key: str) -> Any | None:
        return self._get("measures", path, key)

    def put_measures(self, path: str, key: str, measures: Any) -> None:
        self.put_batch(path, {"measures": (key, measures)})

    def get_scores(self, path: str, key: str) -> Any | None:
        return self._get("scores", path, key)

    def put_scores(self, path: str, key: str, scores: Any) -> None:
        self.put_batch(path, {"scores": (key, scores)})

    def get_path_class(self, path: str) -> Any | None:
        return self._get("path_classes", path, "path-class")

    def put_path_class(self, path: str, record: Any) -> None:
        self.put_batch(path, {"path_classes": ("path-class", record)})

    def put_batch(self, path: str, values: Mapping[str, tuple[str, Any]]) -> None:
        """Atomically replace this file's cache rows, writing scores last."""
        unknown = set(values) - set(LAYERS)
        if unknown:
            raise ValueError(f"unknown cache layers: {', '.join(sorted(unknown))}")
        if self._connection is None:
            for layer in BATCH_ORDER:
                if layer not in values:
                    continue
                key, value = values[layer]
                for old_key in tuple(self._memory[layer]):
                    if old_key[0] == path:
                        del self._memory[layer][old_key]
                encoded = _json(value)
                self._memory[layer][(path, key)] = (encoded, _digest(encoded))
            return

        connection = self._connection
        _begin_immediate(connection)
        try:
            for layer in BATCH_ORDER:
                if layer not in values:
                    continue
                key, value = values[layer]
                encoded = _json(value)
                connection.execute(f"DELETE FROM {layer} WHERE path = ?", (path,))  # noqa: S608 - Layer is selected from the internal layer constants.
                connection.execute(
                    "DELETE FROM cache_keys WHERE layer = ? AND path = ?",
                    (layer, path),
                )
                connection.execute(
                    f"INSERT OR REPLACE INTO {layer}"  # noqa: S608 - Layer is selected from the internal layer constants.
                    "(path, cache_key, value, digest) VALUES (?, ?, ?, ?)",
                    (path, key, encoded, _digest(encoded)),
                )
                connection.execute(
                    "INSERT OR REPLACE INTO cache_keys(layer, path, cache_key) "
                    "VALUES (?, ?, ?)",
                    (layer, path, key),
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def _get(self, layer: str, path: str, key: str) -> Any | None:
        if self._connection is None:
            row = self._memory[layer].get((path, key))
        else:
            try:
                row = self._connection.execute(
                    f"SELECT value, digest FROM {layer} "  # noqa: S608 - Layer is selected from the internal layer constants.
                    "WHERE path = ? AND cache_key = ?",
                    (path, key),
                ).fetchone()
            except sqlite3.DatabaseError:
                return None
        if row is None:
            return None
        value, digest = row
        if _digest(value) != digest:
            return None
        try:
            return json.loads(value)
        except TypeError, json.JSONDecodeError:
            return None

    def invalidate(self, paths: Iterable[str]) -> None:
        selected = tuple(set(paths))
        if not selected:
            return
        if self._connection is None:
            for layer in LAYERS:
                for key in tuple(self._memory[layer]):
                    if key[0] in selected:
                        del self._memory[layer][key]
            return

        connection = self._connection
        _begin_immediate(connection)
        try:
            for offset in range(0, len(selected), SQLITE_VARIABLE_LIMIT):
                chunk = selected[offset : offset + SQLITE_VARIABLE_LIMIT]
                placeholders = ",".join("?" for _ in chunk)
                for layer in LAYERS:
                    connection.execute(
                        f"DELETE FROM {layer} WHERE path IN ({placeholders})",  # noqa: S608 - Layer and placeholder count are internal values.
                        chunk,
                    )
                connection.execute(
                    f"DELETE FROM cache_keys WHERE path IN ({placeholders})",  # noqa: S608 - Placeholder count comes from the bound-value chunk.
                    chunk,
                )
            connection.execute("COMMIT")
        except BaseException:
            connection.execute("ROLLBACK")
            raise

    def collect_garbage(
        self, seen_paths: Iterable[str], *, size_cap: int = 256 * 1024 * 1024
    ) -> int:
        seen = set(seen_paths)
        if self._connection is None:
            stale = {
                path
                for layer in self._memory.values()
                for path, _ in layer
                if path not in seen
            }
            self.invalidate(stale)
            return len(stale)

        connection = self._connection
        all_paths = {
            row[0] for row in connection.execute("SELECT DISTINCT path FROM cache_keys")
        }
        stale = all_paths - seen
        if self._database_size() > size_cap:
            stale = all_paths
            self.invalidate(stale)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.execute("VACUUM")
            return len(stale)
        self.invalidate(stale)
        return len(stale)

    def _database_size(self) -> int:
        if self.path is None:
            return 0
        total = 0
        for candidate in (self.path, Path(f"{self.path}-wal")):
            with contextlib.suppress(OSError):
                total += candidate.stat().st_size
        return total


def open_store(index_dir: str | Path) -> Store:
    """Open the versioned cache in the index directory; fall back to memory."""
    directory = Path(index_dir)
    connection: sqlite3.Connection | None = None
    try:
        if not directory.is_dir():
            raise FileNotFoundError(f"config directory does not exist: {directory}")
        if _readonly_directory(directory):
            raise PermissionError(f"directory is read-only: {directory}")
        with _startup_lock(directory):
            connection, path = _open_database(directory)
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return Store(connection, path)
    except (OSError, sqlite3.DatabaseError) as exc:
        if connection is not None:
            connection.close()
        print(
            f"quality store unavailable; results are not cached: {exc}", file=sys.stderr
        )
        return Store(None, None)
