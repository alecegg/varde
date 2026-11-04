import asyncio
from pathlib import Path

import pytest
from test_send_path import FakePlugin
from varde_runner.clients import (
    ClientRole,
    ObserverReadOnly,
    UnknownClient,
    WriterBusy,
    WriterLeases,
)
from varde_runner.plugins import SessionSpec
from varde_runner.supervisor import SendOutcome, Supervisor
from varde_runner.waits import approval_wait_id


async def _supervisor(tmp_path: Path, *, interrupt=False):
    plugin = FakePlugin(interrupt=interrupt)
    supervisor = Supervisor(tmp_path / "store", {"fake": plugin})
    session = await supervisor.start_session(
        SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
    )
    return supervisor, plugin, session.session_id


def test_observer_and_spoofed_writer_cannot_write(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path, interrupt=True)
        watch = supervisor.watch(
            session_id, client_id="observer", role=ClientRole.OBSERVER
        )
        assert (await anext(watch))["type"] == "snapshot"

        with pytest.raises(ObserverReadOnly):
            await supervisor.send(session_id, "blocked", client_id="observer")
        with pytest.raises(ObserverReadOnly):
            await supervisor.send_with_interrupt(
                session_id, "blocked", client_id="observer"
            )
        with pytest.raises(ObserverReadOnly):
            await supervisor.respond(
                session_id, "request", "approve", client_id="observer"
            )

        with pytest.raises(ObserverReadOnly):
            await supervisor.send(session_id, "spoof", client_id="observer")
        assert plugin.send_calls == 0
        assert plugin.responses == []
        await watch.aclose()

    asyncio.run(exercise())


