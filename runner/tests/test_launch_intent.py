import asyncio
import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.plugins.process_state import ProcessIdentity, persist_spec
from varde_runner.supervisor import Supervisor

FAKES = Path(__file__).parent / "fakes"


class PersistentPlugin:
    capabilities = RunnerCapabilities(
        resume=True, idle_status=True, persistent_process=True
    )

    def __init__(self, spec):
        self.spec = spec
        self.sends = []

    async def start(self, spec):
        self.spec = spec
        return SessionRef(spec.provider, "remote")

    async def resume(self, ref):
        return ref

    def _load_spec(self, ref):
        return self.spec

    async def idle_status(self, ref):
        return "idle"

    async def send(self, ref, prompt):
        self.sends.append(prompt)

    async def stop(self, ref):
        return None

    async def events(self, ref):
        if False:
            yield None

    async def close(self):
        return None


def test_persisted_spec_contains_prompt_and_is_private(tmp_path):
    path = tmp_path / "spec.json"
    persist_spec(
        path,
        SessionSpec("provider", "model", "workspace", str(tmp_path), prompt="hello"),
    )

    assert json.loads(path.read_text())["prompt"] == "hello"
    assert path.stat().st_mode & 0o777 == 0o600


def test_restart_resends_prompt_only_before_agent_output_or_running_status(tmp_path):
    async def run():
        spec = SessionSpec(
            "fake", "model", "workspace", str(tmp_path), prompt="start me"
        )
        plugin = PersistentPlugin(spec)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "runner-id", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )

        await supervisor.start()
        assert plugin.sends == ["start me"]
        assert any(
            event["kind"] == "activity"
            and event["payload"].get("message") == "launch prompt resent"
            for event in supervisor.store.events_after("runner-id", 0)
        )
        assert "runner-id" in supervisor._startup_tasks
        await supervisor.shutdown()
        supervisor.store.close()

    asyncio.run(run())


def test_restart_does_not_resend_after_output_or_running_status(tmp_path):
    async def run():
        for event_kind, payload in (
            ("text", {"text": "hello"}),
            ("status", {"status": "running"}),
        ):
            data_dir = tmp_path / event_kind
            data_dir.mkdir()
            spec = SessionSpec(
                "fake", "model", "workspace", str(data_dir), prompt="start me"
            )
            plugin = PersistentPlugin(spec)
            supervisor = Supervisor(data_dir, {"fake": plugin})
            supervisor.store.create_session(
                "runner-id",
                "fake",
                {"provider": "fake", "session_id": "remote"},
                "builder",
            )
            supervisor.store.append_event("runner-id", event_kind, payload)
            if event_kind == "status":
                supervisor.store.append_event("runner-id", "status", {"status": "idle"})

            await supervisor.start()
            assert plugin.sends == []
            assert "runner-id" not in supervisor._startup_tasks
            assert "runner-id" in supervisor._startup_send_pending
            await supervisor.shutdown()
            supervisor.store.close()

    asyncio.run(run())


def test_resume_of_live_session_does_not_resend_launch_prompt(tmp_path):
    async def run():
        spec = SessionSpec(
            "fake", "model", "workspace", str(tmp_path), prompt="start me"
        )
        plugin = PersistentPlugin(spec)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "runner-id", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )

        await supervisor.resume("runner-id", "system:dashboard")
        assert plugin.sends == ["start me"]

        await supervisor.resume("runner-id", "system:dashboard")
        assert plugin.sends == ["start me"]

        session = await supervisor.start_session(spec, "builder")
        sends_after_start = list(plugin.sends)
        await supervisor.resume(session.session_id, "system:dashboard")
        assert plugin.sends == sends_after_start
        await supervisor.shutdown()
        supervisor.store.close()

    asyncio.run(run())


def test_restart_does_not_resend_prompt_to_stopped_session(tmp_path):
    async def run():
        spec = SessionSpec(
            "fake", "model", "workspace", str(tmp_path), prompt="start me"
        )
        plugin = PersistentPlugin(spec)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        session = await supervisor.start_session(spec, "builder")
        await supervisor.stop(session.session_id, "system:dashboard")
        await supervisor.shutdown()
        supervisor.store.close()
        plugin.sends.clear()

        restarted = Supervisor(tmp_path, {"fake": plugin})
        await restarted.start()
        assert plugin.sends == []
        assert session.session_id not in restarted._startup_tasks
        await restarted.shutdown()
        restarted.store.close()

    asyncio.run(run())


def test_silent_restarts_resend_n_minus_one_times_before_parking(tmp_path):
    async def run():
        spec = SessionSpec(
            "fake", "model", "workspace", str(tmp_path), prompt="start me"
        )
        plugin = PersistentPlugin(spec)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "runner-id", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )

        for _ in range(3):
            await supervisor.start()

        row = supervisor.store.get_session("runner-id")
        assert row is not None and row["lifecycle"] == "failed"
        assert row["no_progress_restarts"] == 3
        assert plugin.sends == ["start me", "start me"]
        await supervisor.shutdown()
        supervisor.store.close()

    asyncio.run(run())


