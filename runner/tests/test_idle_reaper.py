from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from varde_runner.events import RunnerEvent
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.supervisor import Supervisor
from varde_runner.waits import approval_wait_id


@dataclass
class FakeClock:
    now: float = 0
    sleepers: list[tuple[float, asyncio.Future[None]]] = field(default_factory=list)

    async def sleep(self, seconds: float) -> None:
        future = asyncio.get_running_loop().create_future()
        self.sleepers.append((self.now + seconds, future))
        await future

    def advance(self, seconds: float) -> None:
        self.now += seconds
        for deadline, future in self.sleepers:
            if deadline <= self.now and not future.done():
                future.set_result(None)


class FakePlugin:
    capabilities = RunnerCapabilities(resume=True, idle_status=True)

    def __init__(self):
        self.stop_calls = 0
        self.resume_calls = 0

    async def start(self, _spec):
        return SessionRef("fake", "remote-session")

    async def resume(self, ref):
        self.resume_calls += 1
        return ref

    async def send(self, _ref, _prompt):
        return None

    async def events(self, _ref):
        await asyncio.Future()
        yield RunnerEvent("status", "remote-session")

    async def stop(self, _ref):
        self.stop_calls += 1

    async def close(self):
        return None


async def make_idle_session(tmp_path, clock: FakeClock, role="builder"):
    plugin = FakePlugin()
    supervisor = Supervisor(tmp_path, {"fake": plugin})
    supervisor._idle_reap_timeout_s = 10
    supervisor._idle_reap_clock = lambda: clock.now
    supervisor._idle_reap_sleep = clock.sleep
    session = await supervisor.start_session(
        SessionSpec("fake", "model", "workspace", str(tmp_path)), role
    )
    supervisor.store.update_session(
        session.session_id, status="idle", idle_status="idle"
    )
    return supervisor, plugin, session.session_id


def test_idle_session_process_is_reaped_after_deadline(tmp_path):
    async def run():
        clock = FakeClock()
        supervisor, plugin, session_id = await make_idle_session(tmp_path, clock)
        supervisor._schedule_idle_reap(session_id)
        await asyncio.sleep(0)
        assert plugin.stop_calls == 0
        clock.advance(9)
        await asyncio.sleep(0)
        assert plugin.stop_calls == 0
        clock.advance(1)
        await asyncio.gather(*tuple(supervisor._idle_reap_tasks.values()))
        assert plugin.stop_calls == 1
        assert session_id not in supervisor._refs
        row = supervisor.store.get_session(session_id)
        assert row is not None and row["ref"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_reaped_session_resumes_from_persisted_ref(tmp_path):
    async def run():
        clock = FakeClock()
        supervisor, plugin, session_id = await make_idle_session(tmp_path, clock)
        supervisor._schedule_idle_reap(session_id)
        await asyncio.sleep(0)
        clock.advance(10)
        await asyncio.gather(*tuple(supervisor._idle_reap_tasks.values()))
        await supervisor.resume(session_id, "system:dashboard")
        assert plugin.resume_calls == 1
        assert session_id in supervisor._refs
        await supervisor.shutdown()

    asyncio.run(run())


def test_running_and_pending_sessions_are_not_scheduled_for_reaping(tmp_path):
    async def run():
        for kind in ("approval", "wake"):
            clock = FakeClock()
            supervisor, plugin, session_id = await make_idle_session(
                tmp_path / kind, clock
            )
            supervisor.store.update_session(session_id, status="running")
            supervisor._schedule_idle_reap(session_id)
            assert session_id not in supervisor._idle_reap_tasks
            supervisor.store.update_session(session_id, status="idle")
            if kind == "approval":
                wait_id = approval_wait_id(session_id, "request-1")
                payload = {"request_id": "request-1"}
            else:
                wait_id = "wake:mail-1"
                payload = {"message_ids": ["mail-1"]}
            supervisor.store.create_wait(wait_id, session_id, kind, payload=payload)
            supervisor._schedule_idle_reap(session_id)
            assert session_id not in supervisor._idle_reap_tasks
            clock.advance(100)
            await asyncio.sleep(0)
            assert plugin.stop_calls == 0
            await supervisor.shutdown()

    asyncio.run(run())


def test_orchestrator_with_open_watcher_is_not_reaped(tmp_path):
    async def run():
        clock = FakeClock()
        supervisor, plugin, session_id = await make_idle_session(
            tmp_path, clock, "orchestrator"
        )
        supervisor.clients.attach(session_id, "watcher-1", "observer")
        supervisor._schedule_idle_reap(session_id)
        assert session_id not in supervisor._idle_reap_tasks
        supervisor.clients.detach(session_id, "watcher-1")
        supervisor._schedule_idle_reap(session_id)
        await asyncio.sleep(0)
        clock.advance(10)
        await asyncio.gather(*tuple(supervisor._idle_reap_tasks.values()))
        assert plugin.stop_calls == 1
        await supervisor.shutdown()

    asyncio.run(run())


def test_locked_session_send_is_not_interrupted_by_reaper(tmp_path):
    async def run():
        clock = FakeClock()
        supervisor, plugin, session_id = await make_idle_session(tmp_path, clock)
        row = supervisor.store.get_session(session_id)
        assert row is not None
        lock = supervisor._send_locks.setdefault(
            supervisor._session_lock_key(row), asyncio.Lock()
        )
        await lock.acquire()
        supervisor._schedule_idle_reap(session_id)
        await asyncio.sleep(0)
        clock.advance(10)
        await asyncio.gather(*tuple(supervisor._idle_reap_tasks.values()))
        lock.release()
        assert plugin.stop_calls == 0
        await supervisor.shutdown()

    asyncio.run(run())


def test_zero_timeout_and_no_agents_create_no_idle_timers(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path, {"fake": FakePlugin()})
        assert supervisor._idle_reap_tasks == {}
        clock = FakeClock()
        supervisor._idle_reap_timeout_s = 0
        supervisor._idle_reap_clock = lambda: clock.now
        supervisor._idle_reap_sleep = clock.sleep
        session = await supervisor.start_session(
            SessionSpec("fake", "model", "workspace", str(tmp_path)), "builder"
        )
        supervisor.store.update_session(session.session_id, status="idle")
        supervisor._schedule_idle_reap(session.session_id)
        assert supervisor._idle_reap_tasks == {}
        await supervisor.shutdown()

    asyncio.run(run())
