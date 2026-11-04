from __future__ import annotations

import asyncio
import json
import os

import pytest
from varde_runner.config import PiDurableSettings
from varde_runner.node_host import Event
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.pi_durable import PiDurablePlugin
from varde_runner.protocol import ResumeSettings


class FakeHost:
    def __init__(self, *args, **_kwargs):
        self.state = "down"
        self.calls = []
        self.restart = None
        self.subscriptions = []
        self.init_args = args

    def on_restart(self, callback):
        self.restart = callback

    async def start(self):
        self.state = "ready"

    async def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        if method == "session.start":
            return {
                "session": "conversation-1",
                "resumed": bool(params.get("conversation")),
            }
        if method == "session.alive":
            return {"alive": True, "state": "running"}
        return {}

    async def stop(self):
        self.state = "down"

    def subscribe(self, _session_id):
        subscription = FakeSubscription()
        self.subscriptions.append(subscription)
        return subscription


class FakeSubscription:
    def __init__(self):
        self.queue = asyncio.Queue()

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return value

    def close(self):
        self.queue.put_nowait(None)


def _plugin(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_PROVIDER_KEY", "secret-never-persist")
    monkeypatch.setenv("VARDE_RUNNER_STATE_DIR", str(tmp_path / "data"))
    hosts = []

    def make_host(*args, **kwargs):
        host = FakeHost(*args, **kwargs)
        hosts.append(host)
        return host

    settings = PiDurableSettings(
        True, "pi-durable", "openai", "openai/gpt", "TEST_PROVIDER_KEY", 0.01
    )
    plugin = PiDurablePlugin(
        settings,
        config_text="version = 1",
        state_dir=tmp_path / "adapter",
        host_factory=make_host,
    )
    return plugin, hosts


def test_start_passes_role_identity_and_storage_to_engine_and_persists_no_key(
    tmp_path, monkeypatch
):
    async def run():
        plugin, hosts = _plugin(tmp_path, monkeypatch)
        spec = SessionSpec(
            "pi-durable",
            "openai/gpt",
            "workspace",
            str(tmp_path),
            prompt="hello",
            mode_id="workspace-write",
            agent_id="agent-1",
            role="builder",
        )
        ref = await plugin.start(spec)
        assert hosts[0].init_args[0][1].endswith("runner/node-host/host.mjs")
        assert hosts[0].init_args[1].name == "index.mjs"
        method, params = hosts[0].calls[0]
        assert method == "session.start"
        assert params["role"] == "builder"
        assert params["env"]["VARDE_AGENT_ID"] == "agent-1"
        assert params["env"]["VARDE_HARNESS"] == "pi-durable"
        assert plugin.process_alive(ref)
        await plugin.send_with_id(ref, "again", "retry-stable-id")
        assert hosts[0].calls[-1] == (
            "session.send",
            {
                "session": ref.session_id,
                "text": "again",
                "requestId": "retry-stable-id",
            },
        )
        persisted = plugin._state_path.read_text()
        assert "secret-never-persist" not in persisted
        assert os.stat(plugin._state_path).st_mode & 0o777 == 0o600
        await plugin.close()

    asyncio.run(run())


def test_resume_rejects_mode_before_mutating_persisted_spec(tmp_path, monkeypatch):
    async def run():
        plugin, hosts = _plugin(tmp_path, monkeypatch)
        spec = SessionSpec(
            "pi-durable",
            "openai/gpt",
            "workspace",
            str(tmp_path),
            mode_id="workspace-write",
            role="builder",
        )
        ref = await plugin.start(spec)
        original = json.loads(plugin._state_path.read_text())[ref.session_id]["spec"][
            "mode_id"
        ]
        with pytest.raises(ValueError, match="does not support mode"):
            await plugin.resume(ref, ResumeSettings(mode_id="full-access"))
        current = json.loads(plugin._state_path.read_text())[ref.session_id]["spec"][
            "mode_id"
        ]
        assert current == original == "workspace-write"
        assert len(hosts[0].calls) == 1
        await plugin.close()

    asyncio.run(run())


def test_silent_turn_is_flagged_without_stopping_host(tmp_path, monkeypatch):
    async def run():
        plugin, hosts = _plugin(tmp_path, monkeypatch)
        ref = await plugin.start(
            SessionSpec(
                "pi-durable",
                "openai/gpt",
                "workspace",
                str(tmp_path),
                mode_id="workspace-write",
                role="builder",
            )
        )
        events = plugin.events(ref)
        event = await asyncio.wait_for(anext(events), 1)
        assert event.kind == "status"
        assert event.payload == {"status": "running", "silent": True}
        assert hosts[0].state == "ready"
        hosts[0].subscriptions[0].queue.put_nowait(
            Event(
                "message",
                ref.session_id,
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "awake"}],
                    "cursor": 1,
                },
                1,
            )
        )
        resumed = await anext(events)
        assert resumed.kind == "status"
        assert resumed.payload == {"status": "running", "silent": False}
        assert (await anext(events)).payload["text"] == "awake"
        await events.aclose()
        await plugin.close()

    asyncio.run(run())


def test_event_cursor_is_saved_after_the_consumer_resumes(tmp_path, monkeypatch):
    async def run():
        plugin, hosts = _plugin(tmp_path, monkeypatch)
        ref = await plugin.start(
            SessionSpec(
                "pi-durable",
                "openai/gpt",
                "workspace",
                str(tmp_path),
                mode_id="workspace-write",
                role="builder",
            )
        )
        events = plugin.events(ref)
        first_task = asyncio.create_task(anext(events))
        while not hosts[0].subscriptions:
            await asyncio.sleep(0)
        subscription = hosts[0].subscriptions[0]
        subscription.queue.put_nowait(
            Event(
                "message",
                ref.session_id,
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "hello"}],
                    "cursor": 1,
                },
                1,
            )
        )
        subscription.queue.put_nowait(
            Event(
                "message",
                ref.session_id,
                {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "world"}],
                    "cursor": 2,
                },
                2,
            )
        )
        first = await first_task
        assert first.kind == "text"
        assert first.payload["text"] == "hello"
        assert plugin._sessions[ref.session_id]["cursor"] == 0
        second = await anext(events)
        assert second.payload["text"] == "world"
        assert plugin._sessions[ref.session_id]["cursor"] == 1
        await events.aclose()
        await plugin.close()

    asyncio.run(run())
