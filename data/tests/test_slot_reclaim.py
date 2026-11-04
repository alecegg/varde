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

NOW = "2030-01-01T00:00:00+00:00"


def _data(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return open_data(root, DataConfig())


def _register(data, slot_id: str, *, lease_s: int = 30) -> None:
    data.slots.register(
        slot_id,
        plan_id="plan",
        role="worker",
        agent_ref=f"agent-{slot_id}",
        lease_s=lease_s,
    )


def _heartbeat_process(root: str, ready, finished) -> None:
    data = _data(Path(root))
    ready.set()
    assert finished.wait(5)
    data.slots.heartbeat(
        "plan-race",
        epoch=1,
        now="2029-12-31T23:59:59+00:00",
        progress_note="still working",
    )


def test_reclaim_stale_expires_claims_and_is_idempotent(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data, "plan-stale")
    data.slots.heartbeat("plan-stale", epoch=1, now="2029-12-31T23:00:00+00:00")
    data.queue.enqueue(
        QueueItemInput(id="item", plan_dir="plan", queue_name="roles/plan")
    )
    data.slots.claim(
        "plan-stale",
        epoch=1,
        queue_name="roles/plan",
        lease_s=10,
        now="2029-12-31T23:59:00+00:00",
    )
    generation = data.queue.get("roles/plan", "item").claim_generation

    report = data.slots.reclaim_stale(NOW)
    assert report.reclaimed == ("plan-stale",)
    assert [item.id for item in report.expired_items] == ["item"]
    item = data.queue.get("roles/plan", "item")
    assert item.state == "queued"
    assert item.claim_generation == generation + 1
    assert data.slots.show("plan-stale").state == "dead"
    assert [event.kind for event in data.slots.events("plan-stale")][-2:] == [
        "dead",
        "reclaim",
    ]

    second = data.slots.reclaim_stale(NOW)
    assert second.reclaimed == ()
    assert second.expired_items == ()


def test_claim_expiry_comparison_uses_utc_instants(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data, "plan-offset")
    data.queue.enqueue(
        QueueItemInput(id="offset-item", plan_dir="plan", queue_name="roles/plan")
    )
    data.slots.claim(
        "plan-offset",
        epoch=1,
        queue_name="roles/plan",
        lease_s=3600,
        now="2029-12-31T23:30:00+00:00",
    )

    before_expiry = data.slots.reclaim_stale("2030-01-01T01:00:00+01:00")
    assert before_expiry.reclaimed == ()
    assert data.slots.show("plan-offset").state == "active"
    assert data.queue.get("roles/plan", "offset-item").claimed_by == "plan-offset"

    after_expiry = data.slots.reclaim_stale("2030-01-01T01:31:00+01:00")
    assert after_expiry.reclaimed == ("plan-offset",)
    assert data.queue.get("roles/plan", "offset-item").state == "queued"


def test_reclaim_marks_claimless_stale_but_preserves_live_and_parked(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    _register(data, "plan-claimless")
    _register(data, "plan-live")
    _register(data, "plan-parked")
    data.slots.heartbeat("plan-claimless", epoch=1, now="2029-12-31T23:00:00+00:00")
    data.slots.heartbeat("plan-live", epoch=1, now="2029-12-31T23:59:50+00:00")
    data.slots.park("plan-parked", epoch=1, now="2029-12-31T23:00:00+00:00")

    report = data.slots.reclaim_stale(NOW)
    assert report.reclaimed == ("plan-claimless",)
    assert data.slots.show("plan-live").state == "active"
    assert data.slots.show("plan-parked").state == "parked"


def test_reclaim_leaves_non_slot_workers_and_lapsed_parked_slots_wait(
    tmp_path: Path,
) -> None:
    data = _data(tmp_path)
    _register(data, "plan-parked")
    data.queue.enqueue(
        QueueItemInput(id="external", plan_dir="plan", queue_name="roles/plan")
    )
    data.queue.claim(
        "roles/plan",
        worker="external-worker",
        lease_s=1,
        now="2029-12-31T23:59:00+00:00",
    )
    data.slots.park("plan-parked", epoch=1, now="2029-12-31T23:00:00+00:00")

    report = data.slots.reclaim_stale(NOW)
    assert report.reclaimed == ()
    assert data.queue.get("roles/plan", "external").claimed_by == "external-worker"
    later = data.slots.reclaim_stale("2030-01-01T05:00:00+00:00")
    assert later.reclaimed == ("plan-parked",)


def test_heartbeat_between_candidate_read_and_fence_keeps_claims(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = _data(tmp_path)
    _register(data, "plan-race")
    data.queue.enqueue(
        QueueItemInput(id="race-item", plan_dir="plan", queue_name="roles/plan")
    )
    data.slots.claim(
        "plan-race",
        epoch=1,
        queue_name="roles/plan",
        lease_s=3600,
        now="2029-12-31T23:00:00+00:00",
    )
    # Force the heartbeat after candidate discovery and before queue.expire's
    # transaction fence, using a second process to exercise SQLite locking.
    from varde_data.backends.sqlite import slot_reclaim

    original = slot_reclaim.SQLiteQueue.expire
    ready = multiprocessing.Event()
    finished = multiprocessing.Event()
    process = multiprocessing.Process(
        target=_heartbeat_process, args=(str(tmp_path), ready, finished)
    )

    def expire(queue, *args, **kwargs):
        process.start()
        assert ready.wait(5)
        finished.set()
        process.join(5)
        assert process.exitcode == 0
        return original(queue, *args, **kwargs)

    monkeypatch.setattr(slot_reclaim.SQLiteQueue, "expire", expire)
    report = data.slots.reclaim_stale(NOW)
    assert report.reclaimed == ()
    assert report.skipped == ("plan-race",)
    assert data.queue.get("roles/plan", "race-item").claimed_by == "plan-race"
    assert data.slots.show("plan-race").state == "active"


def test_dead_slot_heartbeat_and_unpark_raise_conflict(tmp_path: Path) -> None:
    data = _data(tmp_path)
    _register(data, "plan-dead")
    data.slots.heartbeat("plan-dead", epoch=1, now="2029-12-31T23:00:00+00:00")
    assert data.slots.reclaim_stale(NOW).reclaimed == ("plan-dead",)
    with pytest.raises(Conflict):
        data.slots.heartbeat("plan-dead", epoch=1, now=NOW)
    with pytest.raises(Conflict):
        data.slots.unpark("plan-dead", epoch=1, now=NOW)
