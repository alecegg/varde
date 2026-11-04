"""Read Codex's hook trust status through its local app server."""

from __future__ import annotations

import json
import os
import selectors
import shutil
import subprocess
import time
from contextlib import suppress
from pathlib import Path
from typing import Any


def untrusted_varde_hooks(
    response: dict[str, Any], cwd: Path | None = None
) -> list[dict[str, str]]:
    """Return Varde hooks Codex reports as untrusted or modified."""
    result = response.get("result")
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list):
        return []
    entries = [entry for entry in data if isinstance(entry, dict)]
    if cwd is not None:
        requested_cwd = _resolved_path(str(cwd))
        matching = [
            entry
            for entry in entries
            if _resolved_path(entry.get("cwd")) == requested_cwd
        ]
        entries = matching or entries
    found = []
    for entry in entries:
        hooks = entry.get("hooks")
        if not isinstance(hooks, list):
            continue
        for hook in hooks:
            if not isinstance(hook, dict):
                continue
            command = hook.get("command")
            status = hook.get("trustStatus")
            if (
                isinstance(command, str)
                and "varde hook" in command
                and isinstance(status, str)
                and status.lower() in ("untrusted", "modified")
            ):
                key = hook.get("key")
                found.append(
                    {
                        "key": str(key or hook.get("eventName") or "unknown"),
                        "state": status.lower(),
                        "command": command,
                    }
                )
    return found


def _resolved_path(value: Any) -> Path | None:
    if not isinstance(value, str):
        return None
    try:
        return Path(value).resolve()
    except OSError:
        return None


def query_hooks(cwd: Path) -> dict[str, Any] | None:
    """Query hooks/list; return None when Codex is absent or unavailable."""
    executable = shutil.which("codex")
    if executable is None:
        return None
    process = None
    try:
        process = subprocess.Popen(  # noqa: S603 - discovered Codex app-server executable
            [executable, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
        )
        if process.stdin is None or process.stdout is None:
            return None
        requests = (
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {"name": "varde", "version": "0"},
                    "capabilities": {},
                },
            },
            {"jsonrpc": "2.0", "method": "initialized", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "hooks/list",
                "params": {"cwds": [str(cwd)]},
            },
        )
        for request in requests:
            process.stdin.write((json.dumps(request) + "\n").encode())
        process.stdin.flush()
        deadline = time.monotonic() + 10
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = b""
        try:
            while True:
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    message = json.loads(line)
                    if isinstance(message, dict) and message.get("id") == 2:
                        return (
                            message if isinstance(message.get("result"), dict) else None
                        )
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return None
                chunk = os.read(process.stdout.fileno(), 65536)
                if not chunk:
                    return None
                buffer += chunk
        finally:
            selector.close()
    except OSError, ValueError, subprocess.SubprocessError:
        return None
    finally:
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            with suppress(OSError):
                process.terminate()
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
    return None
