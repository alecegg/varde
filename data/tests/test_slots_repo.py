from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest
from varde_data.config import DataConfig
from varde_data.errors import Conflict, WrongMode
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_data.slot_model import is_stale


def _sqlite_data(tmp_path):
    initialize(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return open_data(tmp_path, DataConfig())


def _sqlite_slots(tmp_path):
    return _sqlite_data(tmp_path).slots


def test_slot_repository_lifecycle_and_fencing(tmp_path):
    slots = _sqlite_slots(tmp_path)
    registered = slots.register(
        "plan-worker", plan_id="plan", role="worker", agent_ref="agent-1"
    )
    assert registered.epoch == 1
    assert (
        slots.register(
            "plan-worker", plan_id="plan", role="worker", agent_ref="agent-1"
        )
        == registered
    )

    heartbeat = slots.heartbeat(
        "plan-worker",
        epoch=1,
        progress_note="working",
        context_tokens=120,
        turn_count=4,
        now="2020-01-01T00:00:00+00:00",
    )
    assert heartbeat.last_progress_note == "working"
    assert heartbeat.context_tokens == 120
    assert heartbeat.turn_count == 4
    assert slots.park("plan-worker", epoch=1).state == "parked"
    assert slots.unpark("plan-worker", epoch=1).state == "active"

    replaced = slots.replace(
        "plan-worker",
        new_agent_ref="agent-2",
        actor="test",
        now="2026-10-27T12:00:00+00:00",
    )
    assert replaced.epoch == 2
    assert replaced.agent_ref == "agent-2"
    assert replaced.last_progress_at == "2026-10-27T12:00:00+00:00"
    assert not is_stale(
        replaced, datetime(2026, 10, 27, 12, 0, 1, tzinfo=UTC), replaced.lease_s
    )
    with pytest.raises(Conflict):
        slots.heartbeat("plan-worker", epoch=1)
    assert slots.show("plan-worker") == replaced
    assert [event.kind for event in slots.events("plan-worker")] == [
        "register",
        "heartbeat",
        "park",
        "unpark",
        "replace",
    ]


def test_slot_lookup_by_session_id(tmp_path):
    slots = _sqlite_slots(tmp_path)
    registered = slots.register(
        "plan-worker",
        plan_id="plan",
        role="worker",
        agent_ref="agent-1",
        session_id="session-1",
    )
    assert slots.by_session("session-1") == registered
    assert slots.by_session("session-2") is None


def test_slot_lookup_prefers_a_live_slot(tmp_path):
    slots = _sqlite_slots(tmp_path)
    live = slots.register(
        "plan-live",
        plan_id="plan",
        role="worker",
        agent_ref="agent-1",
        session_id="session-1",
    )
    slots.register(
        "plan-handed-off",
        plan_id="plan",
        role="worker",
        agent_ref="agent-2",
        session_id="session-1",
    )
    slots.handoff(
        "plan-handed-off",
        epoch=1,
        checkpoint="{}",
        now="2030-01-01T00:00:00+00:00",
    )

    assert slots.by_session("session-1") == live


def test_park_renews_claims_for_the_park_lease(tmp_path):
    data = _sqlite_data(tmp_path)
    data.slots.register(
        "plan-worker", plan_id="plan", role="worker", agent_ref="agent-1", lease_s=10
    )
    data.queue.enqueue(QueueItemInput("one", "plan", queue_name="roles/plan"))
    data.slots.claim(
        "plan-worker",
        epoch=1,
        queue_name="roles/plan",
        lease_s=10,
        now="2030-01-01T00:00:00+00:00",
    )

    parked = data.slots.park("plan-worker", epoch=1, now="2030-01-01T00:00:05+00:00")

    assert parked.state == "parked"
    assert (
        data.queue.get("roles/plan", "one").claim_expires_at
        == "2030-01-01T04:00:05+00:00"
    )
    assert data.queue.expire("2030-01-01T00:01:00+00:00") == []
    assert [item.id for item in data.slots.claimed("plan-worker")] == ["one"]


def test_handoff_records_checkpoint_and_fences_stale_epoch(tmp_path):
    slots = _sqlite_slots(tmp_path)
    slots.register("plan-worker", plan_id="plan", role="worker", agent_ref="agent-1")
    handed = slots.handoff(
        "plan-worker",
        epoch=1,
        checkpoint='{"epoch": 1}',
        now="2026-10-27T12:00:00+00:00",
    )
    assert handed.state == "handed_off"
    assert handed.checkpoint == '{"epoch": 1}'
    assert handed.epoch == 1
    assert handed.updated_at == "2026-10-27T12:00:00+00:00"

    slots.replace("plan-worker", new_agent_ref="agent-2", actor="test")
    with pytest.raises(Conflict):
        slots.handoff("plan-worker", epoch=1, checkpoint='{"epoch": 1, "stale": true}')
    current = slots.show("plan-worker")
    assert current.checkpoint == '{"epoch": 1}'
    assert current.state == "active"
    assert current.epoch == 2
    assert [event.kind for event in slots.events("plan-worker")] == [
        "register",
        "handoff",
        "replace",
    ]


def test_slots_require_sqlite_store_mode(tmp_path):
    initialize(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with pytest.raises(WrongMode):
        _ = open_data(tmp_path, DataConfig()).slots
    assert database.exists()
