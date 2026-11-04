"""Derived SQLite index for the canonical friction event log."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from varde_data.backends.sqlite.friction_migrate import prepare_store, rebuild_cache
from varde_data.backends.sqlite.friction_schema import migrate
from varde_data.friction_events import replay
from varde_data.locking import blocking_file_lock

LOG_NAME = "friction.jsonl"
META_BYTES = "log_bytes"
META_HASH = "log_hash"
META_MAP = "log_map"


class SqliteFrictionIndex:
    """Refresh a rebuildable cache from log events while holding the shared lock."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "learn.db"

    def refresh(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        log = self.root / LOG_NAME
        with blocking_file_lock(log):
            if self.path.is_file() and not _has_sqlite_header(self.path):
                if not replay(log).events:
                    raise sqlite3.DatabaseError("friction database header is corrupt")
                self._preserve_corrupt_database()
            try:
                prepare_store(self.root, self.path)
            except sqlite3.DatabaseError as error:
                if not _is_not_a_database(error) or not replay(log).events:
                    raise
                self._preserve_corrupt_database()

        with blocking_file_lock(log):
            try:
                with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
                    migrate(db)
                    self._refresh_database(db)
            except sqlite3.DatabaseError as error:
                if not _is_not_a_database(error) or not replay(log).events:
                    raise
                self._preserve_corrupt_database()
                with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
                    migrate(db)
                    self._refresh_database(db)

    def _refresh_database(self, db: sqlite3.Connection) -> None:
        path = self.root / LOG_NAME
        raw = path.read_bytes() if path.exists() else b""
        complete = (
            raw if not raw or raw.endswith(b"\n") else raw[: raw.rfind(b"\n") + 1]
        )
        digest = hashlib.sha256(complete).hexdigest()
        found = dict(
            db.execute(
                "SELECT key,value FROM meta WHERE key IN (?,?)",
                (META_BYTES, META_HASH),
            )
        )
        if found == {META_BYTES: str(len(complete)), META_HASH: digest}:
            return
        rebuild_cache(db, self.root)

    def read_mapping(self) -> dict[str, dict[str, int | str]]:
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            row = db.execute(
                "SELECT value FROM meta WHERE key=?", (META_MAP,)
            ).fetchone()
        if row is None:
            return {}
        try:
            value = json.loads(row[0])
        except TypeError, ValueError:
            return {}
        return value if isinstance(value, dict) else {}

    def persist_mapping(self, mapping: dict[str, dict[str, int | str]]) -> None:
        if not mapping:
            return
        log = self.root / LOG_NAME
        with (
            blocking_file_lock(log),
            closing(sqlite3.connect(self.path, timeout=30)) as db,
            db,
        ):
            migrate(db)
            rebuild_cache(db, self.root, mapping)

    def _preserve_corrupt_database(self) -> None:
        if not self.path.exists():
            return
        backup = Path(f"{self.path}.corrupt")
        suffix = 1
        while backup.exists():
            backup = Path(f"{self.path}.corrupt.{suffix}")
            suffix += 1
        shutil.copy2(self.path, backup)
        self.path.unlink()
        for sidecar in ("-wal", "-shm"):
            current = Path(f"{self.path}{sidecar}")
            if not current.exists():
                continue
            shutil.copy2(current, Path(f"{backup}{sidecar}"))
            current.unlink()


def _has_sqlite_header(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(16) == b"SQLite format 3\x00"


def _is_not_a_database(error: sqlite3.DatabaseError) -> bool:
    return error.sqlite_errorcode == sqlite3.SQLITE_NOTADB
