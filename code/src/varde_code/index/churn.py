"""Recent per-file Git activity used by the code index."""

from __future__ import annotations

import contextlib
import os
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from varde_code.git import run_git

_CHURN_WINDOW = "--since=90 days ago"


def commit_counts_batch(files: Sequence[str], known_root: Path) -> dict[str, int]:
    """Count recent commits for indexed files, walking each repository once."""
    counts = dict.fromkeys(files, 0)
    if not counts:
        return counts

    with contextlib.suppress(OSError):
        known_root = known_root.resolve()
    if not _has_git_context(known_root) and all(
        _relative_to_root(Path(file), known_root) is not None for file in counts
    ):
        return counts
    git_root = _repo_root(known_root)
    under_root: list[tuple[str, Path]] = []
    elsewhere: list[str] = []
    for file in counts:
        relative = _relative_to_root(Path(file), git_root)
        if relative is None:
            elsewhere.append(file)
        else:
            under_root.append((file, relative))

    _count_files_at_root(counts, git_root, under_root)
    _count_files_elsewhere(counts, elsewhere)
    return counts


def _has_git_context(directory: Path) -> bool:
    if any(
        os.environ.get(name) for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")
    ):
        return True
    return any((parent / ".git").exists() for parent in (directory, *directory.parents))


def commit_count(file: str) -> int:
    """Count commits touching ``file`` in the last 90 days, or return zero."""
    directory = Path(file).parent
    output = run_git(
        [
            "-c",
            "core.quotepath=false",
            "log",
            "--pretty=oneline",
            _CHURN_WINDOW,
            "--",
            file,
        ],
        directory if str(directory) else Path("."),
    )
    if output is None:
        return 0
    return sum(bool(line.strip()) for line in output.splitlines())


def _repo_root(directory: Path) -> Path | None:
    output = run_git(["rev-parse", "--show-toplevel"], directory)
    if output is None or not output.strip():
        return None
    try:
        return Path(output.strip()).resolve()
    except OSError:
        return None


def _relative_to_root(path: Path, root: Path | None) -> Path | None:
    if root is None:
        return None
    try:
        return path.relative_to(root)
    except ValueError:
        try:
            return path.resolve().relative_to(root)
        except OSError, ValueError:
            return None


def _count_files_at_root(
    result: dict[str, int], root: Path | None, files: list[tuple[str, Path]]
) -> None:
    if root is None or not files:
        return
    path_counts = _commit_counts_for_root(root, [relative for _, relative in files])
    for file, relative in files:
        result[file] = path_counts.get(relative.as_posix(), 0)


def _count_files_elsewhere(result: dict[str, int], files: list[str]) -> None:
    by_root: dict[Path, list[str]] = defaultdict(list)
    root_cache: dict[Path, Path | None] = {}
    for file in files:
        directory = Path(file).parent
        if directory not in root_cache:
            try:
                root_cache[directory] = _repo_root(directory)
            except OSError:
                root_cache[directory] = None
        root = root_cache[directory]
        if root is None:
            continue
        by_root[root].append(file)

    for root, root_files in by_root.items():
        files_with_paths: list[tuple[str, str | None]] = []
        for file in root_files:
            try:
                relative = Path(file).resolve().relative_to(root).as_posix()
            except OSError, ValueError:
                relative = None
            files_with_paths.append((file, relative))
        paths = [relative for _, relative in files_with_paths if relative is not None]
        path_counts = _commit_counts_for_root(root, paths)
        for file, relative in files_with_paths:
            result[file] = path_counts.get(relative, 0) if relative is not None else 0


def _commit_counts_for_root(
    root: Path, indexed_paths: Sequence[Path | str]
) -> dict[str, int]:
    if not indexed_paths:
        return {}
    output = run_git(
        [
            "-c",
            "core.quotepath=false",
            "log",
            "--name-only",
            "-z",
            "--pretty=format:",
            _CHURN_WINDOW,
        ],
        root,
    )
    if output is None:
        return {}

    indexed = {Path(path).as_posix() for path in indexed_paths}
    counts: dict[str, int] = {}
    for path in output.split("\0"):
        if path in indexed:
            counts[path] = counts.get(path, 0) + 1
    return counts
