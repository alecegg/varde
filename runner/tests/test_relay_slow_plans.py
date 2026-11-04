from __future__ import annotations

import asyncio
import threading
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from test_relay_triggers import FakeProvider, bind
from varde_data.records.messages import NewMessage
from varde_runner.relay import DataRelay, RelayWorker

PLAN_COUNT = 300


def _stalled_plans() -> dict[str, Any]:
    newest = datetime.now(UTC).timestamp() - 3600
    return {
        "plans": [
            {
                "id": f"plan-{index}",
                "assigned_to": "owner",
                "idle_no_handback": True,
                "newest_activity": newest,
                "done": 1,
                "total": 3,
                "state": "active",
            }
            for index in range(PLAN_COUNT)
        ],
        "events": [],
    }


class HangingOwnerProvider(FakeProvider):
    async def target_idle_status(self, agent_id, _harness=None):
        if agent_id == "owner-agent":
            await asyncio.Event().wait()
        return "idle"


async def _delivered_before_deadline(
    adapter: DataRelay, provider: FakeProvider, seconds: float
) -> tuple[float, str]:
    bind(adapter, "main", "main-agent")
    adapter.messages.append(
        NewMessage("orchestrator", "main", "merge-ready", "merge request ready")
    )
    worker = RelayWorker(adapter, provider)
    started = time.monotonic()
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(provider.sent_event.wait(), timeout=seconds)
        return time.monotonic() - started, worker.state
    finally:
        worker._stop = True
        adapter.stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_slow_plan_watch_does_not_delay_first_wake(tmp_path: Path):
    release = threading.Event()

    def slow_watch(_stale):
        release.wait(10)
        return _stalled_plans()

    async def exercise():
        provider = FakeProvider()
        adapter = DataRelay(tmp_path, supervisor=provider, plan_watch=slow_watch)
        try:
            elapsed, _ = await _delivered_before_deadline(adapter, provider, 3)
        finally:
            release.set()
        assert elapsed < 3

    asyncio.run(exercise())


def test_hanging_stall_probe_does_not_block_wakes(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("varde_runner.relay.STALL_TIMEOUT", 0.2)

    async def exercise():
        provider = HangingOwnerProvider()
        adapter = DataRelay(
            tmp_path, supervisor=provider, plan_watch=lambda _s: _stalled_plans()
        )
        bind(adapter, "owner", "owner-agent")
        elapsed, state = await _delivered_before_deadline(adapter, provider, 3)
        assert elapsed < 3
        assert state in {"waiting", "delivering"}

    asyncio.run(exercise())


def test_hanging_stall_probe_does_not_starve_later_plan(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("varde_runner.relay.IDLE_STATUS_TIMEOUT", 0.01)

    class OneHangingProvider(FakeProvider):
        async def target_idle_status(self, agent_id, _harness=None):
            if agent_id == "first-agent":
                await asyncio.Event().wait()
            return "idle"

    async def exercise():
        provider = OneHangingProvider()
        adapter = DataRelay(tmp_path, supervisor=provider)
        bind(adapter, "first-owner", "first-agent")
        bind(adapter, "second-owner", "second-agent")
        now = datetime.now(UTC).timestamp() - 3600
        plans = {
            "plans": [
                {
                    "id": "first",
                    "assigned_to": "first-owner",
                    "idle_no_handback": True,
                    "newest_activity": now,
                    "done": 0,
                    "total": 1,
                    "detail": "first stalled",
                },
                {
                    "id": "second",
                    "assigned_to": "second-owner",
                    "idle_no_handback": True,
                    "newest_activity": now,
                    "done": 0,
                    "total": 1,
                    "detail": "second stalled",
                },
            ]
        }

        await adapter._emit_stalls(plans)

        sent = [message.text for message in adapter.messages.read_all().records]
        assert any(message.startswith("Stall second@") for message in sent)

    asyncio.run(exercise())


def test_hanging_idle_probe_fails_the_wake_instead_of_hanging(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setattr("varde_runner.relay.IDLE_STATUS_TIMEOUT", 0.1)

    async def exercise():
        provider = HangingOwnerProvider()
        adapter = DataRelay(
            tmp_path, supervisor=provider, plan_watch=lambda _s: {"plans": []}
        )
        worker = RelayWorker(adapter, provider)

        async def renew(_action_id):
            return {"status": "ok"}

        adapter.renew = renew  # type: ignore[method-assign]
        result = await asyncio.wait_for(
            worker.deliver({"action_id": "a1", "wake": {"agent_id": "owner-agent"}}),
            timeout=2,
        )
        assert result == ("failed", "no-send")

    asyncio.run(exercise())
