import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from test_supervisor import FakePlugin
from varde_runner.plugins import RunnerCapabilities, SessionRef
from varde_runner.store import SessionStore
from varde_runner.supervisor import Supervisor
from varde_runner.waits import approval_wait_id


def wait_for(store: SessionStore, wait_id: str) -> dict[str, Any]:
    wait = store.get_wait(wait_id)
    assert wait is not None
    return wait


class RespondingPlugin(FakePlugin):
    def __init__(self, tmp_path: Path, *, resume=True):
        super().__init__(
            RunnerCapabilities(resume=resume, respond=True),
            str(tmp_path / "pid"),
            str(tmp_path / "prompt"),
        )
        self.answers = []
        self.fail_next_answer = False

    async def respond_permission(self, ref, request_id, decision):
        if self.fail_next_answer:
            self.fail_next_answer = False
            raise OSError("temporary plugin failure")
        self.answers.append((request_id, decision))


def test_approval_wait_is_created_and_duplicate_responses_are_idempotent(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        supervisor._refs["s1"] = SessionRef("fake", "remote")

        assert await supervisor.respond("s1", "r1", "approve") == "responded"
        assert await supervisor.respond("s1", "r1", "approve") == "responded"
        assert await supervisor.respond("s1", "r1", "allow") == "responded"
        assert await supervisor.respond("s1", "r1", "deny") == "stale"
        assert plugin.answers == [("r1", "approve")]
        decision = supervisor.store.decision_events()[0]
        assert decision["response"] == "approve"
        assert decision["answered_at"] is not None
        assert decision["time_to_answer_s"] is not None
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_expire_never_answers_harness(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path, resume=False)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()

        wait = supervisor.store.get_wait("approval:s1:r1")
        assert wait is not None and wait["state"] == "expired"
        assert supervisor.store.decision_events()[0]["response"] == "expired"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_plugin_resolved_event_resolves_wait(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.record_event(
            "s1", "permission_resolved", {"request_id": "r1", "decision": "allow"}
        )

        wait = supervisor.store.get_wait("approval:s1:r1")
        assert wait is not None and wait["state"] == "resolved"
        assert wait["decision"] == "approve"
        decision_event = supervisor.store.decision_events()[0]
        assert decision_event["response"] == "approve"
        assert decision_event["answered_at"] is not None
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_backfills_permission_wait_missing_from_store(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        supervisor.store.append_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()
        wait = supervisor.store.get_wait("approval:s1:r1")
        assert wait is not None and wait["state"] == "pending"
        assert supervisor.store.decision_events()[0]["card_kind"] == "permission"
        assert await supervisor.respond("s1", "r1", "approve") == "responded"
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "resolved"
        assert plugin.answers == [("r1", "approve")]
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_backfills_before_reconciling_legacy_request(tmp_path):
    async def run():
        class PluginWithoutPending(RespondingPlugin):
            async def list_agents(self):
                return [{"id": "remote", "pendingPermissions": []}]

        plugin = PluginWithoutPending(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        supervisor.store.append_event(
            "s1", "permission_requested", {"request_id": "legacy"}
        )
        await supervisor.start()
        assert wait_for(supervisor.store, "approval:s1:legacy")["state"] == "expired"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_expired_answer_intent_is_not_recorded_as_expired_after_restart(tmp_path):
    async def run():
        class PluginWithoutPending(RespondingPlugin):
            async def list_agents(self):
                return [{"id": "remote", "pendingPermissions": []}]

        plugin = PluginWithoutPending(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        supervisor.store.set_pending_wait_decision("approval:s1:r1", "approve")
        await supervisor.start()
        wait = wait_for(supervisor.store, "approval:s1:r1")
        assert wait["state"] == "resolved"
        assert wait["decision"] == "approve"
        row = next(
            row
            for row in supervisor.store.decision_events()
            if row["request_id"] == approval_wait_id("s1", "r1")
        )
        assert row["response"] == "approve"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_supervisor_expires_waits_while_running(tmp_path):
    async def run():
        class PluginWithPending(RespondingPlugin):
            async def list_agents(self):
                return [{"id": "remote", "pendingPermissions": [{"id": "r1"}]}]

        plugin = PluginWithPending(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        deadline = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        supervisor.store.connection.execute(
            "UPDATE waits SET deadline = ? WHERE wait_id = ?",
            (deadline, "approval:s1:r1"),
        )
        supervisor.store.connection.commit()
        await supervisor.start()
        past = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        supervisor.store.connection.execute(
            "UPDATE waits SET deadline = ? WHERE wait_id = ?",
            (past, "approval:s1:r1"),
        )
        supervisor.store.connection.commit()
        for _ in range(20):
            if wait_for(supervisor.store, "approval:s1:r1")["state"] == "expired":
                break
            await asyncio.sleep(0.1)
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "expired"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_failed_answer_keeps_approval_pending_for_retry(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        plugin.fail_next_answer = True
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        supervisor._refs["s1"] = SessionRef("fake", "remote")

        assert await supervisor.respond("s1", "r1", "approve") == "failed"
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "pending"
        assert await supervisor.respond("s1", "r1", "approve") == "responded"
        assert plugin.answers == [("r1", "approve")]
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_expires_approval_missing_from_plugin_pending_list(tmp_path):
    async def run():
        class PluginWithPendingList(RespondingPlugin):
            async def list_agents(self):
                return [{"id": "remote", "pendingPermissions": []}]

        plugin = PluginWithPendingList(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()

        wait = supervisor.store.get_wait("approval:s1:r1")
        assert wait is not None and wait["state"] == "expired"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_keeps_approval_when_plugin_lists_it_as_pending(tmp_path):
    async def run():
        class PluginWithPendingList(RespondingPlugin):
            async def list_agents(self):
                return [{"id": "remote", "pendingPermissions": [{"id": "r1"}]}]

        plugin = PluginWithPendingList(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "pending"
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_keeps_wait_when_pending_agent_listing_fails(tmp_path):
    async def run():
        class BrokenPlugin(RespondingPlugin):
            async def list_agents(self):
                raise OSError("plugin directory unavailable")

        plugin = BrokenPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "pending"
        assert "s1" in supervisor._refs
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_keeps_wait_when_pending_agent_is_absent(tmp_path):
    async def run():
        class PluginWithoutListedAgent(RespondingPlugin):
            async def list_agents(self):
                return []

        plugin = PluginWithoutListedAgent(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await supervisor.record_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        await supervisor.start()
        assert wait_for(supervisor.store, "approval:s1:r1")["state"] == "pending"
        await supervisor.shutdown()

    asyncio.run(run())


def test_start_expires_past_deadline_without_answering_harness(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        deadline = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        supervisor.store.create_wait(
            "approval:s1:r1",
            "s1",
            "approval",
            deadline,
            {"request_id": "r1"},
        )
        await supervisor.start()

        wait = supervisor.store.get_wait("approval:s1:r1")
        assert wait is not None and wait["state"] == "expired"
        assert plugin.answers == []
        await supervisor.shutdown()

    asyncio.run(run())


def test_backfill_wait_event_does_not_reset_no_progress_restart_count(tmp_path):
    async def run():
        plugin = RespondingPlugin(tmp_path)
        supervisor = Supervisor(tmp_path, {"fake": plugin})
        supervisor.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        supervisor.store.append_event(
            "s1", "permission_requested", {"request_id": "r1"}
        )
        supervisor.store.update_session("s1", seq_at_last_start=1)

        await supervisor.start()

        session = supervisor.store.get_session("s1")
        assert session is not None and session["no_progress_restarts"] == 1
        assert any(
            event["kind"] == "wait_created"
            for event in supervisor.store.events_after("s1", 0)
        )
        await supervisor.start()
        session = supervisor.store.get_session("s1")
        assert session is not None and session["no_progress_restarts"] == 2
        await supervisor.shutdown()

    asyncio.run(run())
