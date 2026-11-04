from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from varde_runner.events import RunnerEvent
from varde_runner.harness_map import paseo_settings
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.varde_cli import VardeCLI
from varde_runner.web.app import _permission_decision

PASEO_CLI = Path("/Applications/Paseo.app/Contents/Resources/bin/paseo")


class _PaseoStatus:
    def __init__(self, plugin: PaseoPlugin) -> None:
        self.plugin = plugin

    async def idle_status(self, session_id: str) -> str:
        return await self.plugin.idle_status(SessionRef("paseo", session_id))


def test_missing_paseo_sidecar_dependency_has_install_instructions(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        plugin = PaseoPlugin(tmp_path / "unused.sock", "ws://unused")
        plugin._client_package = tmp_path / "missing" / "@getpaseo" / "client"

        with pytest.raises(RuntimeError, match="npm ci --prefix runner/sidecar"):
            await plugin._ensure_started()

        assert plugin._server is None

    asyncio.run(exercise())


def test_permission_option_maps_to_decision():
    assert (
        _permission_decision(
            "Allow", [{"id": "allow-once", "label": "Allow", "kind": "allow"}]
        )
        == "allow"
    )


def test_permission_wait_keeps_event_stream_open_across_poll_timeout() -> None:
    class FakePlugin:
        async def inspect(self, ref: SessionRef) -> dict[str, object]:
            return {"pending_permissions": []}

    class FakeAdapter:
        async def idle_status(self, session_id: str) -> str:
            return "running"

    async def events():
        await asyncio.sleep(0.6)
        yield RunnerEvent(
            kind="permission_requested",
            session_id="session-a",
            payload={"request_id": "permission-a"},
        )

    async def exercise() -> None:
        ref = SessionRef("paseo", "session-a")
        request_id, event = await _permission_until_idle(
            FakePlugin(), FakeAdapter(), ref, events(), timeout=2
        )
        assert request_id == "permission-a"
        assert event is not None and event.kind == "permission_requested"

    asyncio.run(exercise())


def test_permission_resolution_can_precede_idle_status() -> None:
    class FakeAdapter:
        def __init__(self) -> None:
            self.statuses = iter(("running", "idle"))

        async def idle_status(self, session_id: str) -> str:
            return next(self.statuses)

    async def exercise() -> None:
        await _wait_for_status(FakeAdapter(), "session-a", "idle", timeout=2)

    asyncio.run(exercise())


@pytest.mark.skipif(
    os.environ.get("VARDE_RUNNER_PASEO_LIVE") != "1",
    reason="set VARDE_RUNNER_PASEO_LIVE=1 to use the approved live Paseo agent",
)
def test_real_paseo_registry_delivery_and_re_adoption(tmp_path: Path) -> None:
    if not PASEO_CLI.is_file():
        pytest.skip(f"Paseo CLI not found at {PASEO_CLI}")
    workspace_id = os.environ.get("VARDE_RUNNER_PASEO_WORKSPACE_ID")
    workspace_cwd = os.environ.get("VARDE_RUNNER_PASEO_CWD")
    if not workspace_id or not workspace_cwd:
        pytest.skip("set VARDE_RUNNER_PASEO_WORKSPACE_ID and VARDE_RUNNER_PASEO_CWD")
    asyncio.run(_exercise(tmp_path, workspace_id, workspace_cwd))


async def _exercise(tmp_path: Path, workspace_id: str, cwd: str) -> None:
    address = f"1d-live-{uuid.uuid4().hex[:12]}"
    plugin = PaseoPlugin(
        Path("/tmp") / f"vr-{uuid.uuid4().hex[:16]}.sock",  # noqa: S108 - Unix socket fixture uses a short path for platform limits.
        _daemon_url(),
    )
    registry_path = tmp_path / "registry.json"
    ref: SessionRef | None = None
    try:
        marker = await _new_address_marker(address, cwd)
        prompt, ref, permission_probe_path = await _start_live_session(
            plugin, address, marker, workspace_id, cwd
        )
        binding = SessionBinding(
            address, "codex-app-server", "paseo", ref.session_id, "builder"
        )
        registry = SessionRegistry(registry_path)
        registry.expect_marker(marker)
        assert registry.bind_first_prompt(prompt, binding)
        await _send_cli_message(address, cwd)
        await asyncio.sleep(1)
        assert await plugin.idle_status(ref) == "running"

        stream = plugin.events(ref)
        await _handle_permission_and_reconnect(
            plugin, _PaseoStatus(plugin), ref, stream, permission_probe_path
        )
        adopted_registry = SessionRegistry(registry_path)
        adopted = adopted_registry.resolve(address)
        assert adopted == binding
        await plugin.resume(ref)
        assert adopted_registry.resolve(address) == binding
        (tmp_path / "agent-id").write_text(ref.session_id, encoding="utf-8")
    finally:
        if ref:
            await plugin.stop(ref)
        await plugin.close()


async def _new_address_marker(address: str, cwd: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "varde",
        "msg",
        "address",
        "new",
        address,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await process.communicate()
    if process.returncode:
        raise AssertionError("varde msg address new failed")
    return stdout.decode().strip()


async def _start_live_session(
    plugin, address: str, marker: str, workspace_id: str, cwd: str
) -> tuple[str, SessionRef, Path]:
    settings = paseo_settings(
        {
            "harness": "codex-app-server",
            "model": "gpt-6-luna",
            "reasoning_effort": "low",
            "mode": "auto",
        }
    )
    permission_probe_path = (
        Path("/Users/alec/Library") / f"varde-probe-{uuid.uuid4().hex}.txt"
    )
    path = str(permission_probe_path)
    prompt = (
        f"""{marker}
You are a coding agent with a shell tool in the repository at your """
        f"working directory. "
        f"Use your shell tool now to create the file {path} containing the word ok "
        f"(run: echo ok > {path}). If the sandbox blocks it, request approval to "
        "run it outside the sandbox. Do nothing else."
    )
    ref = await plugin.start(
        SessionSpec(
            provider=str(settings["paseo_provider"]),
            model=str(settings["model"]),
            reasoning_effort=str(settings["thinking_option_id"]),
            mode_id=str(settings["mode_id"]),
            workspace_id=workspace_id,
            cwd=cwd,
            prompt=prompt,
        )
    )
    assert (await plugin.inspect(ref)).get("current_mode_id") == "auto"
    return prompt, ref, permission_probe_path


async def _send_cli_message(address: str, cwd: str) -> None:
    process = await asyncio.create_subprocess_exec(
        "varde",
        "msg",
        "send",
        "--from",
        "1D-builder",
        "--to",
        address,
        "--kind",
        "info",
        "deliver this once",
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await process.communicate()
    if process.returncode:
        raise AssertionError("varde msg send failed")
    messages = VardeCLI(cwd=Path(cwd)).read_messages()
    assert any(
        message.get("to") == address and message.get("text") == "deliver this once"
        for message in messages
    )


async def _handle_permission_and_reconnect(
    plugin, adapter, ref, stream, permission_probe_path: Path
) -> None:
    permission_id, request_event = await _permission_until_idle(
        plugin, adapter, ref, stream, 90
    )
    if not permission_id:
        await stream.aclose()
        return
    assert request_event is not None
    assert request_event.kind == "permission_requested"
    assert request_event.kind != "status"
    await plugin.respond_permission(ref, permission_id, "deny")
    assert not permission_probe_path.exists()
    while True:
        event = await _next_event(stream, 20)
        if event.kind == "permission_resolved":
            break
    await _wait_for_status(adapter, ref.session_id, "idle", 90)
    await stream.aclose()

    process = plugin._process
    assert process is not None
    process.kill()
    await asyncio.wait_for(process.wait(), timeout=10)
    queue = plugin._event_queue(ref.session_id)
    while not queue.empty():
        queue.get_nowait()
    await plugin.resume(ref)
    reconnected = plugin.events(ref)
    deadline = asyncio.get_running_loop().time() + 30
    while asyncio.get_running_loop().time() < deadline:
        try:
            event = await _next_event(reconnected, 5)
        except TimeoutError:
            continue
        if event.kind == "status" and event.payload.get("status") == "idle":
            await reconnected.aclose()
            return
    raise TimeoutError("restarted Paseo sidecar did not report the idle status")


def _daemon_url() -> str:
    result = subprocess.run(  # noqa: S603 - Test invokes the local relay CLI with controlled fixture arguments.
        [str(PASEO_CLI), "daemon", "status", "--json"],
        check=True,
        capture_output=True,
        text=True,
    )
    status = json.loads(result.stdout)
    if status.get("localDaemon") != "running":
        raise AssertionError(
            f"Paseo daemon is not running: {status.get('localDaemon')}"
        )
    return f"ws://{status['listen']}/ws"


async def _wait_for_status(
    adapter: Any, session_id: str, expected: str, timeout: int
) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if await adapter.idle_status(session_id) == expected:
            return
        await asyncio.sleep(1)
    raise TimeoutError(f"Paseo agent {session_id} did not become {expected}")


async def _permission_until_idle(plugin, adapter, ref, stream, timeout: int):
    deadline = asyncio.get_running_loop().time() + timeout
    event_task: asyncio.Task | None = None
    try:
        while asyncio.get_running_loop().time() < deadline:
            if event_task is None:
                event_task = asyncio.create_task(anext(stream))
            snapshot = await plugin.inspect(ref)
            pending = snapshot.get("pending_permissions", [])
            pending_id = pending[0].get("requestId") if pending else None
            done, _ = await asyncio.wait({event_task}, timeout=0.5)
            event = None
            if done:
                try:
                    event = event_task.result()
                except StopAsyncIteration as exc:
                    if await adapter.idle_status(ref.session_id) == "idle":
                        return None, None
                    raise RuntimeError(
                        "Paseo event stream ended before the session idled"
                    ) from exc
                event_task = None
            if event and event.kind == "permission_requested":
                request_id = event.payload.get("request_id")
                assert request_id
                return str(request_id), event
            if pending_id and not event:
                continue
            if await adapter.idle_status(ref.session_id) == "idle":
                return None, None
    finally:
        if event_task is not None and not event_task.done():
            event_task.cancel()
            with suppress(asyncio.CancelledError):
                await event_task
    raise TimeoutError(
        f"Paseo agent {ref.session_id} neither requested permission nor became idle"
    )


async def _next_event(stream, timeout: int):
    return await asyncio.wait_for(anext(stream), timeout=timeout)
