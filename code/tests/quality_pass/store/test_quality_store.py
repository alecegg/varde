from __future__ import annotations

import multiprocessing
import queue
import shutil
import sqlite3
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from varde_code.index.paths import repo_db_path
from varde_code.quality_pass.store import open_store, quality_store_path
from varde_code.quality_pass.store.store import FILE_NAME


def _cold_start_worker(directory: str, path: str, barrier, results) -> None:
    try:
        barrier.wait(timeout=20)
        store = open_store(directory)
        try:
            store.put_facts(path, "l1", {"path": path})
        finally:
            store.close()
        results.put(("ok", str(store.path)))
    except BaseException:
        results.put(("error", traceback.format_exc()))
        raise


def _pause_during_batch(directory: str, marker: str) -> None:
    store = open_store(directory)

    def pause() -> int:
        Path(marker).write_text("entered")
        while True:
            time.sleep(1)

    assert store._connection is not None
    store._connection.create_function("pause_write", 0, pause)
    assert store._connection is not None
    store._connection.execute(
        "CREATE TRIGGER pause_score BEFORE INSERT ON scores "
        "BEGIN SELECT pause_write(); END"
    )
    store.put_batch(
        "a.py",
        {"facts": ("new-l1", {"tokens": 99}), "scores": ("new-l4", {"score": 9})},
    )


def test_store_uses_versioned_database_beside_fast_index(tmp_path: Path) -> None:
    fast_dir = tmp_path / "repo-cache"
    fast_dir.mkdir()
    fast_index = fast_dir / "index.db"
    fast_index.touch()

    store = open_store(fast_dir)
    assert store.path is not None
    try:
        assert store.path == fast_dir / FILE_NAME
        assert store.path.is_file()
        assert store.path != fast_index
        assert store.get_facts("src/a.py", "l1") is None
    finally:
        store.close()


def test_repo_helper_places_store_beside_fast_index(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config"
    repo = tmp_path / "checkout"
    repo.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))

    fast_index = repo_db_path(repo)
    quality_db = quality_store_path(repo)

    assert quality_db.parent == fast_index.parent
    assert quality_db.name == FILE_NAME
    assert quality_db != fast_index


def test_concurrent_writers_both_commit(tmp_path: Path) -> None:
    directory = tmp_path / "cache"
    directory.mkdir()
    first = open_store(directory)
    second = open_store(directory)
    assert first.path is not None and second.path is not None

    def write(store, path: str) -> None:
        store.put_facts(path, "l1", {"path": path})

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(write, first, "a.py"),
                pool.submit(write, second, "b.py"),
            ]
            for future in futures:
                future.result()
        assert first.path == second.path
        assert first.path is not None
        assert first.get_facts("a.py", "l1") == {"path": "a.py"}
        assert second.get_facts("b.py", "l1") == {"path": "b.py"}
    finally:
        first.close()
        second.close()


