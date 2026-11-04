import asyncio
from types import SimpleNamespace

import pytest
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.supervisor import Supervisor


class SilentPlugin:
    capabilities = RunnerCapabilities(
        resume=True, idle_status=True, persistent_process=True
    )

    def __init__(self):
        self.stopped = False

    async def start(self, spec):
        return SessionRef("provider", "remote")

    async def events(self, ref):
        while True:
            await asyncio.sleep(10)
            if False:
                yield None

    async def stop(self, ref):
        self.stopped = True

    async def close(self):
        pass


def test_silent_start_warns_then_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.01, startup_kill_timeout_s=0.03),
    )

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "m", "w", str(tmp_path), prompt="hello"), "builder"
        )
        await asyncio.sleep(0.06)
        row = supervisor.store.get_session(session.session_id)
        assert row is not None
        events = supervisor.store.latest_events(session.session_id, 20)
        assert plugin.stopped
        assert row["status"] == "error"
        assert any(event["kind"] == "warning" for event in events)
        await supervisor.shutdown()

    asyncio.run(run())


def test_agent_status_and_usage_do_not_cancel_watchdog(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.01, startup_kill_timeout_s=0.03),
    )

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "m", "w", str(tmp_path), prompt="hello"), "builder"
        )
        await supervisor.record_event(
            session.session_id, "status", {"status": "running"}
        )
        await supervisor.record_event(session.session_id, "usage", {})
        await asyncio.sleep(0.06)
        assert plugin.stopped
        await supervisor.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("harness", ["claude-cli", "codex-app-server"])
def test_fake_processes_are_stopped_by_watchdog(tmp_path, monkeypatch, harness):
    from pathlib import Path

    fake_dir = Path(__file__).parent / "fakes"
    if harness == "claude-cli":
        monkeypatch.setenv("FAKE_CLAUDE_HANG", "1")
        plugin = ClaudeCliPlugin(
            fake_dir / "fake_claude.py", state_dir=tmp_path / "state"
        )
    else:
        monkeypatch.setenv("FAKE_CODEX_HANG", "1")
        plugin = CodexAppServerPlugin(
            fake_dir / "fake_codex_app_server.py", state_dir=tmp_path / "state"
        )
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.1, startup_kill_timeout_s=0.25),
    )

    async def run():
        supervisor = Supervisor(tmp_path / "runner", {harness: plugin})
        unbound = []
        monkeypatch.setattr(supervisor, "_unbind_address_binding", unbound.append)
        session = await supervisor.start_session(
            SessionSpec(harness, "model", "workspace", str(tmp_path), prompt="start"),
            "builder",
        )
        ref = supervisor._refs[session.session_id]
        if isinstance(plugin, ClaudeCliPlugin):
            process = plugin._processes[ref.session_id]
        else:
            process = plugin._sessions[ref.session_id].process
        assert process is not None
        pid = process.pid
        await asyncio.sleep(0.6)
        assert process.returncode is not None
        assert not plugin.process_group_exists(pid)
        row = supervisor.store.get_session(session.session_id)
        assert row is not None
        assert row["status"] == "error"
        assert session.session_id in unbound
        await supervisor.shutdown()

    asyncio.run(run())


@pytest.mark.parametrize("event_kind,payload", [("text", {"text": "ready"})])
def test_agent_output_cancels_kill(tmp_path, monkeypatch, event_kind, payload):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.01, startup_kill_timeout_s=0.04),
    )

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "m", "w", str(tmp_path), prompt="hello"), "builder"
        )
        await supervisor.record_event(session.session_id, event_kind, payload)
        await asyncio.sleep(0.06)
        assert not plugin.stopped
        await supervisor.shutdown()

    asyncio.run(run())


def test_warn_only_zero_kill_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.01, startup_kill_timeout_s=0),
    )

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "m", "w", str(tmp_path), prompt="hello"), "builder"
        )
        await asyncio.sleep(0.04)
        assert not plugin.stopped
        assert any(
            event["kind"] == "warning"
            for event in supervisor.store.latest_events(session.session_id, 20)
        )
        await supervisor.shutdown()

    asyncio.run(run())


def test_stop_during_startup_silence_cancels_kill(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "varde_runner.supervisor.load_config",
        lambda *_: SimpleNamespace(startup_timeout_s=0.01, startup_kill_timeout_s=0.04),
    )

    async def run():
        plugin = SilentPlugin()
        supervisor = Supervisor(tmp_path, {"provider": plugin})
        session = await supervisor.start_session(
            SessionSpec("provider", "m", "w", str(tmp_path), prompt="hello"), "builder"
        )
        await asyncio.sleep(0.02)
        # Detach the watcher so its own cleanup cannot cancel the kill task;
        # stop() alone must cancel it.
        watcher = supervisor._session_event_tasks.pop(session.session_id)
        await supervisor.stop(session.session_id, "system:dashboard")
        await asyncio.sleep(0.06)
        watcher.cancel()
        row = supervisor.store.get_session(session.session_id)
        assert row is not None
        events = supervisor.store.latest_events(session.session_id, 20)
        assert row["lifecycle"] == "completed"
        assert row["status"] == "completed"
        assert not any(
            "process stopped" in str(event.get("payload")) for event in events
        )
        await supervisor.shutdown()

    asyncio.run(run())
