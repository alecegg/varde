"""Time-limited access checks for filesystem paths."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence

_OPEN_SCRIPT = "import os, sys; fd = os.open(sys.argv[1], os.O_RDONLY); os.close(fd)"


def probe_paths(
    paths: Sequence[str],
    timeout_s: float,
    *,
    child_command: Sequence[str] | None = None,
) -> dict[str, str]:
    """Open each path in an isolated child and classify its result."""
    command = list(child_command or (sys.executable, "-c", _OPEN_SCRIPT))
    results: dict[str, str] = {}
    for path in paths:
        try:
            completed = subprocess.run(  # noqa: S603 - child command is supplied by the caller or fixed below.
                [*command, path],
                check=False,
                capture_output=True,
                timeout=timeout_s,
            )
        except subprocess.TimeoutExpired:
            results[path] = "timeout"
        except OSError, subprocess.SubprocessError:
            results[path] = "error"
        else:
            results[path] = "ok" if completed.returncode == 0 else "error"
    return results
