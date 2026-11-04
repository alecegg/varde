import asyncio

import pytest
from fakes.plugin import FakePlugin
from varde_runner.clients import ClientRole, ObserverReadOnly, WriterBusy
from varde_runner.plugins import RunnerCapabilities, SessionSpec
from varde_runner.protocol import UnsupportedCapability
from varde_runner.supervisor import SendOutcome, Supervisor


def setup_supervisor(tmp_path, capabilities=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    plugin = FakePlugin(capabilities)
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    ref = asyncio.run(
        supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
    )
    row = supervisor.resolve_session(ref.session_id)
    assert row is not None
    return supervisor, plugin, ref, row


def test_stop_stops_owned_process_and_is_idempotent(tmp_path):
    supervisor, plugin, ref, row = setup_supervisor(tmp_path)

    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    asyncio.run(supervisor.stop(row["agent_id"], "system:dashboard"))

    assert plugin.stopped == ["remote-1"]
    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "completed"


def test_archive_refuses_running_and_is_terminal(tmp_path):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)

    with pytest.raises(RuntimeError, match="running"):
        asyncio.run(supervisor.archive(ref.session_id, "system:dashboard"))

    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    asyncio.run(supervisor.archive(ref.session_id, "system:dashboard"))
    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "archived"
    assert ref.session_id not in supervisor._refs
    assert plugin.stopped == ["remote-1"]


def test_interrupt_success_timeout_and_unsupported(tmp_path):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)
    assert asyncio.run(supervisor.interrupt(ref.session_id, "system:dashboard")) is None
    assert plugin.interrupted == ["remote-1"]

    plugin.interrupt_sets_idle = False
    supervisor.interrupt_timeout = 0
    outcome = asyncio.run(supervisor.interrupt(ref.session_id, "system:dashboard"))
    assert outcome == SendOutcome.FAILED_INTERRUPT

    other, _plugin, other_ref, _row = setup_supervisor(
        tmp_path / "unsupported", RunnerCapabilities(resume=True)
    )
    with pytest.raises(UnsupportedCapability):
        asyncio.run(other.interrupt(other_ref.session_id, "system:dashboard"))


def test_interrupt_does_not_resume_stopped_session(tmp_path):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))

    with pytest.raises(RuntimeError, match="not live"):
        asyncio.run(supervisor.interrupt(ref.session_id, "system:dashboard"))
    assert plugin.resumed == []
    assert plugin.interrupted == []


def test_observer_cannot_interrupt(tmp_path):
    supervisor, _plugin, ref, _row = setup_supervisor(tmp_path)
    supervisor.clients.attach(ref.session_id, "observer", ClientRole.OBSERVER)

    with pytest.raises(ObserverReadOnly):
        asyncio.run(supervisor.interrupt(ref.session_id, "observer"))


@pytest.mark.parametrize("action", ["stop", "archive", "resume"])
def test_lifecycle_actions_require_writer_and_respect_lease(tmp_path, action):
    supervisor, _plugin, ref, _row = setup_supervisor(tmp_path)
    supervisor.clients.attach(ref.session_id, "observer", ClientRole.OBSERVER)
    supervisor.clients.attach(ref.session_id, "writer", ClientRole.WRITER)
    supervisor.clients.attach(ref.session_id, "another-writer", ClientRole.WRITER)
    method = getattr(supervisor, action)

    with pytest.raises(ObserverReadOnly):
        asyncio.run(method(ref.session_id, "observer"))

    supervisor.writer_leases.acquire(ref.session_id, "writer")
    if action == "resume":
        with pytest.raises(WriterBusy):
            asyncio.run(method(ref.session_id, "another-writer"))
    elif action == "archive":
        with pytest.raises(RuntimeError):
            asyncio.run(method(ref.session_id, "another-writer"))
        assert supervisor.writer_leases.holder(ref.session_id) == "writer"
        return
    else:
        asyncio.run(method(ref.session_id, "another-writer"))
        assert supervisor.writer_leases.holder(ref.session_id) is None

    if action == "resume":
        asyncio.run(method(ref.session_id, "writer"))
    assert supervisor.writer_leases.holder(ref.session_id) is None


def test_resume_success_and_unsupported(tmp_path):
    supervisor, plugin, ref, _row = setup_supervisor(tmp_path)
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    asyncio.run(supervisor.resume(ref.session_id, "system:dashboard"))
    assert plugin.resumed == ["remote-1"]

    other, _plugin, other_ref, _row = setup_supervisor(
        tmp_path / "unsupported", RunnerCapabilities()
    )
    with pytest.raises(UnsupportedCapability):
        asyncio.run(other.resume(other_ref.session_id, "system:dashboard"))


def test_resume_refuses_archived_session(tmp_path):
    supervisor, _plugin, ref, _row = setup_supervisor(tmp_path)
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))
    asyncio.run(supervisor.archive(ref.session_id, "system:dashboard"))

    with pytest.raises(RuntimeError, match="archived"):
        asyncio.run(supervisor.resume(ref.session_id, "system:dashboard"))


def test_stop_then_failing_event_stream_keeps_completed(tmp_path, monkeypatch):
    supervisor, plugin, ref, row = setup_supervisor(tmp_path)
    asyncio.run(supervisor.stop(ref.session_id, "system:dashboard"))

    async def fail_events(ref):
        del ref
        raise RuntimeError("event stream failed")
        yield  # Make this an async generator.

    monkeypatch.setattr(plugin, "events", fail_events)
    asyncio.run(supervisor._consume_events(row["id"], plugin, ref, 0))

    resolved = supervisor.resolve_session(ref.session_id)
    assert resolved is not None and resolved["lifecycle"] == "completed"


def test_unknown_agent_raises(tmp_path):
    supervisor = Supervisor(tmp_path, {"fake": FakePlugin()})
    for operation in (
        lambda: supervisor.stop("missing", "system:dashboard"),
        lambda: supervisor.archive("missing", "system:dashboard"),
        lambda: supervisor.interrupt("missing", "system:dashboard"),
        lambda: supervisor.resume("missing", "system:dashboard"),
    ):
        with pytest.raises(KeyError):
            asyncio.run(operation())
