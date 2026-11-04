"""Compatibility subprocess adapter for runner relay cutover.

Rollback covers relay commands only; runner address reads use the data layer.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.views.msg_status import runner_relay_alive


def parse_relay_mode(value: str | None) -> str | None:
    """Normalize the runner relay selector; unset or 0/off disables app startup."""
    if value in {None, "", "0", "off"}:
        return None
    if value == "1":
        return "data"
    if value in {"cli", "data"}:
        return value
    raise ValueError("VARDE_RUNNER_RELAY must be cli, data, 1, 0, or off")


def _data(stdout: str) -> dict[str, Any]:
    value = json.loads(stdout)
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    value = value.get("data", value)
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return value


class RelayCommandError(RuntimeError):
    def __init__(self, returncode: int, message: str):
        super().__init__(message)
        self.returncode = returncode


def command_error(
    code: int, stdout: str, stderr: str, args: tuple[str, ...]
) -> RelayCommandError:
    message = stderr.strip() or stdout.strip()
    if not message:
        message = f"varde {shlex.join(args)} exited {code}"
    return RelayCommandError(code, message)


class RelayCLI:
    """Async subprocess wrapper for the installed varde command."""

    def __init__(self, *, cwd: Path | None = None, env: dict[str, str] | None = None):
        self.env = {**os.environ, **(env or {})}
        working = self.env.get("VARDE_WORKING_DIR")
        if cwd is not None:
            cwd = cwd.expanduser().resolve()
        elif working:
            cwd = Path(working).expanduser().resolve()
        if cwd is None:
            raise ValueError("RelayCLI requires cwd or VARDE_WORKING_DIR")
        self.cwd = cwd
        self.env["VARDE_WORKING_DIR"] = str(cwd)

    async def run(self, *args: str) -> tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            "varde",
            *args,
            cwd=self.cwd,
            env=self.env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await process.communicate()
        except BaseException:
            process.kill()
            await process.wait()
            raise
        return process.returncode or 0, stdout.decode(), stderr.decode()

    async def json(self, *args: str) -> dict[str, Any]:
        code, stdout, stderr = await self.run(*args)
        if code:
            raise command_error(code, stdout, stderr, args)
        return _data(stdout)

    async def status(self) -> dict[str, Any]:
        data = open_data(self.cwd, load_data_config())
        addresses = data.addresses
        snapshot = await asyncio.to_thread(addresses.relay_snapshot)
        now = datetime.now(UTC)
        mailmen = [
            {
                "id": token,
                "alive": await asyncio.to_thread(addresses.mailman_alive, token, now),
            }
            for token in snapshot.mailman_started
        ]
        current = await asyncio.to_thread(addresses.current_token, "mailman")
        bindings = await asyncio.to_thread(addresses.list_bindings)
        bound_addresses = {binding.address for binding in bindings}
        pending = await asyncio.to_thread(data.messages.pending_by_address)
        bad = any(
            address not in bound_addresses
            or any(
                (now - datetime.fromisoformat(message.ts)).total_seconds()
                > (
                    600
                    if message.kind in {"needs-user", "blocked", "merge-ready", "stale"}
                    else 1800
                )
                for message in pending_messages
            )
            for address, pending_messages in pending.items()
        )
        relay_alive = runner_relay_alive(
            {
                "current_mailman": snapshot.current_mailman,
                "events": [dict(event) for event in snapshot.events],
            },
            now,
        )
        return {
            "runner_relay": "up" if relay_alive else "down",
            "mailman": "alive"
            if any(row["id"] == current and row["alive"] for row in mailmen)
            else "dead"
            if current
            else "none",
            "mailmen": mailmen,
            "bad": bad,
        }

    async def bindings(self) -> list[dict[str, Any]]:
        result = await self.json("msg", "address", "list", "--json")
        bindings = result.get("bindings", [])
        return [item for item in bindings if isinstance(item, dict)]

    async def issue_and_bind(self, session_id: str) -> str:
        return await self._issue_and_bind(session_id, supersede=False)

    async def issue_and_bind_superseding(self, session_id: str) -> str:
        return await self._issue_and_bind(session_id, supersede=True)

    async def _issue_and_bind(self, session_id: str, *, supersede: bool) -> str:
        args = ["msg", "address", "new", "mailman"]
        if supersede:
            args.append("--supersede")
        code, marker, stderr = await self.run(*args)
        if code:
            raise command_error(code, marker, stderr, tuple(args))
        marker = marker.strip()
        code, stdout, stderr = await self.run(
            "msg",
            "address",
            "bind",
            marker,
            # The core keys bindings by harness/session, but relay leases and
            # liveness use token IDs.
            "--harness",
            "codex",
            "--session",
            session_id,
        )
        if code:
            raise command_error(
                code,
                stdout,
                stderr,
                (
                    "msg",
                    "address",
                    "bind",
                    marker,
                    "--harness",
                    "codex",
                    "--session",
                    session_id,
                ),
            )
        bindings = await self.json("msg", "address", "list", "--json")
        for binding in bindings.get("bindings", []):
            if (
                binding.get("address") == "mailman"
                and binding.get("session_id") == session_id
            ):
                return str(binding["token_id"])
        raise RuntimeError("mailman binding was not created")

    async def wait(self, identity: str) -> dict[str, Any]:
        return await self.json(
            "msg", "relay", "--wait", "--timeout", "60", "--as", identity
        )

    async def confirm(
        self,
        action_id: str,
        result: str,
        evidence: str,
        identity: str,
        *,
        harness: str,
    ) -> None:
        declared_harness = harness if harness in {"claude", "codex"} else "unknown"
        await self.json(
            "msg",
            "relay",
            "confirm",
            action_id,
            "--result",
            result,
            "--evidence",
            evidence,
            # Only harnesses with a mailbox receipt can enter the receipt wait.
            "--harness",
            declared_harness,
            "--by",
            identity,
        )

    async def renew(self, action_id: str) -> dict[str, Any]:
        return await self.json("msg", "relay", "renew", action_id)

    async def end(self, identity: str) -> None:
        await self.json("msg", "relay", "end", "--as", identity)

    async def unbind(self, session_id: str) -> None:
        args = ("msg", "address", "unbind", session_id)
        code, stdout, stderr = await self.run(*args)
        if code:
            raise command_error(code, stdout, stderr, args)
