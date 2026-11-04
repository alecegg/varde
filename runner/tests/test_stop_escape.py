import asyncio
import time
from pathlib import Path

import pytest
from fakes.plugin import FakePlugin
from varde_runner.clients import ClientRole, ObserverReadOnly, UnknownClient
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin
from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin
from varde_runner.supervisor import SendOutcome, Supervisor


def setup_supervisor(tmp_path):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    ref = asyncio.run(
        supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
    )
    row = supervisor.resolve_session(ref.session_id)
    assert row is not None
    return supervisor, plugin, ref, row


@pytest.mark.parametrize("failure", [False, True])
def test_stop_escapes_foreign_lease_and_stuck_send(tmp_path, failure):
    supervisor, plugin, ref, row = setup_supervisor(tmp_path)
    supervisor.stop_lock_timeout_s = 0.01
    supervisor.clients.attach(ref.session_id, "sender", ClientRole.WRITER)
    supervisor.clients.attach(ref.session_id, "stopper", ClientRole.WRITER)
    supervisor.writer_leases.acquire(ref.session_id, "sender")

    async def run():
        started = asyncio.Event()
        release = asyncio.Event()

        async def send(ref: SessionRef, prompt: str) -> None:
            del ref, prompt
            started.set()
            await release.wait()
            if failure:
                raise RuntimeError("send failed")

        plugin.send = send
        send_task = asyncio.create_task(
            supervisor.send(ref.session_id, "hello", client_id="sender")
        )
        await started.wait()
        await supervisor.stop(ref.session_id, "stopper")
        completed = supervisor.resolve_session(ref.session_id)
        assert completed is not None and completed["lifecycle"] == "completed"
        release.set()
        assert await send_task == (SendOutcome.FAILED if failure else SendOutcome.SENT)

    asyncio.run(run())
    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "completed"
    assert supervisor.writer_leases.holder(ref.session_id) is None
    events = supervisor.store.events_after(row["id"], 0)
    assert any(
        event["kind"] == "activity"
        and event["payload"].get("message") == "stop proceeded without send lock"
        for event in events
    )


def native_plugin(
    harness: str, state_dir: Path
) -> ClaudeCliPlugin | CodexAppServerPlugin:
    fakes = Path(__file__).parent / "fakes"
    if harness == "claude-cli":
        return ClaudeCliPlugin(fakes / "fake_claude.py", state_dir=state_dir)
    return CodexAppServerPlugin(fakes / "fake_codex_app_server.py", state_dir=state_dir)


def native_pid(plugin: ClaudeCliPlugin | CodexAppServerPlugin, ref: SessionRef) -> int:
    if isinstance(plugin, ClaudeCliPlugin):
        process = plugin._processes[ref.session_id]
    else:
        process = plugin._sessions[ref.session_id].process
    assert process is not None
    return process.pid


@pytest.mark.parametrize("harness", ["claude-cli", "codex-app-server"])
def test_stop_escapes_stuck_send_with_native_fakes(tmp_path, harness):
    plugin = native_plugin(harness, tmp_path / "state")
    supervisor = Supervisor(tmp_path / "runner", {harness: plugin})
    supervisor.stop_lock_timeout_s = 0.05
    stop_bound_s = 2 * plugin.stop_timeout + supervisor.stop_lock_timeout_s

    async def run():
        session = await supervisor.start_session(
            SessionSpec(harness, "model", "workspace", str(tmp_path)), "builder"
        )
        supervisor.clients.attach(session.session_id, "sender", ClientRole.WRITER)
        supervisor.clients.attach(session.session_id, "stopper", ClientRole.WRITER)
        pid = native_pid(plugin, supervisor._refs[session.session_id])
        started = asyncio.Event()
        release = asyncio.Event()

        async def send(ref: SessionRef, prompt: str) -> None:
            del ref, prompt
            started.set()
            await release.wait()

        plugin.send = send  # type: ignore[method-assign]
        send_task = asyncio.create_task(
            supervisor.send(session.session_id, "hello", client_id="sender")
        )
        await started.wait()
        began = time.monotonic()
        await supervisor.stop(session.session_id, "stopper")
        assert time.monotonic() - began < stop_bound_s
        assert not plugin.process_group_exists(pid)
        release.set()
        await send_task
        row = supervisor.resolve_session(session.session_id)
        assert row is not None and row["lifecycle"] == "completed"
        await supervisor.shutdown()

    asyncio.run(run())


def test_archive_stopped_session_clears_foreign_lease(tmp_path):
    supervisor, _plugin, ref, _row = setup_supervisor(tmp_path)
    supervisor.clients.attach(ref.session_id, "holder", ClientRole.WRITER)
    supervisor.clients.attach(ref.session_id, "archiver", ClientRole.WRITER)
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    supervisor.writer_leases.acquire(ref.session_id, "holder")

    asyncio.run(supervisor.archive(ref.session_id, "archiver"))

    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "archived"
    assert supervisor.writer_leases.holder(ref.session_id) is None


@pytest.mark.parametrize(
    "role, error",
    [(ClientRole.OBSERVER, ObserverReadOnly), (None, UnknownClient)],
)
def test_stop_still_rejects_nonwriters(tmp_path, role, error):
    supervisor, _plugin, ref, _row = setup_supervisor(tmp_path)
    if role is not None:
        supervisor.clients.attach(ref.session_id, "not-writer", role)

    with pytest.raises(error):
        asyncio.run(supervisor.stop(ref.session_id, "not-writer"))


def test_rejected_archive_keeps_writer_lease(tmp_path):
    supervisor, _plugin, ref, row = setup_supervisor(tmp_path)
    supervisor.clients.attach(ref.session_id, "holder", ClientRole.WRITER)
    supervisor.clients.attach(ref.session_id, "archiver", ClientRole.WRITER)
    supervisor.store.update_session(row["id"], status="running")
    supervisor.writer_leases.acquire(ref.session_id, "holder")

    with pytest.raises(RuntimeError):
        asyncio.run(supervisor.archive(ref.session_id, "archiver"))

    assert supervisor.writer_leases.holder(ref.session_id) == "holder"


def test_failed_plugin_stop_keeps_writer_lease(tmp_path):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)
    supervisor.clients.attach(ref.session_id, "holder", ClientRole.WRITER)
    supervisor.clients.attach(ref.session_id, "stopper", ClientRole.WRITER)
    supervisor.writer_leases.acquire(ref.session_id, "holder")

    async def failing_stop(ref: SessionRef) -> None:
        del ref
        raise RuntimeError("stop failed")

    plugin.stop = failing_stop
    with pytest.raises(RuntimeError):
        asyncio.run(supervisor.stop(ref.session_id, "stopper"))

    assert supervisor.writer_leases.holder(ref.session_id) == "holder"


@pytest.mark.parametrize("failure", [False, True])
def test_interrupt_send_does_not_reopen_stopped_session(tmp_path, failure):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)
    supervisor.stop_lock_timeout_s = 0.01
    original_interrupt = plugin.interrupt
    session_id = ref.session_id

    async def interrupt_then_stop(ref: SessionRef) -> None:
        await original_interrupt(ref)
        await supervisor.stop(session_id, "system:dashboard")

    async def send(ref: SessionRef, prompt: str) -> None:
        del ref, prompt
        if failure:
            raise RuntimeError("send failed")

    plugin.interrupt = interrupt_then_stop
    plugin.send = send
    outcome = asyncio.run(
        supervisor.send_with_interrupt(ref.session_id, "hello", client_id=None)
    )

    assert outcome == (SendOutcome.FAILED if failure else SendOutcome.SENT)
    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "completed"
