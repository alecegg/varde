from __future__ import annotations

import asyncio
import json
import os
import runpy
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from typing import Any

from fakes.plugin import FakePlugin
from starlette.applications import Starlette
from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_runner.config import Role, RoleConfig
from varde_runner.plugins import RunnerCapabilities, SessionRef
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin, ProcessIdentity
from varde_runner.plugins.claude_cli.plugin import child_env as claude_child_env
from varde_runner.plugins.claude_cli.wire import parse_line
from varde_runner.plugins.registry import PluginRegistry
from varde_runner.web.app import create_app

_NATIVE_SMOKE = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts" / "native_smoke.py")
)


async def _request(app: Starlette, method: str, path: str, payload=None):
    body = json.dumps(payload).encode() if payload is not None else b""
    messages = []
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:80")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 80),
        },
        receive,
        send,
    )
    return messages[0]["status"], json.loads(messages[1].get("body", b"{}"))


def _event_line(event) -> bytes:
    return (
        f"data: {json.dumps({'kind': event.kind, 'payload': event.payload})}\n".encode()
    )


async def _emit_events(plugin, ref, events) -> None:
    for event in events:
        await plugin.emit(ref, event)


class _DriverAPI:
    def __init__(self, app, loop, plugin) -> None:
        self.app = app
        self.loop = loop
        self.plugin = plugin
        self.agent_id = ""

    def request(self, path: str, payload: dict[str, Any] | None = None):
        status, body = asyncio.run_coroutine_threadsafe(
            _request(self.app, "POST", path, payload), self.loop
        ).result()
        if path == "/api/agents":
            self.agent_id = body["agent_id"]
        return {"http_status": status, "body": body}

    def events(self, agent_id: str, _client: str, _timeout: float):
        assert agent_id == self.agent_id
        ref = SessionRef("claude_cli", "remote-1")
        turn_events = parse_line(
            json.dumps(
                {
                    "type": "result",
                    "subtype": "success",
                    "result": "initial complete",
                }
            ),
            ref.session_id,
        )
        asyncio.run_coroutine_threadsafe(
            _emit_events(self.plugin, ref, turn_events), self.loop
        ).result()
        text_events = [
            parse_line(
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {"content": [{"type": "text", "text": text}]},
                    }
                ),
                ref.session_id,
            )[0]
            for text in ("ok", "woke")
        ]
        idle = parse_line(
            json.dumps(
                {
                    "type": "system",
                    "subtype": "session_state_changed",
                    "state": {"name": "idle"},
                }
            ),
            ref.session_id,
        )[0]
        stream_events = [
            turn_events[0],
            text_events[0],
            *turn_events[1:],
            text_events[1],
            idle,
        ]
        return BytesIO(b"".join(_event_line(event) for event in stream_events))


async def _wait_for_turn_end(app, agent_id: str) -> None:
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        events = app.state.supervisor.store.latest_events(agent_id, 20)
        if any(event["kind"] == "session_end" for event in events):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Claude result frame was not recorded")


async def _wait_for_delivery(app) -> None:
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        if app.state.relay_worker.last_delivery:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(
        f"relay did not wake agent: {app.state.relay_worker.snapshot()}"
    )


