from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde_data.records.addresses import ReaderContext
from varde_data.records.messages import NewMessage
from varde_runner.relay import DataRelay, RelayWaitStopped, RelayWorker
from varde_runner.supervisor import SendOutcome
from varde_workflow.msg_status import load_report


class FakeProvider:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.sent_event = asyncio.Event()

    async def target_idle_status(self, _agent_id, _harness=None):
        return "idle"

    async def send(self, agent_id, prompt, _harness=None, *, request_id=None):
        self.sent.append((agent_id, prompt))
        self.sent_event.set()
        return SendOutcome.SENT


def bind(adapter: DataRelay, address: str, agent_id: str) -> None:
    now = datetime.now(UTC)
    marker = adapter.addresses.issue(
        address, now=now, issuer="test", supersede=address == "main"
    )
    assert adapter.addresses.redeem(
        marker,
        f"session-{address}",
        "codex",
        ReaderContext(cwd=str(adapter.cwd), agent_id=agent_id, runner_harness="codex"),
        now=now,
    )


async def run_until_sent(adapter: DataRelay, provider: FakeProvider) -> None:
    worker = RelayWorker(adapter, provider)
    task = asyncio.create_task(worker.run())
    try:
        await asyncio.wait_for(provider.sent_event.wait(), timeout=15)
    finally:
        worker._stop = True
        if isinstance(adapter, DataRelay):
            adapter.stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def test_merge_ready_wakes_main_without_watchdog(tmp_path: Path):
    async def exercise():
        provider = FakeProvider()
        adapter = DataRelay(
            tmp_path,
            supervisor=provider,
            plan_watch=lambda _stale: {"plans": [], "events": []},
        )
        bind(adapter, "main", "main-agent")
        worker = RelayWorker(adapter, provider)
        task = asyncio.create_task(worker.run())
        try:
            deadline = asyncio.get_running_loop().time() + 15
            while True:
                state_path = tmp_path / ".cache/inbox/relay/state.json"
                state = (
                    json.loads(state_path.read_text()) if state_path.exists() else {}
                )
                current = state.get("current_mailman")
                waiting = any(
                    event.get("token_id") == current and event.get("event") == "waiting"
                    for event in state.get("events", [])
                )
                if waiting:
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("runner relay did not enter waiting")
                await asyncio.sleep(0.05)

            assert load_report(str(tmp_path), datetime.now(UTC))["runner_relay"] == "up"
            message = adapter.messages.append(
                NewMessage("orchestrator", "main", "merge-ready", "merge request ready")
            )
            await asyncio.wait_for(provider.sent_event.wait(), timeout=15)

            assert len(provider.sent) == 1
            assert provider.sent[0][0] == "main-agent"
            prompt_lines = provider.sent[0][1].splitlines()
            assert prompt_lines[0].startswith("[varde-delivery: ")
            assert prompt_lines[1] == f"Varde messages for main: {message.id}"
            assert len(prompt_lines) == 3
        finally:
            worker._stop = True
            adapter.stop_event.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    asyncio.run(exercise())


def test_failed_runner_confirm_persists_evidence_as_reason(tmp_path: Path):
    async def exercise():
        adapter = DataRelay(tmp_path)
        bind(adapter, "reader", "reader-agent")
        message = adapter.messages.append(
            NewMessage("sender", "reader", "merge-ready", "trigger")
        )
        action = adapter.service.once("test-token")["actions"][0]

        await adapter.confirm(
            action["action_id"], "failed", "provider timeout", "runner", harness="codex"
        )

        delivery = next(
            row for row in adapter.messages.deliveries() if row.message_id == message.id
        )
        assert delivery.reason == "provider timeout"

    asyncio.run(exercise())


