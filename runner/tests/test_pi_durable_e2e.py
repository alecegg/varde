from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from threading import Event, Thread

import pytest
from varde_runner.config import PiDurableSettings
from varde_runner.plugins import SessionSpec
from varde_runner.plugins.pi_durable import PiDurablePlugin

pytestmark = pytest.mark.slow

RUNNER = Path(__file__).resolve().parents[1]
ENGINE = RUNNER / "node-host/engines/durable/index.mjs"
FAKE_PROVIDER = Path(__file__).parent / "fakes/fake_pi_durable_provider.mjs"


def _plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, tool=None, hold=False):
    state = tmp_path / "scenario.json"
    requests = tmp_path / "requests.jsonl"
    started = tmp_path / "provider-started"
    effect_started = tmp_path / "effect-started"
    effect_target = (
        tmp_path / tool["arguments"]["path"]
        if tool and tool.get("name") == "write"
        else None
    )
    state.write_text(
        json.dumps(
            {
                "requests": str(requests),
                "started": str(started),
                "effectStarted": str(effect_started),
                "effectTarget": str(effect_target) if effect_target else None,
                "firstTool": tool,
                "holdFirst": hold,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_RUNNER_STATE_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VARDE_PI_DURABLE_FAKE_PROVIDER", str(state))
    monkeypatch.setenv("NODE_OPTIONS", f"--import={FAKE_PROVIDER}")
    monkeypatch.setenv("OPENAI_API_KEY", "test-only-fake-key")
    engine = Path(os.environ.get("VARDE_PI_DURABLE_ENGINE_PATH", ENGINE))
    monkeypatch.setattr(
        "varde_runner.plugins.pi_durable.plugin.node_host_engine_path",
        lambda _name: engine,
    )
    plugin = PiDurablePlugin(
        PiDurableSettings(
            True, "pi-durable", "openai", "openai/gpt-4o-mini", "OPENAI_API_KEY", 30
        ),
        config_text="version = 1",
        state_dir=tmp_path / "adapter",
    )
    spec = SessionSpec(
        "pi-durable",
        "openai/gpt-4o-mini",
        "workspace",
        str(tmp_path),
        mode_id="workspace-write",
        role="builder",
        agent_id="e2e-agent",
    )
    return plugin, spec, requests, started


async def _next_text(events, timeout=15):
    while True:
        event = await asyncio.wait_for(anext(events), timeout)
        if event.kind == "text":
            return event


def test_safe_tool_and_event_resume_have_no_gaps_or_duplicates(tmp_path, monkeypatch):
    async def run():
        (tmp_path / "known.txt").write_text("safe result", encoding="utf-8")
        plugin, spec, requests, _ = _plugin(
            tmp_path,
            monkeypatch,
            tool={"name": "read", "arguments": {"path": "known.txt"}},
        )
        ref = await plugin.start(spec)
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "run the configured safe faux tool")
            tool_result = await asyncio.wait_for(anext(events), 15)
            while tool_result.kind != "tool_result":
                tool_result = await asyncio.wait_for(anext(events), 15)
            assert "safe result" in str(tool_result.payload)
            await _next_text(events)

            seen = []
            for index in range(100):
                await plugin.send(ref, f"turn {index}")
                seen.append((await _next_text(events)).payload["text"])
            assert seen == ["fake reply"] * 100
            assert len(requests.read_text(encoding="utf-8").splitlines()) == 102
        finally:
            await events.aclose()
            await plugin.close()

    asyncio.run(run())


def test_approval_gated_bash_survives_kill_nine_and_runs_once(tmp_path, monkeypatch):
    async def run():
        marker = tmp_path / "effect.txt"
        command = f"printf effect >> {marker}"
        plugin, spec, _requests, _started = _plugin(
            tmp_path,
            monkeypatch,
            tool={"name": "bash", "arguments": {"command": command}},
        )
        ref = await plugin.start(spec)
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "request an approved faux bash call")
            approval = await asyncio.wait_for(anext(events), 15)
            assert approval.kind == "permission_requested"
            host = plugin._host
            assert host is not None and host.pid is not None
            old_pid = host.pid
            os.killpg(old_pid, signal.SIGKILL)
            for _ in range(500):
                if host.state == "ready" and host.pid != old_pid:
                    break
                await asyncio.sleep(0.02)
            assert host.state == "ready" and host.pid != old_pid
            await events.aclose()
            events = plugin.events(ref)
            await plugin.respond_permission(
                ref, approval.payload["request_id"], "approve"
            )
            result = await asyncio.wait_for(anext(events), 20)
            while result.kind != "tool_result":
                result = await asyncio.wait_for(anext(events), 20)
            await _next_text(events, 20)
            assert marker.read_text(encoding="utf-8") == "effect"
        finally:
            await events.aclose()
            await plugin.close()

    asyncio.run(run())


def test_interrupted_unsafe_write_is_reported_partial_and_not_replayed(
    tmp_path, monkeypatch
):
    async def run():
        target = tmp_path / "large.txt"
        os.mkfifo(target)
        effect_started = tmp_path / "effect-started"
        plugin, spec, requests, _ = _plugin(
            tmp_path,
            monkeypatch,
            tool={
                "name": "write",
                "arguments": {
                    "path": "large.txt",
                    "content": "x" * 2_000_000,
                },
            },
        )
        ref = await plugin.start(spec)
        events = plugin.events(ref)
        try:
            await plugin.send(ref, "write the configured large file")
            intent = await asyncio.wait_for(anext(events), 20)
            while intent.kind != "tool_intent":
                intent = await asyncio.wait_for(anext(events), 20)
            host = plugin._host
            assert host is not None and host.pid is not None
            old_pid = host.pid

            reader_open = Event()
            release_reader = Event()

            def hold_fifo_reader() -> None:
                with target.open("rb", buffering=0):
                    reader_open.set()
                    release_reader.wait(15)

            reader = Thread(target=hold_fifo_reader, daemon=True)
            reader.start()
            for _ in range(500):
                if effect_started.exists():
                    break
                await asyncio.sleep(0.01)
            assert effect_started.exists(), "fake write did not open the FIFO"
            assert reader_open.is_set()
            os.killpg(old_pid, signal.SIGKILL)
            release_reader.set()
            reader.join(timeout=5)
            for _ in range(500):
                if host.state == "ready" and host.pid != old_pid:
                    break
                await asyncio.sleep(0.02)
            assert host.state == "ready" and host.pid != old_pid
            await events.aclose()
            events = plugin.events(ref)
            partial = await asyncio.wait_for(anext(events), 30)
            while partial.kind != "tool_result":
                partial = await asyncio.wait_for(anext(events), 30)
            assert "partial" in str(partial.payload).lower()
            recovered = [
                json.loads(line)
                for line in requests.read_text(encoding="utf-8").splitlines()
            ]
            assert len(recovered) == 2
            assert "partial" in json.dumps(recovered[1]).lower()
        finally:
            await events.aclose()
            await plugin.close()

    asyncio.run(run())


def test_storage_fence_refuses_a_second_plugin_writer(tmp_path, monkeypatch):
    async def run():
        first, spec, _requests, _started = _plugin(tmp_path, monkeypatch)
        await first.start(spec)
        second = PiDurablePlugin(
            first.settings,
            config_text="version = 1",
            state_dir=tmp_path / "other-adapter",
        )
        try:
            with pytest.raises(Exception, match="fence|locked|writer|storage"):
                await second.start(spec)
        finally:
            await second.close()
            await first.close()

    asyncio.run(run())


def test_kill_nine_mid_model_call_recovers_without_repeating_committed_reply(
    tmp_path, monkeypatch
):
    async def run():
        plugin, spec, requests, started = _plugin(tmp_path, monkeypatch, hold=True)
        ref = await plugin.start(spec)
        events = plugin.events(ref)
        await plugin.send(ref, "call that gets interrupted")
        try:
            for _ in range(300):
                if started.exists():
                    break
                await asyncio.sleep(0.02)
            assert started.exists(), "fake model request did not start"
            host = plugin._host
            assert host is not None and host.pid is not None
            os.killpg(host.pid, signal.SIGKILL)
            for _ in range(500):
                if (
                    host.state == "ready"
                    and len(requests.read_text().splitlines()) >= 2
                ):
                    break
                await asyncio.sleep(0.02)
            assert host.state == "ready"
            reply = await _next_text(events, 30)
            assert reply.payload["text"] == "fake reply"
            assert len(requests.read_text(encoding="utf-8").splitlines()) == 2
        finally:
            await events.aclose()
            await plugin.close()

    asyncio.run(run())
