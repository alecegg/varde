from __future__ import annotations

import multiprocessing
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from varde_data.backends.sqlite.workitems import SqliteWorkItems
from varde_data.errors import Invalid
from varde_data.workitems import open_workitems, workitem_store_files


def test_sqlite_repository_persists_rows_and_versions(tmp_path: Path) -> None:
    store = SqliteWorkItems(tmp_path)
    item = store.create("key", "request", "project")
    initial = store.version()
    assert store.claim_planner_start(item.id)
    assert store.version() != initial

    reopened = SqliteWorkItems(tmp_path)
    assert reopened.get(item.id) == store.get(item.id)
    assert reopened.audit(item.id)[0].detail == "submitted"
    assert reopened.audit(item.id)[1].detail == "planner start claimed"


def test_factory_and_store_paths(tmp_path: Path) -> None:
    store = open_workitems(tmp_path)
    item = store.create("key", "request", "project")
    assert Path(item.notes_path).is_file()
    assert workitem_store_files(tmp_path) == (
        tmp_path / "workitems.sqlite3",
        tmp_path / "workitems.sqlite3-wal",
        tmp_path / "workitems.sqlite3-shm",
        tmp_path / "workitem-notes",
    )
    with sqlite3.connect(tmp_path / "workitems.sqlite3") as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1


def test_memory_factory_uses_shared_notes_directory(tmp_path: Path) -> None:
    store = open_workitems(tmp_path, "memory")
    item = store.create("key", "request", "project")

    assert Path(item.notes_path).parent.parent == tmp_path / "workitem-notes"


def test_two_instances_share_exclusive_planner_claim(tmp_path: Path) -> None:
    first = SqliteWorkItems(tmp_path)
    item = first.create("key", "request", "project")
    second = SqliteWorkItems(tmp_path)
    barrier = Barrier(2)

    def claim(store: SqliteWorkItems) -> bool:
        barrier.wait()
        return store.claim_planner_start(item.id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, (first, second)))

    assert sum(results) == 1


def test_noop_operations_do_not_advance_version(tmp_path: Path) -> None:
    store = SqliteWorkItems(tmp_path)
    item = store.create("key", "request", "project")
    store.claim_planner_start(item.id)
    store.attach_planner(item.id, "session")
    before = store.version()

    store.attach_planner(item.id, "session")

    assert store.version() == before
    assert store.create("key", "ignored", "ignored") == store.get(item.id)
    assert not store.claim_planner_start(item.id)
    store.get(item.id)
    store.list()
    assert store.version() == before


def test_note_helpers_handle_nul_names(tmp_path: Path) -> None:
    store = SqliteWorkItems(tmp_path)
    item = store.create("key", "request", "project")

    with pytest.raises(Invalid, match="NUL"):
        store.write_note(item.id, "bad\x00name", "note")
    assert not store.owns_note(item.id, str(tmp_path / "bad\x00name"))


def test_create_removes_note_when_database_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SqliteWorkItems(tmp_path)

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise sqlite3.OperationalError("forced audit failure")

    monkeypatch.setattr(store, "_audit", fail_audit)
    with pytest.raises(sqlite3.OperationalError, match="forced audit failure"):
        store.create("key", "request", "project")

    assert list(store.notes_dir.iterdir()) == []


def _claim_in_process(
    root: str, item_id: str, barrier: object, results: object
) -> None:
    barrier.wait()  # type: ignore[attr-defined]
    claimed = SqliteWorkItems(Path(root)).claim_planner_start(item_id)
    results.put(claimed)  # type: ignore[attr-defined]


def test_multiprocess_claim_is_exclusive(tmp_path: Path) -> None:
    store = SqliteWorkItems(tmp_path)
    item = store.create("key", "request", "project")
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_claim_in_process,
            args=(str(tmp_path), item.id, barrier, results),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join()

    assert all(process.exitcode == 0 for process in processes)
    assert sum(results.get() for _ in processes) == 1
