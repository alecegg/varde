# ruff: noqa: S603, S607
"""Scoped memory writes only under the data dir, not the repo or Claude dirs."""

from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import pytest
from varde_learn.loop import cli_memory, cli_memory_migrate, cli_memory_surface

GIT_USER = "[user]\n\tname = Alice\n\temail = a@example.invalid\n"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def tree(root: Path) -> set[str]:
    return (
        {str(p.relative_to(root)) for p in root.rglob("*")} if root.exists() else set()
    )


def git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".gitconfig").write_text(GIT_USER)
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "main", str(repo))
    bare = tmp_path / "remote.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    seed = tmp_path / "seed"
    git("clone", "-q", str(bare), str(seed))
    (seed / "README.md").write_text("shared\n")
    git("-C", str(seed), "add", "-A")
    git("-C", str(seed), "commit", "-qm", "init")
    git("-C", str(seed), "push", "-q", "origin", "main")
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "config.toml").write_text(f'[memory]\nshared = "{bare}"\n')
    learn = tmp_path / "learn"
    learn.mkdir()
    (learn / "memory-decisions.jsonl").write_text("")
    for name in ("VARDE_MEMORY_DIR", "XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(cfg))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_LEARN_STORE", str(learn))
    monkeypatch.chdir(repo)
    return repo, home


def test_memory_commands_write_nothing_in_repo_or_claude_projects(sandbox) -> None:
    repo, home = sandbox
    claude_projects = home / ".claude" / "projects"
    before = (tree(repo), tree(claude_projects))

    out = Io()
    assert (
        cli_memory.run(
            ["memory", "add", "--scope", "global", "--text", "a lesson", "--json"], out
        )
        == 0
    ), out.stderr.getvalue()
    entry_id = json.loads(out.stdout.getvalue())["data"]["id"]
    assert cli_memory_surface.run(["surface", "--json"], Io()) == 0
    assert cli_memory.run(["memory", "pull"], Io()) == 0
    out = Io()
    assert cli_memory.run(["memory", "promote", entry_id], out) == 0, (
        out.stderr.getvalue()
    )
    assert cli_memory_migrate.run(["migrate", "--json"], Io()) == 0

    assert (tree(repo), tree(claude_projects)) == before
    written = tree(Path(home).parent / "share")
    assert any(path.endswith(".md") for path in written)
