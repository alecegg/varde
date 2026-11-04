"""The stable launcher that pointers name: resolves the interpreter at run time.

An accepted extraction leaves `sh <shim> <skill>/<step>` in skill text. The shim
lives in the user's data directory, not in a release, and finds the interpreter
of the installed `varde` each time it runs, so CLI deploys that swap release
directories do not break pointers.
"""

from __future__ import annotations

import os
from pathlib import Path

from varde_core.paths import local_share_dir

SHIM_NAME = "step-tool"
POINTER_PATH = '"${XDG_DATA_HOME:-$HOME/.local/share}/varde/' + SHIM_NAME + '"'
ENTRY_MODULE = "varde_learn.loop.improve.tool_entry"
SHIM_TEXT = f"""#!/bin/sh
# Counted step tool launcher: runs the installed varde interpreter on the wrapper.
fail() {{ echo "step-tool: $1" >&2; exit 127; }}
varde_bin=$(command -v varde) || fail "varde is not on PATH"
python=$(sed -n '1s/^#!//p' "$varde_bin")
python=${{python%% *}}
case "$python" in */env) python="" ;; esac
[ -x "$python" ] || python="$(dirname "$varde_bin")/python"
[ -x "$python" ] || fail "cannot resolve the varde interpreter from $varde_bin"
exec "$python" -m {ENTRY_MODULE} "$@"
"""


def shim_path() -> Path:
    return local_share_dir() / "varde" / SHIM_NAME


def install_shim() -> Path:
    """Write the launcher when missing or different; return its path."""
    path = shim_path()
    if path.is_file() and path.read_text() == SHIM_TEXT:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{SHIM_NAME}.tmp")
    temp.write_text(SHIM_TEXT)
    temp.chmod(0o755)
    os.replace(temp, path)
    return path
