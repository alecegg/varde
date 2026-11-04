"""Run the daemon, and find or start one from a client."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from varde_serve.daemon.app import DaemonContext, build_app
from varde_serve.daemon.config import ServeConfig, bind_refusal, load_serve_config
from varde_serve.daemon.local_http import open_local
from varde_serve.daemon.state import (
    DaemonInfo,
    read_info,
    remove_info_of,
    try_lock,
    write_info,
)
from varde_serve.daemon.tokens import ensure_tokens, state_dir

DISCOVERY_WAIT_S = 5.0
PROBE_TIMEOUT_S = 1.0
IDLE_CHECK_S = 5.0
DAEMON_ARGV = (sys.executable, "-m", "varde_serve", "daemon")


class DaemonError(RuntimeError):
    """The daemon could not be reached or started."""


def run_daemon(
    config_dir: Path,
    version: str,
    *,
    config: ServeConfig | None = None,
    requested_bind: str | None = None,
    configure: Callable[[DaemonContext], None] = lambda ctx: None,
) -> int:
    """Hold the lock and serve until shutdown, idle exit or a signal."""
    config = config or load_serve_config(config_dir)
    refusal = bind_refusal(config, requested_bind)
    if refusal:
        sys.stderr.write(f"{refusal}\n")
        return 2
    state = state_dir(config_dir)
    lock = try_lock(state)
    if lock is None:
        return 0  # another daemon owns the lock; never double-start
    address = requested_bind or config.bind
    try:
        listener = bound_listener(address, config.port)
    except OSError as error:
        os.close(lock)
        sys.stderr.write(f"serve: cannot bind {address}:{config.port}: {error}\n")
        return 2
    try:
        port = listener.getsockname()[1]
        tokens = ensure_tokens(config_dir)
        ctx = DaemonContext(config, tokens, version, port)
        configure(ctx)
        server = uvicorn.Server(uvicorn.Config(build_app(ctx), log_level="warning"))
        ctx.on_shutdown = lambda: setattr(server, "should_exit", True)
        # uvicorn re-raises SIGTERM after serve() returns, skipping the finally
        # below; the lifespan shutdown runs first and removes the file.
        ctx.on_stopped = lambda: remove_info_of(state, os.getpid())
        started = datetime.now(UTC).isoformat()
        log_bind(state, address, port)
        write_info(state, DaemonInfo(os.getpid(), port, started, version, address))
        asyncio.run(_serve(server, ctx, listener))
    finally:
        remove_info_of(state, os.getpid())
        listener.close()
        os.close(lock)
    return 0


def bound_listener(address: str, port: int) -> socket.socket:
    """A bound (not yet listening) socket of the address's family."""
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    listener = socket.socket(family)
    try:
        listener.bind((address, port))
    except OSError:
        listener.close()
        raise
    return listener


def log_bind(state: Path, address: str, port: int) -> None:
    """Record the bind once per start in `daemon.log` (and on stderr)."""
    line = f"{datetime.now(UTC).isoformat()} serve: bound {address}:{port}\n"
    (state / "daemon.log").write_text(line, encoding="utf-8")
    sys.stderr.write(line)


async def _serve(server: uvicorn.Server, ctx: DaemonContext, listener) -> None:
    watcher = asyncio.create_task(_idle_exit(server, ctx))
    try:
        await server.serve(sockets=[listener])
    finally:
        watcher.cancel()


async def _idle_exit(server: uvicorn.Server, ctx: DaemonContext) -> None:
    while not server.should_exit:
        await asyncio.sleep(min(IDLE_CHECK_S, ctx.config.idle_s))
        for job in ctx.periodic_jobs:
            job()
        if ctx.idle_for() >= ctx.config.idle_s:
            server.should_exit = True


def process_command(pid: int) -> str | None:
    """The command line of `pid`, or None when `ps` cannot tell."""
    try:
        done = subprocess.run(  # noqa: S603 - fixed ps query for one integer pid
            ["ps", "-o", "command=", "-p", str(pid)],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except OSError, subprocess.SubprocessError:
        return None
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def is_serve_process(pid: int) -> bool:
    """True when `pid` is alive, ours to signal, and (if checkable) varde-serve."""
    try:
        os.kill(pid, 0)
    except OSError:  # gone, or another user's process
        return False
    command = process_command(pid)
    return command is None or "varde_serve" in command or "varde-serve" in command


def genuine_health(health: object, info: DaemonInfo) -> bool:
    """A /health body from the daemon `info` names, not a spoofing listener."""
    if not isinstance(health, dict):
        return False
    pid = health.get("pid")
    shape = (
        isinstance(health.get("version"), str)
        and isinstance(health.get("api_version"), int)
        and isinstance(health.get("features"), list)
    )
    pid_ok = isinstance(pid, int) and not isinstance(pid, bool) and pid > 1
    return shape and pid_ok and pid == info.pid and is_serve_process(info.pid)


def probe_health(info: DaemonInfo) -> dict | None:
    """GET /health; the body only when it is that daemon's, else None."""
    request = urllib.request.Request(  # noqa: S310
        f"{info.base_url}/health", headers={"Host": info.authority}
    )
    try:
        with open_local(request, PROBE_TIMEOUT_S) as response:
            health = json.loads(response.read())
    except urllib.error.URLError, OSError, ValueError:
        return None
    return health if genuine_health(health, info) else None


def _live_info(state: Path) -> DaemonInfo | None:
    info = read_info(state)
    if info is not None and probe_health(info) is not None:
        return info
    return None


def _wait_for(state: Path, seconds: float) -> DaemonInfo | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        info = _live_info(state)
        if info is not None:
            return info
        time.sleep(0.05)
    return None


def spawn_daemon(argv: Sequence[str] = DAEMON_ARGV) -> None:
    subprocess.Popen(  # noqa: S603
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def ensure_daemon(
    config_dir: Path, spawn: Callable[[], None] = spawn_daemon
) -> DaemonInfo:
    """Return a live daemon, starting one if none runs; never start two."""
    state = state_dir(config_dir)
    info = _live_info(state)
    if info is not None:
        return info
    lock = try_lock(state)
    if lock is not None:  # nothing holds the lock: no daemon is starting or running
        os.close(lock)
        spawn()  # the daemon overwrites any stale daemon.json; clients never delete it
    info = _wait_for(state, DISCOVERY_WAIT_S)
    if info is None:
        raise DaemonError("serve daemon did not become ready within 5 s")
    return info


def stop_daemon(config_dir: Path) -> bool:
    """Ask a running daemon to stop with the human token; True if one was running."""
    state = state_dir(config_dir)
    info = _live_info(state)
    if info is None:
        return False
    token = ensure_tokens(config_dir).human
    request = urllib.request.Request(  # noqa: S310
        f"{info.base_url}/shutdown",
        method="POST",
        headers={"Host": info.authority, "Authorization": f"Bearer {token}"},
    )
    with contextlib.suppress(urllib.error.URLError, OSError):
        open_local(request, PROBE_TIMEOUT_S)
    return True
