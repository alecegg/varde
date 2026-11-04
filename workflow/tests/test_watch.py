import json
import os
import time
from argparse import Namespace

from varde_workflow.commands import watch
from varde_workflow.commands.watch import run_frames, run_watch


def _write_plan(working, plan_id, status="active", body=""):
    directory = working / "plans" / plan_id
    directory.mkdir(parents=True)
    plan = directory / "plan.md"
    plan.write_text(
        f"---\ntype: plan\nid: {plan_id}\nstatus: {status}\nowner: worker\n---\n{body}"
    )
    return directory


def _write_task(directory, task_id, status, depends=""):
    tasks = directory / "tasks"
    tasks.mkdir(exist_ok=True)
    dependency = f"depends_on: [{depends}]\n" if depends else ""
    (tasks / f"{task_id}.md").write_text(
        f"---\ntype: task\nid: {task_id}\nstatus: {status}\n{dependency}---\n"
    )


def _append_messages(working, rows):
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.messages import NewMessage

    repo = open_data(working, load_data_config()).messages
    for row in rows:
        repo.append(
            NewMessage(
                row.get("from", "sender"),
                row.get("to", "main"),
                row.get("kind", "info"),
                row.get("text", "message"),
                ts=row.get("ts", "2026-10-22T10:00:00Z"),
            )
        )


def test_stalled_requires_old_slot_binding_open_work_and_no_handback(tmp_path):
    record = {"id": "plan-a", "assigned_to": "orchestrator-1"}
    tasks = [{"status": "todo"}]
    bindings = [{"address": "orchestrator-1", "last_seen": "2026-10-22T10:00:00Z"}]
    now = 1_792_667_200.0

    detail = watch.stalled_detail(record, tasks, bindings, tmp_path, now)

    assert detail and detail.startswith("stalled;")
    assert (
        watch.stalled_detail(record, [{"status": "done"}], bindings, tmp_path, now)
        is None
    )
    _append_messages(tmp_path, [{"from": "plan-a", "ts": "2026-10-22T10:15:00Z"}])
    assert watch.stalled_detail(record, tasks, bindings, tmp_path, now) is None


def test_stalled_is_suppressed_while_waiting_for_user(tmp_path):
    record = {"id": "plan-a", "assigned_to": "orchestrator-1", "status": "active"}
    tasks = [{"status": "todo"}]
    bindings = [{"address": "orchestrator-1", "last_seen": "2026-10-22T10:00:00Z"}]
    _append_messages(
        tmp_path,
        [
            {
                "from": "orchestrator-1",
                "to": "main",
                "kind": "needs-user",
                "text": "approve",
            }
        ],
    )

    assert (
        watch.stalled_detail(record, tasks, bindings, tmp_path, 1_792_667_200.0) is None
    )


def test_fixture_frames_are_limited_and_use_injected_clock() -> None:
    snapshots = [
        [{"id": "zeta", "state": "stale", "newest_activity": 10}],
        [
            {
                "id": "alpha",
                "state": "active",
                "newest_activity": 20,
                "blocked_tasks": ["task-b", "task-a"],
            }
        ],
        [{"id": "ignored", "state": "finished", "newest_activity": 30}],
    ]
    times = iter([100, 200])

    lines = run_frames(snapshots, limit=2, clock=lambda: next(times), threshold=30)

    assert lines == [
        "stale zeta idle 90s",
        "blocked alpha task-a",
        "blocked alpha task-b",
    ]


def test_unchanged_fixture_state_does_not_emit_twice() -> None:
    snapshot = [{"id": "plan-a", "state": "merge-ready", "newest_activity": 0}]
    ticks = iter([100, 101])

    lines = run_frames([snapshot, snapshot], limit=2, clock=lambda: next(ticks))

    assert lines == ["merge-ready plan-a idle 100s"]


