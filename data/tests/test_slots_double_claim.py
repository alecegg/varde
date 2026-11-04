from __future__ import annotations

import multiprocessing
import sqlite3
from collections import Counter
from functools import partial
from pathlib import Path
from typing import Any

from varde_data.config import DataConfig
from varde_data.errors import Conflict
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput

NOW = "2020-01-01T00:00:00+00:00"
RECLAIM_NOW = "2020-01-01T00:00:02+00:00"
RECLAIM_TARGET = "reclaim-target"


def _data(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return open_data(root, DataConfig())


def _ready_for_racing_claim(
    candidate: Any,
    _in_flight: Any,
    *,
    worker_id: int,
    first_claim: bool,
    reclaim_done: Any,
) -> bool:
    if first_claim:
        return candidate.id == str(worker_id)
    return candidate.id != RECLAIM_TARGET or reclaim_done.is_set()


def _replace_and_report(
    root: str, start: Any, replaced: Any, continue_replacing: Any, count: int
) -> None:
    data = _data(Path(root))
    start.wait(timeout=10)
    for index in range(count):
        slot = data.slots.replace(
            "slot", new_agent_ref=f"new-agent-{index}", actor="replacement"
        )
        replaced.put(slot.epoch)
        continue_replacing.get(timeout=10)


def _zombie_calls(
    root: str, replaced: Any, results: Any, continue_zombie: Any, count: int
) -> None:
    data = _data(Path(root))
    for _ in range(count):
        replaced_epoch = replaced.get(timeout=10)
        conflicts = 0
        for operation in (
            lambda: data.slots.claim("slot", epoch=1, queue_name="work", lease_s=60),
            lambda: data.slots.heartbeat("slot", epoch=1),
            lambda: data.slots.release(
                "slot", epoch=1, queue_name="work", item_id="held"
            ),
        ):
            try:
                operation()
            except Conflict:
                conflicts += 1
        results.put((replaced_epoch, conflicts))
        continue_zombie.get(timeout=10)


def _claim_items(
    root: str,
    start: Any,
    race_start: Any,
    reclaim_done: Any,
    output: Any,
    worker_id: int,
) -> None:
    data = _data(Path(root))
    start.wait(timeout=10)
    claimed: list[str] = []
    first_claim = True
    while True:
        epoch = data.slots.show("slot").epoch
        try:
            item = data.slots.claim(
                "slot",
                epoch=epoch,
                queue_name="work",
                lease_s=3600,
                now=NOW,
                ready=partial(
                    _ready_for_racing_claim,
                    worker_id=worker_id,
                    first_claim=first_claim,
                    reclaim_done=reclaim_done,
                ),
            )
        except Conflict:
            continue
        if item is None:
            assert not first_claim, f"worker {worker_id} could not claim its marker"
            if reclaim_done.is_set():
                break
            assert reclaim_done.wait(timeout=15)
            continue
        claimed.append(item.id)
        if first_claim:
            first_claim = False
            race_start.wait(timeout=10)
    output.put(claimed)


def _claim_expiring_item(
    root: str, start: Any, claimed_event: Any, reclaim_done: Any
) -> None:
    data = _data(Path(root))
    start.wait(timeout=10)
    item = data.slots.claim(
        "expired-slot",
        epoch=1,
        queue_name="work",
        lease_s=1,
        now=NOW,
        ready=lambda candidate, _: candidate.id == RECLAIM_TARGET,
    )
    assert item is not None and item.id == RECLAIM_TARGET
    claimed_event.set()
    assert reclaim_done.wait(timeout=15)


def _replace_many(
    root: str, start: Any, claimed_event: Any, race_start: Any, count: int
) -> None:
    data = _data(Path(root))
    start.wait(timeout=10)
    assert claimed_event.wait(timeout=10)
    race_start.wait(timeout=10)
    for index in range(count):
        data.slots.replace("slot", new_agent_ref=f"racer-{index}", now=NOW)


def _reclaim_once(
    root: str,
    start: Any,
    claimed_event: Any,
    race_start: Any,
    reclaim_done: Any,
    output: Any,
) -> None:
    data = _data(Path(root))
    start.wait(timeout=10)
    assert claimed_event.wait(timeout=10)
    race_start.wait(timeout=10)
    report = data.slots.reclaim_stale(RECLAIM_NOW)
    assert report.reclaimed == ("expired-slot",)
    assert [item.id for item in report.expired_items] == [RECLAIM_TARGET]
    output.put([item.id for item in report.expired_items])
    reclaim_done.set()


def test_replacement_fences_zombie_and_retags_every_held_claim(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    data.slots.register(
        "slot", plan_id="plan", role="worker", agent_ref="old-agent", lease_s=3600
    )
    data.queue.enqueue(QueueItemInput("held", "plan", queue_name="work"))
    claimed = data.slots.claim("slot", epoch=1, queue_name="work", lease_s=3600)
    assert claimed is not None and claimed.claim_epoch == 1

    context = multiprocessing.get_context("spawn")
    start = context.Event()
    replaced = context.Queue()
    results = context.Queue()
    continue_replacing = context.Queue()
    continue_zombie = context.Queue()
    count = 5
    replacer = context.Process(
        target=_replace_and_report,
        args=(str(tmp_path), start, replaced, continue_replacing, count),
    )
    zombie = context.Process(
        target=_zombie_calls,
        args=(str(tmp_path), replaced, results, continue_zombie, count),
    )
    replacer.start()
    zombie.start()
    start.set()

    for _ in range(count):
        epoch, conflicts = results.get(timeout=15)
        assert conflicts == 3
        assert data.slots.show("slot").epoch == epoch
        held = data.slots.claimed("slot")
        assert all(item.claim_epoch == epoch for item in held)
        continue_zombie.put(True)
        continue_replacing.put(True)
    replacer.join(15)
    zombie.join(15)
    assert replacer.exitcode == zombie.exitcode == 0
    assert data.slots.show("slot").epoch == count + 1
    assert [item.claim_epoch for item in data.slots.claimed("slot")] == [count + 1]


def test_six_processes_race_claim_replace_and_reclaim_without_double_claims(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    data.slots.register(
        "slot", plan_id="plan", role="worker", agent_ref="agent", lease_s=3600
    )
    data.slots.heartbeat("slot", epoch=1, now=NOW)
    data.slots.register(
        "expired-slot",
        plan_id="plan",
        role="worker",
        agent_ref="expired-agent",
        lease_s=1,
    )
    data.slots.heartbeat("expired-slot", epoch=1, now=NOW)
    item_ids = {RECLAIM_TARGET, *(str(index) for index in range(1, 20))}
    for item_id in item_ids:
        data.queue.enqueue(QueueItemInput(item_id, "plan", queue_name="work"))

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(6)
    race_start = context.Barrier(5)
    claimed_event = context.Event()
    reclaim_done = context.Event()
    output = context.Queue()
    expired_output = context.Queue()
    claimers = [
        context.Process(
            target=_claim_items,
            args=(str(tmp_path), start, race_start, reclaim_done, output, index),
        )
        for index in range(1, 4)
    ]
    expired_claimer = context.Process(
        target=_claim_expiring_item,
        args=(str(tmp_path), start, claimed_event, reclaim_done),
    )
    replacer = context.Process(
        target=_replace_many,
        args=(str(tmp_path), start, claimed_event, race_start, 20),
    )
    reclaimer = context.Process(
        target=_reclaim_once,
        args=(
            str(tmp_path),
            start,
            claimed_event,
            race_start,
            reclaim_done,
            expired_output,
        ),
    )
    workers = [*claimers, expired_claimer, replacer, reclaimer]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(30)
        assert worker.exitcode == 0

    assert expired_output.get(timeout=5) == [RECLAIM_TARGET]
    claimed_ids = [item_id for _ in claimers for item_id in output.get(timeout=5)]
    assert Counter(claimed_ids) == Counter(item_ids)
    assert claimed_ids.count(RECLAIM_TARGET) == 1
    current_epoch = data.slots.show("slot").epoch
    assert current_epoch == 21
    items = [data.queue.get("work", item_id) for item_id in item_ids]
    assert all(
        item.state == "claimed"
        and item.claimed_by == "slot"
        and item.claim_epoch == current_epoch
        for item in items
    )
    assert data.queue.get("work", RECLAIM_TARGET).claim_generation == 3
    assert len({item.id for item in data.slots.claimed("slot")}) == 20
    assert data.slots.show("expired-slot").state == "dead"
    assert data.slots.claimed("expired-slot") == []
