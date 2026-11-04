from __future__ import annotations

import multiprocessing
import queue
import time
from pathlib import Path

import pytest
from contract_queue import check_queue_contract, check_queue_lease_and_role_contract
from varde_data.backends.memory.queue import MemoryQueue
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Conflict
from varde_data.records.queue import QueueItemInput


def _claim_ready(path: str, worker: str, result) -> None:
    repo = SQLiteQueue(Path(path))
    observed: list[int] = []

    def ready(item, active) -> bool:
        observed.append(len(active))
        return not any(
            set(item.owned_files.split(",")) & set(other.owned_files.split(","))
            for other in active
        )

    result.put((repo.claim("race", worker=worker, lease_s=60, ready=ready), observed))


def test_claim_order_dependencies_generation_release_and_expiry(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("dep", "plan", state="queued", queue_name="q"))
    repo.enqueue(
        QueueItemInput("first", "plan", priority=1, depends_on=("dep",), queue_name="q")
    )
    repo.enqueue(QueueItemInput("later", "plan", priority=2, queue_name="q"))
    claimed = repo.claim(
        "q", worker="slot", lease_s=30, now="2020-01-01T00:00:00+00:00", epoch=7
    )
    assert claimed is not None and claimed.id == "dep"
    assert claimed.claim_epoch == 7 and claimed.claim_generation == 1
    with pytest.raises(Conflict):
        repo.renew("q", "dep", worker="other", generation=1, lease_s=10)
    repo.release("q", "dep", worker="slot", generation=1)
    dep = repo.transition("q", "dep", "merged", actor="slot")
    next_item = repo.claim(
        "q", worker="slot", lease_s=30, now="2020-01-01T00:00:00+00:00"
    )
    assert next_item is not None and next_item.id == "first"
    expired = repo.expire("2020-01-01T00:01:00+00:00")
    assert [item.id for item in expired] == ["first"]
    assert expired[0].claim_generation == next_item.claim_generation + 1
    assert repo.get("q", "dep").state == dep.state == "merged"


def test_shared_queue_contract_runs_against_sqlite(tmp_path: Path) -> None:
    check_queue_contract(SQLiteQueue(tmp_path / "queue.sqlite3"))
    check_queue_lease_and_role_contract(SQLiteQueue(tmp_path / "roles.sqlite3"))


def test_serialize_with_blocks_until_item_leaves_active_state(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("active", "p", queue_name="q"))
    repo.enqueue(
        QueueItemInput("serial", "p", serialize_with=("active",), queue_name="q")
    )
    active = repo.claim("q", worker="w", lease_s=10)
    assert active is not None and active.id == "active"
    assert repo.claim("q", worker="w2", lease_s=10) is None
    repo.release("q", "active", worker="w", generation=active.claim_generation)
    resumed = repo.claim("q", worker="w2", lease_s=10)
    assert resumed is not None and resumed.id == "active"


def test_ready_in_flight_is_transactional_across_processes(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    for index in range(20):
        repo.enqueue(
            QueueItemInput(
                str(index),
                "p",
                owned_files=f"file-{index % 2}.py",
                priority=index,
                queue_name="race",
            )
        )
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    workers = [
        context.Process(target=_claim_ready, args=(str(repo.path), str(index), output))
        for index in range(8)
    ]
    try:
        for worker in workers:
            worker.start()
        deadline = time.monotonic() + 30
        # Drain child results before joining so Queue feeder threads can flush.
        outcomes = [
            output.get(timeout=max(0, deadline - time.monotonic())) for _ in workers
        ]
        for worker in workers:
            worker.join(max(0, deadline - time.monotonic()))
        timed_out = [worker.pid for worker in workers if worker.is_alive()]
        assert not timed_out, f"workers did not finish within 30 seconds: {timed_out}"
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
        for worker in workers:
            if worker.pid is None:
                continue
            worker.join(timeout=1)
            if worker.is_alive():
                worker.kill()
            worker.join()
        while True:
            try:
                output.get_nowait()
            except queue.Empty:
                break
        output.close()
        output.join_thread()
    assert all(worker.exitcode == 0 for worker in workers)
    claimed = [item for item, _seen in outcomes if item is not None]
    assert len(claimed) == 2
    assert len({item.owned_files for item in claimed}) == len(claimed)
    assert any(seen and seen[0] > 0 for _item, seen in outcomes)


def test_ready_can_reject_every_item(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    repo.enqueue(QueueItemInput("one", "p", queue_name="q"))
    assert (
        repo.claim("q", worker="w", lease_s=1, ready=lambda item, active: False) is None
    )


def test_renew_all_can_cover_claims_in_every_queue(tmp_path: Path) -> None:
    repo = SQLiteQueue(tmp_path / "queue.sqlite3")
    for item_id, queue_name in (
        ("plan-item", "roles/plan"),
        ("global-item", "roles/global"),
    ):
        repo.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        claim = repo.claim(
            queue_name,
            worker="slot",
            lease_s=10,
            now="2030-01-01T00:00:00+00:00",
        )
        assert claim is not None

    renewed = repo.renew_all(
        None,
        worker="slot",
        lease_s=60,
        now="2030-01-01T00:00:05+00:00",
    )

    assert {item.queue_name for item in renewed} == {"roles/plan", "roles/global"}
    assert all(item.claim_expires_at == "2030-01-01T00:01:05+00:00" for item in renewed)
    assert all(
        item.claim_expires_at == "2030-01-01T00:01:05+00:00" for item in repo.list()
    )


def test_memory_renew_all_can_cover_claims_in_every_queue() -> None:
    repo = MemoryQueue()
    for item_id, queue_name in (
        ("plan-item", "roles/plan"),
        ("global-item", "roles/global"),
    ):
        repo.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        claim = repo.claim(
            queue_name,
            worker="slot",
            lease_s=10,
            now="2030-01-01T00:00:00+00:00",
        )
        assert claim is not None

    renewed = repo.renew_all(
        None,
        worker="slot",
        lease_s=60,
        now="2030-01-01T00:00:05+00:00",
    )

    assert {item.queue_name for item in renewed} == {"roles/plan", "roles/global"}
    assert all(item.claim_expires_at == "2030-01-01T00:01:05+00:00" for item in renewed)
    assert all(
        item.claim_expires_at == "2030-01-01T00:01:05+00:00" for item in repo.list()
    )
