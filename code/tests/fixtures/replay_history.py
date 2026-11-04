"""Replay the deterministic two-commit history used by change and hotspot tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent / "repos" / "history"
AUTHORS = {
    "GIT_AUTHOR_NAME": "Varde Fixture",
    "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
    "GIT_COMMITTER_NAME": "Varde Fixture",
    "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
}


def git(*args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(["git", "-C", str(REPO), *args], check=True, env=env)


def commit(message: str, timestamp: str) -> None:
    env = os.environ.copy()
    env.update(AUTHORS)
    env["GIT_AUTHOR_DATE"] = timestamp
    env["GIT_COMMITTER_DATE"] = timestamp
    git("add", "README.md", "src/main.py", env=env)
    git("commit", "-m", message, env=env)


def main() -> None:
    if (REPO / ".git").exists():
        raise SystemExit(f"refusing to overwrite existing history: {REPO / '.git'}")
    git("init", "--quiet", "--initial-branch=main")
    commit("fixture baseline", "2020-01-02T03:04:05+00:00")
    (REPO / "src/main.py").write_text(
        "def answer():\n    return 42\n\n\ndef changed():\n    return answer()\n",
        encoding="utf-8",
    )
    commit("fixture change", "2020-01-03T03:04:05+00:00")


if __name__ == "__main__":
    main()
