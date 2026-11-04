from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from varde_runner.node_host.frames import Event
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.claude_sdk.plugin import ClaudeSdkPlugin, child_env
from varde_runner.protocol import ResumeSettings, resume


class FakeSubscription:
    def __init__(self) -> None:
        self.events: asyncio.Queue[Event | None] = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self) -> Event:
        event = await self.events.get()
        if event is None:
            raise StopAsyncIteration
        return event

    def close(self) -> None:
        self.events.put_nowait(None)


class FakeHost:
    state = "ready"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.subscriptions: dict[str, FakeSubscription] = {}
        self.callbacks = []

    def subscribe(self, session: str) -> FakeSubscription:
        subscription = FakeSubscription()
        self.subscriptions[session] = subscription
        return subscription

    async def call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((method, params))
        if method == "session.start":
            return {"session": params["session"], "resumed": "resume_handle" in params}
        return {}

    def on_restart(self, callback) -> None:
        self.callbacks.append(callback)

    async def start(self) -> None:
        self.state = "ready"

    async def stop(self) -> None:
        self.state = "down"


def spec(prompt: str = "launch") -> SessionSpec:
    return SessionSpec(
        "claude-sdk", "sonnet", "ws-1", "/workspace/project", prompt, agent_id="agent-1"
    )


def test_start_persists_sdk_handle_and_passes_stream_timeout(tmp_path: Path) -> None:
    async def exercise() -> None:
        host = FakeHost()
        plugin = ClaudeSdkPlugin(
            state_dir=tmp_path,
            settings_text="[claude_sdk]\nstream_idle_timeout_s=321",
            host=host,  # type: ignore[arg-type]
        )
        ref = await plugin.start(spec())
        start = next(
            params for method, params in host.calls if method == "session.start"
        )
        assert start["stream_idle_timeout_s"] == 321
        host.subscriptions[ref.session_id].events.put_nowait(
            Event(
                "handle",
                ref.session_id,
                {"handle": "sdk-session-id", "cwd": "/workspace/project"},
                1,
            )
        )
        await asyncio.sleep(0)
        state = json.loads(next(tmp_path.glob("*.json")).read_text())
        assert state["handle"] == "sdk-session-id"
        assert start["env"]["VARDE_AGENT_ID"] == "agent-1"
        assert start["env"]["VARDE_HARNESS"] == "claude-sdk"

    asyncio.run(exercise())


def test_resume_uses_persisted_handle_and_original_cwd(tmp_path: Path) -> None:
    async def exercise() -> None:
        host = FakeHost()
        plugin = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        ref = await plugin.start(spec())
        host.subscriptions[ref.session_id].events.put_nowait(
            Event(
                "handle",
                ref.session_id,
                {"handle": "persisted-id", "cwd": "/workspace/project"},
                1,
            )
        )
        await asyncio.sleep(0)
        plugin._tasks[ref.session_id].cancel()
        plugin._tasks.pop(ref.session_id)
        await resume(plugin, ref, ResumeSettings(mode_id="read-only"))
        method, params = next(
            (method, params)
            for method, params in reversed(host.calls)
            if method == "session.start"
        )
        assert method == "session.start"
        assert params["resume_handle"] == "persisted-id"
        assert params["cwd"] == "/workspace/project"
        assert params["prompt"] == ""
        assert params["mode"] == "read-only"

    asyncio.run(exercise())


@pytest.mark.parametrize("mode_id", ["", "danger-full-access", "unknown"])
def test_resume_rejects_unsupported_mode_without_persisting(
    tmp_path: Path, mode_id: str
) -> None:
    async def exercise() -> None:
        host = FakeHost()
        plugin = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        ref = await plugin.start(spec())
        state_path = next(tmp_path.glob("*.json"))
        before = json.loads(state_path.read_text())
        with pytest.raises(ValueError, match="unsupported Claude SDK mode"):
            await plugin.resume(ref, ResumeSettings(mode_id=mode_id))
        assert json.loads(state_path.read_text()) == before
        assert [method for method, _ in host.calls].count("session.start") == 1

    asyncio.run(exercise())


def test_send_after_interrupt_resumes_from_persisted_handle(tmp_path: Path) -> None:
    async def exercise() -> None:
        host = FakeHost()
        plugin = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        ref = await plugin.start(spec())
        host.subscriptions[ref.session_id].events.put_nowait(
            Event(
                "handle",
                ref.session_id,
                {"handle": "resume-me", "cwd": "/workspace/project"},
                1,
            )
        )
        await asyncio.sleep(0)
        await plugin.interrupt(ref)
        await plugin.send(ref, "continue after interrupt")
        starts = [params for method, params in host.calls if method == "session.start"]
        assert starts[-1]["resume_handle"] == "resume-me"
        assert starts[-1]["cwd"] == "/workspace/project"
        assert host.calls[-1] == (
            "session.send",
            {"session": ref.session_id, "text": "continue after interrupt"},
        )

    asyncio.run(exercise())


def test_event_stream_continues_when_send_resumes_after_interrupt(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        host = FakeHost()
        plugin = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        ref = await plugin.start(spec())
        host.subscriptions[ref.session_id].events.put_nowait(
            Event("handle", ref.session_id, {"handle": "continue-id"}, 1)
        )
        await asyncio.sleep(0)
        stream = plugin.events(ref)
        await plugin.interrupt(ref)
        await plugin.send(ref, "continue")
        next_event = asyncio.create_task(anext(stream))
        host.subscriptions[ref.session_id].events.put_nowait(
            Event("text", ref.session_id, {"text": "resumed"}, 1)
        )
        event = await asyncio.wait_for(next_event, 1)
        assert event.kind == "text"
        assert event.payload == {"text": "resumed"}

    asyncio.run(exercise())


def test_python_restart_resumes_saved_handle_and_expires_pending_approval(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        host = FakeHost()
        original = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        ref = await original.start(spec())
        original._handles[ref.session_id] = "saved-handle"
        original._pending[ref.session_id] = {"tool-use-7"}
        original._save(ref.session_id)

        restarted = ClaudeSdkPlugin(state_dir=tmp_path, host=host)  # type: ignore[arg-type]
        await restarted.resume(ref)
        event = await anext(restarted.events(ref))
        assert event.kind == "permission_resolved"
        assert event.payload == {"request_id": "tool-use-7", "decision": "expired"}
        start = next(
            params
            for method, params in reversed(host.calls)
            if method == "session.start"
        )
        assert start["resume_handle"] == "saved-handle"
        assert start["prompt"] == ""

    asyncio.run(exercise())


def test_child_env_scrubs_credentials_and_sets_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    env = child_env(spec())
    assert not (
        {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"}
        & env.keys()
    )
    assert env["VARDE_AGENT_ID"] == "agent-1"
    assert env["VARDE_HARNESS"] == "claude-sdk"
