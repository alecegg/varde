from __future__ import annotations

import multiprocessing
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_data.queue import open_queue, open_slots
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_runner.lease_keeper import expire_tick
from varde_workflow.role_pull import pull
from varde_workflow.role_queue_budget import BudgetLimits, ResourceSnapshot

NOW = datetime(2030, 1, 1, tzinfo=UTC)
QUEUE_NAME = "roles/plan"
LIMITS = BudgetLimits({}, 256, 50, 16, 24)


def _repositories(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return open_queue(root), open_slots(root)


def _snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        taken_at=NOW,
        providers={},
        rss_mb=240,
        cpu_pct=45,
        processes=15,
        live_workers=0,
    )


def _pull_worker(root: str, index: int, start, output) -> None:
    queue, slots = _repositories(Path(root))
    slot_id = f"slot-{index}"
    start.wait(timeout=15)
    result = pull(
        queue,
        slots,
        queue_name=QUEUE_NAME,
        role="builder",
        slot_id=slot_id,
        epoch=1,
        lease_s=10,
        snapshot=_snapshot(),
        limits=LIMITS,
        now=NOW,
    )
    output.put((slot_id, result.item.id if result.item else None, result.reason))


def test_eight_slots_pull_independent_items_and_expire_stopped_slot(
    tmp_path: Path,
) -> None:
    queue, slots = _repositories(tmp_path)
    for index in range(8):
        slots.register(
            f"slot-{index}",
            plan_id="plan",
            role="builder",
            agent_ref=f"agent-{index}",
            lease_s=10,
        )
    for index in range(20):
        group = index // 2
        queue.enqueue(
            QueueItemInput(
                f"item-{index:02}",
                "plan",
                role="builder",
                queue_name=QUEUE_NAME,
                owned_files=f"src/group-{group}.py",
            )
        )

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    output = context.Queue()
    processes = [
        context.Process(
            target=_pull_worker,
            args=(str(tmp_path), index, start, output),
        )
        for index in range(8)
    ]
    try:
        for process in processes:
            process.start()
        start.set()
        for process in processes:
            process.join(30)
            assert process.exitcode == 0
        results = [output.get(timeout=3) for _ in processes]
    finally:
        for process in processes:
            if process.pid is not None and process.is_alive():
                process.terminate()
        for process in processes:
            if process.pid is not None:
                process.join(timeout=5)
                if process.is_alive():
                    process.kill()
                    process.join()

    claims = [(slot_id, item_id) for slot_id, item_id, _ in results if item_id]
    assert len(claims) == 8
    assert len({slot_id for slot_id, _ in claims}) == 8
    claimed_items = [queue.get(QUEUE_NAME, item_id) for _, item_id in claims]
    assert len({item.owned_files for item in claimed_items}) == len(claimed_items)
    assert all(item.state == "claimed" for item in claimed_items)
    assert len(queue.list(QUEUE_NAME, state="queued")) == 12

    blocked = pull(
        queue,
        slots,
        queue_name=QUEUE_NAME,
        role="builder",
        slot_id="slot-0",
        epoch=1,
        lease_s=10,
        snapshot=ResourceSnapshot(
            taken_at=NOW,
            providers={},
            rss_mb=257,
            cpu_pct=45,
            processes=15,
            live_workers=0,
        ),
        limits=LIMITS,
        now=NOW,
    )
    assert blocked.item is None
    assert blocked.reason == "rss_mb_max"

    _, abandoned_id = claims[0]
    renewed_slot, renewed_id = claims[1]
    abandoned_before = queue.get(QUEUE_NAME, abandoned_id)
    slots.heartbeat(
        renewed_slot,
        epoch=1,
        lease_s=10,
        now=(NOW + timedelta(seconds=5)).isoformat(),
    )

    assert expire_tick(queue, NOW + timedelta(seconds=11)) == 7
    abandoned_after = queue.get(QUEUE_NAME, abandoned_id)
    renewed_after = queue.get(QUEUE_NAME, renewed_id)
    assert abandoned_after.state == "queued"
    assert abandoned_after.claim_generation == abandoned_before.claim_generation + 1
    assert renewed_after.state == "claimed"
