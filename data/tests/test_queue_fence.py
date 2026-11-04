from __future__ import annotations

import multiprocessing
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Conflict, Invalid
from varde_data.queue_mode_lock import barrier
from varde_data.records.queue import QueueItemInput


def _read_then_claim(path: str, read_old, changed, result) -> None:
    repo = SQLiteQueue(Path(path))
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT value FROM probe").fetchone()[0] == "old"
    read_old.set()
    assert changed.wait(5)

    def fence(db: sqlite3.Connection | None) -> None:
        assert db is not None
        result.put(db.execute("SELECT value FROM probe").fetchone()[0])

    repo.claim("q", worker="w", lease_s=10, fence=fence)


def _write_probe(path: str, ready, done) -> None:
    ready.wait(5)
    with sqlite3.connect(path) as db:
        db.execute("UPDATE probe SET value='new'")
    done.set()


def test_fence_runs_inside_transaction_and_raise_rolls_back(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "p", queue_name="q"))
    with sqlite3.connect(repo.path) as db:
        db.execute("CREATE TABLE probe(value TEXT)")
        db.execute("INSERT INTO probe VALUES ('old')")
    before = repo.events("one")

    def fail(db) -> None:
        assert db.in_transaction
        db.execute("UPDATE probe SET value='changed'")
        raise Conflict("fence rejected")

    with pytest.raises(Conflict):
        repo.claim("q", worker="w", lease_s=10, fence=fail)
    assert repo.get("q", "one").state == "queued"
    assert repo.events("one") == before
    with sqlite3.connect(repo.path) as db:
        assert db.execute("SELECT value FROM probe").fetchone()[0] == "old"


def test_fence_sees_concurrent_probe_commit_before_claim(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "p", queue_name="q"))
    with sqlite3.connect(repo.path) as db:
        db.execute("CREATE TABLE probe(value TEXT)")
        db.execute("INSERT INTO probe VALUES ('old')")
    context = multiprocessing.get_context("spawn")
    read_old, changed = context.Event(), context.Event()
    observed = context.Queue()
    writer = context.Process(
        target=_write_probe, args=(str(repo.path), read_old, changed)
    )
    claimant = context.Process(
        target=_read_then_claim,
        args=(str(repo.path), read_old, changed, observed),
    )
    writer.start()
    claimant.start()
    assert observed.get(timeout=5) == "new"
    writer.join(5)
    claimant.join(5)
    assert writer.exitcode == claimant.exitcode == 0


def test_renew_all_is_atomic_and_expire_filters_workers(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    first = repo.enqueue(QueueItemInput("one", "p", queue_name="q"))
    repo.enqueue(QueueItemInput("two", "p", queue_name="q"))
    repo.enqueue(QueueItemInput("three", "p", queue_name="q"))
    a = repo.claim("q", worker="a", lease_s=5, now="2030-01-01T00:00:00+00:00")
    b = repo.claim("q", worker="a", lease_s=5, now="2030-01-01T00:00:00+00:00")
    c = repo.claim("q", worker="b", lease_s=5, now="2030-01-01T00:00:00+00:00")
    assert a and b and c and first.id == "one"

    def fail(db) -> None:
        db.execute("CREATE TABLE transient(value TEXT)")
        raise Conflict("reject all")

    with pytest.raises(Conflict):
        repo.renew_all(
            "q", worker="a", lease_s=100, now="2030-01-01T00:00:00+00:00", fence=fail
        )
    assert [
        item.claim_expires_at for item in repo.list("q") if item.claimed_by == "a"
    ] == [a.claim_expires_at, b.claim_expires_at]
    with sqlite3.connect(repo.path) as db:
        assert (
            db.execute(
                "SELECT name FROM sqlite_master WHERE name='transient'"
            ).fetchone()
            is None
        )
    assert (
        len(
            repo.renew_all(
                "q", worker="a", lease_s=100, now="2030-01-01T00:00:00+00:00"
            )
        )
        == 2
    )
    expired = repo.expire("2030-01-01T00:02:00+00:00", workers=["a"])
    assert {item.id for item in expired} == {a.id, b.id}
    assert repo.get("q", c.id).claimed_by == "b"


def test_fence_cannot_reenter_queue_operation(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "p", queue_name="q"))

    def reenter(_db: sqlite3.Connection | None) -> None:
        repo.claim("q", worker="nested", lease_s=10)

    with pytest.raises(Invalid):
        repo.claim("q", worker="w", lease_s=10, fence=reenter)


def test_renew_all_starts_lease_after_waiting_for_mode_barrier(
    tmp_path: Path,
) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "p", queue_name="q"))
    claimed = repo.claim("q", worker="first", lease_s=60)
    assert claimed is not None
    started = threading.Event()
    completed = threading.Event()
    renewed = []

    def renew() -> None:
        started.set()
        renewed.extend(repo.renew_all("q", worker="first", lease_s=0.05))
        completed.set()

    with barrier(tmp_path):
        thread = threading.Thread(target=renew)
        thread.start()
        assert started.wait(2)
        assert not completed.wait(0.25)

    thread.join(2)
    assert not thread.is_alive()
    assert len(renewed) == 1
    current = datetime.now(UTC)
    assert datetime.fromisoformat(renewed[0].claim_expires_at) > current
    assert repo.expire(current.isoformat()) == []
    assert repo.claim("q", worker="second", lease_s=60) is None


def test_expired_leases_cannot_be_renewed(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("single", "p", queue_name="q"))
    repo.enqueue(QueueItemInput("batch", "p", queue_name="q"))
    single = repo.claim(
        "q", worker="single-worker", lease_s=1, now="2020-01-01T00:00:00+00:00"
    )
    batch = repo.claim(
        "q", worker="batch-worker", lease_s=1, now="2020-01-01T00:00:00+00:00"
    )
    assert single is not None and batch is not None

    with pytest.raises(Conflict, match="lease has expired"):
        repo.renew(
            "q",
            single.id,
            worker="single-worker",
            generation=single.claim_generation,
            lease_s=30,
        )
    with pytest.raises(Conflict, match="lease has expired"):
        repo.renew_all(
            "q",
            worker="batch-worker",
            lease_s=30,
            now="2020-01-01T00:00:02+00:00",
        )
    assert repo.get("q", single.id).claim_expires_at == single.claim_expires_at
    assert repo.get("q", batch.id).claim_expires_at == batch.claim_expires_at
    assert [event.kind for event in repo.events("single")] == ["enqueue", "claim"]
    assert [event.kind for event in repo.events("batch")] == ["enqueue", "claim"]
