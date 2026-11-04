"""Git facts about a checkout used by pack generation and status."""

from __future__ import annotations

from pathlib import Path

from varde_code.git import run_git
from varde_code.packs import DOC_DIR

_COMMIT_MARK = "\x01"


def toplevel(path: Path) -> Path:
    """Return the git top level containing ``path``, or ``path`` outside git."""
    output = run_git(["rev-parse", "--show-toplevel"], path)
    return Path(output.strip()) if output and output.strip() else path


def is_dirty(root: Path) -> bool:
    """Whether the tree has uncommitted changes outside the pack directory."""
    output = run_git(["status", "--porcelain", "--", ".", f":(exclude){DOC_DIR}"], root)
    return bool(output and output.strip())


def commits_after(root: Path, sha: str) -> list[list[str]] | None:
    """Return each ``sha..HEAD`` commit's changed paths, or ``None`` on git error."""
    output = run_git(
        [
            "-c",
            "core.quotepath=off",
            "log",
            "--no-renames",
            "--name-only",
            f"--format={_COMMIT_MARK}%H",
            f"{sha}..HEAD",
        ],
        root,
    )
    if output is None:
        return None
    chunks = [chunk for chunk in output.split(_COMMIT_MARK) if chunk.strip()]
    return [[line for line in chunk.splitlines()[1:] if line] for chunk in chunks]
