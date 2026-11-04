"""Best-effort git timestamps for concept files."""

from __future__ import annotations

import subprocess
from pathlib import Path

from varde_learn.knowledge.crud import concept_path_or


def git_created_updated(bundle: str | Path, slug: str) -> tuple[str | None, str | None]:
    """Return first and latest commit timestamps, or ``(None, None)``."""
    bundle = Path(bundle)
    try:
        path = concept_path_or(bundle, slug)
    except OSError:
        return None, None
    try:
        relative_path = path.relative_to(bundle)
        result = subprocess.run(  # noqa: S603 - Reads repository timestamps using a fixed Git command.
            [  # noqa: S607 - Git is resolved from PATH as the repository tool.
                "git",
                "-C",
                str(bundle),
                "log",
                "--follow",
                "--format=%cI",
                "--",
                str(relative_path),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError, ValueError:
        return None, None
    if result.returncode != 0:
        return None, None
    lines = result.stdout.splitlines()
    if not lines:
        return None, None
    return lines[-1], lines[0]


__all__ = ["git_created_updated"]
