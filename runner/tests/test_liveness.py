from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fakes.plugin import FakePlugin
from varde_runner.config import default_config
from varde_runner.liveness import event_age_s
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.supervisor import Supervisor
from varde_runner.waits import approval_wait_id


class DeadProcessPlugin(FakePlugin):
    def process_alive(self, _ref) -> bool:
        return False


class InspectFailPlugin(FakePlugin):
    async def inspect(self, _ref):
        raise AssertionError("liveness must not inspect the child")


@pytest.fixture
def isolated_config(monkeypatch):
    config = replace(default_config(), stall_after_s=10)
    monkeypatch.setattr("varde_runner.supervisor.load_config", lambda *_: config)


def stale_event(supervisor, session_id: str, seconds: int = 30) -> None:
    supervisor.store.append_event(session_id, "status", {"status": "running"})
    created_at = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()
    supervisor.store.connection.execute(
        "UPDATE events SET created_at = ? WHERE session_id = ?",
        (created_at, session_id),
    )
    supervisor.store.connection.commit()


def test_supervisor_liveness_waiting_and_process_gone(
    tmp_path, isolated_config
) -> None:
    plugin = DeadProcessPlugin(RunnerCapabilities())
    supervisor = Supervisor(tmp_path, {"claude_cli": plugin})
    ref = asyncio.run(
        supervisor.start_session(
            SessionSpec("claude_cli", "model", "workspace", str(tmp_path), "prompt"),
            "builder",
        )
    )
    supervisor.store.update_session(
        ref.session_id, status="running", idle_status="running"
    )
    assert asyncio.run(supervisor.liveness(ref.session_id)).reason == "process_gone"
    supervisor.store.create_wait(
        approval_wait_id(ref.session_id, "r1"), ref.session_id, "approval", payload={}
    )
    assert asyncio.run(supervisor.liveness(ref.session_id)).state == "waiting"


def test_liveness_without_ref_uses_stored_row(tmp_path, isolated_config) -> None:
    plugin = FakePlugin(RunnerCapabilities(idle_status=True))
    supervisor = Supervisor(tmp_path, {"claude_cli": plugin})
    supervisor.store.create_session(
        "s1", "claude_cli", {}, "builder", lifecycle="failed"
    )
    supervisor.store.update_session("s1", status="error", idle_status="unknown")
    assert asyncio.run(supervisor.liveness("s1")).state == "error"
    assert supervisor.store.last_event_at("s1") is None


def test_silent_session_is_stalled(tmp_path, isolated_config) -> None:
    plugin = InspectFailPlugin(RunnerCapabilities(idle_status=True))
    supervisor = Supervisor(tmp_path, {"claude_cli": plugin})
    supervisor.store.create_session(
        "s1", "claude_cli", {"session_id": "remote"}, "builder", lifecycle="running"
    )
    supervisor.store.update_session("s1", status="running", idle_status="unknown")
    plugin.status["remote"] = "running"
    supervisor._refs["s1"] = SessionRef("claude_cli", "remote")
    stale_event(supervisor, "s1")
    result = asyncio.run(supervisor.liveness("s1"))
    assert (result.state, result.reason) == ("stalled", "silent")


def test_resumed_idle_session_is_not_stalled(tmp_path, isolated_config) -> None:
    plugin = FakePlugin(RunnerCapabilities(idle_status=True))
    supervisor = Supervisor(tmp_path, {"claude_cli": plugin})
    supervisor.store.create_session(
        "s1", "claude_cli", {"session_id": "remote"}, "builder", lifecycle="running"
    )
    supervisor.store.update_session("s1", status="running", idle_status="unknown")
    plugin.status["remote"] = "idle"
    supervisor._refs["s1"] = SessionRef("claude_cli", "remote")
    stale_event(supervisor, "s1")
    assert asyncio.run(supervisor.liveness("s1")).state == "idle"


def test_no_ref_and_plugin_without_process_hook_do_not_claim_death(
    tmp_path, isolated_config
) -> None:
    plugin = FakePlugin(RunnerCapabilities(idle_status=True))
    supervisor = Supervisor(tmp_path, {"claude_cli": plugin})
    supervisor.store.create_session(
        "s1", "claude_cli", {}, "builder", lifecycle="running"
    )
    supervisor.store.update_session("s1", status="running", idle_status="running")
    supervisor.store.append_event("s1", "status", {"status": "running"})
    assert not hasattr(plugin, "process_alive")
    assert asyncio.run(supervisor.liveness("s1")).state == "running"


def test_event_age_s_is_pure() -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert event_age_s(None, now) is None
    assert event_age_s((now - timedelta(seconds=20)).isoformat(), now) == 20
