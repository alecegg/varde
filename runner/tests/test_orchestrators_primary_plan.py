from __future__ import annotations

from varde_runner.varde_cli import VardeCLI
from varde_runner.web.app import _plan_rows, select_slot_plans
from varde_runner.web.queue import _plan_repository


def test_slot_primary_prefers_child_with_tasks_over_umbrella():
    umbrella = {"id": "umbrella", "title": "Umbrella", "group": True, "total": 0}
    child = {
        "id": "child",
        "title": "Child",
        "status": "active",
        "done": 2,
        "total": 5,
    }

    primary, others = select_slot_plans([umbrella, child])

    assert primary is child
    assert others == [
        {"id": "umbrella", "title": "Umbrella", "status": "", "done": 0, "total": 0}
    ]


def test_slot_primary_chooses_latest_child_with_tasks():
    earlier = {"id": "earlier", "total": 3, "now_at": "2026-10-20T10:00:00Z"}
    later = {"id": "later", "total": 2, "now_at": "2026-10-21T10:00:00Z"}

    primary, others = select_slot_plans([earlier, later])

    assert primary is later
    assert [item["id"] for item in others] == ["earlier"]


def test_slot_primary_prefers_active_over_backlog_before_activity():
    backlog = {
        "id": "older-active",
        "status": "backlog",
        "total": 3,
        "now_at": "2026-10-22T10:00:00Z",
    }
    active = {"id": "newer-active", "status": "active", "total": 1}

    primary, _ = select_slot_plans([backlog, active])

    assert primary is active


def test_taskless_child_still_ranks_above_group_umbrella():
    umbrella = {
        "id": "z-umbrella",
        "group": True,
        "total": 1,
        "children": [{"id": "a-child"}],
    }
    child = {"id": "a-child", "group": False, "total": 0}

    primary, others = select_slot_plans([umbrella, child])

    assert primary is child
    assert [other["id"] for other in others] == ["z-umbrella"]


def test_slot_excludes_terminal_plans():
    active = {"id": "active", "status": "active", "total": 0}
    terminal = {"id": "terminal", "status": "completed", "total": 5}

    primary, others = select_slot_plans([terminal, active])

    assert primary is active
    assert others == []


def test_slot_ties_use_id_and_lone_umbrella_is_kept():
    first = {"id": "a", "total": 2, "now_at": "2026-10-20T10:00:00Z"}
    second = {"id": "b", "total": 2, "now_at": "2026-10-20T10:00:00Z"}
    umbrella = {"id": "umbrella", "group": True, "total": 0}

    primary, others = select_slot_plans([second, first])
    only, no_others = select_slot_plans([umbrella])

    assert primary is second
    assert [item["id"] for item in others] == ["a"]
    assert only is umbrella
    assert no_others == []


def test_unjoined_orchestrator_row_keeps_existing_fields_and_empty_other_plans():
    rows, _, _ = _plan_rows(
        {"plans": []},
        {"events": []},
        [],
        object(),
        [{"address": "unjoined-slot", "wake_context": {}}],
        [],
    )

    assert rows[0]["id"] == "unjoined-slot"
    assert rows[0]["plan_id"] == "unjoined-slot"
    assert rows[0]["address"] == "unjoined-slot"
    assert rows[0]["plan_joined"] is False
    assert rows[0]["title"] == "orch unjoined-slot"
    assert rows[0]["label"] == "orch unjoined-slot"
    assert rows[0]["queue"] == []
    assert rows[0]["other_plans"] == []
    assert set(rows[0]) == {
        "activity",
        "address",
        "agent_id",
        "agent_status",
        "awaiting_user",
        "group_name",
        "id",
        "idle_for",
        "label",
        "last_activity",
        "last_event_at",
        "last_message_age",
        "model",
        "now",
        "now_at",
        "open_questions",
        "other_plans",
        "owner",
        "plan_id",
        "plan_joined",
        "queue",
        "status",
        "title",
        "workers",
        "worktree",
    }


def test_orchestrator_row_uses_child_plan_and_lists_umbrella():
    umbrella = {
        "id": "umbrella",
        "title": "Shared data layer",
        "group": True,
        "status": "active",
        "assigned_to": "orchestrator-1",
        "done": 0,
        "total": 0,
    }
    child = {
        "id": "data-plans-writers",
        "title": "Plan writers",
        "status": "active",
        "assigned_to": "orchestrator-1",
        "done": 2,
        "total": 5,
        "tasks": [{"id": f"task-{number}", "status": "todo"} for number in range(5)],
    }

    rows, _, _ = _plan_rows(
        {"plans": [umbrella, child]},
        {"events": []},
        [],
        object(),
        [{"address": "orchestrator-1"}],
        [],
    )

    assert rows[0]["id"] == "data-plans-writers"
    assert len(rows[0]["queue"]) == 5
    assert rows[0]["other_plans"] == [
        {
            "id": "umbrella",
            "title": "Shared data layer",
            "status": "active",
            "done": 0,
            "total": 0,
        }
    ]


def test_cli_and_queue_share_the_repository_for_a_working_directory(tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(working)})

    assert cli._plans() is _plan_repository(working)
