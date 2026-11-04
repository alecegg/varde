from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_learn.knowledge import memory
from varde_workflow import cli
from varde_workflow.module import register

HELP_DIR = Path(__file__).parents[1] / "src" / "varde_workflow" / "help"


def _use_working(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    return working


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _init_repo(root: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    return root


def _plan_with_task(root: Path) -> Path:
    plan = root / "plans" / "sample"
    (plan / "tasks").mkdir(parents=True)
    (root / "src").mkdir(exist_ok=True)
    (root / "src" / "alpha.py").touch()
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n# Sample\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    (plan / "tasks" / "alpha.md").write_text(
        "---\ntype: task\nstatus: todo\ndepends_on: []\n"
        "owns: [src/alpha.py]\n---\n# Alpha\n",
        encoding="utf-8",
    )
    return plan


@pytest.mark.parametrize(
    "snapshot",
    sorted(
        path for path in HELP_DIR.glob("*.txt") if not path.name.endswith(".short.txt")
    ),
    ids=lambda path: path.stem,
)
def test_module_help_matches_every_committed_snapshot(snapshot: Path) -> None:
    route = snapshot.stem.replace("_", " ")

    assert register().help(route) == snapshot.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "snapshot",
    sorted(HELP_DIR.glob("*.short.txt")),
    ids=lambda path: path.stem,
)
def test_short_help_matches_committed_snapshot(
    snapshot: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    route = snapshot.name.removesuffix(".short.txt").replace("_", " ")

    assert cli.run([*route.split(), "-h"]) == 0
    assert capsys.readouterr().out == snapshot.read_text(encoding="utf-8")


def test_plan_gate_help_is_registered(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.run(["plan", "gate", "--help"]) == 0
    assert "Usage: varde plan gate <TASK> [--commit <SHA>]" in capsys.readouterr().out


def test_plan_handoff_check_is_registered_and_uses_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    handoff = tmp_path / "handoff.md"
    handoff.write_text(
        "Summary: Continue\nGoal:\nFinish work.\nContext:\nCurrent branch.\n"
        "State:\n- Ready.\nNext:\n1. Review.\nOpen:\n- None.\n"
        "Reading list:\n- README.md\nPointers:\n- mem-1\nDo not redo:\n- Setup.\n",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("read me", encoding="utf-8")

    assert (
        cli.run(["plan", "handoff-check", str(handoff), "--root", str(tmp_path)]) == 0
    )
    assert capsys.readouterr().out == "Handoff format is valid.\n"


def test_plan_handoff_check_help_is_registered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.run(["plan", "handoff-check", "--help"]) == 0
    assert "Usage: varde plan handoff-check [OPTIONS] <FILE>" in capsys.readouterr().out


def test_plan_check_task_ownership_reports_stray_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _init_repo(tmp_path / "repo")
    task = root / "tasks" / "task.md"
    task.parent.mkdir()
    task.write_text("---\ntype: task\nstatus: todo\nowns: [src/owned.py]\n---\n")
    (root / "src").mkdir()
    (root / "src" / "owned.py").write_text("ok")
    (root / "stray.py").write_text("stray")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "initial")
    (root / "src" / "owned.py").write_text("changed")
    (root / "stray.py").write_text("changed")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "change")

    assert (
        cli.run(
            [
                "plan",
                "check-task-ownership",
                "--task",
                str(task),
                "--commit",
                "HEAD",
                "--repo-root",
                str(root),
            ]
        )
        == 2
    )
    assert capsys.readouterr().err == (
        "error: task ownership found stray paths: stray.py\n"
        "Fix: add each stray path to the task's `owns:` or the plan's `shared:`, "
        "then rerun check-task-ownership\n"
    )


def test_plan_execution_wave_json_lists_next_wave(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _init_repo(tmp_path / "repo")
    plan = _plan_with_task(root)
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "plan")

    assert (
        cli.run(
            [
                "plan",
                "execution-wave",
                str(plan),
                "--repo-root",
                str(root),
                "--max-workers",
                "2",
                "--json",
            ]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert output.startswith('{"data":')
    assert json.loads(output)["data"]["next_wave"] == ["alpha"]


def test_plan_readiness_json_reports_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "plan.md"
    path.write_text("---\ntype: plan\nstatus: active\n---\n", encoding="utf-8")

    assert cli.run(["plan", "readiness", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["ready"] is True


def test_plan_status_json_lists_plan_progress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    working = _use_working(monkeypatch, tmp_path)
    root = _init_repo(working)
    _plan_with_task(root)

    assert cli.run(["plan", "status", "--json", "--repo", str(root)]) == 0
    report = json.loads(capsys.readouterr().out)["data"]
    assert [(item["id"], item["done"], item["total"]) for item in report["plans"]] == [
        ("sample", 0, 1)
    ]
    assert report["plans"][0]["now"] == "next: alpha"


def test_plan_now_writes_and_clears_progress_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    working = _use_working(monkeypatch, tmp_path)
    _plan_with_task(_init_repo(working))

    assert cli.run(["plan", "now", "sample", "building", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] == {
        "now": "building",
        "plan": "sample",
    }
    assert cli.run(["plan", "status", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)["data"]
    assert report["plans"][0]["now"] == "building"

    assert cli.run(["plan", "now", "sample", "--clear", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] == {
        "cleared": True,
        "plan": "sample",
    }


def test_plan_owner_sets_and_clears_frontmatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    working = _use_working(monkeypatch, tmp_path)
    plan = _plan_with_task(_init_repo(working))

    path = plan / "plan.md"
    assert cli.run(["plan", "owner", str(path), "claude:one"]) == 0
    assert capsys.readouterr().out == f"Set owner for {path.resolve()}.\n"
    assert "owner: claude:one" in path.read_text(encoding="utf-8")

    assert cli.run(["plan", "owner", str(path), "--clear"]) == 0
    assert capsys.readouterr().out == f"Cleared owner for {path.resolve()}.\n"
    assert "owner:" not in (plan / "plan.md").read_text(encoding="utf-8")


def test_plan_watch_once_writes_the_session_notes_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = _use_working(monkeypatch, tmp_path)
    root = _init_repo(working)
    _plan_with_task(root)
    notes = tmp_path / "session.md"

    assert (
        cli.run(
            [
                "plan",
                "watch",
                "--once",
                "--no-inbox",
                "--no-wake",
                "--stale",
                "20m",
                "--repo",
                str(root),
                "--notes",
                str(notes),
            ]
        )
        == 0
    )
    assert "sample [active] 0/1" in notes.read_text(encoding="utf-8")


def test_plan_conclude_completes_the_reviewed_plan(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _init_repo(tmp_path / "repo")
    plan = root / "plans" / "sample"
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "review")
    reviewed = _git(root, "rev-parse", "HEAD")
    _git(root, "commit", "--allow-empty", "-qm", "merge")
    (plan / "review.md").write_text(
        f"---\nverdict: approved\nhead: {reviewed}\n---\n", encoding="utf-8"
    )

    assert (
        cli.run(
            [
                "plan",
                "conclude",
                str(plan),
                "--merged",
                reviewed,
                "--repo",
                str(root),
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "concluded sample\n"
    assert "status: completed" in (plan / "plan.md").read_text(encoding="utf-8")


def test_plan_distill_prints_the_draft_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _use_working(monkeypatch, tmp_path)
    plan = tmp_path / "plan"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: completed\n---\n# Example\n\n"
        "## Problem\nNeed it.\n\n## Solution\nDo it.\n",
        encoding="utf-8",
    )
    (plan / "tasks" / "one.md").write_text("---\nstatus: done\n---\n# Task\n")

    assert cli.run(["plan", "distill", str(plan)]) == 0
    output = capsys.readouterr().out
    assert output.startswith("# Example\n\nStatus: completed\n")
    assert "- Task (done)" in output


def test_plan_graph_json_lists_dependency_edges(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parent = tmp_path / "plans" / "parent"
    dependency = tmp_path / "plans" / "dependency"
    parent.mkdir(parents=True)
    dependency.mkdir()
    (parent / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\ndepends_on: [dependency]\n---\n"
    )
    (dependency / "plan.md").write_text("---\ntype: plan\nstatus: completed\n---\n")

    assert cli.run(["plan", "graph", str(parent / "plan.md"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["edges"] == [
        {"from": "parent", "to": "dependency", "relationship": "depends_on"}
    ]


def test_msg_send_then_read_json_includes_message_id(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "x")
    assert (
        cli.run(
            [
                "msg",
                "send",
                "--from",
                "sender",
                "--to",
                "x",
                "--kind",
                "info",
                "hello",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == ""
    assert cli.run(["msg", "read", "--as", "x", "--json"]) == 0
    read = capsys.readouterr()
    output = read.out
    assert '"id":"m-' in output
    assert '"text":"hello"' in output
    assert cli.run(["msg", "read", "--as", "x", "--all", "--json"]) == 0
    assert '"text":"hello"' in capsys.readouterr().out


def test_msg_read_json_prints_sorted_cli_envelope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)
    from varde_workflow.commands.msg import append_message

    append_message("worker", "main", "info", "ready", working=tmp_path)

    assert cli.run(["msg", "read", "--json"]) == 0
    output = capsys.readouterr().out
    assert output.endswith("\n")
    envelope = json.loads(output)
    assert list(envelope) == [
        "data",
        "envelope_version",
        "meta",
        "ok",
        "outcome",
        "schema_version",
    ]
    assert envelope["data"]["messages"][0]["text"] == "ready"


def test_msg_send_invalid_kind_uses_cli_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    (tmp_path / ".cache" / "inbox").mkdir(parents=True)

    assert (
        cli.run(
            [
                "msg",
                "send",
                "--from",
                "agent",
                "--to",
                "main",
                "--kind",
                "invalid",
                "hello",
            ]
        )
        == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == (
        "Error: unknown message kind `invalid`; allowed kinds are blocked, "
        "needs-user, done, info, info-failure, stale, merge-ready\n"
    )


def test_msg_send_from_nested_cwd_uses_resolved_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    working = tmp_path / "working"
    nested = tmp_path / "repo" / "workflow" / "src"
    nested.mkdir(parents=True)
    _init_repo(tmp_path / "repo")
    monkeypatch.chdir(nested)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    from varde_workflow.slots import add_alias

    add_alias(working, "b")
    assert (
        cli.run(["msg", "send", "--from", "a", "--to", "b", "--kind", "info", "hello"])
        == 0
    )
    capsys.readouterr()
    assert (working / ".cache" / "inbox" / "messages.jsonl").exists()
    assert not (nested / "memory-bank" / "working" / ".cache" / "inbox").exists()


def test_msg_read_from_nested_cwd_does_not_create_local_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    repo = tmp_path / "repo"
    nested = repo / "workflow" / "src"
    nested.mkdir(parents=True)
    _init_repo(repo)
    working = tmp_path / "working"
    monkeypatch.chdir(nested)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    assert cli.run(["msg", "read", "--as", "b"]) == 0
    capsys.readouterr()
    assert not (nested / "memory-bank").exists()


def test_msg_send_without_project_refuses_cwd_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    monkeypatch.setattr(memory, "find_root", lambda _path, **_options: None)
    assert (
        cli.run(["msg", "send", "--from", "a", "--to", "b", "--kind", "info", "hello"])
        == 2
    )
    error = capsys.readouterr().err
    assert "fell back to cwd" in error
    assert "no repo root or config was found" in error
    assert "VARDE_WORKING_DIR" in error
    assert "varde setup paths set" in error
    assert not (working / ".cache" / "inbox").exists()


def test_msg_send_in_fresh_repo_creates_configured_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    repo = _init_repo(tmp_path / "repo")
    working = tmp_path / "configured-working"
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    from varde_workflow.slots import add_alias

    add_alias(working, "b")
    assert (
        cli.run(["msg", "send", "--from", "a", "--to", "b", "--kind", "info", "hello"])
        == 0
    )
    capsys.readouterr()
    assert (working / ".cache" / "inbox" / "messages.jsonl").exists()


def test_address_list_outputs_store_path_and_json_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    working = _use_working(monkeypatch, tmp_path)
    assert cli.run(["msg", "address", "list"]) == 0
    assert capsys.readouterr().out == f"store: {working / '.cache' / 'inbox'}\n"
    assert cli.run(["msg", "address", "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["store"] == str(
        working / ".cache" / "inbox"
    )


def test_msg_status_warns_about_stray_stores(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    repo = tmp_path / "repo"
    _init_repo(repo)
    (repo / "memory-bank" / "working" / ".cache" / "inbox").mkdir(parents=True)
    stray = repo / "runner" / "memory-bank" / "working" / ".cache" / "inbox"
    stray.mkdir(parents=True)
    (stray / "messages.jsonl").write_text(
        json.dumps({"id": "m-stray", "to": "main", "text": "recover"}) + "\n"
    )
    empty = repo / "empty" / "memory-bank" / "working" / ".cache" / "inbox"
    empty.mkdir(parents=True)
    excluded = [
        repo / ".venv" / ".cache" / "inbox",
        repo / "node_modules" / ".cache" / "inbox",
        repo / "__pycache__" / ".cache" / "inbox",
        repo / ".varde" / "worktrees" / "other" / ".cache" / "inbox",
    ]
    for path in excluded:
        path.mkdir(parents=True)
    working = repo / "memory-bank" / "working"
    monkeypatch.chdir(repo)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )
    assert cli.run(["msg", "status"]) in (0, 1)
    warnings = capsys.readouterr().err
    assert str(stray) in warnings
    assert str(empty) not in warnings
    assert all(str(path) not in warnings for path in excluded)


def test_msg_migrate_replays_urgent_messages_to_main(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=tmp_path)),
    )
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    (inbox / "messages.jsonl").write_text(
        json.dumps(
            {
                "ts": "2026-10-17T11:00:00+00:00",
                "from": "worker",
                "to": "old",
                "kind": "needs-user",
                "text": "urgent",
                "id": "m-12345678",
            }
        )
        + "\n"
    )

    assert cli.run(["msg", "migrate"]) == 0
    assert capsys.readouterr().out == ""
    assert cli.run(["msg", "read", "--all", "--json"]) == 0
    assert (
        json.loads(capsys.readouterr().out)["data"]["messages"][-1]["text"] == "urgent"
    )


def test_msg_migrate_strays_cli_dry_run_and_apply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    repo = tmp_path / "repo"
    repo.mkdir()
    working = repo / "memory-bank" / "working"
    stray = repo / "nested" / "memory-bank" / "working" / ".cache" / "inbox"
    stray.mkdir(parents=True)
    (stray / "messages.jsonl").write_text(
        json.dumps({"id": "m-stray", "text": "recover", "to": "main"}) + "\n"
    )
    monkeypatch.chdir(repo)
    monkeypatch.setattr(memory, "find_root", lambda *_args, **_kwargs: repo)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )

    assert cli.run(["msg", "migrate", "--strays"]) == 0
    assert "Would merge 1 message from 1 stray store." in capsys.readouterr().out
    assert not (working / ".cache" / "inbox" / "messages.jsonl").exists()
    assert cli.run(["msg", "migrate", "--strays", "--apply"]) == 0
    assert "Merged 1 message from 1 stray store." in capsys.readouterr().out
    assert (
        json.loads(
            (working / ".cache" / "inbox" / "messages.jsonl")
            .read_text()
            .splitlines()[0]
        )["id"]
        == "m-stray"
    )


def test_msg_migrate_apply_requires_strays(capsys) -> None:
    assert cli.run(["msg", "migrate", "--apply"]) == 2
    assert "error: --apply requires --strays" in capsys.readouterr().err


def test_msg_migrate_keeps_stray_with_extra_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    from varde_learn.knowledge import memory

    repo = tmp_path / "repo"
    repo.mkdir()
    working = repo / "memory-bank" / "working"
    stray = repo / "nested" / "memory-bank" / "working" / ".cache" / "inbox"
    stray.mkdir(parents=True)
    (stray / "messages.jsonl").write_text(
        json.dumps({"id": "m-stray", "text": "recover", "to": "main"}) + "\n"
    )
    extra = stray / "cursors.json"
    extra.write_text("{}")
    monkeypatch.chdir(repo)
    monkeypatch.setattr(memory, "find_root", lambda *_args, **_kwargs: repo)
    monkeypatch.setattr(
        memory.MemoryPaths,
        "resolve",
        lambda _path: SimpleNamespace(working=SimpleNamespace(path=working)),
    )

    assert cli.run(["msg", "migrate", "--strays", "--apply"]) == 0
    assert f"Kept stray store: {stray}" in capsys.readouterr().out
    assert extra.read_text() == "{}"


def test_setup_instructions_install_dry_run_prints_block_without_writing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    assert (
        cli.run(
            ["setup", "instructions", "install", "--target", "AGENTS.md", "--dry-run"]
        )
        == 0
    )
    output = capsys.readouterr().out
    assert output.startswith(
        f"would write the Varde instruction block to {tmp_path / 'AGENTS.md'}:"
    )
    assert "## varde-toz (tool-output-zone)" in output
    assert not (tmp_path / "AGENTS.md").exists()


def test_setup_instructions_install_then_targets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)

    assert cli.run(["setup", "instructions", "install", "--target", "AGENTS.md"]) == 0
    assert "<!-- varde:start -->" in (tmp_path / "AGENTS.md").read_text(
        encoding="utf-8"
    )
    assert cli.run(["setup", "instructions", "targets"]) == 0
    assert capsys.readouterr().out == f"{tmp_path / 'AGENTS.md'}\n"


def test_setup_instructions_remove_dry_run_keeps_the_block(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    assert cli.run(["setup", "instructions", "install", "--target", "AGENTS.md"]) == 0
    installed = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")

    assert cli.run(["setup", "instructions", "remove", "--dry-run"]) == 0
    assert capsys.readouterr().out == (
        f"would remove the Varde instruction block from {tmp_path / 'AGENTS.md'}\n"
    )
    assert (tmp_path / "AGENTS.md").read_text(encoding="utf-8") == installed


def test_handoff_alias_prints_deprecation_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_workflow.commands import watch

    monkeypatch.setattr(watch, "run_watch", lambda _args: 0)

    assert cli.run(["plan", "watch", "--handoff", "notes.md", "--once"]) == 0
    assert "--handoff is deprecated; use --notes" in capsys.readouterr().err


def test_watch_invalid_duration_matches_cli_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.run(["plan", "watch", "--stale", "zero"]) == 2
    assert capsys.readouterr().err == (
        "error: invalid value 'zero' for '--stale <DURATION>': value must be a "
        "positive duration such as 90s, 20m, or 1h\n\n"
        "For more information, try '--help'.\n"
    )


def test_graph_missing_artifact_uses_json_cli_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert (
        cli.run(["plan", "graph", str(tmp_path / "missing" / "plan.md"), "--json"]) == 1
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith('{"data":{"error":{"code":"internal","fix":')
    assert '"message":"failed to read workflow artifact ' in captured.err


def test_validate_text_output_matches_varde_format(capsys, tmp_path: Path) -> None:
    path = tmp_path / "plan.md"
    path.write_text(
        "---\ntype: plan\nstatus: active\nlabel: Clean Plan Validation\n"
        "group: Tests\n---\n"
        "## Acceptance criteria\n"
        "- valid\n",
        encoding="utf-8",
    )
    assert cli.run(["plan", "validate", str(path)]) == 0
    assert capsys.readouterr().out == f"valid: {path}\n"


def test_error_report_uses_rust_prefix_and_fix_line(capsys) -> None:
    from varde_workflow.errors import report_error
    from varde_workflow.task_ownership import OwnershipError

    assert report_error(OwnershipError("git_error", "missing commit"), False) == 1
    assert capsys.readouterr().err == (
        "Error: missing commit\n"
        "Fix: Repair Git input or restore the unavailable object described in "
        "the error.\n"
    )


def test_execution_wave_zero_workers_uses_invalid_input_envelope(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    plan = tmp_path / "plan"
    (plan / "tasks").mkdir(parents=True)
    assert (
        cli.run(
            [
                "plan",
                "execution-wave",
                str(plan),
                "--repo-root",
                str(tmp_path),
                "--max-workers",
                "0",
                "--json",
            ]
        )
        == 1
    )
    output = capsys.readouterr().err
    assert '"code":"invalid_input"' in output
    assert '"outcome":"tool-error"' in output


def test_short_help_is_distinct_from_long_help(capsys) -> None:
    assert cli.run(["plan", "validate", "-h"]) == 0
    short = capsys.readouterr().out
    assert "Validate one workflow artifact without mutation" in short
    assert "Arguments:" in short
    assert cli.run(["plan", "validate", "--help"]) == 0
    assert short != capsys.readouterr().out