def test_json_frame_output_has_stable_key_order() -> None:
    snapshot = [
        [{"id": "plan-a", "state": "finished", "newest_activity": 0, "owner": "main"}]
    ]

    lines = run_frames(snapshot, limit=1, clock=lambda: 10, json_output=True)

    assert lines == [
        '{"kind":"finished","plan":"plan-a","owner":"main","detail":"idle 10s"}'
    ]


def test_once_reports_stale_plan_without_owner_handback(
    tmp_path, monkeypatch, capsys
) -> None:
    working = tmp_path / "working"
    plans = working / "plans" / "plan-a"
    plans.mkdir(parents=True)
    plan = plans / "plan.md"
    plan.write_text("---\ntype: plan\nid: plan-a\nstatus: active\nowner: worker\n---\n")
    old = time.time() - 7200
    plan.touch()
    os.utime(plan, (old, old))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    args = Namespace(
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=1,
        interval=60,
        repo=tmp_path,
        json=False,
    )

    assert run_watch(args) == 0
    assert capsys.readouterr().out.startswith("idle-no-handback plan-a ")


def test_scan_classifies_blocked_decision_merge_ready_finished_and_stale(tmp_path):
    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    blocked = _write_plan(working, "blocked")
    _write_task(blocked, "task-a", "blocked")
    _write_task(blocked, "task-b", "todo", "task-a")
    decision = _write_plan(
        working, "decision", body="\n## Open Questions\n\n- choose one\n"
    )
    _write_task(decision, "task-a", "done")
    merge_ready = _write_plan(working, "merge-ready")
    _write_task(merge_ready, "task-a", "done")
    finished = _write_plan(working, "finished", "completed")
    stale = _write_plan(working, "stale")
    old = time.time() - 7200
    for directory in (blocked, decision, merge_ready, stale):
        for path in directory.rglob("*"):
            if path.is_file():
                os.utime(path, (old, old))
    os.utime(finished / "plan.md", (time.time(), time.time()))

    plans = scan(working, repo, time.time(), 60)

    assert {plan["id"]: plan["state"] for plan in plans} == {
        "blocked": "blocked",
        "decision": "needs-decision",
        "finished": "finished",
        "merge-ready": "merge-ready",
        "stale": "stale",
    }


def test_watch_json_plan_includes_merge_and_stalled_state(tmp_path):
    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = _write_plan(
        working,
        "plan-a",
    )
    plan = plan_dir / "plan.md"
    plan.write_text(
        plan.read_text().replace(
            "status: active\nowner: worker\n",
            "status: active\nowner: worker\nassigned_to: orchestrator-1\n"
            "merge_approved_at: '2026-10-22T10:00:00Z'\n",
        )
    )
    _write_task(plan_dir, "open", "todo")
    plans = scan(working, repo, time.time(), 3600)

    assert plans[0]["assigned_to"] == "orchestrator-1"
    assert plans[0]["merge_approved_at"] == "2026-10-22T10:00:00Z"
    assert plans[0]["merge_state"] == "unknown"
    assert plans[0]["stalled"] is False


def test_watch_once_without_stale_uses_default_duration(tmp_path, monkeypatch):
    working = tmp_path / "working"
    _write_plan(working, "plan-a")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    args = Namespace(
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=None,
        interval=60,
        repo=tmp_path,
        json=True,
    )

    assert run_watch(args) == 0


def test_watch_once_persists_cache_across_runs(tmp_path, monkeypatch, capsys):
    working = tmp_path / "working"
    plan = _write_plan(working, "stale")
    old = time.time() - 7200
    for path in plan.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    args = Namespace(
        once=True,
        no_inbox=False,
        no_wake=True,
        stale=60,
        interval=60,
        repo=tmp_path,
        json=True,
    )

    assert run_watch(args) == 0
    assert capsys.readouterr().out == ""
    assert run_watch(args) == 0
    assert capsys.readouterr().out == ""


