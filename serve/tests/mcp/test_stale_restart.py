"""A daemon whose version differs from the shim's is replaced."""

import os
import time
from collections.abc import Callable
from pathlib import Path

import pytest
from conftest import Served
from varde_serve.mcp.shim import ensure_current_daemon


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_version_mismatch_replaces_the_daemon(
    served_factory: Callable[..., Served],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    served = served_factory()  # runs as version "test"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(served.config_dir))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)
    old = served.info.pid
    assert ensure_current_daemon(served.config_dir, "test").pid == old
    started = time.monotonic()
    fresh = ensure_current_daemon(served.config_dir, "something-else")
    # SIGTERM removes daemon.json, so the replacement never waits out the timer.
    assert time.monotonic() - started < 3.0
    assert fresh.pid != old
    deadline = time.monotonic() + 5
    while alive(old) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not alive(old)
    os.kill(fresh.pid, 15)
