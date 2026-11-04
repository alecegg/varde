"""The ``varde serve`` commands: start, stop, status and the MCP shim.

Each command runs the ``varde-serve`` executable; the app never imports serve.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_EXECUTABLE = "varde-serve"
_ACTIONS = {"": "start", "stop": "stop", "status": "status", "mcp": "mcp"}
_USAGE = "usage: varde serve [stop | status | mcp]"
_MISSING = (
    "serve: varde-serve is not installed. Run python3 runner/deploy/deploy.py "
    "from the Varde checkout, or `uv tool install <checkout>/serve`. "
    "The portable PEX does not include it."
)


def _executable() -> str | None:
    found = shutil.which(_EXECUTABLE)
    if found:
        return found
    stable = Path.home() / ".local" / "bin" / _EXECUTABLE
    return str(stable) if stable.is_file() else None


def run(argv: list[str], io: object) -> int:
    """Run a serve command and return its process exit status."""
    del io
    if len(argv) > 1 or (argv and argv[0] not in _ACTIONS):
        print(_USAGE, file=sys.stderr)
        return 2
    executable = _executable()
    if executable is None:
        print(_MISSING, file=sys.stderr)
        return 1
    action = _ACTIONS[argv[0] if argv else ""]
    return subprocess.run([executable, action], check=False).returncode  # noqa: S603 - fixed varde-serve action.
