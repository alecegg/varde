from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - Runs git with controlled arguments in a temporary repo.
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit_all(root: Path, message: str) -> str:
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Path:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    root = tmp_path / "repo"
    (root / "src" / "x").mkdir(parents=True)
    (root / "src" / "x" / "mod.py").write_text("def f():\n    return 1\n")
    (root / "src" / "y.py").write_text(
        "from src.x import mod\n\n\ndef g():\n    return mod.f()\n"
    )
    git(root, "init", "-q", "-b", "main")
    commit_all(root, "init")
    return root
