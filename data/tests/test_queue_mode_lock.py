import multiprocessing
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from varde_data.errors import Invalid, Locked
from varde_data.queue_mode_lock import barrier, callback_scope, operation


def _hold_barrier(working: str, entered: Any, release: Any) -> None:
    with barrier(Path(working), timeout=5):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release barrier")


def _hold_operation(working: str, entered: Any, release: Any) -> None:
    with operation(Path(working), timeout=5):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release operation")


def _try_operation(working: str, started: Any, result: Any) -> None:
    started.set()
    try:
        with operation(Path(working), timeout=0.2):
            result.put("acquired")
    except Locked:
        result.put("locked")


def _write_mode(working: Path, mode: str) -> None:
    database = working / ".cache/data/queue.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO meta VALUES ('store_mode', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (mode,),
        )


def test_operations_overlap_and_reenter_in_same_process(tmp_path: Path) -> None:
    ready = threading.Barrier(2)

    def run() -> None:
        with operation(tmp_path) as mode:
            assert mode == "markdown"
            ready.wait(timeout=2)

    thread = threading.Thread(target=run)
    thread.start()
    with operation(tmp_path) as mode:
        assert mode == "markdown"
        ready.wait(timeout=2)
        with operation(tmp_path) as nested:
            assert nested == mode
    thread.join(2)
    assert not thread.is_alive()


def test_barrier_waits_for_operations_and_operation_sees_flipped_mode(
    tmp_path: Path,
) -> None:
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_hold_operation, args=(str(tmp_path), entered, release)
    )
    worker.start()
    assert entered.wait(5)
    barrier_entered = threading.Event()

    def migrate() -> None:
        with barrier(tmp_path, timeout=5):
            _write_mode(tmp_path, "sqlite")
            barrier_entered.set()

    migration = threading.Thread(target=migrate)
    migration.start()
    time.sleep(0.1)
    assert not barrier_entered.is_set()
    release.set()
    worker.join(5)
    migration.join(5)
    assert worker.exitcode == 0
    assert barrier_entered.is_set()
    with operation(tmp_path) as mode:
        assert mode == "sqlite"


def test_operation_waits_for_barrier_then_reads_new_mode(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_hold_barrier, args=(str(tmp_path), entered, release)
    )
    worker.start()
    assert entered.wait(5)
    observed: list[str] = []
    operation_thread = threading.Thread(
        target=lambda: observed.append(_operation_mode(tmp_path))
    )
    operation_thread.start()
    time.sleep(0.1)
    assert observed == []
    _write_mode(tmp_path, "sqlite")
    release.set()
    worker.join(5)
    operation_thread.join(5)
    assert worker.exitcode == 0
    assert observed == ["sqlite"]


def _operation_mode(working: Path) -> str:
    with operation(working, timeout=2) as mode:
        return mode


def test_lock_timeout_raises_locked(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    entered = context.Event()
    release = context.Event()
    worker = context.Process(
        target=_hold_barrier, args=(str(tmp_path), entered, release)
    )
    worker.start()
    assert entered.wait(5)
    with pytest.raises(Locked), barrier(tmp_path, timeout=0.05):
        pass
    release.set()
    worker.join(5)
    assert worker.exitcode == 0


def test_mode_is_reread_after_wait(tmp_path: Path) -> None:
    with operation(tmp_path) as mode:
        assert mode == "markdown"
    _write_mode(tmp_path, "sqlite")
    with operation(tmp_path) as mode:
        assert mode == "sqlite"


def test_operation_reentry_from_callback_is_invalid(tmp_path: Path) -> None:
    with callback_scope(), pytest.raises(Invalid), operation(tmp_path):
        pass


def test_barrier_holder_can_enter_operation_and_nested_barrier(
    tmp_path: Path,
) -> None:
    with barrier(tmp_path), operation(tmp_path) as mode:
        assert mode == "markdown"
        with barrier(tmp_path), operation(tmp_path) as nested_mode:
            assert nested_mode == mode


def test_barrier_still_blocks_operation_in_another_process(tmp_path: Path) -> None:
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    result = context.Queue()
    with barrier(tmp_path):
        worker = context.Process(
            target=_try_operation, args=(str(tmp_path), started, result)
        )
        worker.start()
        assert started.wait(5)
        assert result.get(timeout=5) == "locked"
        worker.join(5)
        assert worker.exitcode == 0


def test_barrier_reentry_from_callback_is_invalid(tmp_path: Path) -> None:
    with callback_scope(), pytest.raises(Invalid), barrier(tmp_path):
        pass
