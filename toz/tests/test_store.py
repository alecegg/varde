from __future__ import annotations

import os

from varde_toz.chunk import chunk_default
from varde_toz.store import NewCapture, Store


def test_schema_search_migrations_and_permissions(tmp_path):
    path = tmp_path / "nested" / "toz.db"
    store = Store.open(path)
    handle = store.insert_capture(
        NewCapture("demo", "run", "demo", bytes=40),
        [
            ("stdout", c)
            for c in chunk_default("The runners were running past quartzneedle\n")
        ],
    )
    row = store.get_by_handle(handle)
    assert row["chunk_count"] == 1
    assert store.search("running")
    assert store.search("artzneed", substring=True)
    assert (
        store.conn.execute(
            "SELECT value FROM meta WHERE key='schema_version'"
        ).fetchone()[0]
        == "4"
    )
    if os.name == "posix":
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700
        assert path.with_suffix(".db.init.lock").stat().st_mode & 0o777 == 0o600
    store.close()


def test_interoperable_init_flock_and_columns(tmp_path):
    path = tmp_path / "toz.db"
    first = Store.open(path)
    second = Store.open(path)
    assert first.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert second.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert {row[1] for row in second.conn.execute("PRAGMA table_info(query_log)")} >= {
        "outcome",
        "details_json",
    }
    first.close()
    second.close()
