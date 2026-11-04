from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from varde_data.records.addresses import ReaderContext
from varde_runner.plugins import RunnerCapabilities
from varde_runner.relay import DataRelay, RelayWorker
from varde_runner.store import SessionStore
from varde_runner.supervisor import Supervisor
from varde_runner.web import create_app
from varde_workflow.msg_status import load_report


class FakeCLI:
    def read_messages(self):
        return []

    def read_plan(self):
        return {"plans": []}

    def read_address_bindings(self):
        return []

    def read_message_status(self):
        return {"messages": []}

    def send(self, **_kwargs):
        return {"id": "delivery"}


async def get_json(app, path: str) -> dict:
    response = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        response.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost:8765")],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8765),
        },
        receive,
        send,
    )
    body = b"".join(item.get("body", b"") for item in response)
    return json.loads(body)


def make_app(tmp_path):
    return create_app(data_dir=tmp_path, cli=FakeCLI())


def test_relay_endpoint_disabled_has_no_worker_data(tmp_path, monkeypatch):
    monkeypatch.delenv("VARDE_RUNNER_RELAY", raising=False)
    app = make_app(tmp_path)

    assert asyncio.run(get_json(app, "/api/relay")) == {"enabled": False}


def test_relay_endpoint_returns_worker_snapshot_when_enabled(tmp_path):
    app = make_app(tmp_path)

    class FakeWorker:
        def snapshot(self):
            return {
                "state": "refused",
                "identity": None,
                "refusal": "mailman is held by human-session",
            }

    app.state.relay_enabled = True
    app.state.relay_worker = FakeWorker()
    assert asyncio.run(get_json(app, "/api/relay")) == {
        "state": "refused",
        "identity": None,
        "refusal": "mailman is held by human-session",
        "enabled": True,
    }


def test_relay_endpoint_uses_persisted_runner_liveness(tmp_path):
    now = datetime.now(UTC)
    adapter = DataRelay(tmp_path, plan_watch=lambda _stale: {"plans": [], "events": []})
    marker = adapter.addresses.issue("mailman", now=now, issuer="test")
    assert adapter.addresses.redeem(
        marker,
        "session-mailman",
        "codex",
        ReaderContext(cwd=str(tmp_path)),
        now=now,
    )
    token = adapter.addresses.current_token("mailman")
    assert token is not None
    worker = RelayWorker(adapter, object())
    worker.identity = token
    worker.state = "waiting"
    adapter.addresses.heartbeat(
        token,
        "waiting",
        now,
        instance_id=adapter.service.instance_id,
        expect_return_by=now + timedelta(minutes=1),
    )
    app = make_app(tmp_path)
    app.state.relay_enabled = True
    app.state.relay_worker = worker

    fresh = asyncio.run(get_json(app, "/api/relay"))
    assert fresh["state"] == "waiting"
    assert fresh["relay_alive"] is True
    assert load_report(str(tmp_path), now)["runner_relay"] == "up"

    adapter.addresses.heartbeat(
        token,
        "waiting",
        now - timedelta(minutes=5),
        instance_id=adapter.service.instance_id,
        expect_return_by=now - timedelta(minutes=4),
    )
    stale = asyncio.run(get_json(app, "/api/relay"))
    assert stale["state"] == "stale"
    assert stale["relay_alive"] is False
    assert load_report(str(tmp_path), now)["runner_relay"] == "down"


def test_relay_endpoint_handles_live_state_with_sqlite_store(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "relay-state-live-shapes.json"
    state_path = tmp_path / ".cache" / "inbox" / "relay" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(fixture.read_text())
    now = datetime(2026, 10, 24, 13, 50, 32, 37604, tzinfo=UTC)
    adapter = DataRelay(
        tmp_path,
        now=lambda: now,
        plan_watch=lambda _stale: {"plans": [], "events": []},
    )
    store = SessionStore(tmp_path / "runner")
    worker = RelayWorker(adapter, SimpleNamespace(store=store))
    worker.identity = "d40a82ce5619e264"
    worker.state = "waiting"
    app = make_app(tmp_path)
    app.state.relay_enabled = True
    app.state.relay_worker = worker

    result = asyncio.run(get_json(app, "/api/relay"))

    assert result == {
        "next_deadline": None,
        "state": "waiting",
        "identity": "d40a82ce5619e264",
        "queue": {"actions": 0, "deferred": 0},
        "last_plan": None,
        "last_delivery": None,
        "failures": [],
        "last_error": None,
        "refusal": None,
        "started_at": worker.started_at,
        "task_done": False,
        "task_exception": None,
        "relay_alive": True,
        "enabled": True,
    }
    store.connection.close()


def test_relay_lifespan_starts_and_cancels_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_RUNNER_RELAY", "1")
    started = asyncio.Event()
    stopped = asyncio.Event()
    closed = []
    plugins = []

    class FakePlugin:
        capabilities = RunnerCapabilities()

        async def close(self):
            closed.append(True)

    class FakeWorker:
        def __init__(self, cli, supervisor, plan_watch=None, manager_wake=None):
            self.cli = cli
            self.supervisor = supervisor
            self.plan_watch = plan_watch
            self.manager_wake = manager_wake

        async def run(self):
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()

    monkeypatch.setattr(
        "varde_runner.web.registry.PaseoPlugin.from_environment",
        lambda: plugins.append(FakePlugin()) or plugins[-1],
    )
    monkeypatch.setattr("varde_runner.relay.RelayCLI", object)
    monkeypatch.setattr("varde_runner.web.app.RelayWorker", FakeWorker)
    app = make_app(tmp_path)

    async def exercise():
        async with app.router.lifespan_context(app):
            await asyncio.wait_for(started.wait(), timeout=1)
            assert app.state.relay_enabled is True
            supervisor = app.state.relay_worker.supervisor
            assert isinstance(supervisor, Supervisor)
        assert stopped.is_set()

    asyncio.run(exercise())
    assert closed == [True]
