"""Daemon lock and `daemon.json`."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from varde_data.locking import atomic_write


@dataclass(frozen=True)
class DaemonInfo:
    pid: int
    port: int
    started_at: str
    version: str
    bind: str = "127.0.0.1"

    @property
    def host(self) -> str:
        """The address clients connect to for the daemon's bind."""
        if self.bind in ("0.0.0.0", ""):  # noqa: S104 - connect target, not a bind
            return "127.0.0.1"
        if self.bind == "::":
            return "[::1]"
        return f"[{self.bind}]" if ":" in self.bind else self.bind

    @property
    def authority(self) -> str:
        return f"{self.host}:{self.port}"

    @property
    def base_url(self) -> str:
        return f"http://{self.authority}"


def info_path(state: Path) -> Path:
    return state / "daemon.json"


def lock_path(state: Path) -> Path:
    return state / "daemon.lock"


def valid_info(info: DaemonInfo) -> bool:
    ints = isinstance(info.pid, int) and isinstance(info.port, int)
    texts = isinstance(info.bind, str) and isinstance(info.version, str)
    return ints and texts and info.pid > 1 and 0 < info.port < 65536


def read_info(state: Path) -> DaemonInfo | None:
    try:
        info = DaemonInfo(**json.loads(info_path(state).read_text(encoding="utf-8")))
    except OSError, ValueError, TypeError:
        return None
    return info if valid_info(info) else None


def write_info(state: Path, info: DaemonInfo) -> None:
    atomic_write(info_path(state), json.dumps(asdict(info)).encode(), mode=0o600)


def remove_info_of(state: Path, pid: int) -> None:
    """Remove `daemon.json` only if it still names `pid` (never a live peer's)."""
    info = read_info(state)
    if info is not None and info.pid == pid:
        info_path(state).unlink(missing_ok=True)


def try_lock(state: Path) -> int | None:
    """Take the daemon lock without blocking; return the fd, or None if held."""
    descriptor = os.open(lock_path(state), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor
