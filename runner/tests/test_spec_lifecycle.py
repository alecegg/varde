import asyncio
import json
import uuid
from pathlib import Path

from varde_runner.clients import SYSTEM_CLIENT_IDS
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin, ProcessIdentity
from varde_runner.plugins.process_state import persist_spec, spec_path
from varde_runner.supervisor import Supervisor

FAKE_CLAUDE = Path(__file__).parent / "fakes" / "fake_claude.py"


class SpecPlugin:
    capabilities = RunnerCapabilities(
        resume=True, idle_status=True, persistent_process=True
    )

    def __init__(self, state_dir):
        self.state_dir = state_dir
        self.sends = []

    async def start(self, spec):
        ref = SessionRef(spec.provider, str(uuid.uuid4()))
        persist_spec(spec_path(self.state_dir, ref.session_id, "Test"), spec)
        return ref

    async def resume(self, ref):
        self._load_spec(ref)
        return ref

    def _load_spec(self, ref):
        value = json.loads(
            spec_path(self.state_dir, ref.session_id, "Test").read_text()
        )
        return SessionSpec(
            **{
                key: value[key]
                for key in SessionSpec.__dataclass_fields__
                if key in value
            }
        )

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

    def remove_spec(self, session_id):
        spec_path(self.state_dir, session_id, "Test").unlink(missing_ok=True)


class PluginWithoutSpecHook:
    capabilities = RunnerCapabilities()

    async def close(self):
        return None


def test_stop_keeps_spec_and_archive_removes_it(tmp_path):
    async def run():
        plugin = SpecPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        ref = await supervisor.start_session(
            SessionSpec(
                "fake", "model", "workspace", str(tmp_path), prompt="saved prompt"
            ),
            "builder",
        )
        row = supervisor.store.get_session(ref.session_id)
        assert row is not None
        remote_id = json.loads(row["ref"])["session_id"]
        path = spec_path(tmp_path, remote_id, "Test")

        await supervisor.stop(ref.session_id, next(iter(SYSTEM_CLIENT_IDS)))
        assert path.exists()
        assert plugin._load_spec(SessionRef("fake", remote_id)).prompt == "saved prompt"

        await asyncio.wait_for(
            supervisor.resume(ref.session_id, next(iter(SYSTEM_CLIENT_IDS))), 3
        )
        assert plugin.sends == ["saved prompt"]
        assert path.exists()
        await supervisor.stop(ref.session_id, next(iter(SYSTEM_CLIENT_IDS)))

        await supervisor.archive(ref.session_id, next(iter(SYSTEM_CLIENT_IDS)))
        assert not path.exists()
        await supervisor.shutdown()
        supervisor.store.close()

    asyncio.run(run())


def test_send_triggered_resume_sends_only_the_incoming_prompt(tmp_path):
    async def run():
        plugin = SpecPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        ref = await supervisor.start_session(
            SessionSpec(
                "fake", "model", "workspace", str(tmp_path), prompt="saved prompt"
            ),
            "builder",
        )
        await supervisor.stop(ref.session_id, "system:dashboard")

        assert (
            await asyncio.wait_for(supervisor.send(ref.session_id, "user prompt"), 3)
            == "sent"
        )
        assert plugin.sends == ["user prompt"]
        assert ref.session_id in supervisor._startup_tasks
        row = supervisor.store.get_session(ref.session_id)
        assert row is not None
        assert ref.session_id not in supervisor._startup_send_pending
        await supervisor.shutdown()

    asyncio.run(run())


def test_archive_works_without_remove_spec_hook(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path, {"fake": PluginWithoutSpecHook()})
        supervisor.store.create_session(
            "session", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.archive("session", next(iter(SYSTEM_CLIENT_IDS)))
        row = supervisor.store.get_session("session")
        assert row is not None and row["lifecycle"] == "archived"
        await supervisor.shutdown()
        supervisor.store.close()

    asyncio.run(run())


def test_native_spec_survives_stop_and_resume_then_archive_removes_it(
    tmp_path, monkeypatch
):
    async def run():
        monkeypatch.setenv("FAKE_CLAUDE_HANG", "1")
        plugin = ClaudeCliPlugin(
            FAKE_CLAUDE,
            state_dir=tmp_path / "native",
            process_inspector=lambda _pid, command: ProcessIdentity(
                "test-start", " ".join(command)
            ),
        )
        supervisor = Supervisor(tmp_path / "runner", {"claude-cli": plugin})
        session = await supervisor.start_session(
            SessionSpec(
                "claude-cli",
                "model",
                "workspace",
                str(tmp_path),
                prompt="saved prompt",
            ),
            "builder",
        )
        remote_ref = supervisor._refs[session.session_id]
        path = plugin._spec_path(remote_ref.session_id)

        await supervisor.stop(session.session_id, "system:dashboard")
        assert path.exists()
        assert plugin._load_spec(remote_ref).prompt == "saved prompt"

        await asyncio.wait_for(
            supervisor.resume(session.session_id, "system:dashboard"), 3
        )
        assert path.exists()
        assert plugin._load_spec(remote_ref).prompt == "saved prompt"
        assert any(
            event["kind"] == "activity"
            and event["payload"].get("message") == "launch prompt resent"
            for event in supervisor.store.events_after(session.session_id, 0)
        )

        await supervisor.stop(session.session_id, "system:dashboard")
        await supervisor.archive(session.session_id, "system:dashboard")
        assert not path.exists()
        await supervisor.shutdown()

    asyncio.run(run())