def _native_plugin(harness, state_dir):
    def identity(_pid, command):
        return ProcessIdentity("test-start", " ".join(command))

    if harness == "claude-cli":
        return ClaudeCliPlugin(
            FAKES / "fake_claude.py",
            state_dir=state_dir,
            process_inspector=identity,
        )
    return CodexAppServerPlugin(
        FAKES / "fake_codex_app_server.py",
        state_dir=state_dir,
        process_inspector=identity,
    )


def _save_prompt(plugin, ref, spec, prompt):
    path = plugin._spec_path(ref.session_id)
    value = json.loads(path.read_text())
    value["prompt"] = prompt
    plugin._write_state(path, value)
    saved_spec = replace(spec, prompt=prompt)
    if isinstance(plugin, ClaudeCliPlugin):
        plugin._specs[ref.session_id] = saved_spec
    else:
        plugin._sessions[ref.session_id].spec = saved_spec


async def _record_codex_running_status(supervisor, plugin, session_id, ref):
    await plugin.send(ref, "hold")
    for _ in range(100):
        if supervisor.store.has_status_event(session_id, "running"):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("Codex fake did not record its turn/started status")


@pytest.mark.parametrize(
    ("harness", "hang_flag"),
    [
        ("claude-cli", "FAKE_CLAUDE_HANG"),
        ("codex-app-server", "FAKE_CODEX_HANG"),
    ],
)
def test_native_resume_with_prior_progress_stays_alive(
    tmp_path, monkeypatch, harness, hang_flag
):
    async def run():
        monkeypatch.delenv(hang_flag, raising=False)
        monkeypatch.setattr(
            "varde_runner.supervisor.load_config",
            lambda *_: SimpleNamespace(
                startup_timeout_s=0.01,
                startup_kill_timeout_s=0.04,
                stall_after_s=600,
                guard=lambda: None,
            ),
        )
        state_dir = tmp_path / "native"
        plugin = _native_plugin(harness, state_dir)
        supervisor = Supervisor(tmp_path / "runner", {harness: plugin})
        try:
            spec = SessionSpec(harness, "model", "workspace", str(tmp_path))
            session = await supervisor.start_session(spec, "builder")
            remote_ref = supervisor._refs[session.session_id]
            _save_prompt(plugin, remote_ref, spec, "saved prompt")
            if harness == "codex-app-server":
                await _record_codex_running_status(
                    supervisor, plugin, session.session_id, remote_ref
                )
            else:
                for _ in range(100):
                    if supervisor.store.has_agent_output(session.session_id):
                        break
                    await asyncio.sleep(0.01)
                assert supervisor.store.has_agent_output(session.session_id)
            monkeypatch.setenv(hang_flag, "1")

            await asyncio.wait_for(supervisor.start(), 5)
            await asyncio.sleep(0.12)

            process = (
                plugin._processes[remote_ref.session_id]
                if isinstance(plugin, ClaudeCliPlugin)
                else plugin._sessions[remote_ref.session_id].process
            )
            assert process is not None and process.returncode is None
            events = supervisor.store.events_after(session.session_id, 0)
            assert not any(
                event["kind"] == "error"
                and event["payload"].get("message", "").startswith("startup silent")
                for event in events
            )
        finally:
            await asyncio.wait_for(supervisor.shutdown(), 5)

    asyncio.run(run())


@pytest.mark.parametrize(
    ("harness", "hang_flag", "seed_running_status", "expected_resends"),
    [
        ("claude-cli", "FAKE_CLAUDE_HANG", False, 2),
        ("codex-app-server", "FAKE_CODEX_HANG", True, 0),
    ],
)
def test_native_silent_restart_parking_resend_counts(
    tmp_path, monkeypatch, harness, hang_flag, seed_running_status, expected_resends
):
    async def run():
        if harness == "codex-app-server":
            monkeypatch.delenv(hang_flag, raising=False)
        else:
            monkeypatch.setenv(hang_flag, "1")
        monkeypatch.setattr(
            "varde_runner.supervisor.load_config",
            lambda *_: SimpleNamespace(
                startup_timeout_s=10,
                startup_kill_timeout_s=20,
                stall_after_s=600,
                guard=lambda: None,
            ),
        )
        state_dir = tmp_path / "native"
        plugin = _native_plugin(harness, state_dir)
        supervisor = Supervisor(tmp_path / "runner", {harness: plugin})
        try:
            spec = SessionSpec(harness, "model", "workspace", str(tmp_path))
            session = await supervisor.start_session(spec, "builder")
            remote_ref = supervisor._refs[session.session_id]
            _save_prompt(plugin, remote_ref, spec, "saved prompt")
            if seed_running_status:
                await _record_codex_running_status(
                    supervisor, plugin, session.session_id, remote_ref
                )
                monkeypatch.setenv(hang_flag, "1")

            for _ in range(3):
                await asyncio.wait_for(supervisor.start(), 5)

            row = supervisor.store.get_session(session.session_id)
            assert row is not None and row["lifecycle"] == "failed"
            assert row["no_progress_restarts"] == 3
            events = supervisor.store.events_after(session.session_id, 0)
            assert (
                sum(
                    event["kind"] == "activity"
                    and event["payload"].get("message") == "launch prompt resent"
                    for event in events
                )
                == expected_resends
            )
        finally:
            await asyncio.wait_for(supervisor.shutdown(), 5)

    asyncio.run(run())