def test_watch_seed_is_silent_then_emits_later_transition(
    tmp_path, monkeypatch, capsys
):
    working = tmp_path / "working"
    plan = _write_plan(working, "historical", "active")
    old = time.time() - 7200
    for path in plan.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    args = Namespace(
        once=True,
        no_inbox=False,
        no_wake=True,
        stale=60,
        interval=60,
        repo=tmp_path,
        json=True,
    )

    assert run_watch(args) == 0
    assert capsys.readouterr().out == ""

    (plan / "plan.md").write_text(
        "---\ntype: plan\nid: historical\nstatus: completed\nowner: worker\n---\n"
    )
    os.utime(plan / "plan.md", None)
    assert run_watch(args) == 0
    assert json.loads(capsys.readouterr().out)["kind"] == "finished"


def test_watch_waiting_for_user_is_not_stalled_or_stale(tmp_path, monkeypatch):
    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    decision = _write_plan(
        working, "decision", body="\n## Open Questions\n\n- choose one\n"
    )
    plan = decision / "plan.md"
    plan.write_text(
        plan.read_text().replace(
            "owner: worker", "owner: worker\nassigned_to: orchestrator-1"
        )
    )
    _write_task(decision, "open", "todo")
    old = time.time() - 7200
    for path in decision.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    _append_messages(
        working,
        [
            {
                "from": "orchestrator-1",
                "to": "main",
                "kind": "needs-user",
                "text": "approve",
            }
        ],
    )

    plans = scan(working, repo, time.time(), 60)

    assert plans[0]["state"] == "needs-decision"
    assert plans[0]["awaiting_user"] == "approve"
    assert "stalled" not in plans[0]["detail"]


def test_watch_is_silent_while_awaiting_user_then_reports_stale_when_cleared(tmp_path):
    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    plan_dir = _write_plan(working, "waiting")
    plan = plan_dir / "plan.md"
    plan.write_text(
        plan.read_text().replace(
            "owner: worker", "owner: worker\nassigned_to: orchestrator-1"
        )
    )
    _write_task(plan_dir, "open", "todo")
    old = time.time() - 7200
    for path in plan_dir.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))
    _append_messages(
        working,
        [
            {
                "from": "orchestrator-1",
                "to": "main",
                "kind": "needs-user",
                "text": "approve",
            }
        ],
    )
    snapshot = scan(working, repo, time.time(), 60)
    events, cache = watch.frame_events(snapshot, time.time(), 60)
    assert snapshot[0]["awaiting_user"] == "approve"
    assert snapshot[0]["state"] != "stale"
    assert not any(event.kind in {"stale", "blocked"} for event in events)

    _append_messages(
        working,
        [{"from": "main", "to": "orchestrator-1", "kind": "info", "text": "approved"}],
    )
    cleared = scan(working, repo, time.time(), 60)
    assert cleared[0]["awaiting_user"] is None
    events, _ = watch.frame_events(cleared, time.time(), 60, cache)
    assert any(event.kind == "stale" for event in events)


def test_awaiting_suppresses_only_stale_and_blocked_events():
    plans = [
        {
            "id": state,
            "state": state,
            "detail": "detail",
            "newest_activity": 0,
            "awaiting_user": "approval",
            "blocked_tasks": ["task-a"],
        }
        for state in ("stale", "blocked", "needs-decision", "merge-ready", "finished")
    ]

    events, cache = watch.frame_events(plans, 100, 60)

    assert {event.kind for event in events} == {
        "needs-decision",
        "merge-ready",
        "finished",
    }
    assert {plan_id: item.state for plan_id, item in cache.plans.items()} == {
        state: state
        for state in ("stale", "blocked", "needs-decision", "merge-ready", "finished")
    }
    followup, _ = watch.frame_events(plans, 101, 60, cache)
    assert followup == []


def test_watch_seed_keeps_actual_state_while_awaiting():
    plan = {
        "id": "plan-a",
        "state": "needs-decision",
        "detail": "one open question",
        "newest_activity": 10,
        "awaiting_user": "approval",
    }

    events, cache = watch.frame_events([plan], 100, 60, seed=True)

    assert events == []
    assert cache.plans["plan-a"].state == "needs-decision"
    followup, _ = watch.frame_events([plan], 101, 60, cache)
    assert followup == []


