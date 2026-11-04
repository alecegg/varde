"""Cached Git facts shared by status and watch collectors."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, replace
from math import ceil
from pathlib import Path

from varde_workflow.collectors import GitFacts
from varde_workflow.execution_wave_tools import git


@dataclass(frozen=True)
class ReviewedCommitFacts:
    exists: bool
    commits: tuple[tuple[str, ...], ...]


_cache: dict[Path, GitFacts] = {}
_activity_cursor: dict[Path, int] = {}
_activity_priority_checked_at: dict[Path, float] = {}
_git_dirs: dict[Path, Path] = {}
_reviewed_cache: dict[
    tuple[Path, tuple[tuple[str, int, int, int], ...], str], ReviewedCommitFacts
] = {}
WORKTREE_ACTIVITY_BATCH_SIZE = 1
WORKTREE_ACTIVITY_PRIORITY_INTERVAL_SECONDS = 15 * 60


def worktree_activity_max_age_seconds(
    worktree_count: int, refresh_interval_seconds: float
) -> float:
    """Bound a full status cycle, including one known-active check per interval."""
    if worktree_count <= 0:
        return 0.0
    cycle_checks = ceil(worktree_count / WORKTREE_ACTIVITY_BATCH_SIZE)
    priority_checks = ceil(
        cycle_checks
        * refresh_interval_seconds
        / WORKTREE_ACTIVITY_PRIORITY_INTERVAL_SECONDS
    )
    return (cycle_checks + priority_checks) * refresh_interval_seconds


def _git_dir(repo: Path) -> Path:
    cached = _git_dirs.get(repo)
    if cached is not None:
        return cached
    result = git(repo, ["rev-parse", "--git-dir"], timeout=2)
    path = Path(result[1].strip()) if result else repo / ".git"
    if not path.is_absolute():
        path = repo / path
    _git_dirs[repo] = path
    return path


def refs_signature(repo: Path) -> tuple[tuple[str, int, int, int], ...]:
    git_dir = _git_dir(repo)
    refs = git_dir / "refs" / "heads"
    paths = [refs, git_dir / "packed-refs", git_dir / "HEAD"]
    worktrees = git_dir / "worktrees"
    paths.append(worktrees)
    if worktrees.is_dir():
        paths.extend(sorted(worktrees.glob("*/HEAD")))
    if refs.is_dir():
        paths.extend(Path(directory) for directory, _, _ in os.walk(refs))
    signature = []
    for path in paths:
        try:
            info = path.stat()
            signature.append(
                (str(path), info.st_mtime_ns, info.st_ctime_ns, info.st_size)
            )
        except OSError:
            signature.append((str(path), 0, 0, 0))
    return tuple(signature)


def get_git_facts(repo: Path, *, refresh: bool = False) -> GitFacts:
    repo = repo.resolve()
    signature = refs_signature(repo)
    current = _cache.get(repo)
    if current is not None and current.refs_signature == signature and not refresh:
        activity = _refresh_activity_batch(
            repo, current.worktrees, current.worktree_activity
        )
        refreshed = replace(current, worktree_activity=activity)
        _cache[repo] = refreshed
        return refreshed
    result = git(
        repo,
        [
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)\t%(committerdate:unix)",
        ],
        timeout=2,
    )
    branches: dict[str, float] = {}
    if result is not None and result[0] == 0:
        for line in result[1].splitlines():
            name, separator, raw_date = line.partition("\t")
            if separator:
                try:
                    branches[name] = float(int(raw_date))
                except ValueError:
                    continue
    merged_result = git(
        repo,
        ["branch", "--merged", "main", "--format=%(refname:short)"],
        timeout=2,
    )
    merged = (
        frozenset(merged_result[1].splitlines())
        if merged_result and merged_result[0] == 0
        else frozenset()
    )
    worktree_result = git(repo, ["worktree", "list", "--porcelain"], timeout=2)
    worktrees: dict[str, Path] = {}
    path = None
    branch = None
    if worktree_result and worktree_result[0] == 0:
        for line in worktree_result[1].splitlines() + [""]:
            if line.startswith("worktree "):
                path, branch = Path(line.removeprefix("worktree ")), None
            elif line.startswith("branch refs/heads/"):
                branch = line.removeprefix("branch refs/heads/")
            elif not line and path is not None and branch is not None:
                worktrees[branch] = path
                path, branch = None, None
    prior_activity = current.worktree_activity if current is not None else {}
    activity = _refresh_activity_batch(repo, worktrees, prior_activity)
    facts = GitFacts(signature, branches, merged, worktrees, activity)
    _cache[repo] = facts
    return facts


def _refresh_activity_batch(
    repo: Path,
    worktrees: dict[str, Path],
    previous: dict[str, tuple[float, str] | None],
) -> dict[str, tuple[float, str] | None]:
    branches = tuple(worktrees)
    activity = {branch: previous.get(branch) for branch in branches}
    if not branches:
        return activity
    start = _activity_cursor.get(repo, 0) % len(branches)
    stop = min(start + WORKTREE_ACTIVITY_BATCH_SIZE, len(branches))
    selected = branches[start:stop]
    if not selected:
        selected = branches[:WORKTREE_ACTIVITY_BATCH_SIZE]
        stop = len(selected)
    now = time.time()
    last_priority_check = _activity_priority_checked_at.get(repo, 0.0)
    recent_activity = [
        (activity[0], branch)
        for branch, activity in previous.items()
        if activity is not None
        and now - activity[0] <= WORKTREE_ACTIVITY_PRIORITY_INTERVAL_SECONDS
    ]
    if (
        recent_activity
        and now - last_priority_check >= WORKTREE_ACTIVITY_PRIORITY_INTERVAL_SECONDS
    ):
        _, priority_branch = max(recent_activity)
        if priority_branch in worktrees:
            selected = [priority_branch]
            _activity_priority_checked_at[repo] = now
    for branch in selected:
        activity[branch] = _worktree_activity(worktrees[branch])
    _activity_cursor[repo] = stop % len(branches)
    return activity


def reviewed_commit_facts(repo: Path, reviewed: str) -> ReviewedCommitFacts:
    """Return cached commit existence and changed paths since a review commit."""
    repo = repo.resolve()
    facts = _cache.get(repo) or get_git_facts(repo)
    key = (repo, facts.refs_signature, reviewed)
    cached = _reviewed_cache.get(key)
    if cached is not None:
        return cached
    exists = git(repo, ["cat-file", "-e", f"{reviewed}^{{commit}}"], timeout=2)
    if not exists or exists[0] != 0:
        value = ReviewedCommitFacts(False, ())
    else:
        result = git(
            repo,
            ["log", "--format=%H", "--name-only", f"{reviewed}..HEAD"],
            timeout=2,
        )
        groups = []
        paths = []
        if result and result[0] == 0:
            for raw_line in result[1].splitlines():
                line = raw_line.strip()
                if len(line) == 40 and all(
                    char in "0123456789abcdefABCDEF" for char in line
                ):
                    if paths:
                        groups.append(tuple(paths))
                    paths = []
                elif line:
                    paths.append(line)
            if paths:
                groups.append(tuple(paths))
        value = ReviewedCommitFacts(True, tuple(groups))
    _reviewed_cache.clear()
    _reviewed_cache[key] = value
    return value


def _worktree_activity(worktree: Path) -> tuple[float, str] | None:
    latest = None
    result = git(worktree, ["status", "--porcelain"], timeout=2)
    if result is not None and result[0] == 0:
        for line in result[1].splitlines():
            if len(line) < 4:
                continue
            relative = line[3:].rsplit(" -> ", 1)[-1].strip().strip('"')
            try:
                modified = (worktree / relative).stat().st_mtime
            except OSError:
                continue
            if latest is None or modified >= latest[0]:
                latest = (modified, "uncommitted change")
    for relative in (
        "clis/target/debug/deps",
        "clis/target/debug/.fingerprint",
        "clis/target/debug/build",
    ):
        try:
            modified = (worktree / relative).stat().st_mtime
        except OSError:
            continue
        if latest is None or modified >= latest[0]:
            latest = (modified, "build output")
    return latest
