"""Runtime paths shared by the optional hook client and server."""

import os
import tempfile
from pathlib import Path


def runtime_dir() -> Path:
    base = (
        os.environ.get("XDG_RUNTIME_DIR")
        or os.environ.get("TMPDIR")
        or tempfile.gettempdir()
    )
    path = Path(base) / "varde-toz"
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def socket_path() -> Path:
    return runtime_dir() / "hook.sock"
