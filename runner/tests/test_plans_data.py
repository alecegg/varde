"""Plan running and needs-you counts against live-shaped data."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from test_web import app_request
from varde_data import Conflict
from varde_runner.decisions import DecisionStore
from varde_runner.intake import InboxProjector
from varde_runner.open_decisions import open_decision_items
from varde_runner.varde_cli import VardeCLI
from varde_runner.web.activity import (
    plan_activity,
    plan_id_for_address,
    waiting_plan_ids,
)
from varde_runner.web.app import DashboardData, _needs_you_items, _plan_rows
from varde_runner.web.queue import create_queue_routes

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=UTC)
REPO = "/Users/alec/source/varde"


def orchestrator(agent_id, status, last_activity):
    return {
        "id": agent_id,
        "status": status,
        "cwd": REPO,
        "lastActivity": last_activity,
    }


AGENTS = [
    {"agent": orchestrator("o-idle-old", "idle", "2026-10-20T04:56:36.588Z")},
    {"agent": orchestrator("o-idle-new", "idle", "2026-10-21T09:45:00Z")},
    {"agent": orchestrator("o-live", "running", "2026-10-21T09:59:00Z")},
    # A builder in an unrelated worktree under the repo root.
    {"agent": {"id": "w-1", "status": "running", "cwd": f"{REPO}/.varde/worktrees/F3"}},
]
PARTLY_DONE = [{"status": "done"}, {"status": "todo"}]


def plan(plan_id, status, tasks=()):
    return {"id": plan_id, "status": status, "queue": list(tasks)}


def activity(row, agent_id):
    orch = next(a["agent"] for a in AGENTS if a["agent"]["id"] == agent_id)
    return plan_activity(row, AGENTS, orch, NOW)


def test_idle_orchestrator_does_not_inherit_unrelated_repo_workers():
    result = activity(plan("p", "running"), "o-idle-old")
    assert result["workers"] == []
    assert result["activity"] == "stalled"


def test_partly_done_plan_with_old_orchestrator_activity_is_stale():
    assert (
        activity(plan("p", "running", PARTLY_DONE), "o-idle-old")["activity"]
        == "stalled"
    )


def test_partly_done_plan_with_recent_orchestrator_activity_is_active():
    assert (
        activity(plan("p", "running", PARTLY_DONE), "o-idle-new")["activity"] == "idle"
    )


def test_live_orchestrator_is_running():
    assert (
        activity(plan("p", "running", PARTLY_DONE), "o-live")["activity"] == "running"
    )


def test_worker_inside_plan_worktree_counts():
    row = plan("p", "running", PARTLY_DONE) | {
        "worktree": f"{REPO}/.varde/worktrees/F3"
    }

    result = activity(row, "o-idle-old")
    assert result["activity"] == "running" and len(result["workers"]) == 1


def test_activity_precedence_and_stale_threshold():
    active = plan("p", "active")
    idle_orchestrator = orchestrator("orch", "idle", "2026-10-21T09:39:00Z")
    assert plan_activity(active, [], idle_orchestrator, NOW)["activity"] == "stalled"
    assert (
        plan_activity(active, [], idle_orchestrator, NOW, open_questions=1)["activity"]
        == "waiting"
    )
    assert (
        plan_activity({**active, "status": "blocked"}, [], idle_orchestrator, NOW, 1)[
            "activity"
        ]
        == "blocked"
    )
    assert (
        plan_activity({**active, "status": "completed"}, [], idle_orchestrator, NOW, 1)[
            "activity"
        ]
        == "done"
    )


def test_waiting_requires_joined_plan_with_open_question():
    completed = plan_activity(
        {"id": "pstack-measure", "status": "completed", "_joinable": True},
        [],
        orchestrator("orch", "running", "2026-10-21T09:59:00Z"),
        NOW,
        open_questions=1,
    )
    unjoined = plan_activity(
        {"id": "qs-call-resolver", "status": "active", "_joinable": False},
        [],
        orchestrator("orch", "idle", "2026-10-21T09:59:00Z"),
        NOW,
        open_questions=6,
    )
    live = plan_activity(
        {"id": "joined", "status": "active", "_joinable": True},
        [],
        orchestrator("orch", "running", "2026-10-21T09:59:00Z"),
        NOW,
        open_questions=1,
    )

    assert completed["activity"] == "done"
    assert unjoined["activity"] != "waiting"
    assert live["activity"] == "waiting"
    assert (
        plan_activity(
            {"id": "joined", "status": "active", "_joinable": True},
            [],
            orchestrator("orch", "idle", "2026-10-21T09:59:00Z"),
            NOW,
            open_questions=1,
        )["activity"]
        == "waiting"
    )
    assert waiting_plan_ids(
        [
            {"id": "pstack-measure", "plan_joined": True, **completed},
            {"id": "qs-call-resolver", "plan_joined": False, **unjoined},
            {"id": "joined", "plan_joined": True, **live},
        ]
    ) == {"joined"}


def test_needs_you_projection_matches_waiting_plans_and_keeps_nonplan_items():
    open_items = [
        {"msg_id": "waiting", "sender": "orch-waiting"},
        {"msg_id": "concluded", "sender": "orch-concluded"},
        {"msg_id": "unjoined-row", "sender": "unjoined-row"},
        {"msg_id": "unjoined-binding", "sender": "orch-unjoined"},
        {"msg_id": "nonplan", "sender": "external"},
    ]
    plans = [
        {"id": "live-plan", "assigned_to": "orch-waiting"},
        {"id": "done-plan", "assigned_to": "orch-concluded"},
        {"id": "unjoined-row", "plan_joined": False},
    ]
    bindings = [
        {"address": "orch-waiting", "plan_id": "live-plan"},
        {"address": "orch-concluded", "plan_id": "done-plan"},
        {"address": "orch-unjoined"},
    ]

    result = _needs_you_items(open_items, plans, bindings, {"live-plan"})

    assert [item["msg_id"] for item in result] == ["waiting", "nonplan"]


def test_unjoinable_plan_is_unknown_even_with_a_known_orchestrator():
    result = plan_activity(
        {"id": "address", "_joinable": False},
        [],
        {"id": "orch", "status": "idle"},
        NOW,
    )
    assert result["activity"] == "unknown"


def test_unjoinable_plan_with_running_worker_is_running():
    result = plan_activity(
        {"id": "review-address", "_joinable": False, "status": "active"},
        [
            {
                "id": "worker",
                "status": "running",
                "labels": {"paseo.parent-agent-id": "orch"},
            }
        ],
        {"id": "orch", "status": "idle"},
        NOW,
    )
    assert result["activity"] == "running"


def test_idle_for_unknown_with_active_plan_and_no_live_orchestrator_is_stalled():
    result = plan_activity({"id": "p", "status": "active"}, [], {}, NOW)
    assert result["activity"] == "stalled"
    assert result["idle_for"] is None


def test_plan_status_not_finished_when_all_tasks_are_done():
    result = plan_activity(plan("p", "active", [{"status": "done"}]), [], {}, NOW)
    assert result["activity"] == "stalled"
    completed = plan_activity(plan("p", "completed", [{"status": "todo"}]), [], {}, NOW)
    assert completed["activity"] == "done"


def test_backlog_plan_with_orchestrator_is_idle():
    result = plan_activity(
        plan("p", "backlog"),
        [],
        orchestrator("orch", "idle", "2026-10-21T09:59:00Z"),
        NOW,
    )
    assert result["activity"] == "idle"


def test_workers_include_running_and_error_descendants_only():
    agents = [
        {
            "id": "idle",
            "status": "idle",
            "labels": {"paseo.parent-agent-id": "orch"},
        },
        {
            "id": "running",
            "status": "running",
            "labels": {"paseo.parent-agent-id": "orch"},
        },
        {
            "id": "error",
            "status": "error",
            "labels": {"paseo.parent-agent-id": "orch"},
        },
    ]
    result = plan_activity(
        {"id": "p", "status": "active"}, agents, {"id": "orch", "status": "idle"}, NOW
    )
    assert [worker["id"] for worker in result["workers"]] == ["running", "error"]


def test_orchestrator_address_join_precedence():
    plans = [{"id": "2026-10-21-example"}]
    assert (
        plan_id_for_address("orch", plans, [{"address": "orch", "plan_id": "explicit"}])
        == "explicit"
    )
    assert plan_id_for_address("2026-10-21-example", plans, []) == "2026-10-21-example"
    assert plan_id_for_address("example", plans, []) == "2026-10-21-example"
    assert plan_id_for_address("missing", plans, []) is None


def test_approved_and_stalled_states_are_copied_for_assigned_to_slot():
    class CLI:
        def read_plan_tasks(self, _plan_id):
            return []

    plans, _, _ = _plan_rows(
        {
            "plans": [
                {
                    "id": "2026-10-21-dashboard-states",
                    "status": "active",
                    "assigned_to": "orchestrator-2",
                    "merge_approved_at": "2026-10-21T09:00:00Z",
                    "title": "Dashboard states",
                    "tasks": [],
                }
            ]
        },
        {
            "plans": [
                {
                    "id": "2026-10-21-dashboard-states",
                    "assigned_to": "orchestrator-2",
                    "merge_state": "approved_not_merged",
                    "stalled": True,
                }
            ],
            "events": [],
        },
        [],
        CLI(),
        [{"address": "orchestrator-2"}],
        [],
    )

    assert len(plans) == 1
    assert plans[0]["id"] == "2026-10-21-dashboard-states"
    assert plans[0]["assigned_to"] == "orchestrator-2"
    assert plans[0]["merge_state"] == "approved_not_merged"
    assert plans[0]["merge_approved_at"] == "2026-10-21T09:00:00Z"
    assert plans[0]["stalled"] is True


def test_assigned_to_join_does_not_use_plan_name_or_binding_plan_id():
    class CLI:
        def read_plan_tasks(self, _plan_id):
            return []

        def read_plan_summary(self, _plan_id):
            raise FileNotFoundError

    plans, _, _ = _plan_rows(
        {
            "plans": [
                {
                    "id": "2026-10-21-dashboard-states",
                    "status": "active",
                    "assigned_to": "orchestrator-2",
                    "tasks": [],
                }
            ]
        },
        {"plans": [], "events": []},
        [],
        CLI(),
        [{"address": "dashboard-states"}],
        [],
    )

    assert plans[0]["plan_joined"] is False


def test_stalled_status_from_json_wins_over_live_activity():
    result = plan_activity(
        {"id": "p", "status": "active", "stalled": True},
        [],
        {"id": "orch", "status": "running"},
        NOW,
    )

    assert result["activity"] == "stalled"


def test_plan_watch_reader_keeps_snapshot_plan_states(tmp_path, monkeypatch):
    from varde_runner import varde_cli

    monkeypatch.setattr(
        varde_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(
                '{"kind":"finished","plans":[{"id":"p","assigned_to":"orchestrator-1",'
                '"merge_state":"approved_not_merged","stalled":true}],"events":'
                '[{"kind":"finished","plan_id":"p"}]}'
            )
        ),
    )

    assert VardeCLI(cwd=tmp_path).read_plan_watch() == {
        "plans": [
            {
                "id": "p",
                "assigned_to": "orchestrator-1",
                "merge_state": "approved_not_merged",
                "stalled": True,
            }
        ],
        "events": [{"kind": "finished", "plan_id": "p"}],
    }


def test_plan_watch_reader_keeps_events_only_output(tmp_path, monkeypatch):
    from varde_runner import varde_cli

    monkeypatch.setattr(
        varde_cli.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout='{"kind":"finished","plan_id":"p"}'
        ),
    )

    assert VardeCLI(cwd=tmp_path).read_plan_watch() == {
        "events": [{"kind": "finished", "plan_id": "p"}]
    }


def test_plan_read_adapters_preserve_typed_frontmatter_fields(tmp_path):
    folder = tmp_path / "plans" / "2026-10-21-example"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nid: example\ntitle: Example\nstatus: backlog\nowner: [alice, bob]\n---\n",
        encoding="utf-8",
    )
    (folder / "tasks" / "task.md").write_text(
        (
            "---\ntype: task\nid: t1\ntitle: Task\nstatus: todo\n"
            "owner: [alice, bob]\n---\n"
        ),
        encoding="utf-8",
    )
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    assert cli.read_plan_summary("example") == {
        "id": "example",
        "title": "Example",
        "status": "backlog",
        "owner": ["alice", "bob"],
    }
    assert cli.read_plan_tasks("example") == [
        {"id": "t1", "title": "Task", "status": "todo", "owner": ["alice", "bob"]}
    ]


def test_plan_path_adapter_rejects_unresolved_and_ambiguous_refs(tmp_path):
    for name in ("one/shared", "two/shared"):
        folder = tmp_path / "plans" / name
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    for plan_ref in ("missing", "shared"):
        with pytest.raises(FileNotFoundError):
            cli._find_plan_path(plan_ref)


def test_plan_adapters_keep_direct_path_precedence(tmp_path):
    direct = tmp_path / "plans" / "target" / "plan.md"
    nested = tmp_path / "plans" / "nested" / "target" / "plan.md"
    direct.parent.mkdir(parents=True)
    nested.parent.mkdir(parents=True)
    direct.write_text("---\ntitle: Direct\n---\n", encoding="utf-8")
    nested.write_text("---\ntitle: Nested\n---\n", encoding="utf-8")
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    assert cli.read_plan_summary("target")["title"] == "Direct"
    app = Starlette(routes=create_queue_routes(object(), tmp_path))
    detail = app_request(app, "GET", "/api/plans/target")
    assert detail.status_code == 200
    assert "title: Direct" in detail.json()["plan_text"]


def test_plan_adapters_use_basename_before_another_plan_id(tmp_path):
    by_id = tmp_path / "plans" / "elsewhere" / "plan.md"
    by_name = tmp_path / "plans" / "target" / "plan.md"
    by_id.parent.mkdir(parents=True)
    by_name.parent.mkdir(parents=True)
    by_id.write_text("---\nid: target\ntitle: Frontmatter id\n---\n", encoding="utf-8")
    by_name.write_text(
        "---\nid: other\ntitle: Directory basename\n---\n", encoding="utf-8"
    )
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    assert cli.read_plan_summary("target")["title"] == "Directory basename"
    app = Starlette(routes=create_queue_routes(object(), tmp_path))
    detail = app_request(app, "GET", "/api/plans/target")
    assert detail.status_code == 200
    assert "title: Directory basename" in detail.json()["plan_text"]


def test_runner_adapters_reject_task_artifacts(tmp_path):
    task = tmp_path / "plans" / "task-only" / "task.md"
    task.parent.mkdir(parents=True)
    task.write_text("---\ntype: task\ntitle: Task only\n---\n", encoding="utf-8")
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    with pytest.raises(FileNotFoundError):
        cli.read_plan_summary("task-only")
    app = Starlette(routes=create_queue_routes(object(), tmp_path))
    response = app_request(app, "GET", "/api/plans/task-only")
    assert response.status_code == 404


def test_cli_supports_date_suffix_while_queue_keeps_basename_lookup(tmp_path):
    plan = tmp_path / "plans" / "2026-10-23-date-suffix" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\nid: date-suffix\ntitle: Suffix\n---\n", encoding="utf-8")
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    assert cli.read_plan_summary("date-suffix")["title"] == "Suffix"
    app = Starlette(routes=create_queue_routes(object(), tmp_path))
    response = app_request(app, "GET", "/api/plans/date-suffix")
    assert response.status_code == 404


def test_runner_plan_resolution_tier_contract(tmp_path):
    plans = tmp_path / "plans"
    cases = {
        "target": "direct",
        "nested/target": "nested",
        "2026-10-23-suffix": "dated suffix",
    }
    for directory, title in cases.items():
        folder = plans / directory
        folder.mkdir(parents=True)
        plan_id = directory.split("/")[-1]
        (folder / "plan.md").write_text(
            f"---\nid: {plan_id}\ntitle: {title}\n---\n", encoding="utf-8"
        )
    (plans / "target" / "plan.md").write_text(
        "---\nid: not-target\ntitle: direct\n---\n", encoding="utf-8"
    )
    (plans / "by-name").mkdir()
    (plans / "by-name" / "plan.md").write_text(
        "---\nid: different-id\ntitle: basename\n---\n", encoding="utf-8"
    )
    for directory in ("2025-01-shared", "2026-01-shared"):
        folder = plans / directory
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\ntitle: Shared\n---\n", encoding="utf-8")

    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    assert cli.read_plan_summary("target")["title"] == "direct"
    assert cli.read_plan_summary("by-name")["title"] == "basename"
    assert cli.read_plan_summary("suffix")["title"] == "dated suffix"
    with pytest.raises(FileNotFoundError) as ambiguous:
        cli._find_plan_path("shared")
    assert isinstance(ambiguous.value.__cause__, Conflict)
    with pytest.raises(FileNotFoundError) as missing:
        cli._find_plan_path("missing")
    assert missing.value.__cause__ is None


def test_runner_plan_resolution_accepts_frontmatter_id(tmp_path):
    folder = tmp_path / "plans" / "custom-folder"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nid: id-only-ref\ntitle: By id\n---\n", encoding="utf-8"
    )
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})

    # This id-only reference previously raised FileNotFoundError.
    assert cli.read_plan_summary("id-only-ref")["title"] == "By id"


def _touch_with_new_mtime(path):
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 2_000_000_000))


def _age_plan_tree(root):
    old_ns = time.time_ns() - 10_000_000_000
    paths = sorted(root.rglob("*"), key=lambda path: len(path.parts), reverse=True)
    for path in [*paths, root]:
        os.utime(path, ns=(old_ns, old_ns))


def test_plan_repository_and_versioned_list_cache_are_shared(tmp_path, monkeypatch):
    folder = tmp_path / "plans" / "2026-10-23-memo"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nid: memo\nassigned_to: agent-1\n---\n", encoding="utf-8"
    )
    (folder / "tasks" / "task.md").write_text(
        "---\ntype: task\nid: task-1\n---\n", encoding="utf-8"
    )
    _age_plan_tree(tmp_path)
    cli = VardeCLI(
        cwd=tmp_path,
        env={"VARDE_WORKING_DIR": str(tmp_path)},
    )
    repository = cli._plans()
    assert cli._plans() is repository
    original_list = repository.list
    calls = []

    def counted_list(**kwargs):
        calls.append(kwargs)
        return original_list(**kwargs)

    monkeypatch.setattr(repository, "list", counted_list)
    assert cli.read_plan_tasks("memo")[0]["id"] == "task-1"
    cli.read_plan_summary("memo")
    cli.read_assigned_plans()
    cli._find_plan_path("memo")
    assert len(calls) == 2
    assert calls == [
        {"include_tasks": True},
        {"include_tasks": False},
    ]

    _touch_with_new_mtime(folder / "plan.md")
    cli.read_plan_summary("memo")
    assert len(calls) == 3
    assert calls[-1] == {"include_tasks": False}


def test_no_tasks_cache_entry_never_serves_tasks_request(tmp_path, monkeypatch):
    folder = tmp_path / "plans" / "2026-10-23-memo"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_text("---\nid: memo\n---\n", encoding="utf-8")
    (folder / "tasks" / "task.md").write_text(
        "---\ntype: task\nid: task-1\n---\n", encoding="utf-8"
    )
    _age_plan_tree(tmp_path)
    cli = VardeCLI(
        cwd=tmp_path,
        env={"VARDE_WORKING_DIR": str(tmp_path)},
    )
    repository = cli._plans()
    original_list = repository.list
    calls = []

    def interleaved_list(**kwargs):
        calls.append(kwargs)
        result = original_list(**kwargs)
        if len(calls) == 1:
            # A tasks lookup finishes before this no-tasks lookup stores its entry.
            assert cli.read_plan_tasks("memo")[0]["id"] == "task-1"
        return result

    monkeypatch.setattr(repository, "list", interleaved_list)
    cli.read_plan_summary("memo")
    assert cli.read_plan_tasks("memo")[0]["id"] == "task-1"
    assert calls[-1] == {"include_tasks": True}


def test_plan_list_cache_invalidates_when_task_file_changes(tmp_path, monkeypatch):
    folder = tmp_path / "plans" / "memo"
    tasks = folder / "tasks"
    tasks.mkdir(parents=True)
    (folder / "plan.md").write_text("---\nid: memo\n---\n", encoding="utf-8")
    task = tasks / "task.md"
    task.write_text("---\ntype: task\nid: before\n---\n", encoding="utf-8")
    _age_plan_tree(tmp_path)
    cli = VardeCLI(cwd=tmp_path, env={"VARDE_WORKING_DIR": str(tmp_path)})
    repository = cli._plans()
    original_list = repository.list
    calls = []

    def counted_list(**kwargs):
        calls.append(kwargs)
        return original_list(**kwargs)

    monkeypatch.setattr(repository, "list", counted_list)
    assert cli.read_plan_tasks("memo")[0]["id"] == "before"
    _touch_with_new_mtime(task)
    task.write_text("---\ntype: task\nid: after\n---\n", encoding="utf-8")
    assert cli.read_plan_tasks("memo")[0]["id"] == "after"
    assert len(calls) == 2


def test_plan_routes_return_not_found_for_ambiguous_refs(tmp_path):
    for name in ("one/shared", "two/shared"):
        folder = tmp_path / "plans" / name
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
    app = Starlette(routes=create_queue_routes(object(), tmp_path))
    detail = app_request(app, "GET", "/api/plans/shared")
    comment = app_request(
        app,
        "POST",
        "/api/plans/shared/comments",
        content=b'{"target":"plan","text":"comment"}',
        headers={"content-type": "application/json"},
    )

    assert detail.status_code == comment.status_code == 404
    assert detail.json() == comment.json() == {"error": "plan not found"}


def test_queue_plan_read_does_not_block_event_loop(tmp_path, monkeypatch):
    from varde_runner.web import queue

    started = threading.Event()
    release = threading.Event()

    def slow_read(_working_dir):
        started.set()
        release.wait()
        return ()

    monkeypatch.setattr(queue, "_plan_records", slow_read)
    route = next(
        route
        for route in queue.create_queue_routes(object(), tmp_path)
        if route.path == "/api/plans/{plan_id:str}"
    )
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/plans/slow",
            "headers": [],
            "query_string": b"",
            "server": ("test", 80),
            "client": ("test", 1234),
            "scheme": "http",
            "path_params": {"plan_id": "slow"},
        }
    )

    async def verify():
        task = asyncio.create_task(route.endpoint(request))
        await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=1)
        heartbeat = asyncio.Event()
        asyncio.get_running_loop().call_soon(heartbeat.set)
        await asyncio.wait_for(heartbeat.wait(), timeout=0.1)
        release.set()
        response = await task
        assert response.status_code == 404

    asyncio.run(verify())


def test_dashboard_plan_watch_falls_back_to_plan_reader():
    cli = SimpleNamespace(read_plan=lambda: {"plans": [{"id": "legacy-plan"}]})
    projector = cast("InboxProjector", SimpleNamespace(last_messages=[]))
    decisions = cast("DecisionStore", SimpleNamespace())
    dashboard = DashboardData(cli, projector, decisions, None)

    assert dashboard.plan_watch() == {"plans": [{"id": "legacy-plan"}]}


def decision(msg_id, sender, ts="2026-10-21T05:00:00Z"):
    return {
        "msg_id": msg_id,
        "kind": "needs-decision",
        "state": "pending",
        "sender": sender,
        "ts": ts,
    }


def test_needs_you_counts_only_bound_unconcluded_unanswered_decisions():
    items = [
        decision("m-live", "dashboard-ux2"),
        decision("m-concluded", "python-port-core"),
        decision("m-unbound", "relay-restart"),
        decision("m-acked", "dashboard-ux2"),
        decision("m-answered", "qs-call-resolver"),
    ]
    messages = [
        {"from": "main", "to": "qs-call-resolver", "ts": "2026-10-21T06:00:00Z"}
    ]

    open_items = open_decision_items(
        items,
        messages,
        {"m-acked"},
        {"dashboard-ux2", "python-port-core", "qs-call-resolver"},
        {"python-port-core"},
    )

    assert [item["msg_id"] for item in open_items] == ["m-live"]


def test_awaiting_user_is_waiting_above_stalled_and_blocked_below_done():
    reason = "needs your sudo fs_usage capture"
    base = {"id": "p", "status": "active", "stalled": True, "awaiting_user": reason}
    idle = orchestrator("orch", "idle", "2026-10-21T09:39:00Z")

    result = plan_activity(base, [], idle, NOW)
    assert result["activity"] == "waiting" and result["awaiting_user"] == reason
    assert (
        plan_activity({**base, "status": "blocked"}, [], idle, NOW)["activity"]
        == "waiting"
    )
    assert (
        plan_activity({**base, "status": "completed"}, [], idle, NOW)["activity"]
        == "done"
    )
    assert (
        plan_activity({**base, "awaiting_user": None}, [], idle, NOW)["activity"]
        == "stalled"
    )


def _awaiting_rows(status_plans, watch):
    class CLI:
        def read_plan_tasks(self, _plan_id):
            return []

        def read_plan_summary(self, _plan_id):
            raise FileNotFoundError

    plans, _, _ = _plan_rows(
        {"plans": status_plans}, watch, [], CLI(), [{"address": "orch"}], []
    )
    return plans[0]


def test_plan_row_takes_awaiting_user_from_watch_plan_or_event():
    status = [{"id": "p", "status": "active", "assigned_to": "orch", "tasks": []}]
    from_plan = _awaiting_rows(
        status, {"plans": [{"id": "p", "awaiting_user": "approve merge"}], "events": []}
    )
    from_event = _awaiting_rows(
        status,
        {"plans": [], "events": [{"plan": "p", "awaiting_user": "approve merge"}]},
    )
    for row in (from_plan, from_event):
        assert row["awaiting_user"] == "approve merge"
        assert row["activity"] == "waiting"