def test_wedged_wait_cycle_stops_heartbeats_after_stale_window(
    tmp_path: Path, monkeypatch
):
    async def exercise():
        now = [datetime(2026, 10, 24, 12, tzinfo=UTC)]
        monotonic = [1000.0]
        adapter = DataRelay(
            tmp_path,
            now=lambda: now[0],
            monotonic=lambda: monotonic[0],
            plan_watch=lambda _stale: {"plans": [], "events": []},
        )
        bind(adapter, "mailman", "old-agent")
        previous = adapter.addresses.current_token("mailman")
        assert previous is not None
        adapter.service.end(previous, now[0])
        marker = adapter.addresses.issue(
            "mailman", now=now[0], issuer="test", supersede=True
        )
        assert adapter.addresses.redeem(
            marker,
            "session-mailman-new",
            "codex",
            ReaderContext(cwd=str(tmp_path), agent_id="main-agent"),
            now=now[0],
        )
        current = adapter.addresses.current_token("mailman")
        assert current is not None and current != previous

        observed_status = []
        worker = RelayWorker(adapter, object())
        worker.state = "waiting"
        worker.identity = current

        def long_poll(seconds: float) -> None:
            now[0] += timedelta(seconds=seconds)
            monotonic[0] += seconds
            time.sleep(0.08)
            observed_status.append(load_report(str(tmp_path), now[0])["runner_relay"])
            adapter.stop_event.set()

        adapter.service.sleep = long_poll
        adapter._wait_timeout = lambda snapshot: 200.0
        monkeypatch.setattr("varde_runner.relay.HEARTBEAT_SECONDS", 0.01)
        monkeypatch.setattr("varde_data.relay.POLL_SECONDS", 150.0)
        with suppress(RelayWaitStopped):
            await adapter.wait(current)

        waiting = [
            event
            for event in adapter.addresses.relay_snapshot().events
            if event.get("token_id") == current and event.get("event") == "waiting"
        ]
        assert observed_status == ["down"]
        assert len(waiting) == 1
        assert datetime.fromisoformat(waiting[0]["at"]) == now[0] - timedelta(
            seconds=150
        )
        assert load_report(str(tmp_path), now[0])["runner_relay"] == "down"
        snapshot = worker.snapshot()
        assert snapshot["relay_alive"] is False
        assert snapshot["state"] == "stale"

    asyncio.run(exercise())


def test_stall_wakes_main_after_idle_deadline(tmp_path: Path):
    async def exercise():
        provider = FakeProvider()
        now = datetime.now(UTC)
        snapshot = json.loads(
            (
                Path(__file__).parents[2]
                / "workflow/tests/golden/plans/plans-watch-stalled.json"
            ).read_text()
        )
        plan = snapshot["plans"][0]
        plan["assigned_to"] = "builder"
        plan["newest_activity"] = now.timestamp() - 2
        adapter = DataRelay(
            tmp_path,
            supervisor=provider,
            stale_after=timedelta(seconds=1),
            now=lambda: now,
            plan_watch=lambda _stale: snapshot,
        )
        bind(adapter, "builder", "builder-agent")
        bind(adapter, "main", "main-agent")

        await run_until_sent(adapter, provider)
        await adapter._emit_stalls(snapshot)

        assert provider.sent[0][0] == "main-agent"
        assert "stalled: assigned@" in provider.sent[0][1]
        notices = [
            message
            for message in adapter.messages.read_all().records
            if message.text.startswith("Stall assigned@")
        ]
        assert len(notices) == 1

    asyncio.run(exercise())


def test_stall_flag_waits_for_configured_stale_deadline(tmp_path: Path):
    async def exercise():
        provider = FakeProvider()
        now = datetime.now(UTC)
        snapshot = json.loads(
            (
                Path(__file__).parents[2]
                / "workflow/tests/golden/plans/plans-watch-stalled.json"
            ).read_text()
        )
        plan = snapshot["plans"][0]
        plan["assigned_to"] = "builder"
        plan["newest_activity"] = (
            now.timestamp() - timedelta(minutes=10).total_seconds()
        )
        adapter = DataRelay(
            tmp_path,
            supervisor=provider,
            stale_after=timedelta(minutes=20),
            now=lambda: now,
            plan_watch=lambda _stale: snapshot,
        )
        bind(adapter, "builder", "builder-agent")
        bind(adapter, "main", "main-agent")

        await adapter._emit_stalls(snapshot)

        assert adapter.messages.read_all().records == ()

    asyncio.run(exercise())


def test_idle_relay_sends_nothing_without_events(tmp_path: Path):
    async def exercise():
        provider = FakeProvider()
        adapter = DataRelay(
            tmp_path,
            supervisor=provider,
            plan_watch=lambda _stale: {"plans": [], "events": []},
        )
        worker = RelayWorker(adapter, provider)
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.1)
        worker._stop = True
        adapter.stop_event.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

        assert provider.sent == []

    asyncio.run(exercise())