@pytest.mark.slow
def test_cold_start_stress_has_one_database_and_all_rows(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    for round_number in range(40):
        directory = tmp_path / f"round-{round_number}"
        directory.mkdir()
        barrier = context.Barrier(6)
        results = context.Queue()
        processes = [
            context.Process(
                target=_cold_start_worker,
                args=(str(directory), f"file-{number}.py", barrier, results),
            )
            for number in range(6)
        ]
        try:
            for process in processes:
                process.start()
            reports = []
            for _ in processes:
                try:
                    reports.append(results.get(timeout=30))
                except queue.Empty:
                    break
            for process in processes:
                process.join(30)
            timed_out = [process.pid for process in processes if process.is_alive()]
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
            for process in processes:
                if process.pid is None:
                    continue
                process.join(timeout=1)
                if process.is_alive():
                    process.kill()
                process.join()
            while True:
                try:
                    results.get_nowait()
                except queue.Empty:
                    break
            results.close()
            results.join_thread()
        worker_failures = [
            (process.pid, process.exitcode)
            for process in processes
            if process.exitcode != 0
        ]
        errors = [report for report in reports if report[0] == "error"]
        filenames = [report[1] for report in reports if report[0] == "ok"]
        assert not timed_out, (
            f"workers exceeded 30s join: {timed_out}; reports={reports}"
        )
        assert not worker_failures, (
            f"worker exit codes: {worker_failures}; worker exceptions={errors}"
        )
        assert len(filenames) == len(processes), f"worker results missing: {reports}"
        assert len(set(filenames)) == 1
        database_files = list(directory.glob("quality-v*.sqlite"))
        assert len(database_files) == 1
        store = open_store(directory)
        try:
            for number in range(6):
                path = f"file-{number}.py"
                assert store.get_facts(path, "l1") == {"path": path}
        finally:
            store.close()


def test_empty_versioned_file_is_initialized_in_place(tmp_path: Path) -> None:
    empty_database = tmp_path / FILE_NAME
    empty_database.touch()

    store = open_store(tmp_path)
    try:
        assert store.path == empty_database
        assert store.meta["schema_version"] == "1"
        assert list(tmp_path.glob("quality-v*.sqlite")) == [empty_database]
    finally:
        store.close()


def test_unknown_schema_is_ignored_and_new_store_is_empty(tmp_path: Path) -> None:
    path = tmp_path / FILE_NAME
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE meta (key TEXT, value TEXT)")
        connection.execute("INSERT INTO meta VALUES ('schema_version', '999')")

    store = open_store(tmp_path)
    try:
        assert store.meta["schema_version"] == "1"
        assert store.get_facts("a.py", "k") is None
        assert (tmp_path / "quality-v2.sqlite").is_file()
        with sqlite3.connect(path) as old_connection:
            assert old_connection.execute("SELECT value FROM meta").fetchone() == (
                "999",
            )
    finally:
        store.close()


def test_deleting_store_starts_with_cold_cache(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_scores("a.py", "l4", {"score": 5})
    path = store.path
    assert path is not None
    store.close()
    path.unlink()
    Path(f"{path}-wal").unlink(missing_ok=True)
    Path(f"{path}-shm").unlink(missing_ok=True)

    cold = open_store(tmp_path)
    try:
        assert cold.get_scores("a.py", "l4") is None
    finally:
        cold.close()


def test_failed_batch_write_preserves_previous_values(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_facts("a.py", "old-l1", {"tokens": 4})
    store.put_scores("a.py", "old-l4", {"score": 1})
    assert store._connection is not None
    with store._connection:
        assert store._connection is not None
    store._connection.execute(
        "CREATE TRIGGER abort_score BEFORE INSERT ON scores "
        "BEGIN SELECT RAISE(ABORT, 'simulated interruption'); END"
    )

    with pytest.raises(sqlite3.IntegrityError, match="simulated interruption"):
        store.put_batch(
            "a.py",
            {
                "facts": ("new-l1", {"tokens": 99}),
                "scores": ("new-l4", {"score": 9}),
            },
        )
    assert store.get_facts("a.py", "old-l1") == {"tokens": 4}
    assert store.get_facts("a.py", "new-l1") is None
    assert store.get_scores("a.py", "old-l4") == {"score": 1}
    store.close()


def test_process_interruption_keeps_previous_batch_readable(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_facts("a.py", "old-l1", {"tokens": 4})
    store.put_scores("a.py", "old-l4", {"score": 1})
    store.close()

    context = multiprocessing.get_context("spawn")
    marker = tmp_path / "writer-entered-score"
    process = context.Process(
        target=_pause_during_batch,
        args=(str(tmp_path), str(marker)),
    )
    process.start()
    deadline = time.monotonic() + 15
    while not marker.exists() and process.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    entered = marker.exists()
    process.terminate()
    process.join(15)
    if process.is_alive():
        process.kill()
        process.join()
    assert not process.is_alive(), "writer process remained alive after terminate/kill"
    assert entered

    recovered = open_store(tmp_path)
    try:
        assert recovered.get_facts("a.py", "old-l1") == {"tokens": 4}
        assert recovered.get_facts("a.py", "new-l1") is None
        assert recovered.get_scores("a.py", "old-l4") == {"score": 1}
    finally:
        recovered.close()


def test_corrupted_row_is_a_cache_miss(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_edges("a.py", "l2", [{"callee": "f"}])
    assert store._connection is not None
    with store._connection:
        assert store._connection is not None
    store._connection.execute("UPDATE edges SET value = '{}' WHERE path = 'a.py'")
    assert store.get_edges("a.py", "l2") is None
    store.close()


def test_garbage_collection_removes_unseen_file_rows(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_facts("src/seen.py", "l1", {"ok": True})
    store.put_edges("src/gone.py", "l2", [])
    store.put_path_class("src/gone.py", {"excluded": "generated"})

    assert store.collect_garbage(["src/seen.py"]) == 1
    assert store.get_facts("src/seen.py", "l1") == {"ok": True}
    assert store.get_edges("src/gone.py", "l2") is None
    assert store.get_path_class("src/gone.py") is None
    store.close()


def test_relative_paths_hit_after_cache_is_restored_elsewhere(tmp_path: Path) -> None:
    original = tmp_path / "checkout-one" / "cache"
    restored = tmp_path / "checkout-two" / "cache"
    original.mkdir(parents=True)
    restored.mkdir(parents=True)
    store = open_store(original)
    store.put_measures("src/module.py", "l3", {"depth": 2})
    store.close()
    shutil.copy2(original / FILE_NAME, restored / FILE_NAME)

    moved = open_store(restored)
    try:
        assert moved.get_measures("src/module.py", "l3") == {"depth": 2}
    finally:
        moved.close()


def test_read_only_directory_falls_back_with_diagnostic(tmp_path: Path, capsys) -> None:
    directory = tmp_path / "readonly"
    directory.mkdir()
    directory.chmod(0o555)
    try:
        store = open_store(directory)
        store.put_facts("a.py", "l1", {"cached": True})
        assert store.path is None
        assert store.get_facts("a.py", "l1") == {"cached": True}
        assert "results are not cached" in capsys.readouterr().err
        store.close()
    finally:
        directory.chmod(0o755)


def test_missing_directory_uses_memory_with_diagnostic(tmp_path: Path, capsys) -> None:
    missing = tmp_path / "not-created"
    store = open_store(missing)
    try:
        store.put_scores("a.py", "l4", {"score": 7})
        assert store.path is None
        assert store.get_scores("a.py", "l4") == {"score": 7}
        assert not missing.exists()
        assert "results are not cached" in capsys.readouterr().err
    finally:
        store.close()


def test_database_read_error_is_a_cache_miss(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_facts("a.py", "l1", {"tokens": 4})
    assert store._connection is not None
    with store._connection:
        assert store._connection is not None
    store._connection.execute("DROP TABLE facts")
    assert store.get_facts("a.py", "l1") is None
    store.close()


def test_batch_replaces_old_keys_and_persists_unicode_path_class(
    tmp_path: Path,
) -> None:
    store = open_store(tmp_path)
    store.put_batch(
        "src/café.py",
        {
            "facts": ("old-l1", {"text": "naïve"}),
            "path_classes": ("path-class", {"excluded": "generated"}),
            "scores": ("l4", {"score": 8}),
        },
    )
    store.put_facts("src/café.py", "new-l1", {"text": "東京"})
    path = store.path
    store.close()

    reopened = open_store(tmp_path)
    try:
        assert reopened.get_facts("src/café.py", "old-l1") is None
        assert reopened.get_facts("src/café.py", "new-l1") == {"text": "東京"}
        assert reopened.get_path_class("src/café.py") == {"excluded": "generated"}
        assert reopened.get_scores("src/café.py", "l4") == {"score": 8}
        assert path == reopened.path
    finally:
        reopened.close()


def test_gc_size_cap_clears_cache_and_compacts_database(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    for number in range(20):
        store.put_facts(f"{number}.py", "l1", {"payload": "x" * 4000})
    before = store._database_size()

    removed = store.collect_garbage(
        [f"{number}.py" for number in range(20)], size_cap=1
    )

    assert removed == 20
    assert store.get_facts("0.py", "l1") is None
    assert store._database_size() < before
    store.close()


def test_invalidate_chunks_large_path_lists(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    paths = [f"{number}.py" for number in range(1100)]
    for path in paths:
        store.put_edges(path, "l2", [])

    store.invalidate(paths)

    assert all(store.get_edges(path, "l2") is None for path in paths)
    store.close()


def test_invalidate_removes_every_layer_for_selected_paths(tmp_path: Path) -> None:
    store = open_store(tmp_path)
    store.put_facts("src/keep.py", "l1", {"value": 1})
    store.put_edges("src/drop.py", "l2", [])
    store.put_measures("src/drop.py", "l3", {"depth": 1})
    store.put_scores("src/drop.py", "l4", {"score": 3})
    store.put_path_class("src/drop.py", {"excluded": None})

    store.invalidate(["src/drop.py"])

    assert store.get_facts("src/keep.py", "l1") == {"value": 1}
    assert store.get_edges("src/drop.py", "l2") is None
    assert store.get_measures("src/drop.py", "l3") is None
    assert store.get_scores("src/drop.py", "l4") is None
    assert store.get_path_class("src/drop.py") is None
    assert store.meta["schema_version"] == "1"
    store.close()
