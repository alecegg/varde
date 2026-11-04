from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_code.index.certified import (
    CERTIFIED_COMPLEXITY_LANGUAGES,
    has_certified_complexity_profile,
)
from varde_code.index.churn import commit_count, commit_counts_batch


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = subprocess.run(  # noqa: S603 - Runs the git fixture command without a shell.
        ["git", *args],  # noqa: S607 - Uses the system git executable from PATH.
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _commit(repo: Path, name: str, content: str, when: datetime) -> None:
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", "--", name)
    timestamp = when.strftime("%Y-%m-%dT%H:%M:%S%z")
    env = os.environ | {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
        "GIT_AUTHOR_DATE": timestamp,
        "GIT_COMMITTER_DATE": timestamp,
    }
    _git(repo, "commit", "-m", "update", env=env)


def test_churn_counts_recent_commits_and_handles_missing_paths(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    now = datetime.now(UTC)
    _commit(repo, "src/main.py", "old\n", now - timedelta(days=100))
    _commit(repo, "src/main.py", "one\n", now - timedelta(days=2))
    _commit(repo, "src/main.py", "two\n", now - timedelta(days=1))
    _commit(repo, "src/café.py", "unicode\n", now - timedelta(days=1))

    main = str(repo / "src/main.py")
    unicode_file = str(repo / "src/café.py")
    untracked = str(repo / "new.py")
    assert commit_count(main) == 2
    assert commit_counts_batch([main, unicode_file, untracked], repo) == {
        main: 2,
        unicode_file: 1,
        untracked: 0,
    }


def test_churn_returns_zero_outside_a_git_repository(tmp_path: Path) -> None:
    file = tmp_path / "plain.py"
    file.write_text("x\n", encoding="utf-8")
    assert commit_count(str(file)) == 0
    assert commit_counts_batch([str(file)], tmp_path) == {str(file): 0}
    assert commit_counts_batch([], tmp_path) == {}


def test_certified_complexity_languages_match_the_parser_registry() -> None:
    assert set(CERTIFIED_COMPLEXITY_LANGUAGES) == {
        "bash",
        "c",
        "cpp",
        "csharp",
        "dart",
        "elixir",
        "go",
        "haskell",
        "java",
        "javascript",
        "kotlin",
        "lua",
        "php",
        "python",
        "ruby",
        "rust",
        "scala",
        "solidity",
        "swift",
        "tsx",
        "typescript",
    }
    for language in CERTIFIED_COMPLEXITY_LANGUAGES:
        assert has_certified_complexity_profile(Path(f"example.{_extension(language)}"))
    assert not has_certified_complexity_profile(Path("README.md"))


def _extension(language: str) -> str:
    return {
        "bash": "sh",
        "c": "c",
        "cpp": "cpp",
        "csharp": "cs",
        "dart": "dart",
        "elixir": "ex",
        "go": "go",
        "haskell": "hs",
        "java": "java",
        "javascript": "js",
        "kotlin": "kt",
        "lua": "lua",
        "php": "php",
        "python": "py",
        "ruby": "rb",
        "rust": "rs",
        "scala": "scala",
        "solidity": "sol",
        "swift": "swift",
        "tsx": "tsx",
        "typescript": "ts",
    }[language]
