from __future__ import annotations

import json
from argparse import Namespace

from varde_workflow.commands import watch


def test_plan_snapshot_includes_model_worktree_and_event_time(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plan_dir = working / "plans" / "plan-a"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\ntype: plan\nid: plan-a\nstatus: active\nowner: codex:agent-7\n"
        "model: gpt-6-luna\nbranch: worktree/plan-a\n---\n"
    )
    now = 1_800_000_000.0
    worktree = tmp_path / "worktree-plan-a"
    monkeypatch.setattr(watch, "_read_branches", lambda repo: {"worktree/plan-a": now})
    monkeypatch.setattr(
        watch, "_read_worktrees", lambda repo: {"worktree/plan-a": worktree}
    )

    plans = watch.scan(working, tmp_path, now, 1200)

    assert plans[0]["model"] == "gpt-6-luna"
    assert plans[0]["worktree"] == str(worktree)
    assert plans[0]["last_event_at"] == "2027-01-15T08:00:00+00:00"
    assert plans[0]["detail"] == ""


def test_waiting_is_live_uses_legacy_now_line_mtime(tmp_path):
    working = tmp_path / "working"
    plans_dir = working / "plans"
    plan = plans_dir / "plan-a" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nid: plan-a\nstatus: active\n---\n")
    legacy_now = working / "plan-now" / "plan-a.txt"
    legacy_now.parent.mkdir(parents=True)
    legacy_now.write_text("waiting: review\n")

    assert watch._waiting_is_live(working, plans_dir, plan, now=1000, threshold=60)


def test_once_json_outputs_plan_snapshots_and_events(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        watch,
        "collect_watch",
        lambda *args, **kwargs: [
            {
                "id": "plan-a",
                "state": "active",
                "newest_activity": 1_800_000_000,
                "owner": "codex:agent-7",
                "model": "gpt-6-luna",
                "worktree": str(tmp_path),
                "last_event_at": "2027-01-15T08:00:00+00:00",
                "detail": "working",
            }
        ],
    )
    args = Namespace(
        working=tmp_path,
        repo=tmp_path,
        once=True,
        no_inbox=True,
        no_wake=True,
        stale=1200,
        notes=None,
        json=True,
        interval=60,
    )

    assert watch.run_watch(args, clock=lambda: 1_800_000_001) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plans"][0]["model"] == "gpt-6-luna"
    assert payload["plans"][0]["worktree"] == str(tmp_path)
    assert isinstance(payload["events"], list)
