from __future__ import annotations

import multiprocessing
import sqlite3
from pathlib import Path

import pytest
from varde_data.config import DataConfig
from varde_data.errors import Conflict
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput


def _database_path(root: Path) -> Path:
    return root / QUEUE_DATABASE


def _data(root: Path):
    initialize(root)
    database = _database_path(root)
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return open_data(root, DataConfig())


def _register(data, *, lease_s: int = 30) -> None:
    data.slots.register(
        "plan-worker",
        plan_id="plan",
        role="worker",
        agent_ref="agent-1",
        lease_s=lease_s,
    )


def _replace_after_epoch_read(
    root_path: str, action: str, item_id, ready, replaced, outcome
) -> None:
    data = _data(Path(root_path))
    epoch = data.slots.show("plan-worker").epoch
    ready.set()
    assert replaced.wait(5)
    try:
        if action == "claim":
            data.slots.claim(
                "plan-worker", epoch=epoch, queue_name="roles/plan", lease_s=30
            )
        else:
            data.slots.release(
                "plan-worker",
                epoch=epoch,
                queue_name="roles/plan",
                item_id=item_id,
            )
    except Conflict:
        outcome.put("conflict")
    else:
        outcome.put("succeeded")


def _replace_slot(root_path: str, ready, replaced) -> None:
    assert ready.wait(5)
    _data(Path(root_path)).slots.replace(
        "plan-worker",
        new_agent_ref="agent-2",
        lease_s=30,
        now="2030-01-01T00:00:00+00:00",
    )
    replaced.set()


def test_slot_claims_are_epoch_guarded_and_replace_keeps_claims(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data)
    data.queue.enqueue(QueueItemInput("one", "plan", queue_name="roles/plan"))
    data.queue.enqueue(QueueItemInput("two", "plan", queue_name="roles/global"))
    first = data.slots.claim(
        "plan-worker",
        epoch=1,
        queue_name="roles/plan",
        lease_s=10,
        now="2030-01-01T00:00:00+00:00",
    )
    second = data.slots.claim(
        "plan-worker",
        epoch=1,
        queue_name="roles/global",
        lease_s=10,
        now="2030-01-01T00:00:00+00:00",
    )
    assert first and second
    replaced = data.slots.replace(
        "plan-worker",
        new_agent_ref="agent-2",
        lease_s=60,
        now="2030-01-01T00:00:05+00:00",
    )
    assert replaced.epoch == 2
    assert {item.id for item in data.slots.claimed("plan-worker")} == {
        first.id,
        second.id,
    }
    assert all(
        item.claim_expires_at == "2030-01-01T00:01:05+00:00"
        for item in data.slots.claimed("plan-worker")
    )
    with pytest.raises(Conflict):
        data.slots.claim("plan-worker", epoch=1, queue_name="roles/plan", lease_s=30)
    with pytest.raises(Conflict):
        data.slots.release(
            "plan-worker", epoch=1, queue_name="roles/plan", item_id=first.id
        )


def test_finish_rejects_stale_epoch_without_follow_up(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data)
    data.queue.enqueue(
        QueueItemInput("build", "plan", role="builder", queue_name="roles/plan")
    )
    claimed = data.slots.claim(
        "plan-worker", epoch=1, queue_name="roles/plan", lease_s=30
    )
    assert claimed is not None
    data.slots.replace("plan-worker", new_agent_ref="agent-2")

    with pytest.raises(Conflict, match="epoch or state is stale"):
        data.slots.finish(
            "plan-worker",
            epoch=1,
            queue_name="roles/plan",
            item_id="build",
            generation=claimed.claim_generation,
            follow_ups=(
                QueueItemInput(
                    "build-review", "plan", role="reviewer", queue_name="roles/plan"
                ),
            ),
        )

    assert data.queue.get("roles/plan", "build").state == "claimed"
    assert data.queue.list("roles/plan", state="queued") == []


def test_heartbeat_renews_all_claims_atomically(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data)
    for item_id, queue_name in (("one", "roles/plan"), ("two", "roles/global")):
        data.queue.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        data.slots.claim(
            "plan-worker",
            epoch=1,
            queue_name=queue_name,
            lease_s=10,
            now="2030-01-01T00:00:00+00:00",
        )
    before = {
        item.id: item.claim_expires_at for item in data.slots.claimed("plan-worker")
    }
    assert len(before) == 2
    data.slots.heartbeat(
        "plan-worker",
        epoch=1,
        lease_s=60,
        now="2030-01-01T00:00:05+00:00",
    )
    assert {item.claim_expires_at for item in data.slots.claimed("plan-worker")} == {
        "2030-01-01T00:01:05+00:00"
    }
    with pytest.raises(Conflict):
        data.slots.heartbeat("plan-worker", epoch=2, lease_s=60)


