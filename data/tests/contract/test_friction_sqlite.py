"""Sqlite-specific friction behaviour beyond the shared contract."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from sqlite_friction import factory
from varde_data.backends.sqlite.learn_schema import learn_db_path
from varde_data.learn_store_mode import (
    StaleGeneration,
    exclusive_store_lock,
    flip_domain_locked,
)
from varde_data.repos.friction import FrictionAddRequest, FrictionImportEntry
from varde_data.testing import MemoryFriction


def _add(store, title: str = "Alpha"):
    return store.add(FrictionAddRequest(title, "session", "again", "/work", "/repo"))


def test_rows_hold_friction_jsonl_lines(tmp_path: Path) -> None:
    _add(factory(tmp_path))

    with closing(sqlite3.connect(learn_db_path(tmp_path))) as db:
        rows = [row[0] for row in db.execute("SELECT event FROM friction_events")]

    assert len(rows) == 2
    assert rows[0].startswith("{") and '"kind":"item_added"' in rows[0]
    assert not (tmp_path / "friction.jsonl").exists()
    assert not (tmp_path / "learn.db").exists()


def test_same_operations_give_the_same_numeric_ids_as_memory(tmp_path: Path) -> None:
    sqlite_store = factory(tmp_path / "sqlite")
    memory_store = MemoryFriction(tmp_path / "memory")
    for store in (sqlite_store, memory_store):
        _add(store, "One")
        _add(store, "Two")
        store.add(FrictionAddRequest("", "", "again", "/work", item_id=2))

    def shape(store) -> list[tuple[str, int]]:
        return [
            (item.slug, store.show(str(index)).occurrences.total)
            for index, item in enumerate(store.list_items().items, 1)
        ]

    assert shape(sqlite_store) == shape(memory_store) == [("one", 1), ("two", 2)]


def test_import_keeps_legacy_ids_and_slugs(tmp_path: Path) -> None:
    store = factory(tmp_path)
    entry = FrictionImportEntry("legacy-slug", "Legacy", "session", id=91)

    store.import_entries([entry])
    reopened = factory(tmp_path)

    assert reopened.show("91").item.slug == "legacy-slug"
    assert reopened.list_items().items[0].slug == "legacy-slug"


def test_append_is_refused_when_the_marker_says_files(tmp_path: Path) -> None:
    store = factory(tmp_path)
    (tmp_path / "store-mode.json").unlink()

    with pytest.raises(StaleGeneration):
        _add(store)
    assert store.list_items().total == 0


def test_write_after_another_domain_flips_still_succeeds(tmp_path: Path) -> None:
    store = factory(tmp_path)
    _add(store, "Before")
    with exclusive_store_lock(tmp_path):
        flip_domain_locked(tmp_path, "ledger", "sqlite")

    _add(store, "After")

    assert [item.slug for item in store.list_items().items] == ["before", "after"]


def test_failed_transaction_leaves_no_partial_row(tmp_path: Path) -> None:
    from varde_data.backends.sqlite.learn_friction import (
        insert_event_rows,
        write_transaction,
    )
    from varde_data.backends.sqlite.learn_schema import connect

    with closing(connect(tmp_path)) as db:
        with pytest.raises(RuntimeError), write_transaction(db):
            insert_event_rows(db, ['{"a":1}', '{"b":2}'])
            raise RuntimeError("killed mid-transaction")
        assert db.execute("SELECT COUNT(*) FROM friction_events").fetchone() == (0,)


def test_invalid_event_in_a_batch_appends_nothing(tmp_path: Path) -> None:
    from varde_data.records.friction import Event, ItemAdded

    store = factory(tmp_path)
    good = Event.at("2026-01-01T00:00:00.000Z", None, ItemAdded("Good", "s"))
    bad = Event.at("not-a-time", None, ItemAdded("Bad", "s"))

    with pytest.raises(ValueError):
        store.append_events([good, bad])

    assert store.list_items().total == 0
