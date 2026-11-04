from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput


def _data(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return open_data(root, DataConfig())


def _crash_after_claim(
    root: str, claimed: Any, continue_claiming: Any, claim_count: int
) -> None:
    data = _data(Path(root))
    for _ in range(claim_count):
        item = data.slots.claim(
            "slot",
            epoch=1,
            queue_name="work",
            lease_s=60,
            now="2020-01-01T00:00:00+00:00",
        )
        if item is None:
            break
        claimed.put(item.id)
        continue_claiming.get()
    # The parent kills this process before its first slot heartbeat.


@pytest.mark.parametrize("claim_count", [1, 2])
def test_crash_between_claim_and_heartbeat_reclaims_batch_for_new_slot(
    tmp_path: Path, claim_count: int
) -> None:
    data = _data(tmp_path)
    data.slots.register(
        "slot", plan_id="plan", role="worker", agent_ref="old-agent", lease_s=1
    )
    data.slots.heartbeat("slot", epoch=1, now="2020-01-01T00:00:00+00:00")
    for item_id in ("one", "two", "three"):
        data.queue.enqueue(QueueItemInput(item_id, "plan", queue_name="work"))

    context = multiprocessing.get_context("spawn")
    claimed = context.Queue()
    continue_claiming = context.Queue()
    worker = context.Process(
        target=_crash_after_claim,
        args=(str(tmp_path), claimed, continue_claiming, claim_count),
    )
    worker.start()
    claimed_ids = {claimed.get(timeout=10)}
    for _ in range(claim_count - 1):
        continue_claiming.put(True)
        claimed_ids.add(claimed.get(timeout=10))
    worker.terminate()
    worker.join(10)
    assert worker.exitcode is not None and worker.exitcode < 0
    assert len(claimed_ids) == claim_count

    reclaimed = data.slots.reclaim_stale("2020-01-01T00:02:00+00:00")
    assert reclaimed.reclaimed == ("slot",)
    assert {item.id for item in reclaimed.expired_items} == claimed_ids
    assert all(
        data.queue.get("work", item_id).state == "queued" for item_id in claimed_ids
    )

    replacement = data.slots.register(
        "new-slot", plan_id="plan", role="worker", agent_ref="new-agent"
    )
    new_claims = [
        data.slots.claim(
            "new-slot", epoch=replacement.epoch, queue_name="work", lease_s=60
        )
        for _ in range(claim_count)
    ]
    assert {item.id for item in new_claims if item is not None} == claimed_ids
    assert {item.id for item in data.slots.claimed("new-slot")} == claimed_ids
    assert {item.id for item in data.queue.list(queue_name="work")} == {
        "one",
        "two",
        "three",
    }
