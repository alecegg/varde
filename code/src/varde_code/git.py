"""Git subprocess seam.

Published signature: ``run_git(args: Sequence[str], cwd: Path) -> str | None``.
Returns stdout on exit status zero, and ``None`` for launch or command failure.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path


def run_git(args: Sequence[str], cwd: Path) -> str | None:
    output = run_git_bytes(args, cwd)
    if output is None:
        return None
    return output.decode("utf-8", errors="replace")


def run_git_bytes(args: Sequence[str], cwd: Path) -> bytes | None:
    """Return raw stdout on exit status zero, else ``None``."""
    try:
        result = subprocess.run(  # noqa: S603 - Runs the git command with caller-supplied argv and no shell.
            ["git", *args],  # noqa: S607 - Uses the system git executable from PATH.
            cwd=cwd,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode:
        return None
    return result.stdout
