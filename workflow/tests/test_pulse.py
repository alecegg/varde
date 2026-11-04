from __future__ import annotations

import json
import subprocess

from varde_data.views.watch import WatchEvent
from varde_learn.knowledge import memory
from varde_workflow import cli
from varde_workflow.commands import pulse, watch
from varde_workflow.pulse_facts import fingerprint, is_idle
from varde_workflow.pulse_mail import unread_count


def _write_plan(working, plan_id, status="active", now="working now"):
    directory = working / "plans" / plan_id
    (directory / "tasks").mkdir(parents=True)
    (directory / "plan.md").write_text(
        f"---\ntype: plan\nid: {plan_id}\nstatus: {status}\n"
        "owner: orchestrator-1\n---\n"
    )
    (directory / "tasks" / "task-a.md").write_text(
        "---\ntype: task\nstatus: todo\n---\n"
    )
    (working / ".cache" / "plan-now").mkdir(parents=True, exist_ok=True)
    (working / ".cache" / "plan-now" / f"{plan_id}.txt").write_text(now + "\n")
    return directory


def _repo(path):
    _git(path, "init", "-q", str(path))
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "tracked").write_text("initial")
    _git(path, "add", "tracked")
    _git(path, "commit", "-qm", "initial")


def _git(root, *arguments):
    subprocess.run(  # noqa: S603 - Test invokes fixed Git operations.
        ["git", "-C", str(root), *arguments],  # noqa: S607 - Git is required by this test.
        check=True,
    )


def _setup(monkeypatch, tmp_path):
    working = tmp_path / "working"
    working.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _repo(repo)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: type(
            "Paths", (), {"working": type("Working", (), {"path": working})()}
        )(),
    )
    monkeypatch.chdir(repo)
    return working, repo


def test_fingerprint_is_stable_and_idle_requires_same_reported_plans():
    value = {"a": 1, "b": [2]}
    assert fingerprint(value) == fingerprint({"b": [2], "a": 1})
    assert is_idle({"a": "one"}, {"a": "one"})
    assert not is_idle({"a": "one"}, {})


def test_no_argument_reports_multiple_nonterminal_plans(monkeypatch, tmp_path, capsys):
    working, _ = _setup(monkeypatch, tmp_path)
    _write_plan(working, "one")
    _write_plan(working, "two")
    _write_plan(working, "done", "completed")

    assert cli.run(["plan", "pulse"]) == 0
    output = capsys.readouterr().out
    assert "one: active" in output
    assert "two: active" in output
    assert "done:" not in output


def test_no_argument_skips_unreadable_archived_plan(monkeypatch, tmp_path, capsys):
    working, _ = _setup(monkeypatch, tmp_path)
    _write_plan(working, "readable")
    unreadable = working / "plans" / "archive" / "bad" / "plan.md"
    unreadable.parent.mkdir(parents=True)
    unreadable.write_text("not a plan")

    assert cli.run(["plan", "pulse"]) == 0
    assert "readable: active" in capsys.readouterr().out


def test_second_unchanged_pulse_is_idle_one_liner(monkeypatch, tmp_path, capsys):
    working, _ = _setup(monkeypatch, tmp_path)
    _write_plan(working, "one")

    cli.run(["plan", "pulse"])
    capsys.readouterr()
    assert cli.run(["plan", "pulse"]) == 0
    assert capsys.readouterr().out == "pulse: idle (1 plans)\nmail: none\n"


def test_new_decision_file_breaks_idle(monkeypatch, tmp_path, capsys):
    working, _ = _setup(monkeypatch, tmp_path)
    plan = _write_plan(working, "one")
    cli.run(["plan", "pulse"])
    capsys.readouterr()
    notes = plan / "notes"
    notes.mkdir()
    (notes / "decision-x.json").write_text("{}")

    cli.run(["plan", "pulse"])
    output = capsys.readouterr().out
    assert "decision-x.json" in output
    assert "pulse: idle" not in output

    assert cli.run(["plan", "pulse"]) == 0
    assert capsys.readouterr().out == "pulse: idle (1 plans)\nmail: none\n"


def test_single_plan_pulse_preserves_other_plan_fingerprints(
    monkeypatch, tmp_path, capsys
):
    working, _ = _setup(monkeypatch, tmp_path)
    first = _write_plan(working, "one")
    _write_plan(working, "two")
    cli.run(["plan", "pulse"])
    capsys.readouterr()
    (first / "notes").mkdir()
    (first / "notes" / "decision-x.json").write_text("{}")

    assert cli.run(["plan", "pulse", "one"]) == 0
    capsys.readouterr()
    assert cli.run(["plan", "pulse"]) == 0
    output = capsys.readouterr().out
    assert output.splitlines() == ["pulse: idle (2 plans)", "mail: none"]


def test_mail_peek_does_not_advance_cursor(monkeypatch, tmp_path):
    working, _ = _setup(monkeypatch, tmp_path)
    _write_plan(working, "one")
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "messages.jsonl").write_text(
        '{"id":"m-12345678","to":"orchestrator-1","from":"main","kind":"info","text":"x","ts":"2026-10-23T10:00:00Z"}\n'
    )
    index = inbox / "index" / "orchestrator-1.json"
    index.parent.mkdir()
    index.write_text('{"watermark":0}\n')
    before = index.read_bytes()

    assert unread_count(inbox, "orchestrator-1") == 1
    assert index.read_bytes() == before


def test_json_keeps_every_watch_event_for_a_plan(monkeypatch, tmp_path, capsys):
    working, _repo_path = _setup(monkeypatch, tmp_path)
    _write_plan(working, "one")
    snapshot = [
        {
            "id": "one",
            "status": "active",
            "owner": "orchestrator-1",
            "assigned_to": "orchestrator-1",
            "now_line": "working now",
            "done": 0,
            "total": 1,
            "blocked_tasks": [],
            "worktree": None,
        }
    ]
    monkeypatch.setattr(watch, "scan", lambda *_args, **_kwargs: snapshot)
    monkeypatch.setattr(
        watch,
        "frame_events",
        lambda *_args, **_kwargs: (
            [
                WatchEvent("blocked", "one", "task-a"),
                WatchEvent("needs-decision", "one", "question"),
            ],
            None,
        ),
    )

    assert pulse.run(type("Args", (), {"plan": None, "json": True})()) == 0
    value = json.loads(capsys.readouterr().out)
    assert [event["kind"] for event in value["plans"][0]["events"]] == [
        "blocked",
        "needs-decision",
    ]


def test_json_contains_plan_facts(monkeypatch, tmp_path, capsys):
    working, _ = _setup(monkeypatch, tmp_path)
    _write_plan(working, "one")

    assert cli.run(["plan", "pulse", "--json"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["idle"] is False
    assert value["plans"][0]["id"] == "one"
    assert value["plans"][0]["tasks"] == {"blocked": 0, "done": 0, "open": 1}


def test_unknown_plan_returns_unreadable_plan_code(monkeypatch, tmp_path, capsys):
    _setup(monkeypatch, tmp_path)

    assert cli.run(["plan", "pulse", "unknown"]) == 70
    assert "unknown plan" in capsys.readouterr().err


def test_help_is_available(capsys):
    assert cli.run(["plan", "pulse", "--help"]) == 0
    assert "Usage: varde plan pulse" in capsys.readouterr().out
