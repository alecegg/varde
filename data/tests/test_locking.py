import multiprocessing
import os
import time
from pathlib import Path
from typing import Any

import pytest
from varde_data.errors import Locked
from varde_data.locking import (
    append_line,
    atomic_write,
    atomic_write_unsynced,
    file_lock,
    read_complete_lines,
    remove_stale_temps,
)


def _append_worker(path: str, lock_path: str, worker: int) -> None:
    for index in range(25):
        append_line(Path(path), f"{worker}:{index}".encode(), lock_path=Path(lock_path))


def _locked_worker(path: str, ready: Any) -> None:
    ready.set()
    try:
        with file_lock(Path(path), timeout=0.15):
            pass
    except Locked:
        return
    raise AssertionError


@pytest.fixture(scope="module", autouse=True)
def _spawn_processes() -> None:
    multiprocessing.set_start_method("spawn", force=True)


def test_atomic_writes_and_stale_temp_cleanup(tmp_path: Path) -> None:
    target = tmp_path / "store.json"
    atomic_write(target, b"durable", mode=0o640)
    assert target.read_bytes() == b"durable"
    assert target.stat().st_mode & 0o777 == 0o640
    atomic_write_unsynced(target, b"derived", mode=0o600)
    assert target.read_bytes() == b"derived"

    stale = tmp_path / ".store.json.1.tmp"
    fresh = tmp_path / ".store.json.2.tmp"
    unrelated = tmp_path / ".other.1.tmp"
    for path in (stale, fresh, unrelated):
        path.touch()
    os.utime(stale, (time.time() - 100, time.time() - 100))
    assert remove_stale_temps(tmp_path, older_than=50) == 1
    assert not stale.exists()
    assert fresh.exists() and unrelated.exists()


def test_concurrent_append_is_one_complete_line_per_write(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    lock_path = tmp_path / ".events.lock"
    context = multiprocessing.get_context("spawn")
    workers = [
        context.Process(target=_append_worker, args=(str(path), str(lock_path), i))
        for i in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0

    lines = read_complete_lines(path)
    assert len(lines) == 200
    assert len(set(lines)) == 200


def test_held_lock_times_out_in_another_process(tmp_path: Path) -> None:
    lock_path = tmp_path / ".store.lock"
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    with file_lock(lock_path, timeout=1):
        worker = context.Process(target=_locked_worker, args=(str(lock_path), ready))
        worker.start()
        assert ready.wait(5)
        worker.join(5)
        assert worker.exitcode == 0


def test_torn_tail_append_preserves_existing_offsets(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    lock_path = tmp_path / ".events.lock"
    prefix = b"first\nsecond"
    path.write_bytes(prefix)
    append_line(path, b"third", lock_path=lock_path)
    assert path.read_bytes() == prefix + b"\nthird\n"
    assert path.read_bytes().startswith(prefix)
    assert read_complete_lines(path) == [b"first", b"second", b"third"]


def test_read_ignores_torn_final_line(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_bytes(b"complete\ntorn")
    assert read_complete_lines(path) == [b"complete"]
