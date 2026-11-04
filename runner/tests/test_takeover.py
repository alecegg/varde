import asyncio
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from starlette.applications import Starlette
from varde_data.chat import open_chat
from varde_runner.supervisor import SendOutcome
from varde_runner.takeover import Takeover
from varde_runner.takeover_state import (
    HEARTBEAT_SECONDS,
    LEASE_SECONDS,
    expired,
    should_queue,
)
from varde_runner.web.takeover_route import create_takeover_routes


def test_takeover_heartbeat_window_and_sender_policy():
    now = datetime(2026, 10, 25, 12, tzinfo=UTC)
    heartbeat = (now - timedelta(seconds=LEASE_SECONDS - 1)).isoformat()
    stale = (now - timedelta(seconds=LEASE_SECONDS)).isoformat()

    assert HEARTBEAT_SECONDS == 20
    assert not expired(heartbeat, now)
    assert expired(stale, now)
    assert should_queue(held=True, lease_expired=False, sender_class="other")
    assert not should_queue(held=True, lease_expired=False, sender_class="holder")
    assert not should_queue(held=True, lease_expired=False, sender_class="user_control")
    assert not should_queue(held=True, lease_expired=True, sender_class="other")
    assert not should_queue(held=False, lease_expired=False, sender_class="other")


class FakeSupervisor:
    def __init__(
        self,
        lifecycle: str = "idle",
        statuses: list[str] | None = None,
    ) -> None:
        self.row = {"id": "agent-1", "agent_id": "agent-1", "lifecycle": lifecycle}
        self.store = SimpleNamespace(sessions=lambda: [self.row])
        self.sent: list[tuple[str, str | None]] = []
        self.statuses = iter(statuses or ["running", "idle", "running", "idle"])

    def resolve_session(self, _agent_id: str) -> dict[str, Any] | None:
        return self.row

    async def send(
        self,
        agent_id: str,
        text: str,
        *,
        client_id: str,
        request_id: str | None,
        takeover_holder: bool,
    ) -> SendOutcome:
        assert client_id == "system:takeover-queue"
        assert takeover_holder
        self.sent.append((text, request_id))
        return SendOutcome.SENT

    async def target_idle_status(self, _agent_id: str) -> str:
        return next(self.statuses, "idle")


def test_takeover_queues_only_other_senders_and_drains_one_per_idle(tmp_path):
    async def exercise():
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        chat = open_chat(tmp_path, clock=now.isoformat)
        chat.create_thread("instance:agent-1", agent_id="agent-1")
        manager = Takeover(chat, clock=lambda: now, retry_seconds=0)
        supervisor = FakeSupervisor()

        assert manager.acquire("agent-1", "user:browser")
        assert not manager.acquire("agent-1", "user:other")
        assert not manager.should_queue(
            "agent-1", "holder", "user answer", request_id=None
        )
        assert not manager.should_queue(
            "agent-1", "user_control", "stop", request_id=None
        )
        assert manager.should_queue(
            "agent-1", "other", "first", request_id="wake-1", supervisor=supervisor
        )
        assert manager.should_queue(
            "agent-1", "other", "second", request_id="wake-2", supervisor=supervisor
        )
        assert chat.queued_count("instance:agent-1") == 2
        assert manager.release("agent-1", "user:browser", supervisor)
        for _ in range(100):
            if len(supervisor.sent) == 2 and chat.queued_count("instance:agent-1") == 0:
                break
            await asyncio.sleep(0.005)

        assert supervisor.sent == [("first", "wake-1"), ("second", "wake-2")]
        assert chat.queued_count("instance:agent-1") == 0
        rows = chat.page("instance:agent-1", limit=50)
        assert sum(row.kind == "takeover_queued" for row in rows) == 2
        assert any(row.kind == "takeover_released" for row in rows)

    asyncio.run(exercise())


