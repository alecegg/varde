# ruff: noqa: S603, S607
from __future__ import annotations

import asyncio
import os
import subprocess
from pathlib import Path

from varde_runner.workspaces_service import WorkspacesService

ROOT = Path(__file__).parents[2]
CREATE = (
    ROOT
    / "workflow/src/varde_workflow/skills/varde-orchestrate/scripts/worktree-create.sh"
)
CLEANUP = (
    ROOT
    / "workflow/src/varde_workflow/skills/varde-orchestrate/scripts/worktree-cleanup.sh"
)


def git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def make_repo(path):
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "file").write_text("initial")
    git(path, "add", "file")
    git(path, "commit", "-m", "initial")
    return path


def add_fake_varde(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    executable = bindir / "varde"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    return {**os.environ, "PATH": f"{bindir}:{os.environ.get('PATH', '')}"}


def test_script_created_worktree_is_removed_by_service(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    result = subprocess.run(
        ["bash", str(CREATE), "script-made"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    values = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert values["path"] == str(repo / ".varde/worktrees/script-made")
    assert values["branch"] == "worktree/script-made"

    async def scenario():
        service = WorkspacesService([repo], env=add_fake_varde(tmp_path))

        async def no_watcher(path, env=None):
            return None

        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", no_watcher)
        removed = await service.remove(repo, "script-made", caller=repo)
        assert removed["removed"] is True

    asyncio.run(scenario())
    assert not (repo / ".varde/worktrees/script-made").exists()
    assert "worktree/script-made" not in git(
        repo, "branch", "--list", "worktree/script-made"
    )


def test_service_created_worktree_is_removed_by_cleanup_script(tmp_path):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        return await WorkspacesService([repo]).create(repo, "api-made", caller=repo)

    created = asyncio.run(scenario())
    result = subprocess.run(
        ["bash", str(CLEANUP), "api-made"],
        cwd=repo,
        env=add_fake_varde(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert created["path"] == str(repo / ".varde/worktrees/api-made")
    assert not Path(created["path"]).exists()
    assert "worktree/api-made" not in git(repo, "branch", "--list", "worktree/api-made")
