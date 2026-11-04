from __future__ import annotations

import subprocess
from pathlib import Path

from varde_workflow import git_facts
from varde_workflow.git_facts import get_git_facts


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - fixed Git test setup commands.
        ["git", "-C", str(root), *args],  # noqa: S607 - Git is required by these tests.
        check=True,
        capture_output=True,
    )


def _repository(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "base.txt").write_text("base\n")
    _git(repo, "add", "base.txt")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "worktree/alpha")
    _git(repo, "branch", "worktree/alpha-next")
    return repo


def test_worktree_activity_refreshes_without_ref_change(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    worktree = tmp_path / "alpha"
    _git(repo, "worktree", "add", str(worktree), "worktree/alpha")
    first = get_git_facts(repo, refresh=True)
    before = first.worktree_activity["worktree/alpha"]

    (worktree / "untracked.txt").write_text("new work\n")
    second = get_git_facts(repo, refresh=True)

    after = second.worktree_activity["worktree/alpha"]
    assert after is not None
    assert before is None or after[0] >= before[0]


def test_cached_facts_bound_worktree_status_subprocesses(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repository(tmp_path)
    worktree = tmp_path / "alpha"
    _git(repo, "worktree", "add", str(worktree), "worktree/alpha")
    original_git = git_facts.git
    status_calls = 0

    def count_status(root: Path, args: list[str] | tuple[str, ...], *, timeout: float):
        nonlocal status_calls
        if args[:2] == ["status", "--porcelain"]:
            status_calls += 1
        return original_git(root, args, timeout=timeout)

    monkeypatch.setattr(git_facts, "git", count_status)

    get_git_facts(repo, refresh=True)
    initial_status_calls = status_calls
    get_git_facts(repo)

    assert initial_status_calls > 0
    assert status_calls - initial_status_calls <= git_facts.WORKTREE_ACTIVITY_BATCH_SIZE


def test_worktree_status_checks_are_batched_per_refresh(tmp_path: Path, monkeypatch):
    repo = _repository(tmp_path)
    for number in range(5):
        branch = f"worktree/extra-{number}"
        _git(repo, "branch", branch)
        _git(repo, "worktree", "add", str(tmp_path / f"extra-{number}"), branch)

    original = git_facts._worktree_activity
    checked: list[Path] = []

    def count_status(path: Path):
        checked.append(path)
        return original(path)

    monkeypatch.setattr(git_facts, "_worktree_activity", count_status)
    facts = get_git_facts(repo, refresh=True)
    first_count = len(checked)
    get_git_facts(repo)

    assert first_count <= git_facts.WORKTREE_ACTIVITY_BATCH_SIZE
    assert len(checked) - first_count <= git_facts.WORKTREE_ACTIVITY_BATCH_SIZE
    assert set(facts.worktree_activity) == set(facts.worktrees)


def test_recently_active_worktree_gets_bounded_priority_check(
    tmp_path: Path, monkeypatch
) -> None:
    repo = _repository(tmp_path)
    _git(repo, "worktree", "add", str(tmp_path / "alpha"), "worktree/alpha")
    _git(repo, "worktree", "add", str(tmp_path / "next"), "worktree/alpha-next")
    facts = get_git_facts(repo, refresh=True)
    cursor_branch, recent_branch = "worktree/alpha", "worktree/alpha-next"
    ordered = list(facts.worktrees)
    monkeypatch.setattr(git_facts.time, "time", lambda: 10_000.0)
    git_facts._activity_cursor[repo.resolve()] = ordered.index(cursor_branch)
    git_facts._activity_priority_checked_at.pop(repo.resolve(), None)
    checked: list[Path] = []
    monkeypatch.setattr(
        git_facts,
        "_worktree_activity",
        lambda path: checked.append(path) or None,
    )

    git_facts._refresh_activity_batch(
        repo,
        facts.worktrees,
        {recent_branch: (9_999.0, "recent.txt")},
    )

    assert checked == [facts.worktrees[recent_branch]]
    assert facts.worktrees[cursor_branch] not in checked


def test_worktree_activity_max_age_includes_prioritized_checks() -> None:
    max_age = git_facts.worktree_activity_max_age_seconds(428, 60)

    assert max_age == 27_420
    assert max_age < 8 * 60 * 60


def test_worktree_head_change_updates_refs_signature(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    worktree = tmp_path / "alpha"
    _git(repo, "worktree", "add", str(worktree), "worktree/alpha")
    before = get_git_facts(repo, refresh=True).refs_signature

    _git(worktree, "switch", "worktree/alpha-next")
    after = get_git_facts(repo).refs_signature

    assert after != before
