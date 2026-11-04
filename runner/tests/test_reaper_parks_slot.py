"""The idle reaper parks a session's durable slot and resume unparks it."""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from test_idle_reaper import FakeClock, FakePlugin
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_runner import slot_park
from varde_runner.lease_keeper import expire_tick
from varde_runner.plugins import SessionSpec
from varde_runner.supervisor import Supervisor

SLOT = "plan-builder"


def _sqlite_data(root: Path):
    initialize(root)
    database = root / QUEUE_DATABASE
    with sqlite3.connect(database) as db:
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    return open_data(root, DataConfig())


async def _idle_session(data_dir: Path, clock: FakeClock):
    plugin = FakePlugin()
    supervisor = Supervisor(data_dir, {"fake": plugin})
    supervisor._idle_reap_timeout_s = 10
    supervisor._idle_reap_clock = lambda: clock.now
    supervisor._idle_reap_sleep = clock.sleep
    session = await supervisor.start_session(
        SessionSpec("fake", "model", "workspace", str(data_dir)), "builder"
    )
    supervisor.store.update_session(
        session.session_id, status="idle", idle_status="idle"
    )
    return supervisor, plugin, session.session_id


async def _reap(supervisor, clock: FakeClock, session_id: str) -> None:
    supervisor._schedule_idle_reap(session_id)
    await asyncio.sleep(0)
    clock.advance(10)
    await asyncio.gather(*tuple(supervisor._idle_reap_tasks.values()))


def _register_claim(data, session_id: str, *, lease_s: int = 5) -> None:
    data.slots.register(
        SLOT,
        plan_id="plan",
        role="builder",
        agent_ref="agent-1",
        session_id=session_id,
        lease_s=lease_s,
    )
    data.queue.enqueue(QueueItemInput("item", "plan", queue_name="roles/plan"))
    data.slots.claim(SLOT, epoch=1, queue_name="roles/plan", lease_s=lease_s)


def test_reap_parks_slot_and_claims_outlive_the_normal_lease(
    tmp_path, monkeypatch
) -> None:
    async def run():
        working = tmp_path / "working"
        data = _sqlite_data(working)
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, plugin, session_id = await _idle_session(tmp_path / "data", clock)
        _register_claim(data, session_id)

        await _reap(supervisor, clock, session_id)

        assert plugin.stop_calls == 1
        assert data.slots.show(SLOT).state == "parked"
        later = datetime.now(UTC) + timedelta(seconds=60)
        assert expire_tick(data.queue, later) == 0
        assert data.slots.reclaim_stale(later.isoformat()).reclaimed == ()
        assert [item.id for item in data.slots.claimed(SLOT)] == ["item"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_resume_unparks_the_parked_slot(tmp_path, monkeypatch) -> None:
    async def run():
        working = tmp_path / "working"
        data = _sqlite_data(working)
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, _plugin, session_id = await _idle_session(tmp_path / "data", clock)
        _register_claim(data, session_id)
        await _reap(supervisor, clock, session_id)
        assert data.slots.show(SLOT).state == "parked"

        await supervisor.resume(session_id, "system:dashboard")

        assert data.slots.show(SLOT).state == "active"
        assert [item.id for item in data.slots.claimed(SLOT)] == ["item"]
        await supervisor.shutdown()

    asyncio.run(run())


def test_auto_resume_on_send_unparks_the_slot(tmp_path, monkeypatch) -> None:
    async def run():
        working = tmp_path / "working"
        data = _sqlite_data(working)
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, plugin, session_id = await _idle_session(tmp_path / "data", clock)
        _register_claim(data, session_id)
        await _reap(supervisor, clock, session_id)
        assert data.slots.show(SLOT).state == "parked"

        await supervisor.send(session_id, "wake")

        assert plugin.resume_calls == 1
        assert data.slots.show(SLOT).state == "active"
        await supervisor.shutdown()

    asyncio.run(run())


def test_startup_resume_unparks_the_slot(tmp_path, monkeypatch) -> None:
    async def run():
        working = tmp_path / "working"
        data = _sqlite_data(working)
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, _plugin, session_id = await _idle_session(tmp_path / "data", clock)
        _register_claim(data, session_id)
        await _reap(supervisor, clock, session_id)
        assert data.slots.show(SLOT).state == "parked"
        await supervisor.shutdown()

        plugin = FakePlugin()
        restarted = Supervisor(tmp_path / "data", {"fake": plugin})
        await restarted.start()

        assert plugin.resume_calls == 1
        assert data.slots.show(SLOT).state == "active"
        await restarted.shutdown()

    asyncio.run(run())


def test_session_without_a_slot_reaps_and_resumes(tmp_path, monkeypatch) -> None:
    async def run():
        working = tmp_path / "working"
        data = _sqlite_data(working)
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, plugin, session_id = await _idle_session(tmp_path / "data", clock)

        await _reap(supervisor, clock, session_id)
        await supervisor.resume(session_id, "system:dashboard")

        assert plugin.stop_calls == 1
        assert data.slots.by_session(session_id) is None
        await supervisor.shutdown()

    asyncio.run(run())


def test_markdown_store_does_not_block_reaping(tmp_path, monkeypatch) -> None:
    async def run():
        working = tmp_path / "working"
        working.mkdir()
        monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
        clock = FakeClock()
        supervisor, plugin, session_id = await _idle_session(tmp_path / "data", clock)

        await _reap(supervisor, clock, session_id)

        assert plugin.stop_calls == 1
        assert not (working / ".cache" / "data" / "queue.sqlite3").exists()
        await supervisor.shutdown()

    asyncio.run(run())


def test_store_open_failure_does_not_block_reaping(tmp_path, monkeypatch) -> None:
    async def run():
        monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
        clock = FakeClock()
        supervisor, plugin, session_id = await _idle_session(tmp_path / "data", clock)

        def fail(_working):
            raise OSError("store unavailable")

        monkeypatch.setattr(slot_park, "open_data", fail)
        await _reap(supervisor, clock, session_id)

        assert plugin.stop_calls == 1
        await supervisor.shutdown()

    asyncio.run(run())
