from pathlib import Path

import pytest
from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.errors import NotFound


def test_sqlite_plan_and_task_state_round_trip(tmp_path: Path) -> None:
    state = SQLitePlanState(tmp_path / "queue.sqlite3")

    saved_plan = state.set_plan_state(
        "plans/example",
        status="building",
        status_at="now",
        owner="alec",
        assigned_to="builder",
        merge_approved_at="later",
    )
    saved_task = state.set_task_state(
        "plans/example", "01-work", "in_review", actor="worker"
    )

    assert state.plan_state("plans/example") == saved_plan
    assert state.task_states("plans/example") == [saved_task]
    assert saved_task.status == "in_review"
    with pytest.raises(NotFound):
        state.plan_state("missing")


def test_task_state_transition_records_actor(tmp_path: Path) -> None:
    state = SQLitePlanState(tmp_path / "queue.sqlite3")
    state.set_task_state("plans/example", "01-work", "todo", actor="planner")
    state.set_task_state("plans/example", "01-work", "building", actor="worker")

    with state._connection() as db:
        event = db.execute("SELECT * FROM queue_events ORDER BY seq DESC").fetchone()
    assert event["actor"] == "worker"
    assert event["from_state"] == "todo"
    assert event["to_state"] == "building"
    assert event["source"] == "cli"


def test_status_only_plan_update_preserves_other_fields(tmp_path: Path) -> None:
    state = SQLitePlanState(tmp_path / "queue.sqlite3")
    initial = state.set_plan_state(
        str(tmp_path / "plans/example"),
        status="todo",
        status_at="first",
        owner="alec",
        assigned_to="builder",
        merge_approved_at="approved",
    )

    updated = state.set_plan_state(str(tmp_path / "plans/example"), status="building")

    assert updated.status == "building"
    assert updated.status_at == initial.status_at
    assert updated.owner == "alec"
    assert updated.assigned_to == "builder"
    assert updated.merge_approved_at == "approved"
