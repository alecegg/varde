from __future__ import annotations

import multiprocessing
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from varde_core.frontmatter import parse
from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.backends.sqlite.queue_schema import _SCHEMA_V1
from varde_data.errors import Conflict, Locked
from varde_data.plan_state_sync import export_plan_dir, import_plan_dir
from varde_data.queue_migrate import migrate
from varde_data.records.queue import QueueItemInput


def _claim_items(database: str, worker: str, output: Any) -> None:
    repo = SQLiteQueue(Path(database))
    claimed: list[str] = []
    while (item := repo.claim("race", worker=worker, lease_s=60)) is not None:
        claimed.append(item.id)
    output.put(claimed)


def _transition_once(database: str, worker: str, output: Any) -> None:
    repo = SQLiteQueue(Path(database))
    try:
        repo.transition("race", "one", "building", actor=worker, expect_state="queued")
    except Conflict:
        output.put(False)
    else:
        output.put(True)


def _write_state(database: str, plan: str, start: Any) -> None:
    store = SQLitePlanState(Path(database))
    start.wait(timeout=5)
    for index in range(60):
        store.set_task_state(plan, "one", f"state-{index}", actor="cli")


def _export_state(database: str, plan: str, start: Any) -> None:
    store = SQLitePlanState(Path(database))
    start.wait(timeout=5)
    for _ in range(60):
        export_plan_dir(store.path.parents[2], plan)


def _claim_then_wait(database: str, claimed: Any) -> None:
    repo = SQLiteQueue(Path(database))
    item = repo.claim(
        "race", worker="doomed", lease_s=1, now="2020-01-01T00:00:00+00:00"
    )
    claimed.put(item.id if item else None)
    # The parent terminates this process to simulate a worker killed mid-lease.
    multiprocessing.Event().wait()


def test_eight_processes_claim_each_item_once_and_no_item_is_lost(
    tmp_path: Path,
) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    for index in range(20):
        repo.enqueue(QueueItemInput(str(index), "plan", queue_name="race"))

    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    workers = [
        context.Process(target=_claim_items, args=(str(repo.path), str(i), output))
        for i in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0

    claimed = [item for _ in workers for item in output.get(timeout=2)]
    assert Counter(claimed) == Counter(str(index) for index in range(20))
    assert len(claimed) == 20


def test_concurrent_transition_has_one_winner(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "plan", queue_name="race"))
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    workers = [
        context.Process(target=_transition_once, args=(str(repo.path), str(i), output))
        for i in range(8)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(20)
        assert worker.exitcode == 0
    assert sum(output.get(timeout=2) for _ in workers) == 1
    assert repo.get("race", "one").state == "building"


def test_export_racing_cli_state_writes_keeps_frontmatter_atomic(
    tmp_path: Path,
) -> None:
    plan = tmp_path / "plans/bundle"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text("---\nstatus: active\n---\n")
    (plan / "tasks/one.md").write_text("---\nstatus: todo\n---\n")
    store = SQLitePlanState(tmp_path / ".cache/data/queue.sqlite3")
    import_plan_dir(store.path.parents[2], plan)

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    writer = context.Process(
        target=_write_state, args=(str(store.path), str(plan), start)
    )
    exporter = context.Process(
        target=_export_state, args=(str(store.path), str(plan), start)
    )
    writer.start()
    exporter.start()
    writer.join(20)
    exporter.join(20)
    assert writer.exitcode == exporter.exitcode == 0

    export_plan_dir(store.path.parents[2], plan)
    task, _ = parse((plan / "tasks/one.md").read_bytes())
    assert task["status"] == store.task_states(plan)[0].status
    assert str(task["status"]).startswith("state-")


def test_killed_claimers_lease_expires_and_item_can_be_reclaimed(
    tmp_path: Path,
) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "plan", queue_name="race"))
    context = multiprocessing.get_context("spawn")
    claimed = context.Queue()
    worker = context.Process(target=_claim_then_wait, args=(str(repo.path), claimed))
    worker.start()
    assert claimed.get(timeout=10) == "one"
    worker.terminate()
    worker.join(10)

    expired = repo.expire("2020-01-01T00:00:02+00:00")
    assert [item.id for item in expired] == ["one"]
    reclaimed = repo.claim("race", worker="replacement", lease_s=60)
    assert reclaimed is not None and reclaimed.id == "one"
    assert reclaimed.claim_generation == 3


def test_locked_database_error_is_not_swallowed(tmp_path: Path) -> None:
    database = tmp_path / "queue.sqlite3"
    repo = SQLiteQueue(database, busy_timeout=0.05)
    repo.enqueue(QueueItemInput("one", "plan", queue_name="race"))
    blocker = sqlite3.connect(database, timeout=1)
    blocker.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(Locked):
            repo.transition("race", "one", "building", actor="test")
    finally:
        blocker.rollback()
        blocker.close()


def test_dry_run_does_not_upgrade_existing_v1_database(tmp_path: Path) -> None:
    root = tmp_path / "working"
    (root / "plans").mkdir(parents=True)
    database = root / ".cache/data/queue.sqlite3"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as db:
        for statement in _SCHEMA_V1:
            db.execute(statement)
        db.execute("INSERT INTO meta(key,value) VALUES('store_mode','markdown')")
        db.execute("PRAGMA user_version=1")
    before = database.read_bytes()

    report = migrate(root, dry_run=True)

    assert report.dry_run
    assert database.read_bytes() == before
    with sqlite3.connect(database) as db:
        assert db.execute("PRAGMA user_version").fetchone() == (1,)
        tables = {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "slots" not in tables
    assert "slot_events" not in tables
