from __future__ import annotations

import multiprocessing
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest
from varde_data.errors import Conflict
from varde_data.queue import open_queue, open_slots
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItem, QueueItemInput


def _repositories(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return open_queue(root), open_slots(root)


def _register(slots, slot_id: str) -> None:
    slots.register(
        slot_id,
        plan_id="plan",
        role="builder",
        agent_ref=f"agent-{slot_id}",
        lease_s=30,
    )


def _claim_once(root: str, slot_id: str, start, output) -> None:
    _, slots = _repositories(Path(root))
    start.wait(timeout=10)
    item = slots.claim(
        slot_id,
        epoch=1,
        queue_name="roles/plan",
        lease_s=60,
        ready=lambda candidate, in_flight: not in_flight,
    )
    output.put(item.id if item else None)


def test_slot_claim_is_epoch_fenced(tmp_path: Path) -> None:
    queue, slots = _repositories(tmp_path)
    _register(slots, "slot")
    queue.enqueue(QueueItemInput("one", "plan", queue_name="roles/plan"))
    slots.replace("slot", new_agent_ref="agent-next")

    with pytest.raises(Conflict):
        slots.claim("slot", epoch=1, queue_name="roles/plan", lease_s=60)


def test_heartbeat_renews_all_claims_and_rejects_stale_epoch(
    tmp_path: Path,
) -> None:
    queue, slots = _repositories(tmp_path)
    _register(slots, "slot")
    for item_id, queue_name in (
        ("one", "roles/plan"),
        ("two", "roles/global"),
    ):
        queue.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        assert slots.claim(
            "slot",
            epoch=1,
            queue_name=queue_name,
            lease_s=10,
            now="2030-01-01T00:00:00+00:00",
        )

    slots.heartbeat("slot", epoch=1, lease_s=60, now="2030-01-01T00:00:05+00:00")

    claims = slots.claimed("slot")
    assert {item.id for item in claims} == {"one", "two"}
    assert {item.claim_expires_at for item in claims} == {"2030-01-01T00:01:05+00:00"}
    with pytest.raises(Conflict):
        slots.heartbeat("slot", epoch=2, lease_s=60)


def test_ready_receives_items_claimed_by_another_slot(tmp_path: Path) -> None:
    queue, slots = _repositories(tmp_path)
    _register(slots, "active")
    _register(slots, "candidate")
    queue.enqueue(QueueItemInput("active-item", "plan", queue_name="roles/plan"))
    queue.enqueue(QueueItemInput("next-item", "plan", queue_name="roles/plan"))
    assert slots.claim("active", epoch=1, queue_name="roles/plan", lease_s=60)
    observed: list[tuple[str, ...]] = []

    def ready(item: QueueItem, in_flight: Sequence[QueueItem]) -> bool:
        observed.append(tuple(active.id for active in in_flight))
        return False

    claimed = slots.claim(
        "candidate",
        epoch=1,
        queue_name="roles/plan",
        lease_s=60,
        ready=ready,
    )

    assert claimed is None
    assert observed == [("active-item",)]


def test_eight_processes_claim_at_most_one_under_in_flight_ready_rule(
    tmp_path: Path,
) -> None:
    queue, slots = _repositories(tmp_path)
    for index in range(8):
        _register(slots, f"slot-{index}")
        queue.enqueue(QueueItemInput(f"item-{index}", "plan", queue_name="roles/plan"))

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(
            target=_claim_once,
            args=(str(tmp_path), f"slot-{index}", start, output),
        )
        for index in range(8)
    ]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(20)
        assert process.exitcode == 0

    claimed = [output.get(timeout=2) for _ in processes]
    assert sum(item is not None for item in claimed) == 1
    assert len({item for item in claimed if item is not None}) == 1