async def _drive_mail_wake(app, plugin, workspace: Path, working: Path):
    loop = asyncio.get_running_loop()
    api = _DriverAPI(app, loop, plugin)
    driver_globals = _NATIVE_SMOKE["drive"].__globals__
    send_smoke_mail = driver_globals["send_smoke_mail"]
    binding_before_mail = []

    def send_mail_after_turn(working_dir):
        asyncio.run_coroutine_threadsafe(
            _wait_for_turn_end(app, api.agent_id), loop
        ).result()
        binding = _NATIVE_SMOKE["relay_data_state"](working_dir)["binding"]
        binding_before_mail.append(binding)
        native_env = claude_child_env(plugin.started[-1])
        varde = shutil.which("varde")
        assert varde is not None
        subprocess.run(  # noqa: S603 - Test calls the resolved Varde CLI with fixed args.
            [varde, "hook", "user-prompt-submit", "--harness", "claude"],
            cwd=working_dir,
            env={**os.environ, **native_env},
            input=json.dumps(
                {
                    "session_id": binding["session_id"],
                    "prompt": plugin.started[-1].prompt,
                }
            ),
            text=True,
            capture_output=True,
            check=True,
        )
        status = asyncio.run_coroutine_threadsafe(
            app.state.supervisor.target_idle_status(
                api.agent_id, native_env["VARDE_HARNESS"]
            ),
            loop,
        ).result()
        assert status == "idle"
        binding_before_mail.append(
            _NATIVE_SMOKE["relay_data_state"](working_dir)["binding"]
        )
        sent = send_smoke_mail(working_dir)
        asyncio.run_coroutine_threadsafe(_wait_for_delivery(app), loop).result()
        return sent

    driver_globals["send_smoke_mail"] = send_mail_after_turn
    try:
        note = await asyncio.to_thread(
            _NATIVE_SMOKE["drive"],
            api,
            "claude_cli",
            "builder",
            str(workspace),
            "initial prompt",
            3,
            "test-model",
            "reply",
            True,
            str(working),
        )
    finally:
        driver_globals["send_smoke_mail"] = send_smoke_mail
    return note, binding_before_mail


def test_lifespan_relay_wakes_runner_launched_address(tmp_path, monkeypatch) -> None:
    async def exercise():
        working = tmp_path / "working"
        workspace = tmp_path / "workspace"
        config = tmp_path / "config"
        state = tmp_path / "state"
        working.mkdir()
        workspace.mkdir()
        config.mkdir()
        env = _NATIVE_SMOKE["runner_environment"](config, state, working)
        for key, value in env.items():
            is_smoke_setting = key.startswith(("VARDE_RUNNER_", "VARDE_DATA_"))
            if is_smoke_setting or key == "VARDE_WORKING_DIR":
                monkeypatch.setenv(key, value)
        monkeypatch.setenv("VARDE_RUNNER_RELAY", "data")
        monkeypatch.setenv("PASEO_AGENT_ID", "leak-test-id")
        monkeypatch.setenv("VARDE_AGENT_ID", str(workspace))
        monkeypatch.setenv("VARDE_HARNESS", "claude_cli")
        monkeypatch.setattr(
            "varde_runner.agent_launch.load_config",
            lambda *_args: RoleConfig(
                {"builder": Role("claude_cli", "model", "low", "auto", ())}, ()
            ),
        )
        plugin = FakePlugin(RunnerCapabilities(idle_status=True))
        registry = PluginRegistry(["claude_cli"])
        registry.register("claude_cli", plugin)
        monkeypatch.setattr("varde_runner.web.app.build_registry", lambda: registry)

        class CLI:
            def read_messages(self):
                return []

            def read_plan(self):
                return {"plans": []}

            def read_address_bindings(self):
                return []

            def read_message_status(self):
                return {"messages": []}

            def send(self, **_kwargs):
                return {"id": "delivery"}

        app = create_app(data_dir=tmp_path / "runner", cli=CLI(), bound_port=80)
        async with app.router.lifespan_context(app):
            note, binding_before_mail = await _drive_mail_wake(
                app, plugin, workspace, working
            )

            assert "error" not in note, note.get("error")
            agent_id = note["agent_id"]
            assert (
                app.state.supervisor._session_row(agent_id, "claude-cli")["harness"]
                == "claude-cli"
            )
            assert note["initial_reply"] == "ok"
            assert note["wake_reply"] == "woke"
            assert binding_before_mail[0] is not None

            assert binding_before_mail[0]["wake_context"]["agent_id"] == agent_id
            assert binding_before_mail[1]["wake_context"]["agent_id"] == agent_id
            assert "paseo_id" not in binding_before_mail[0]["wake_context"]
            assert "paseo_id" not in binding_before_mail[1]["wake_context"]
            assert (
                note["relay_data_state"]["binding"]["wake_context"]["agent_id"]
                == agent_id
            )
            assert "paseo_id" not in note["relay_data_state"]["binding"]["wake_context"]

            planned = app.state.relay_worker.snapshot()["last_plan"]
            assert planned is not None
            assert len(planned["actions"]) == 1
            assert planned["actions"][0]["wake"]["agent_id"] == agent_id
            assert plugin.sent, app.state.relay_worker.last_delivery
            assert plugin.sent[-1][0] == "remote-1"
            assert "Acknowledge with" in plugin.sent[-1][1]
            assert app.state.relay_worker.last_delivery["result"] != "failed"
            assert app.state.relay_worker.snapshot()["state"] == "waiting"

    asyncio.run(exercise())


