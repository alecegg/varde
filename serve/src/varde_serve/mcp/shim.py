"""The stdio loop and the daemon client behind the four tools."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import IO, Any

from varde_core.paths import varde_config_dir

from varde_serve.daemon.lifecycle import DaemonError, ensure_daemon, probe_health
from varde_serve.daemon.local_http import open_local
from varde_serve.daemon.state import DaemonInfo, try_lock
from varde_serve.daemon.tokens import TokenMissing, read_mcp_token, state_dir
from varde_serve.mcp.protocol import Call, handle
from varde_serve.mcp.tools import route_for
from varde_serve.version import serve_version

REQUEST_TIMEOUT_S = 40.0  # above the 25 s event long-poll
RESTART_WAIT_S = 5.0
CALL_WORKERS = 8  # tool calls run off the reader so ping is never blocked
INTERNAL_ERROR = -32603


def wait_for_lock_release(config_dir: Path, seconds: float) -> None:
    """Return once no daemon holds the lock (the old one has exited)."""
    state = state_dir(config_dir)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        lock = try_lock(state)
        if lock is not None:
            os.close(lock)
            return
        time.sleep(0.05)


def ensure_current_daemon(config_dir: Path, version: str) -> DaemonInfo:
    """A verified live daemon of exactly `version`; replace a stale one."""
    info = ensure_daemon(config_dir)
    health = probe_health(info)  # None unless /health is genuinely `info`'s
    if health is None or health.get("version") == version:
        return info
    try:
        os.kill(info.pid, signal.SIGTERM)  # info.pid == health["pid"], verified
    except OSError as error:
        raise DaemonError(f"cannot stop the old daemon: {error}") from error
    wait_for_lock_release(config_dir, RESTART_WAIT_S)
    return ensure_daemon(config_dir)


def _send(info: DaemonInfo, token: str, method: str, path: str, body: Any) -> Any:
    headers = {
        "Host": info.authority,
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(  # noqa: S310
        f"{info.base_url}{path}", data, headers, method=method
    )
    with open_local(request, REQUEST_TIMEOUT_S) as response:
        return json.loads(response.read())


def daemon_call(config_dir: Path, version: str) -> Call:
    """A tool-call function that talks to the daemon with the mcp token only."""

    def call(tool: str, arguments: dict[str, Any]) -> tuple[bool, Any]:
        method, path, body = route_for(tool, arguments)  # BadArguments -> -32602
        try:
            info = ensure_current_daemon(config_dir, version)
            token = read_mcp_token(config_dir)  # after the daemon exists: it creates it
            return False, _send(info, token, method, path, body)
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")
            return True, f"HTTP {error.code}: {detail}"
        except (DaemonError, TokenMissing, urllib.error.URLError) as error:
            return True, f"serve daemon unavailable: {error}"
        except Exception as error:  # noqa: BLE001 - one bad call must not end the session
            return True, f"serve call failed: {type(error).__name__}: {error}"

    return call


def internal_error(message: Any, error: Exception) -> dict[str, Any]:
    message_id = message.get("id") if isinstance(message, dict) else None
    text = f"internal error: {type(error).__name__}"
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "error": {"code": INTERNAL_ERROR, "message": text},
    }


def answer(message: Any, call: Call) -> dict[str, Any] | None:
    try:
        return handle(message, call)
    except Exception as error:  # noqa: BLE001 - a JSON-RPC error, never a dead server
        return internal_error(message, error)


def is_tool_call(message: Any) -> bool:
    return isinstance(message, dict) and message.get("method") == "tools/call"


def serve_stdio(stdin: IO[str], stdout: IO[str], call: Call) -> None:
    """Answer newline-delimited JSON-RPC until stdin closes.

    Tool calls run on worker threads (a long poll takes up to 25 s), so `ping`
    and every other request is answered while one is pending.
    """
    write_lock = threading.Lock()

    def send(reply: dict[str, Any] | None) -> None:
        if reply is None:
            return
        with write_lock:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()

    with ThreadPoolExecutor(max_workers=CALL_WORKERS) as pool:
        for line in stdin:
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                send(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "parse error"},
                    }
                )
                continue
            if is_tool_call(message):
                pool.submit(lambda m=message: send(answer(m, call)))
            else:
                send(answer(message, call))


def main() -> int:
    call = daemon_call(varde_config_dir(), serve_version())
    serve_stdio(sys.stdin, sys.stdout, call)
    return 0