def test_unknown_client_rejected_and_system_attach_refused(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        with pytest.raises(UnknownClient):
            await supervisor.send(session_id, "blocked", client_id="unknown")
        with pytest.raises(UnknownClient):
            await supervisor.respond(
                session_id, "request", "approve", client_id="unknown"
            )
        system_watch = supervisor.watch(
            session_id, client_id="system:relay", role="writer"
        )
        with pytest.raises(ValueError, match="system client ids cannot attach"):
            await anext(system_watch)
        assert plugin.send_calls == 0
        assert plugin.responses == []

    asyncio.run(exercise())


def test_second_writer_is_busy_until_holder_disconnects(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        first_watch = supervisor.watch(session_id, client_id="writer-1", role="writer")
        second_watch = supervisor.watch(session_id, client_id="writer-2", role="writer")
        await anext(first_watch)
        await anext(second_watch)
        plugin.release.set()
        assert (
            await supervisor.send(session_id, "first", client_id="writer-1")
            == SendOutcome.SENT
        )
        with pytest.raises(WriterBusy) as busy:
            await supervisor.send(session_id, "second", client_id="writer-2")
        assert busy.value.holder == "writer-1"

        await first_watch.aclose()
        assert supervisor.clients.role(session_id, "writer-1") is None
        plugin.status = "idle"
        assert (
            await supervisor.send(session_id, "second", client_id="writer-2")
            == SendOutcome.SENT
        )
        await second_watch.aclose()

    asyncio.run(exercise())


def test_cancelled_writer_send_releases_lease(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        first_watch = supervisor.watch(session_id, client_id="writer-1", role="writer")
        second_watch = supervisor.watch(session_id, client_id="writer-2", role="writer")
        await anext(first_watch)
        await anext(second_watch)

        sending = asyncio.create_task(
            supervisor.send(session_id, "cancel", client_id="writer-1")
        )
        await plugin.entered.wait()
        sending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sending
        assert supervisor.writer_leases.holder(session_id) is None

        plugin.release.set()
        plugin.status = "idle"
        assert (
            await supervisor.send(session_id, "after cancel", client_id="writer-2")
            == SendOutcome.SENT
        )
        await first_watch.aclose()
        await second_watch.aclose()

    asyncio.run(exercise())


def test_system_senders_are_not_blocked_by_interactive_lease(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        writer = supervisor.watch(session_id, client_id="writer", role="writer")
        await anext(writer)
        supervisor.writer_leases.acquire(session_id, "writer")
        plugin.release.set()

        assert (
            await supervisor.send(session_id, "relay", client_id="system:relay")
            == SendOutcome.SENT
        )
        plugin.status = "idle"
        assert (
            await supervisor.send(session_id, "delivery", client_id="system:delivery")
            == SendOutcome.SENT
        )
        plugin.status = "idle"
        assert await supervisor.send(session_id, "legacy") == SendOutcome.SENT
        assert supervisor.writer_leases.holder(session_id) == "writer"
        await writer.aclose()
        assert supervisor.writer_leases.holder(session_id) is None

    asyncio.run(exercise())


def test_writer_leases_lazily_expire_and_report_holder():
    now = [10.0]
    leases = WriterLeases(timeout=5.0, clock=lambda: now[0])
    leases.acquire("session", "first")
    assert leases.holder("session") == "first"
    with pytest.raises(WriterBusy) as busy:
        leases.acquire("session", "second")
    assert busy.value.holder == "first"

    now[0] = 16.0
    assert leases.holder("session") is None
    leases.acquire("session", "second")
    assert leases.holder("session") == "second"


def test_detach_between_authorize_and_acquire_cannot_orphan_a_lease(
    tmp_path, monkeypatch
):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        watch = supervisor.watch(session_id, client_id="writer", role="writer")
        await anext(watch)
        original = supervisor._authorize_write

        def detach_after_authorize(session, row, client_id):
            result = original(session, row, client_id)
            supervisor.clients.detach(row["id"], client_id)
            return result

        monkeypatch.setattr(supervisor, "_authorize_write", detach_after_authorize)
        with pytest.raises(UnknownClient):
            await supervisor.send(session_id, "detached", client_id="writer")
        assert supervisor.writer_leases.holder(session_id) is None
        assert plugin.send_calls == 0
        await watch.aclose()

    asyncio.run(exercise())


def test_busy_writer_is_rejected_before_resume_side_effects(tmp_path, monkeypatch):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        first_watch = supervisor.watch(session_id, client_id="first", role="writer")
        second_watch = supervisor.watch(session_id, client_id="second", role="writer")
        await anext(first_watch)
        await anext(second_watch)
        plugin.release.set()
        assert (
            await supervisor.send(session_id, "first", client_id="first")
            == SendOutcome.SENT
        )

        resume_calls = []

        async def resume(ref):
            resume_calls.append(ref)
            return ref

        monkeypatch.setattr(plugin, "resume", resume)
        supervisor._refs.pop(session_id)
        with pytest.raises(WriterBusy):
            await supervisor.send(session_id, "second", client_id="second")
        assert resume_calls == []
        await first_watch.aclose()
        await second_watch.aclose()

    asyncio.run(exercise())


def test_same_client_lease_releases_only_after_last_watch_detaches(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        first = supervisor.watch(session_id, client_id="writer", role="writer")
        second = supervisor.watch(session_id, client_id="writer", role="writer")
        await anext(first)
        await anext(second)
        plugin.release.set()
        assert (
            await supervisor.send(session_id, "write", client_id="writer")
            == SendOutcome.SENT
        )
        await first.aclose()
        assert supervisor.writer_leases.holder(session_id) == "writer"
        assert supervisor.clients.role(session_id, "writer") == ClientRole.WRITER
        await second.aclose()
        assert supervisor.writer_leases.holder(session_id) is None

    asyncio.run(exercise())


def test_cancelled_watch_consumer_detaches_and_releases(tmp_path):
    async def exercise():
        supervisor, _, session_id = await _supervisor(tmp_path)
        watch = supervisor.watch(session_id, client_id="writer", role="writer")
        await anext(watch)
        supervisor.writer_leases.acquire(session_id, "writer")
        waiting = asyncio.ensure_future(anext(watch))
        await asyncio.sleep(0)
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert supervisor.clients.role(session_id, "writer") is None
        assert supervisor.writer_leases.holder(session_id) is None
        assert session_id not in supervisor.watch_hub._subscribers

    asyncio.run(exercise())


def test_unmanaged_send_does_not_create_interactive_lease(tmp_path):
    async def exercise():
        plugin = FakePlugin()
        plugin.release.set()
        supervisor = Supervisor(tmp_path / "store", {"fake": plugin})
        assert (
            await supervisor.send("external", "unmanaged", "fake") == SendOutcome.SENT
        )
        assert supervisor.store.sessions() == []
        assert supervisor.writer_leases.holder("external") is None

    asyncio.run(exercise())


def test_writer_respond_acquires_and_keeps_the_lease(tmp_path):
    async def exercise():
        supervisor, plugin, session_id = await _supervisor(tmp_path)
        watch = supervisor.watch(session_id, client_id="writer", role="writer")
        await anext(watch)
        wait_id = approval_wait_id(session_id, "request")
        supervisor.store.create_wait(wait_id, session_id, "approval")

        assert (
            await supervisor.respond(
                session_id, "request", "approve", client_id="writer"
            )
            == "responded"
        )
        assert plugin.responses == [("request", "approve")]
        assert supervisor.writer_leases.holder(session_id) == "writer"
        await watch.aclose()
        assert supervisor.writer_leases.holder(session_id) is None

    asyncio.run(exercise())
