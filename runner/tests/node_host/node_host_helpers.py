from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from pathlib import Path

from varde_runner.node_host import NodeHost, RestartPolicy

NODE_HOST_DIR = Path(__file__).resolve().parents[2] / "node-host"
HOST_SCRIPT = NODE_HOST_DIR / "host.mjs"
ECHO_ENGINE = Path(__file__).parent / "fixtures" / "echo-engine.mjs"
FAST_POLICY = RestartPolicy(max_restarts=3, window_s=60.0, delays_s=(0.05, 0.05, 0.05))


def make_host(**kwargs) -> NodeHost:
    kwargs.setdefault("policy", FAST_POLICY)
    kwargs.setdefault("ready_timeout_s", 20.0)
    kwargs.setdefault("stop_grace_s", 3.0)
    return NodeHost(["node", str(HOST_SCRIPT)], ECHO_ENGINE, **kwargs)


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_until(check: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.05)
    return check()


async def await_until(check: Callable[[], bool], timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        await asyncio.sleep(0.05)
    return check()
