"""`start`, `stop` and `status`: thin, output-only wrappers over the lifecycle."""

from __future__ import annotations

import sys
from pathlib import Path

from varde_core.paths import varde_config_dir

from varde_serve.daemon.lifecycle import (
    DaemonError,
    ensure_daemon,
    probe_health,
    stop_daemon,
)
from varde_serve.daemon.state import read_info
from varde_serve.daemon.tokens import state_dir


def token_path(config_dir: Path) -> Path:
    return state_dir(config_dir) / "token"


def start(config_dir: Path | None = None) -> int:
    config_dir = config_dir or varde_config_dir()
    try:
        info = ensure_daemon(config_dir)
    except DaemonError as error:
        sys.stderr.write(f"serve: {error}\n")
        return 1
    sys.stdout.write(f"serve running on {info.base_url} (pid {info.pid})\n")
    sys.stdout.write(f"token file: {token_path(config_dir)}\n")
    return 0


def stop(config_dir: Path | None = None) -> int:
    stopped = stop_daemon(config_dir or varde_config_dir())
    sys.stdout.write("serve: stopping\n" if stopped else "serve: not running\n")
    return 0


def status(config_dir: Path | None = None) -> int:
    """Print state and the token file path; never the token value."""
    config_dir = config_dir or varde_config_dir()
    info = read_info(state_dir(config_dir))
    health = probe_health(info) if info else None
    if info is None or health is None:
        sys.stdout.write("serve: not running\n")
    else:
        sys.stdout.write(
            f"serve: running on {info.base_url} "
            f"(pid {info.pid}, version {health.get('version')})\n"
        )
    sys.stdout.write(f"token file: {token_path(config_dir)}\n")
    return 0