def test_heartbeat_rolls_back_slot_and_claims_when_a_claim_expired(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    _register(data)
    for item_id, queue_name, now, lease_s in (
        ("one", "roles/plan", "2030-01-01T00:00:00+00:00", 1),
        ("two", "roles/global", "2030-01-01T00:00:02+00:00", 30),
    ):
        data.queue.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        data.slots.claim(
            "plan-worker",
            epoch=1,
            queue_name=queue_name,
            lease_s=lease_s,
            now=now,
        )
    before = data.slots.claimed("plan-worker")
    slot_before = data.slots.show("plan-worker")
    with pytest.raises(Conflict, match="lease has expired"):
        data.slots.heartbeat(
            "plan-worker",
            epoch=1,
            progress_note="must roll back",
            context_tokens=99,
            lease_s=90,
            now="2030-01-01T00:00:05+00:00",
        )
    assert data.slots.show("plan-worker") == slot_before
    assert data.slots.claimed("plan-worker") == before


def test_unpark_renews_claimed_items(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data)
    data.queue.enqueue(QueueItemInput("one", "plan", queue_name="roles/plan"))
    data.queue.enqueue(QueueItemInput("two", "plan", queue_name="roles/global"))
    data.slots.claim(
        "plan-worker",
        epoch=1,
        queue_name="roles/plan",
        lease_s=10,
        now="2030-01-01T00:00:00+00:00",
    )
    data.slots.claim(
        "plan-worker",
        epoch=1,
        queue_name="roles/global",
        lease_s=10,
        now="2030-01-01T00:00:00+00:00",
    )
    data.slots.park("plan-worker", epoch=1, now="2030-01-01T00:00:00+00:00")
    data.slots.unpark(
        "plan-worker", epoch=1, lease_s=60, now="2030-01-01T00:00:05+00:00"
    )
    assert {
        item.queue_name: item.claim_expires_at
        for item in data.slots.claimed("plan-worker")
    } == {
        "roles/plan": "2030-01-01T00:01:05+00:00",
        "roles/global": "2030-01-01T00:01:05+00:00",
    }


def test_replace_rolls_back_slot_and_claims_when_a_claim_expired(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    _register(data)
    for item_id, queue_name, now, lease_s in (
        ("one", "roles/plan", "2030-01-01T00:00:00+00:00", 1),
        ("two", "roles/global", "2030-01-01T00:00:02+00:00", 30),
    ):
        data.queue.enqueue(QueueItemInput(item_id, "plan", queue_name=queue_name))
        data.slots.claim(
            "plan-worker",
            epoch=1,
            queue_name=queue_name,
            lease_s=lease_s,
            now=now,
        )
    before = data.slots.claimed("plan-worker")
    slot_before = data.slots.show("plan-worker")
    with pytest.raises(Conflict, match="lease has expired"):
        data.slots.replace(
            "plan-worker",
            new_agent_ref="agent-2",
            lease_s=90,
            now="2030-01-01T00:00:05+00:00",
        )
    assert data.slots.show("plan-worker") == slot_before
    assert data.slots.claimed("plan-worker") == before


def test_fence_atomic_claim_rejects_replace_after_zombie_epoch_read(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    _register(data)
    data.queue.enqueue(QueueItemInput("one", "plan", queue_name="roles/plan"))
    context = multiprocessing.get_context("spawn")
    ready, replaced = context.Event(), context.Event()
    outcome = context.Queue()
    zombie = context.Process(
        target=_replace_after_epoch_read,
        args=(
            str(tmp_path),
            "claim",
            None,
            ready,
            replaced,
            outcome,
        ),
    )
    replacer = context.Process(
        target=_replace_slot,
        args=(str(tmp_path), ready, replaced),
    )
    zombie.start()
    replacer.start()
    assert outcome.get(timeout=10) == "conflict"
    zombie.join(10)
    replacer.join(10)
    assert zombie.exitcode == replacer.exitcode == 0
    assert data.queue.list("roles/plan")[0].state == "queued"

    claimed = data.slots.claim(
        "plan-worker",
        epoch=2,
        queue_name="roles/plan",
        lease_s=30,
        now="2030-01-01T00:00:00+00:00",
    )
    assert claimed is not None
    ready, replaced = context.Event(), context.Event()
    outcome = context.Queue()
    zombie = context.Process(
        target=_replace_after_epoch_read,
        args=(
            str(tmp_path),
            "release",
            claimed.id,
            ready,
            replaced,
            outcome,
        ),
    )
    replacer = context.Process(
        target=_replace_slot,
        args=(str(tmp_path), ready, replaced),
    )
    zombie.start()
    replacer.start()
    assert outcome.get(timeout=10) == "conflict"
    zombie.join(10)
    replacer.join(10)
    assert zombie.exitcode == replacer.exitcode == 0
    assert data.queue.get("roles/plan", claimed.id).state == "claimed"


def test_dead_slot_heartbeat_raises_conflict(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data)
    with sqlite3.connect(_database_path(tmp_path)) as db:
        db.execute("UPDATE slots SET state='dead' WHERE slot_id='plan-worker'")
    with pytest.raises(Conflict):
        data.slots.heartbeat("plan-worker", epoch=1, lease_s=60)
