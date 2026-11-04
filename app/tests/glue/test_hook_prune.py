"""End-to-end pre_tool_use prune decisions with the runner off and on."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from varde.glue import hook


def _repo_with_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    git = ["git", "-C", str(main)]
    for command in (
        ["git", "init", str(main)],
        [*git, "config", "user.name", "Test"],
        [*git, "config", "user.email", "test@example.com"],
        [*git, "commit", "--allow-empty", "-m", "init"],
        [*git, "worktree", "add", "-b", "task", str(worktree)],
    ):
        subprocess.run(command, check=True, capture_output=True)  # noqa: S603
    return main, worktree


def _decision(capsys, **fields) -> str:
    hook.pre_tool_use(
        "claude",
        json.dumps(
            {
                "session_id": "s",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune"},
                **fields,
            }
        ),
    )
    out = capsys.readouterr().out
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


@pytest.fixture(autouse=True)
def _no_firing_records(monkeypatch) -> None:
    monkeypatch.setattr("varde.glue.hook_record.record_firing", lambda *a, **k: None)


def _no_mailbox(monkeypatch) -> None:
    def unexpected(*args):
        pytest.fail("runner off must not consult the mailbox")

    monkeypatch.setattr("varde.glue.inbox_hook.resolve_address", unexpected)


def test_runner_off_allows_primary_checkout(tmp_path, monkeypatch, capsys) -> None:
    main, _ = _repo_with_linked_worktree(tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    _no_mailbox(monkeypatch)
    assert _decision(capsys, cwd=str(main)) == "allow"


def test_runner_off_denies_linked_worktree(tmp_path, monkeypatch, capsys) -> None:
    _, worktree = _repo_with_linked_worktree(tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    _no_mailbox(monkeypatch)
    assert _decision(capsys, cwd=str(worktree)) == "deny"


def test_runner_off_denies_agent_id_in_primary(tmp_path, monkeypatch, capsys) -> None:
    main, _ = _repo_with_linked_worktree(tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    _no_mailbox(monkeypatch)
    assert _decision(capsys, cwd=str(main), agent_id="sub-1") == "deny"


@pytest.mark.parametrize("cwd", [None, 5])
def test_runner_off_denies_missing_or_bad_cwd(monkeypatch, capsys, cwd) -> None:
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    _no_mailbox(monkeypatch)
    fields = {} if cwd is None else {"cwd": cwd}
    assert _decision(capsys, **fields) == "deny"


def test_runner_off_denies_when_git_dir_set(tmp_path, monkeypatch, capsys) -> None:
    main, _ = _repo_with_linked_worktree(tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    monkeypatch.setenv("GIT_DIR", str(main / ".git"))
    _no_mailbox(monkeypatch)
    assert _decision(capsys, cwd=str(main)) == "deny"


def test_runner_on_uses_mailbox(tmp_path, monkeypatch, capsys) -> None:
    _, worktree = _repo_with_linked_worktree(tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address", lambda harness, sid: "main"
    )
    assert _decision(capsys, cwd=str(worktree)) == "allow"
    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address", lambda harness, sid: "worker"
    )
    assert _decision(capsys, cwd=str(worktree)) == "deny"
