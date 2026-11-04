"""Relational lookups that enrich pattern matches from the persisted index."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from varde_code import ApiError


@dataclass(frozen=True)
class EnclosingFact:
    name: str
    is_async: bool | None


class EnclosingLookup:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def lookup(
        self, file_path: str, start_byte: int, end_byte: int
    ) -> EnclosingFact | None:
        try:
            row = self.conn.execute(
                """SELECT e.name, e.is_async FROM entities e JOIN files f
                   ON f.id=e.file_id WHERE f.path=? AND e.kind=0
                   AND e.start_byte<=? AND e.end_byte>=?
                   ORDER BY (e.end_byte-e.start_byte) ASC LIMIT 1""",
                (file_path, start_byte, end_byte),
            ).fetchone()
        except sqlite3.Error as error:
            raise ApiError("db_error", str(error)) from error
        return (
            None
            if row is None
            else EnclosingFact(row[0], None if row[1] is None else bool(row[1]))
        )


class TestPathLookup:
    __test__ = False

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.cache: dict[str, tuple[bool, bool]] = {}
        self.canonical_cache: dict[str, tuple[bool, bool]] | None = None

    def _lookup(self, file_path: str) -> tuple[bool, bool]:
        if file_path not in self.cache:
            try:
                row = self.conn.execute(
                    "SELECT is_test_path,is_tooling_path FROM files WHERE path=?",
                    (file_path,),
                ).fetchone()
                self.cache[file_path] = (
                    (bool(row[0]), bool(row[1])) if row else (False, False)
                )
                if row is None:
                    # Rust looks up these flags after matching
                    # (pattern.rs:306-314, db.rs:98-155); lexical normalization
                    # makes python-tree.scan return 235 instead of 187.
                    if self.canonical_cache is None:
                        self.canonical_cache = {
                            str(Path(path).resolve()): (bool(is_test), bool(is_tooling))
                            for path, is_test, is_tooling in self.conn.execute(
                                "SELECT path,is_test_path,is_tooling_path FROM files"
                            )
                        }
                    self.cache[file_path] = self.canonical_cache.get(
                        str(Path(file_path).resolve()), (False, False)
                    )
            except sqlite3.Error:
                self.cache[file_path] = (False, False)
        return self.cache[file_path]

    def is_test_path(self, file_path: str) -> bool:
        return self._lookup(file_path)[0]

    def is_tooling_path(self, file_path: str) -> bool:
        return self._lookup(file_path)[1]


def enclosing_function_entity(
    conn: sqlite3.Connection, file_path: str, start_byte: int, end_byte: int
) -> EnclosingFact | None:
    return EnclosingLookup(conn).lookup(file_path, start_byte, end_byte)
