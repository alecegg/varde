import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

from test_supervisor import FakePlugin
from varde_runner.decisions import DecisionStore
from varde_runner.intake import InboxProjector
from varde_runner.plugins import RunnerCapabilities
from varde_runner.relay import RelayWorker
from varde_runner.store import SessionStore
from varde_runner.supervisor import Supervisor
from varde_runner.web.app import DashboardData


def wait_for(store: SessionStore, wait_id: str) -> dict[str, Any]:
    wait = store.get_wait(wait_id)
    assert wait is not None
    return wait


def test_pending_approval_survives_supervisor_restart(tmp_path):
    async def run():
        plugin = FakePlugin(RunnerCapabilities(resume=True, respond=True), "", "")
        first = Supervisor(tmp_path, {"fake": plugin})
        first.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await first.record_event("s1", "permission_requested", {"request_id": "r1"})
        await first.shutdown()

        second = Supervisor(tmp_path, {"fake": plugin})
        await second.start()
        assert [wait["wait_id"] for wait in second.store.pending_waits()] == [
            "approval:s1:r1"
        ]
        assert (await second._handle_ipc({"op": "waits"}))["waits"]
        await second.shutdown()

    asyncio.run(run())


def test_expired_approval_stays_expired_after_restart(tmp_path):
    async def run():
        plugin = FakePlugin(RunnerCapabilities(resume=False, respond=True), "", "")
        first = Supervisor(tmp_path, {"fake": plugin})
        first.store.create_session(
            "s1", "fake", {"provider": "fake", "session_id": "remote"}, "builder"
        )
        await first.record_event("s1", "permission_requested", {"request_id": "r1"})
        first.store.connection.execute(
            "UPDATE waits SET deadline = ? WHERE wait_id = ?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), "approval:s1:r1"),
        )
        first.store.connection.commit()
        await first.shutdown()

        second = Supervisor(tmp_path, {"fake": plugin})
        await second.start()
        assert wait_for(second.store, "approval:s1:r1")["state"] == "expired"
        assert (await second._handle_ipc({"op": "waits"}))["waits"] == []
        assert (await second._handle_ipc({"op": "next_deadline"}))[
            "next_deadline"
        ] is None
        await second.shutdown()

    asyncio.run(run())


def test_stored_wake_survives_supervisor_restart(tmp_path):
    async def run():
        first = Supervisor(tmp_path, {})
        deadline = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
        first.store.create_wait(
            "wake:action-1",
            "unmanaged",
            "wake",
            deadline,
            {"agent_id": "unmanaged", "message_ids": ["m1"]},
        )
        await first.shutdown()

        second = Supervisor(tmp_path, {})
        await second.start()
        pending = second.store.pending_waits()
        assert len(pending) == 1
        assert pending[0]["wait_id"] == "wake:action-1"
        assert (await second._handle_ipc({"op": "next_deadline"}))[
            "next_deadline"
        ] == deadline
        await second.shutdown()

    asyncio.run(run())


def mailbox_dashboard(tmp_path, supervisor, agents=None):
    decisions = DecisionStore(tmp_path / "decisions", send=lambda **_kwargs: {})
    projector = InboxProjector(
        tmp_path / "inbox.sqlite3",
        read_messages=list,
        read_plan=dict,
        decision_store=decisions,
    )

    async def get_supervisor():
        return supervisor

    dashboard = DashboardData(
        cli=object(),
        projector=projector,
        decisions=decisions,
        agent_reader=lambda: agents or [],
        supervisor_getter=get_supervisor,
    )
    return dashboard, decisions, projector


def approval_wait(supervisor, state="pending"):
    supervisor.store.create_session(
        "s1",
        "fake",
        {"provider": "fake", "session_id": "paseo-1"},
        "Builder",
        harness="codex",
    )
    supervisor.store.create_wait(
        "approval:s1:r1",
        "s1",
        "approval",
        payload={"request_id": "r1", "title": "Run tool"},
    )
    if state != "pending":
        supervisor.store.resolve_wait("approval:s1:r1", state, "approve")


def test_mailbox_re_presents_pending_approval_wait(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path / "runner", {})
        approval_wait(supervisor)
        dashboard, decisions, projector = mailbox_dashboard(tmp_path, supervisor)
        items = await dashboard.mailbox_items()
        card = next(item for item in items if item["msg_id"] == "perm:paseo-1:r1")
        assert card["state"] == "pending"
        assert card["harness"] == "codex"
        assert card["agent_title"] == "Builder"
        decision = decisions.get_decision(card["msg_id"])
        assert decision is not None and decision["kind"] == "permission"
        projector.close()
        decisions.close()
        await supervisor.shutdown()

    asyncio.run(run())


def test_mailbox_expired_approval_has_no_answer_buttons(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path / "runner", {})
        approval_wait(supervisor, "expired")
        dashboard, decisions, projector = mailbox_dashboard(tmp_path, supervisor)
        card = next(
            item
            for item in await dashboard.mailbox_items()
            if item["msg_id"] == "perm:paseo-1:r1"
        )
        assert card["state"] == "expired"
        assert card["options"] == []
        projector.close()
        decisions.close()
        await supervisor.shutdown()

    asyncio.run(run())


def test_mailbox_pending_approval_has_no_preselected_answer(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path / "runner", {})
        approval_wait(supervisor)
        dashboard, decisions, projector = mailbox_dashboard(tmp_path, supervisor)
        card = next(
            item
            for item in await dashboard.mailbox_items()
            if item["msg_id"] == "perm:paseo-1:r1"
        )
        assert "recommendation" not in card
        assert "selected" not in card
        projector.close()
        decisions.close()
        await supervisor.shutdown()

    asyncio.run(run())


def test_mailbox_omits_resolved_approval_wait(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path / "runner", {})
        approval_wait(supervisor, "resolved")
        dashboard, decisions, projector = mailbox_dashboard(tmp_path, supervisor)
        assert all(
            item["msg_id"] != "perm:paseo-1:r1"
            for item in await dashboard.mailbox_items()
        )
        projector.close()
        decisions.close()
        await supervisor.shutdown()

    asyncio.run(run())


def test_mailbox_does_not_duplicate_polled_permission_card(tmp_path):
    async def run():
        supervisor = Supervisor(tmp_path / "runner", {})
        approval_wait(supervisor)
        agents = [
            {
                "agent": {
                    "id": "paseo-1",
                    "title": "Builder",
                    "pendingPermissions": [{"id": "r1", "title": "Run tool"}],
                }
            }
        ]
        dashboard, decisions, projector = mailbox_dashboard(
            tmp_path, supervisor, agents
        )
        items = await dashboard.mailbox_items()
        assert sum(item["msg_id"] == "perm:paseo-1:r1" for item in items) == 1
        projector.close()
        decisions.close()
        await supervisor.shutdown()

    asyncio.run(run())


def test_relay_snapshot_reports_next_deadline(tmp_path):
    store = SessionStore(tmp_path)
    deadline = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    store.create_wait("wake:a1", "s1", "wake", deadline, {})
    worker = RelayWorker(None, type("Owner", (), {"store": store})())
    assert worker.snapshot()["next_deadline"] == deadline
    store.close()