def test_awaiting_watch_state_hides_stale_but_keeps_approved_merge_detail(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(watch, "awaiting_user", lambda *_args: "approval")
    monkeypatch.setattr(
        watch, "approved_merge_detail", lambda *_args: "approved 20m ago, not in main"
    )
    record = {"id": "plan-a", "assigned_to": "orchestrator-1"}

    state, detail, idle = watch.watch_state_detail(
        "stale", "stale detail", record, tmp_path, [], [], tmp_path, 100, 0, 100
    )

    assert (state, detail, idle) == ("blocked", "approved 20m ago, not in main", False)

    monkeypatch.setattr(watch, "approved_merge_detail", lambda *_args: None)
    state, detail, idle = watch.watch_state_detail(
        "stale", "stale detail", record, tmp_path, [], [], tmp_path, 100, 0, 100
    )
    assert (state, detail, idle) == ("active", "", False)


def test_concluded_plan_with_open_questions_is_finished_and_hidden_when_old(tmp_path):
    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    concluded = _write_plan(
        working,
        "concluded",
        "completed",
        body="\n## Open Questions\n\n- choose one\n",
    )
    old = time.time() - 7200
    os.utime(concluded / "plan.md", (old, old))

    plans = scan(working, repo, time.time(), 60)

    assert plans == []


def test_watch_once_creates_notes_with_plan_status(tmp_path, monkeypatch, capsys):
    working = tmp_path / "working"
    _write_plan(working, "plan-a")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    notes = tmp_path / "notes.md"
    args = Namespace(
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=60,
        interval=60,
        repo=tmp_path,
        json=False,
        notes=notes,
    )

    assert run_watch(args) == 0

    contents = notes.read_text(encoding="utf-8")
    assert contents.startswith("---\ntype: session-notes\nstatus: draft\n---\n")
    assert "<!-- varde:plan-status:begin -->\nplan-a [active] 0/0\n" in contents
    assert "<!-- varde:plan-status:end -->" in contents
    assert capsys.readouterr().out == ""


def test_watch_once_replaces_only_generated_notes_block(tmp_path, monkeypatch, capsys):
    working = tmp_path / "working"
    _write_plan(working, "plan-a")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    notes = tmp_path / "notes.md"
    notes.write_text(
        "handwritten before\n<!-- varde:plan-status:begin -->\nstale status\n"
        "<!-- varde:plan-status:end -->\nhandwritten after\n",
        encoding="utf-8",
    )
    args = Namespace(
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=60,
        interval=60,
        repo=tmp_path,
        json=False,
        notes=notes,
    )

    assert run_watch(args) == 0

    contents = notes.read_text(encoding="utf-8")
    assert contents == (
        "handwritten before\n<!-- varde:plan-status:begin -->\nplan-a [active] 0/0\n\n"
        "lookup: varde plan status | varde plan show <id> | varde learn friction list --status open | git -C <worktree> log\n"
        "<!-- varde:plan-status:end -->\nhandwritten after\n"
    )
    assert capsys.readouterr().out == ""


def test_recent_bound_branch_commit_keeps_old_plan_active(tmp_path):
    import subprocess

    from varde_workflow.commands.watch import scan

    working = tmp_path / "working"
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    tracked = repo / "file.txt"
    tracked.write_text("content\n")
    subprocess.run(["git", "-C", str(repo), "add", "file.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "recent work"], check=True)
    subprocess.run(["git", "-C", str(repo), "branch", "worktree/plan-a"], check=True)
    plan = _write_plan(working, "plan-a")
    old = time.time() - 7200
    for path in plan.rglob("*"):
        if path.is_file():
            os.utime(path, (old, old))

    plans = scan(working, repo, time.time(), 60)

    assert plans[0]["state"] == "active"
