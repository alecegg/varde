"""Bounded read-only Git and code-impact queries."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Protocol

from .execution_wave_paths import canonical_path

TIMEOUT = 120
OUTPUT_LIMIT = 16 * 1024 * 1024


class ImpactQuery(Protocol):
    def dependents(self, repo_root: Path, file: Path) -> list[Path] | None: ...


def git(
    root: Path,
    args: list[str] | tuple[str, ...],
    *,
    timeout: float = TIMEOUT,
) -> tuple[int, str] | None:
    try:
        result = subprocess.run(  # noqa: S603 - Git inspection uses fixed argv and controlled caller arguments.
            ["git", "-C", str(root), *args],  # noqa: S607 - Git is the required repository executable from PATH.
            check=False,
            capture_output=True,
            timeout=timeout,
        )
    except OSError, subprocess.TimeoutExpired:
        return None
    if len(result.stdout) > OUTPUT_LIMIT:
        return None
    try:
        return result.returncode, result.stdout.decode("utf-8")
    except UnicodeDecodeError:
        return None


def blast_radius(impact: ImpactQuery, root: Path, path: str) -> list[str] | None:
    try:
        found = impact.dependents(root, Path(path))
    except Exception:
        return None
    if found is None:
        return None
    try:
        return [canonical_path(root, value.as_posix()) for value in found]
    except OSError, ValueError:
        return None


def _grep(root: Path, pattern: str) -> list[str] | None:
    result = git(root, ["grep", "-l", "-F", "--", pattern])
    if result is None:
        return None
    status, output = result
    if status == 1:
        return []
    if status != 0:
        return None
    try:
        return [canonical_path(root, line) for line in output.splitlines() if line]
    except ValueError:
        return None


def basename_references(root: Path, path: str) -> list[str] | None:
    basename = Path(path).name
    tracked_result = git(root, ["ls-files", "-z"])
    if tracked_result is None or tracked_result[0] != 0:
        return None
    tracked = tracked_result[1].split("\0")
    duplicates = sum(Path(file).name == basename for file in tracked) > 1
    references = _grep(root, basename)
    if references is None or not duplicates:
        return references
    exact = set(_grep(root, path) or [])
    parent = Path(path).parent.parent.as_posix()
    if parent != ".":
        exact.update(file for file in references if file.startswith(parent + "/"))
    return sorted(exact)
