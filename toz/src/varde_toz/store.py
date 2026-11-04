"""SQLite store matching the Rust toz-core schema and lock-file protocol."""

from __future__ import annotations

import fcntl
import os
import secrets
import sqlite3
import time
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Self

from varde_toz.chunk import Chunk

SCHEMA_VERSION = "4"
SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS captures (
 id INTEGER PRIMARY KEY, handle TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
 kind TEXT NOT NULL, source TEXT NOT NULL, source_key TEXT NOT NULL,
 bytes INTEGER NOT NULL, exit_code INTEGER,
 created_at INTEGER NOT NULL, session TEXT,
 superseded_by INTEGER REFERENCES captures(id) ON DELETE SET NULL,
 file_mtime INTEGER, file_hash BLOB, redactions INTEGER NOT NULL DEFAULT 0,
 binary INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'completed',
 indexed INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS captures_source_key ON captures(source_key, created_at);
CREATE INDEX IF NOT EXISTS captures_created ON captures(created_at);
CREATE TABLE IF NOT EXISTS chunks (
 id INTEGER PRIMARY KEY,
 capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
 ordinal INTEGER NOT NULL, stream TEXT NOT NULL DEFAULT 'stdout', title TEXT NOT NULL,
 line_start INTEGER NOT NULL, line_end INTEGER NOT NULL, content_type TEXT NOT NULL,
 body TEXT NOT NULL, indexed INTEGER NOT NULL DEFAULT 1);
CREATE INDEX IF NOT EXISTS chunks_capture ON chunks(capture_id, ordinal);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_porter USING fts5(
 title, body, content='chunks', content_rowid='id', tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_trigram USING fts5(
 title, body, content='chunks', content_rowid='id', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks WHEN new.indexed = 1 BEGIN
 INSERT INTO chunks_porter(rowid,title,body) VALUES(new.id,new.title,new.body);
 INSERT INTO chunks_trigram(rowid,title,body) VALUES(new.id,new.title,new.body); END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks WHEN old.indexed = 1 BEGIN
 INSERT INTO chunks_porter(chunks_porter,rowid,title,body)
 VALUES('delete',old.id,old.title,old.body);
 INSERT INTO chunks_trigram(chunks_trigram,rowid,title,body)
 VALUES('delete',old.id,old.title,old.body); END;
CREATE TABLE IF NOT EXISTS stats_log(
 id INTEGER PRIMARY KEY,ts INTEGER NOT NULL,kind TEXT NOT NULL,
 bytes_in INTEGER NOT NULL,bytes_out INTEGER NOT NULL,session TEXT);
CREATE INDEX IF NOT EXISTS stats_ts ON stats_log(ts);
CREATE TABLE IF NOT EXISTS query_log(
 id INTEGER PRIMARY KEY,ts INTEGER NOT NULL,kind TEXT NOT NULL,
 bytes_out INTEGER NOT NULL,session TEXT,outcome TEXT NOT NULL DEFAULT 'ok',
 details_json TEXT);
CREATE INDEX IF NOT EXISTS query_ts ON query_log(ts);
CREATE TABLE IF NOT EXISTS capture_records(
 id INTEGER PRIMARY KEY,
 capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
 kind TEXT NOT NULL,seq INTEGER NOT NULL,json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS capture_records_lookup
 ON capture_records(capture_id,kind,seq);
CREATE TABLE IF NOT EXISTS profile_diagnostics(
 id INTEGER PRIMARY KEY,
 capture_id INTEGER NOT NULL REFERENCES captures(id) ON DELETE CASCADE,
 profile_id TEXT NOT NULL,reason TEXT NOT NULL,created_at INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS profile_diagnostics_created
 ON profile_diagnostics(created_at);
"""
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


@dataclass(frozen=True)
class Retention:
    days: int = 30
    superseded_days: int = 7
    max_mb: int = 500


@dataclass
class NewCapture:
    label: str
    kind: str
    source: str
    source_key: str = ""
    legacy_source_key: str | None = None
    bytes: int = 0
    exit_code: int | None = 0
    session: str | None = None
    redactions: int = 0
    binary: bool = False
    file_mtime: int | None = None
    file_hash: bytes | None = None


class Store:
    def __init__(self, path: str | Path, *, readonly: bool = False):
        self.path = Path(path)
        self.live_locks: dict[str, BinaryIO] = {}
        if readonly:
            self.conn = sqlite3.connect(
                f"file:{self.path}?mode=ro", uri=True, timeout=30
            )
            self.conn.execute("PRAGMA busy_timeout=30000")
            return
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        existed = self.path.exists()
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")
        current = self._schema_is_current()
        if not current:
            self._initialize(existed)
        else:
            self.conn.execute("PRAGMA synchronous=NORMAL")
            if self.conn.execute(
                "SELECT 1 FROM captures WHERE state='running' LIMIT 1"
            ).fetchone():
                self._recover_stale_with_lock()

    def _schema_is_current(self) -> bool:
        try:
            row = self.conn.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return False
        return row is not None and row[0] == SCHEMA_VERSION

    def _initialize(self, existed: bool) -> None:
        lock_path = self.path.with_suffix(".db.init.lock")
        with lock_path.open("a+b") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            if self._schema_is_current():
                self.conn.execute("PRAGMA synchronous=NORMAL")
                self._recover_stale_live_captures()
                return
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.executescript("BEGIN;" + SCHEMA + "COMMIT;")
            with self.conn:
                self._migrate()
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                    (SCHEMA_VERSION,),
                )
                if not existed:
                    os.chmod(self.path, 0o600)
                self._recover_stale_live_captures()

    def _recover_stale_with_lock(self) -> None:
        lock_path = self.path.with_suffix(".db.init.lock")
        with lock_path.open("a+b") as lock:
            os.chmod(lock_path, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._recover_stale_live_captures()

    @contextmanager
    def _write_transaction(self):
        if self.conn.in_transaction:
            yield
            return
        with self.conn:
            yield

    @classmethod
    def open(cls, path: str | Path) -> Store:
        return cls(path)

    @classmethod
    def open_readonly(cls, path: str | Path) -> Store:
        return cls(path, readonly=True)

    def _migrate(self) -> None:
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(captures)")}
        if "state" not in columns:
            self.conn.execute(
                "ALTER TABLE captures ADD COLUMN state TEXT NOT NULL "
                "DEFAULT 'completed'"
            )
        for name, declaration in (
            ("outcome", "TEXT NOT NULL DEFAULT 'ok'"),
            ("details_json", "TEXT"),
        ):
            columns = {
                row[1] for row in self.conn.execute("PRAGMA table_info(query_log)")
            }
            if name not in columns:
                self.conn.execute(
                    f"ALTER TABLE query_log ADD COLUMN {name} {declaration}"
                )
        for name, event, condition, statements in (
            (
                "chunks_ai",
                "INSERT",
                "WHEN new.indexed=1",
                (
                    "INSERT INTO chunks_porter(rowid,title,body) "
                    "VALUES(new.id,new.title,new.body); "
                    "INSERT INTO chunks_trigram(rowid,title,body) "
                    "VALUES(new.id,new.title,new.body);"
                ),
            ),
            (
                "chunks_ad",
                "DELETE",
                "WHEN old.indexed=1",
                (
                    "INSERT INTO chunks_porter(chunks_porter,rowid,title,body) "
                    "VALUES('delete',old.id,old.title,old.body); "
                    "INSERT INTO chunks_trigram(chunks_trigram,rowid,title,body) "
                    "VALUES('delete',old.id,old.title,old.body);"
                ),
            ),
        ):
            sql = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='trigger' AND name=?", (name,)
            ).fetchone()
            if sql and condition in sql[0]:
                continue
            self.conn.execute(f"DROP TRIGGER IF EXISTS {name}")
            self.conn.executescript(
                f"CREATE TRIGGER {name} AFTER {event} ON chunks {condition} "
                f"BEGIN {statements} END;"
            )

    def _recover_stale_live_captures(self) -> None:
        rows = list(
            self.conn.execute("SELECT handle FROM captures WHERE state='running'")
        )
        for (handle,) in rows:
            path = self._live_lock_path(handle)
            with path.open("a+b") as lock:
                os.chmod(path, 0o600)
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    continue
                self.conn.execute(
                    "UPDATE captures SET state='interrupted' WHERE handle=?", (handle,)
                )
                path.unlink(missing_ok=True)

    def _live_lock_path(self, handle: str) -> Path:
        return self.path.with_name(f"toz-live-{handle}.lock")

    def _handle(self) -> str:
        for size in range(4, 64):
            value = "".join(secrets.choice(ALPHABET) for _ in range(size))
            if not self.conn.execute(
                "SELECT 1 FROM captures WHERE handle=?", (value,)
            ).fetchone():
                return value
        raise RuntimeError("could not allocate capture handle")

    def insert_capture(
        self,
        capture: NewCapture,
        chunks: Iterable[tuple[str, Chunk]],
        *,
        indexed: bool = True,
    ) -> str:
        with self._write_transaction():
            handle = self._handle()
            cursor = self.conn.execute(
                """INSERT INTO captures(
                handle,label,kind,source,source_key,bytes,exit_code,created_at,
                session,redactions,binary,file_mtime,file_hash,indexed)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    handle,
                    capture.label,
                    capture.kind,
                    capture.source,
                    capture.source_key,
                    capture.bytes,
                    capture.exit_code,
                    int(time.time()),
                    capture.session,
                    capture.redactions,
                    int(capture.binary),
                    capture.file_mtime,
                    capture.file_hash,
                    int(indexed),
                ),
            )
            capture_id = cursor.lastrowid
            self.conn.executemany(
                (
                    "INSERT INTO chunks(capture_id,ordinal,stream,title,line_start,"
                    "line_end,content_type,body,indexed) VALUES(?,?,?,?,?,?,?,?,?)"
                ),
                (
                    (
                        capture_id,
                        ordinal,
                        stream,
                        chunk.title,
                        chunk.line_start,
                        chunk.line_end,
                        chunk.content_type,
                        chunk.body,
                        int(indexed),
                    )
                    for ordinal, (stream, chunk) in enumerate(chunks)
                ),
            )
            if capture.source_key:
                keys = [capture.source_key]
                if capture.legacy_source_key:
                    keys.append(capture.legacy_source_key)
                marks = ",".join("?" for _ in keys)
                self.conn.execute(
                    f"UPDATE captures SET superseded_by=? "  # noqa: S608 - marks contains only one placeholder per key.
                    f"WHERE source_key IN ({marks}) AND id!=? "
                    "AND superseded_by IS NULL",
                    (capture_id, *keys, capture_id),
                )
            return handle

    def reserve_live_capture(self, capture: NewCapture) -> str:
        handle = self._handle()
        path = self._live_lock_path(handle)
        lock = path.open("a+b")
        os.chmod(path, 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        with self.conn:
            self.conn.execute(
                (
                    "INSERT INTO captures(handle,label,kind,source,source_key,bytes,"
                    "exit_code,created_at,session,redactions,binary,file_mtime,"
                    "file_hash,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,'running')"
                ),
                (
                    handle,
                    capture.label,
                    capture.kind,
                    capture.source,
                    capture.source_key,
                    capture.bytes,
                    capture.exit_code,
                    int(time.time()),
                    capture.session,
                    capture.redactions,
                    int(capture.binary),
                    capture.file_mtime,
                    capture.file_hash,
                ),
            )
        self.live_locks[handle] = lock
        return handle

    def append_live_chunk(self, handle: str, stream: str, chunk: Chunk) -> None:
        row = self.conn.execute(
            "SELECT id FROM captures WHERE handle=? AND state='running'", (handle,)
        ).fetchone()
        if not row:
            raise KeyError(handle)
        ordinal = self.conn.execute(
            "SELECT COUNT(*) FROM chunks WHERE capture_id=?", row
        ).fetchone()[0]
        self.conn.execute(
            (
                "INSERT INTO chunks(capture_id,ordinal,stream,title,line_start,"
                "line_end,content_type,body) VALUES(?,?,?,?,?,?,?,?)"
            ),
            (
                row[0],
                ordinal,
                stream,
                chunk.title,
                chunk.line_start,
                chunk.line_end,
                chunk.content_type,
                chunk.body,
            ),
        )

    def finish_live_capture(
        self,
        handle: str,
        *,
        bytes: int | None = None,
        exit_code: int | None = 0,
        redactions: int | None = None,
    ) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE captures SET state='completed',bytes=COALESCE(?,bytes), "
                "exit_code=?,redactions=COALESCE(?,redactions) WHERE handle=?",
                (bytes, exit_code, redactions, handle),
            )
        self._release_live_lock(handle)

    def cancel_live_capture(self, handle: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM captures WHERE handle=? AND state='running'", (handle,)
            )
        self._release_live_lock(handle)

    def _release_live_lock(self, handle: str) -> None:
        lock = self.live_locks.pop(handle, None)
        if lock is not None:
            lock.close()
        self._live_lock_path(handle).unlink(missing_ok=True)

    def chunks_for(self, capture_id: int) -> list[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        return list(
            self.conn.execute(
                "SELECT id,ordinal,stream,title,line_start,line_end,content_type,body "
                "FROM chunks WHERE capture_id=? ORDER BY ordinal",
                (capture_id,),
            )
        )

    def full_text(self, capture_id: int, stream: str = "stdout") -> str:
        lines: list[str] = []
        for start, body in self.conn.execute(
            "SELECT line_start,body FROM chunks WHERE capture_id=? AND stream=? "
            "ORDER BY ordinal",
            (capture_id, stream),
        ):
            first = int(start) - 1
            for offset, line in enumerate(body.split("\n")):
                if first + offset >= len(lines):
                    lines.append(line)
        return "\n".join(lines)

    def line_count(self, capture_id: int, stream: str = "stdout") -> int:
        return int(
            self.conn.execute(
                "SELECT COALESCE(MAX(line_end),0) FROM chunks "
                "WHERE capture_id=? AND stream=?",
                (capture_id, stream),
            ).fetchone()[0]
        )

    def insert_records(
        self, capture_id: int, records: Iterable[tuple[str, str]]
    ) -> None:
        seq: dict[str, int] = {}
        with self._write_transaction():
            for kind, body in records:
                ordinal = seq.get(kind, 0)
                self.conn.execute(
                    "INSERT INTO capture_records(capture_id,kind,seq,json) "
                    "VALUES(?,?,?,?)",
                    (capture_id, kind, ordinal, body),
                )
                seq[kind] = ordinal + 1

    def records_for(self, capture_id: int, kind: str) -> list[str]:
        return [
            row[0]
            for row in self.conn.execute(
                "SELECT json FROM capture_records WHERE capture_id=? AND kind=? "
                "ORDER BY seq",
                (capture_id, kind),
            )
        ]

    def search(
        self, query: str, *, limit: int = 20, substring: bool = False
    ) -> list[sqlite3.Row]:
        table = "chunks_trigram" if substring or len(query) < 3 else "chunks_porter"
        self.conn.row_factory = sqlite3.Row
        return list(
            self.conn.execute(
                f"SELECT c.id,c.capture_id,c.ordinal,c.stream,c.title,c.line_start,"  # noqa: S608 - table is selected from the two internal FTS table names.
                f"c.line_end,c.content_type,c.body,bm25({table}) AS rank FROM {table} "
                f"JOIN chunks c ON c.id={table}.rowid WHERE {table} MATCH ? "
                "ORDER BY rank,c.id LIMIT ?",
                (query, limit),
            )
        )

    def index_deferred(self, handle: str | None = None) -> int:
        rows = list(
            self.conn.execute(
                "SELECT id FROM captures WHERE indexed=0 AND (? IS NULL OR handle=?)",
                (handle, handle),
            )
        )
        with self.conn:
            for (capture_id,) in rows:
                self.conn.execute(
                    "INSERT INTO chunks_porter(rowid,title,body) "
                    "SELECT id,title,body FROM chunks WHERE capture_id=?",
                    (capture_id,),
                )
                self.conn.execute(
                    "INSERT INTO chunks_trigram(rowid,title,body) "
                    "SELECT id,title,body FROM chunks WHERE capture_id=?",
                    (capture_id,),
                )
                self.conn.execute(
                    "UPDATE chunks SET indexed=1 WHERE capture_id=?", (capture_id,)
                )
                self.conn.execute(
                    "UPDATE captures SET indexed=1 WHERE id=?", (capture_id,)
                )
        return len(rows)

    def get_by_handle(self, handle: str):
        self.conn.row_factory = sqlite3.Row
        return self.conn.execute(
            "SELECT c.*,(SELECT COUNT(*) FROM chunks ch WHERE ch.capture_id=c.id) "
            "AS chunk_count FROM captures c WHERE handle=?",
            (handle,),
        ).fetchone()

    def list(self, limit: int = 20, include_superseded: bool = False):
        self.conn.row_factory = sqlite3.Row
        suffix = "" if include_superseded else " WHERE superseded_by IS NULL"
        return list(
            self.conn.execute(
                "SELECT * FROM captures" + suffix + " ORDER BY created_at DESC LIMIT ?",  # noqa: S608 - suffix is either empty or a fixed predicate.
                (limit,),
            )
        )

    def maybe_prune(self, policy) -> int:
        last = self.conn.execute(
            "SELECT value FROM meta WHERE key='last_prune'"
        ).fetchone()
        if last and int(time.time()) - int(last[0]) < 3600:
            return 0
        removed = self.prune(policy)
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES('last_prune',?)",
            (str(int(time.time())),),
        )
        return removed

    def prune(self, policy) -> int:
        now = int(time.time())
        before_chunks = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        with self.conn:
            removed = self.conn.execute(
                "DELETE FROM captures WHERE created_at<? AND state!='running'",
                (now - int(policy.days) * 86400,),
            ).rowcount
            removed += self.conn.execute(
                "DELETE FROM captures WHERE superseded_by IS NOT NULL "
                "AND created_at<? AND state!='running'",
                (now - int(policy.superseded_days) * 86400,),
            ).rowcount
        after_chunks = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if before_chunks and (before_chunks - after_chunks) * 10 >= before_chunks:
            self._optimize_fts()
        cap_bytes = int(policy.max_mb) * 1024 * 1024
        while self.db_used_size_bytes() > cap_bytes:
            row = self.conn.execute(
                "SELECT id FROM captures WHERE state!='running' "
                "ORDER BY (superseded_by IS NULL),created_at LIMIT 1"
            ).fetchone()
            if row is None:
                break
            with self.conn:
                self.conn.execute("DELETE FROM captures WHERE id=?", row)
            removed += 1
        page_size, page_count, free = self._page_stats()
        if (
            free * 20 >= page_count
            and page_count
            and (page_size * page_count > cap_bytes or free * 4 > page_count)
        ):
            self.conn.execute("VACUUM")
        return removed

    def _optimize_fts(self) -> None:
        for table in ("chunks_trigram", "chunks_porter"):
            self.conn.execute(f"INSERT INTO {table}({table}) VALUES('optimize')")

    def _page_stats(self) -> tuple[int, int, int]:
        return tuple(
            self.conn.execute(f"PRAGMA {name}").fetchone()[0]
            for name in ("page_size", "page_count", "freelist_count")
        )

    def db_used_size_bytes(self) -> int:
        size, count, free = self._page_stats()
        return size * (count - free)

    def db_size_bytes(self) -> int:
        size, count, _ = self._page_stats()
        return size * count

    def vacuum(self) -> None:
        self.conn.execute("VACUUM")

    def delete_older_than(self, seconds: int) -> int:
        with self.conn:
            return self.conn.execute(
                "DELETE FROM captures WHERE created_at<? AND state!='running'",
                (int(time.time()) - seconds,),
            ).rowcount

    def close(self) -> None:
        for handle in list(self.live_locks):
            self._release_live_lock(handle)
        self.conn.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_exc) -> None:
        self.close()
