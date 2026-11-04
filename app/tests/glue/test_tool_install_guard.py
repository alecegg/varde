from __future__ import annotations

import subprocess

import pytest
from varde.glue.tool_install_guard import deny_worktree_tool_install


def linked_repos(tmp_path):
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    subprocess.run(["git", "init", str(main)], check=True, capture_output=True)  # noqa: S603, S607 - creates local test repository
    subprocess.run(  # noqa: S603 - configures local test repository
        ["git", "-C", str(main), "config", "user.name", "Test"],  # noqa: S607 - fixed Git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - configures local test repository
        ["git", "-C", str(main), "config", "user.email", "test@example.com"],  # noqa: S607 - fixed Git command
        check=True,
        capture_output=True,
    )
    (main / "app").mkdir()
    (main / "app" / "source.py").write_text("pass\n")
    subprocess.run(  # noqa: S603 - stages local test fixture
        ["git", "-C", str(main), "add", "app/source.py"],  # noqa: S607 - fixed Git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - commits local test fixture
        ["git", "-C", str(main), "commit", "-m", "init"],  # noqa: S607 - fixed Git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - creates local test worktree
        ["git", "-C", str(main), "worktree", "add", "-b", "task", str(worktree)],  # noqa: S607 - fixed Git command
        check=True,
        capture_output=True,
    )
    return main, worktree


@pytest.mark.parametrize(
    "command",
    [
        "uv tool install --force --from ./app varde",
        "uv --quiet tool install varde",
        "uv --directory . tool install varde",
        "uv tool --quiet install varde",
        "uv --directory . --quiet tool --config config.toml install varde",
        "env uv tool install varde",
        "sudo uv tool install varde",
        "sudo -u alec uv tool install varde",
        "command uv tool install varde",
        "command -- uv tool install varde",
        "time uv tool install varde",
        "nohup uv tool install varde &",
        "xargs uv tool install varde",
        "VAR=value uv tool install varde",
        "echo hi\nuv tool install varde",
        "if true; then uv tool install varde; fi",
        "{ uv tool install varde; }",
        "! uv tool install varde",
        "bash -c 'uv tool install varde'",
        'bash -lc "uv tool install varde"',
        "bash -ic 'uv tool install varde'",
        "bash -xc 'uv tool install varde'",
        "bash -x -c 'uv tool install varde'",
        "bash -o pipefail -c 'uv tool install varde'",
        "bash -O extglob -c 'uv tool install varde'",
        "bash -c -x 'uv tool install varde'",
        "exec uv tool install varde",
        "exec -a name uv tool install varde",
        "exec bash -c 'uv tool install varde'",
        'exec sh -c "uv tool install varde"',
        "bash -c \"bash -c 'uv tool install varde'\"",
        'eval "uv tool install varde"',
        "sudo bash -lc 'uv tool install varde'",
        "sh -c 'uv tool install varde'",
        "zsh -c 'uv tool install varde'",
    ],
)
def test_pre_tool_use_denies_wrapped_uv_tool_mutation(tmp_path, command):
    _, worktree = linked_repos(tmp_path)
    assert deny_worktree_tool_install(command, str(worktree))


def test_pre_tool_use_allows_quoted_echo_and_non_mutations(tmp_path):
    _, worktree = linked_repos(tmp_path)
    for command in (
        "echo 'uv tool install varde'",
        "bash -lc 'echo uv tool install varde'",
        "bash -lc 'cd /tmp && echo hi'",
        "exec echo 'uv tool install varde'",
        "eval \"echo 'uv tool install varde'\"",
        "uv run pytest",
        "uv tool list",
    ):
        assert deny_worktree_tool_install(command, str(worktree)) is None
    assert deny_worktree_tool_install("uv tool install varde", str(tmp_path)) is None


def test_pre_tool_use_tracks_cd_and_checks_install_source_paths(tmp_path):
    main, worktree = linked_repos(tmp_path)
    assert (
        deny_worktree_tool_install(
            f"cd {main} && uv tool install --from ./app varde", str(worktree)
        )
        is None
    )
    assert deny_worktree_tool_install(
        f"cd {worktree} && uv tool install varde", str(main)
    )
    assert deny_worktree_tool_install(
        "cd ../worktree && uv tool install varde", str(main)
    )
    assert deny_worktree_tool_install(
        f"cd {worktree} && bash -lc 'uv tool install varde'", str(main)
    )
    for option in ("--from", "--directory", "--project"):
        assert deny_worktree_tool_install(
            f"uv tool install {option} {worktree / 'app'} varde", str(main)
        )
    assert deny_worktree_tool_install(
        f"uv --directory {worktree / 'app'} tool install varde", str(main)
    )


def test_pre_tool_use_expands_tilde_for_cd(tmp_path, monkeypatch):
    main, worktree = linked_repos(tmp_path)
    monkeypatch.setenv("HOME", str(worktree))
    assert deny_worktree_tool_install("cd ~ && uv tool install varde", str(main))


def test_pre_tool_use_fails_open_when_git_times_out(tmp_path, monkeypatch):
    from subprocess import TimeoutExpired

    monkeypatch.setattr(
        "varde.glue.tool_install_guard.subprocess.run",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutExpired("git", 2)),
    )
    assert deny_worktree_tool_install("uv tool install varde", str(tmp_path)) is None