def test_claude_result_frame_keeps_address_binding_after_api_launch(
    tmp_path, monkeypatch
) -> None:
    async def exercise():
        working = tmp_path / "working"
        workspace = tmp_path / "workspace"
        config = tmp_path / "config"
        state = tmp_path / "state"
        for path in (working, workspace, config):
            path.mkdir()
        env = _NATIVE_SMOKE["runner_environment"](config, state, working)
        for key, value in env.items():
            is_smoke_setting = key.startswith(("VARDE_RUNNER_", "VARDE_DATA_"))
            if is_smoke_setting or key == "VARDE_WORKING_DIR":
                monkeypatch.setenv(key, value)
        monkeypatch.setattr(
            "varde_runner.agent_launch.load_config",
            lambda *_args: RoleConfig(
                {"builder": Role("claude_cli", "model", "low", "auto", ())}, ()
            ),
        )
        executable = Path(__file__).parent / "fakes" / "fake_claude.py"
        plugin = ClaudeCliPlugin(
            executable,
            state_dir=state / "claude-cli",
            process_inspector=lambda _pid, command: ProcessIdentity(
                "fake-start", " ".join(command)
            ),
        )
        registry = PluginRegistry(["claude_cli"])
        registry.register("claude_cli", plugin)
        monkeypatch.setattr("varde_runner.web.app.build_registry", lambda: registry)
        app = create_app(data_dir=tmp_path / "runner", bound_port=80)
        async with app.router.lifespan_context(app):
            status, result = await _request(
                app,
                "POST",
                "/api/agents",
                {
                    "harness": "claude_cli",
                    "workspace": str(workspace),
                    "role": "builder",
                    "prompt": "initial prompt",
                    "address": {"slot": "smoke-orch", "plan": "smoke-plan"},
                },
            )
            assert status == 201
            agent_id = result["agent_id"]
            session_id = next(iter(plugin._processes))
            ref = SessionRef("claude-cli", session_id)
            await plugin.send(ref, "complete")

            async def wait_for_turn_end():
                deadline = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < deadline:
                    if any(
                        event["kind"] == "session_end"
                        for event in app.state.supervisor.store.latest_events(
                            agent_id, 20
                        )
                    ):
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError("Claude result frame was not recorded")

            await wait_for_turn_end()
            binding = open_data(working, load_data_config()).addresses.current_binding(
                "smoke-orch"
            )
            assert binding is not None
            assert binding.extra["wake_context"]["agent_id"] == agent_id
            await plugin.send(ref, "fail")

            async def wait_for_process_death():
                deadline = asyncio.get_running_loop().time() + 3
                while asyncio.get_running_loop().time() < deadline:
                    if any(
                        event["kind"] == "session_end"
                        and event["payload"].get("terminal") is True
                        for event in app.state.supervisor.store.latest_events(
                            agent_id, 20
                        )
                    ):
                        return
                    await asyncio.sleep(0.01)
                raise AssertionError("Claude process-death event was not recorded")

            await wait_for_process_death()
            assert (
                open_data(working, load_data_config()).addresses.current_binding(
                    "smoke-orch"
                )
                is None
            )

    asyncio.run(exercise())
