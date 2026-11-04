from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput


def _slots(tmp_path: Path):
    initialize(tmp_path)
    database = tmp_path / QUEUE_DATABASE
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )
    return open_data(tmp_path, DataConfig())


def test_handoff_record_lists_claims_caps_events_and_is_deterministic(tmp_path):
    store = _slots(tmp_path)
    plan_dir = str(tmp_path / "plan")
    slot = store.slots.register(
        "plan-worker", plan_id=plan_dir, role="worker", agent_ref="agent"
    )
    store.queue.enqueue(QueueItemInput("task-b", plan_dir, queue_name="build"))
    store.queue.enqueue(QueueItemInput("task-a", plan_dir, queue_name="build"))
    for _ in range(2):
        claimed = store.slots.claim(
            slot.slot_id,
            epoch=slot.epoch,
            queue_name="build",
            lease_s=300,
        )
        assert claimed is not None

    for turn in range(25):
        store.slots.heartbeat(
            slot.slot_id,
            epoch=slot.epoch,
            progress_note=f"turn {turn}",
            now=f"2026-10-27T00:00:{turn:02d}+00:00",
        )
    database = tmp_path / QUEUE_DATABASE
    state = SQLitePlanState(database)
    state.set_task_state(plan_dir, "task-b", "building", actor="test")
    state.set_task_state(plan_dir, "task-a", "building", actor="test")

    record = store.slots.handoff_record(slot.slot_id)
    assert [item["id"] for item in record["claimed_items"]] == ["task-a", "task-b"]
    assert len(record["recent_events"]) == 20
    assert record["recent_events"][0]["seq"] < record["recent_events"][-1]["seq"]
    assert [task["task_id"] for task in record["task_states"]] == ["task-a", "task-b"]
    assert record["child_slots"] == []
    assert record == store.slots.handoff_record(slot.slot_id)


def test_orchestrator_handoff_record_lists_child_slots_and_their_claims(tmp_path):
    store = _slots(tmp_path)
    plan_dir = str(tmp_path / "plan")
    store.slots.register(
        "plan-orchestrator", plan_id=plan_dir, role="orchestrator", agent_ref="orch"
    )
    builder = store.slots.register(
        "plan-builder", plan_id=plan_dir, role="builder", agent_ref="builder"
    )
    reviewer = store.slots.register(
        "plan-reviewer", plan_id=plan_dir, role="reviewer", agent_ref="reviewer"
    )
    store.slots.register(
        "other-builder",
        plan_id=str(tmp_path / "other-plan"),
        role="builder",
        agent_ref="other",
    )
    store.queue.enqueue(QueueItemInput("task-build", plan_dir, queue_name="build"))
    store.queue.enqueue(QueueItemInput("task-review", plan_dir, queue_name="review"))
    assert (
        store.slots.claim(
            builder.slot_id, epoch=builder.epoch, queue_name="build", lease_s=300
        )
        is not None
    )
    assert (
        store.slots.claim(
            reviewer.slot_id, epoch=reviewer.epoch, queue_name="review", lease_s=300
        )
        is not None
    )

    record = store.slots.handoff_record("plan-orchestrator")

    assert [child["slot"]["slot_id"] for child in record["child_slots"]] == [
        "plan-builder",
        "plan-reviewer",
    ]
    assert [
        [item["id"] for item in child["claimed_items"]]
        for child in record["child_slots"]
    ] == [["task-build"], ["task-review"]]
    assert record == store.slots.handoff_record("plan-orchestrator")
