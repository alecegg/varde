from __future__ import annotations

import os
import subprocess
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.index.paths import repo_db_path
from varde_code.query.mapping import detect_changes, hotspots


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> None:
    subprocess.run(  # noqa: S603 - Test invokes Git with a controlled argument list.
        ["git", "-C", str(root), *args],  # noqa: S607 - Git is resolved from PATH for portability.
        check=True,
        env=env,
        capture_output=True,
        text=True,
    )


def _replay_history(root: Path) -> None:
    _git(root, "init", "--quiet", "--initial-branch=main")
    env = os.environ.copy()
    env.update(
        {
            "GIT_AUTHOR_NAME": "Varde Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
            "GIT_COMMITTER_NAME": "Varde Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        }
    )
    for message, timestamp in (
        ("fixture baseline", "2020-01-02T03:04:05+00:00"),
        ("fixture change", "2020-01-03T03:04:05+00:00"),
    ):
        env["GIT_AUTHOR_DATE"] = timestamp
        env["GIT_COMMITTER_DATE"] = timestamp
        _git(root, "add", "README.md", "src/main.py", env=env)
        _git(root, "commit", "-m", message, env=env)
        if message == "fixture baseline":
            (root / "src/main.py").write_text(
                (
                    "def answer():\n    return 42\n\n\n"
                    "def changed():\n    return answer()\n"
                ),
                encoding="utf-8",
            )


def test_git_modes_use_replayed_history_and_native_index(tmp_path: Path) -> None:
    repo = tmp_path / "history"
    (repo / "src").mkdir(parents=True)
    (repo / "README.md").write_text("History fixture\n", encoding="utf-8")
    (repo / "src/main.py").write_text(
        "def answer():\n    return 42\n", encoding="utf-8"
    )
    _replay_history(repo)
    build(repo, CodeExtractionProvider())
    (repo / "src/main.py").write_text(
        (repo / "src/main.py").read_text(encoding="utf-8") + "\n# working change\n",
        encoding="utf-8",
    )
    query = {"repoRoot": str(repo), "dbPath": str(repo_db_path(repo))}

    changes = detect_changes(query)
    ranked = hotspots(query)

    assert len(changes) == 1
    assert changes[0]["file"] == "src/main.py"
    assert changes[0]["status"] == "M"
    assert isinstance(ranked, list)
    assert all({"file", "complexity", "churn", "score"} <= row.keys() for row in ranked)
