import multiprocessing
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from varde_data.backends.sqlite.queue_backup import (
    _checksum,
    _row_counts,
    _write_manifest,
    backup,
    restore,
)
from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Invalid
from varde_data.queue_mode_lock import barrier, operation


def _write_rows(database: str, count: int) -> None:
    with sqlite3.connect(database, timeout=10) as connection:
        for index in range(count):
            connection.execute(
                "INSERT OR IGNORE INTO queue_items "
                "(id, plan_dir, findings, owned_files, state, queue_name) "
                "VALUES (?, '', '', '', 'queued', 'test')",
                (f"writer-{index}",),
            )
            connection.commit()
            time.sleep(0.002)


def _database(root: Path) -> Path:
    return root / ".cache/data/queue.sqlite3"


def _operation_writer(root: str, started: Any, committed: Any) -> None:
    working = Path(root)
    started.set()
    with operation(working, timeout=5):
        with sqlite3.connect(_database(working)) as connection:
            connection.execute(
                "INSERT INTO queue_items "
                "(id, plan_dir, findings, owned_files, state, queue_name) "
                "VALUES ('after-restore', '', '', '', 'queued', 'test')"
            )
            connection.commit()
            database = _database(working)
        with sqlite3.connect(database) as check:
            assert check.execute(
                "SELECT id FROM queue_items WHERE id='after-restore'"
            ).fetchone() == ("after-restore",)
        committed.set()


def test_backup_during_writer_is_integral_and_restore_keeps_displaced_file(tmp_path):
    database = _database(tmp_path)
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        configure_store(connection)
        connection.execute("PRAGMA journal_mode=WAL")
    process = multiprocessing.Process(target=_write_rows, args=(str(database), 300))
    process.start()
    deadline = time.monotonic() + 10
    count = 0
    while time.monotonic() < deadline:
        with sqlite3.connect(database) as connection:
            count = connection.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0]
        if count:
            break
        time.sleep(0.01)
    assert count > 0
    snapshot = backup(tmp_path)
    process.join(timeout=15)
    assert process.exitcode == 0
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0] > 0

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM queue_items")
        connection.commit()
    displaced = restore(tmp_path, snapshot)
    assert displaced.is_file()
    with sqlite3.connect(displaced) as connection:
        assert connection.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0] == 0
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0] > 0
    restore(tmp_path, displaced)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0] == 0


def test_restore_rejects_backup_missing_required_queue_table(tmp_path):
    database = _database(tmp_path)
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    with connection:
        configure_store(connection)
        connection.execute(
            "INSERT INTO queue_items "
            "(id, plan_dir, findings, owned_files, state, queue_name) "
            "VALUES ('keep', '', '', '', 'queued', 'test')"
        )
    valid_backup = backup(tmp_path)
    broken = tmp_path / "broken.sqlite3"
    with sqlite3.connect(valid_backup) as source, sqlite3.connect(broken) as target:
        source.backup(target)
        target.execute("DROP TABLE queue_items")
        counts = _row_counts(target)
    _write_manifest(broken, _checksum(broken), counts)

    with pytest.raises(Invalid, match="queue_items"):
        restore(tmp_path, broken)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT id FROM queue_items").fetchone() == ("keep",)


def test_restore_barrier_blocks_cross_process_writer_until_replacement_finishes(
    tmp_path,
):
    database = _database(tmp_path)
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    with connection:
        configure_store(connection)
    connection.close()
    snapshot = backup(tmp_path)
    context = multiprocessing.get_context("spawn")
    started = context.Event()
    committed = context.Event()
    worker = context.Process(
        target=_operation_writer, args=(str(tmp_path), started, committed)
    )

    with barrier(tmp_path, timeout=5):
        restore(tmp_path, snapshot)
        worker.start()
        assert started.wait(5)
        time.sleep(0.2)
        assert not committed.is_set()
    worker.join(5)
    assert worker.exitcode == 0
    assert committed.is_set()
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT id FROM queue_items WHERE id='after-restore'"
        ).fetchone() == ("after-restore",)


def test_backup_retains_newest_requested_count(tmp_path):
    database = _database(tmp_path)
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        configure_store(connection)
    backups = [backup(tmp_path, keep=2) for _ in range(3)]
    retained = sorted((tmp_path / ".cache/data/backups").glob("queue-*.sqlite3"))
    assert len(retained) == 2
    assert backups[-1] in retained