def test_takeover_drain_continues_when_target_is_already_idle(tmp_path):
    async def exercise():
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        chat = open_chat(tmp_path, clock=now.isoformat)
        chat.create_thread("instance:agent-1", agent_id="agent-1")
        manager = Takeover(chat, clock=lambda: now, retry_seconds=0)
        supervisor = FakeSupervisor(statuses=["idle"])

        assert manager.acquire("agent-1", "user:browser")
        assert manager.should_queue("agent-1", "other", "first", request_id="wake-1")
        assert manager.should_queue("agent-1", "other", "second", request_id="wake-2")
        assert manager.release("agent-1", "user:browser", supervisor)
        for _ in range(100):
            if chat.queued_count("instance:agent-1") == 0:
                break
            await asyncio.sleep(0.005)

        assert supervisor.sent == [("first", "wake-1"), ("second", "wake-2")]
        assert chat.queued_count("instance:agent-1") == 0

    asyncio.run(exercise())


def test_expiry_and_stopped_agent_drop_queued_row(tmp_path):
    async def exercise():
        now = datetime(2026, 10, 25, 12, tzinfo=UTC)
        current = [now]

        def current_stamp():
            return current[0].isoformat()

        chat = open_chat(tmp_path, clock=current_stamp)
        chat.create_thread("instance:agent-1", agent_id="agent-1")
        manager = Takeover(chat, clock=lambda: current[0], retry_seconds=0)
        supervisor = FakeSupervisor(lifecycle="completed")

        assert manager.acquire("agent-1", "user:browser")
        assert manager.should_queue("agent-1", "other", "wake", request_id="w1")
        current[0] += timedelta(seconds=89)
        await Takeover(chat, clock=lambda: current[0], retry_seconds=0).start(
            FakeSupervisor()
        )
        hold = chat.get_takeover("instance:agent-1")
        assert hold is not None and hold.released_at is None
        assert chat.queued_count("instance:agent-1") == 1
        assert manager.heartbeat("agent-1", "user:browser")
        current[0] += timedelta(seconds=90)
        assert not manager.heartbeat("agent-1", "user:browser")
        await manager.start(supervisor)
        for _ in range(100):
            if chat.queued_count("instance:agent-1") == 0:
                rows = chat.page("instance:agent-1", limit=50)
                if any(row.kind == "takeover_dropped" for row in rows):
                    break
            await asyncio.sleep(0.005)

        rows = chat.page("instance:agent-1", limit=50)
        current_takeover = chat.get_takeover("instance:agent-1")
        assert current_takeover is not None and current_takeover.released_at is not None
        assert any(row.kind == "takeover_dropped" for row in rows)

    asyncio.run(exercise())


def test_takeover_routes_have_user_only_names_and_enforce_single_holder(tmp_path):
    chat = open_chat(tmp_path)
    chat.create_thread("instance:agent-1", agent_id="agent-1")
    manager = Takeover(chat)
    supervisor = FakeSupervisor()
    routes = create_takeover_routes(manager, lambda: supervisor)
    app = Starlette(routes=routes)
    assert all(route.name.startswith("user_only_") for route in routes)

    status, body = _request(
        app, "POST", "/api/instance-threads/agent-1/takeover", {"client": "browser-1"}
    )
    assert status == 200
    assert body == {"holder": "browser-1", "queued": 0}
    status, _ = _request(
        app, "POST", "/api/instance-threads/agent-1/takeover", {"client": "browser-2"}
    )
    assert status == 409
    assert manager.should_queue(
        "agent-1", "other", "arrived during takeover", request_id="queued-1"
    )
    status, body = _request(
        app,
        "POST",
        "/api/instance-threads/agent-1/takeover/heartbeat",
        {"client": "browser-1"},
    )
    assert status == 200
    assert body == {"ok": True, "queued": 1}
    status, _ = _request(
        app, "DELETE", "/api/instance-threads/agent-1/takeover", {"client": "browser-1"}
    )
    assert status == 200


def _request(app: Starlette, method: str, path: str, payload: dict[str, Any]):
    async def dispatch():
        messages = []
        raw_path = path.encode()
        body = json.dumps(payload).encode()
        sent = False

        async def receive():
            nonlocal sent
            if sent:
                return {"type": "http.disconnect"}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": raw_path,
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"host", b"localhost"),
                    (b"content-type", b"application/json"),
                ],
                "client": ("127.0.0.1", 1),
                "server": ("localhost", 80),
            },
            receive,
            send,
        )
        start = next(row for row in messages if row["type"] == "http.response.start")
        response = b"".join(
            row.get("body", b"")
            for row in messages
            if row["type"] == "http.response.body"
        )
        return start["status"], json.loads(response)

    return asyncio.run(dispatch())
