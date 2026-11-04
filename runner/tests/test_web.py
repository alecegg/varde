from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from starlette.routing import Route
from varde_runner.config import ConfigError, default_toml
from varde_runner.decisions import DecisionStore
from varde_runner.web import create_app
from varde_runner.web.app import (
    _event_keepalive_due,
    _event_update_frame,
    _events_snapshot,
    _filter_guard_permissions,
    _sse_orchestrators,
)
from varde_runner.workitems import WorkItemStore


class Response:
    def __init__(self, status_code, headers, content):
        self.status_code, self.headers, self.content = status_code, headers, content

    @property
    def text(self):
        return self.content.decode()

    def json(self):
        return json.loads(self.content)


def test_guard_permission_visibility_hides_unresolved_and_approved_rows():
    item = {"kind": "permission", "sender": "remote", "request_id": "req"}
    base = {
        "session_id": "local",
        "remote_id": "remote",
        "payload": {"request_id": "req"},
        "guard_enabled": True,
    }

    assert _filter_guard_permissions([item], [base]) == []
    assert (
        _filter_guard_permissions(
            [item], [base | {"guard_verdict": {"verdict": "approve"}}]
        )
        == []
    )
    escalated = _filter_guard_permissions(
        [item], [base | {"guard_verdict": {"verdict": "escalate"}}]
    )
    assert escalated == [item | {"guard_escalated": True}]
    assert _filter_guard_permissions([item], [base | {"guard_enabled": False}]) == [
        item
    ]


@pytest.mark.parametrize(
    ("verdict", "expected_permissions", "expected_count"),
    [("approve", 0, 0), ("escalate", 1, 1)],
)
def test_guard_verdict_is_reflected_in_mailbox_and_needs_you_apis(
    tmp_path, monkeypatch, verdict, expected_permissions, expected_count
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.messages = []

    class GuardSupervisor:
        def approval_waits_for_mailbox(self):
            return [
                {
                    "session_id": "local-session",
                    "remote_id": "remote-session",
                    "agent_title": "builder",
                    "harness": "fake",
                    "state": "pending",
                    "created_at": "2026-10-23T00:00:00Z",
                    "payload": {"request_id": "request-1", "title": "Permission"},
                    "guard_enabled": True,
                    "guard_verdict": {"verdict": verdict},
                }
            ]

    async def get_supervisor():
        return GuardSupervisor()

    app.state.dashboard.supervisor_getter = get_supervisor
    mailbox = app_request(app, "GET", "/api/mailbox").json()
    assert len(mailbox["permissions"]) == expected_permissions
    permission_rows = [
        item
        for item in mailbox["all"]
        if item.get("kind") == "permission" and item.get("request_id") == "request-1"
    ]
    assert len(permission_rows) == expected_permissions
    if verdict == "escalate":
        assert mailbox["permissions"][0]["guard_escalated"] is True
        assert asyncio.run(app.state.dashboard.needs_you_threads())
    else:
        assert asyncio.run(app.state.dashboard.needs_you_threads()) == []
    needs_you = app_request(app, "GET", "/api/needs-you-count").json()
    assert needs_you["needs_you_count"] == expected_count
    store.close()


def app_request(app, method, path, *, content=b"", headers=None):
    async def dispatch():
        parsed_path = urlsplit(path)
        response_messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": content, "more_body": False}

        async def send(message):
            response_messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "host": "localhost:8765",
            "path": parsed_path.path,
            "raw_path": parsed_path.path.encode(),
            "query_string": parsed_path.query.encode(),
            "root_path": "",
            "headers": [
                (k.lower().encode(), v.encode())
                for k, v in {"host": "localhost:8765", **(headers or {})}.items()
            ],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8765),
        }
        await app(scope, receive, send)
        start = next(
            message
            for message in response_messages
            if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in response_messages
            if message["type"] == "http.response.body"
        )
        return Response(
            start["status"],
            {key.decode(): value.decode() for key, value in start["headers"]},
            body,
        )

    return asyncio.run(dispatch())


class FakeCLI:
    dashboard_app: object = None

    def __init__(self, notes_path):
        self.messages = [
            {
                "id": "question-1",
                "from": "builder",
                "kind": "needs-user",
                "notes": None,
            },
            {
                "id": "question-options",
                "from": "builder",
                "kind": "needs-user",
                "notes": str(notes_path),
            },
        ]
        self.plan = {
            "plans": [
                {
                    "id": "plan-1",
                    "status": "running",
                    "model": "gpt-6-luna",
                    "worktree": "/tmp/project",  # noqa: S108 - Fixture models a user worktree path.
                    "last_event_at": "2026-10-19T10:00:00Z",
                }
            ]
        }
        self.sent = []
        self.acknowledged: list[tuple[str, str]] = []
        self.message_status = {"messages": []}
        self.extra_bindings = []

    def read_messages(self):
        return self.messages

    def read_plan(self):
        return self.plan

    def read_address_bindings(self):
        return [
            {"address": "plan-1", "wake_context": {"paseo_id": "paseo-plan-1"}},
            *self.extra_bindings,
        ]

    def read_message_status(self):
        return self.message_status

    def send(self, **kwargs):
        self.sent.append(kwargs)
        return {"id": f"delivery-{len(self.sent)}"}

    def acknowledge(self, message_id: str, *, address: str) -> None:
        self.acknowledged.append((message_id, address))


def setup_app(
    tmp_path,
    monkeypatch,
    option_context=None,
    allowed_hosts=frozenset(),
    bound_port=None,
):
    config_dir = tmp_path / "runner-config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "runner.toml").write_text(default_toml())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    notes_path = tmp_path / "question.json"
    notes_path.write_text(
        json.dumps(
            option_context
            or {
                "asked": "Choose",
                "why": "Select one",
                "options": [{"id": "yes", "label": "Yes"}],
            }
        )
    )
    cli = FakeCLI(notes_path)
    store = DecisionStore(tmp_path / "answers", send=cli.send)
    monkeypatch.setattr(
        "varde_runner.web.app.read_context",
        lambda message: {
            "asked": "Which option?",
            "why": "Need a decision.",
            "options": [
                {"id": "yes", "label": "Yes"},
                {"id": "no", "label": "No"},
            ],
        },
    )
    app = create_app(
        data_dir=tmp_path,
        cli=cli,
        decisions=store,
        agents=list,
        bound_port=bound_port,
        allowed_hosts=allowed_hosts,
    )
    return app, cli, store


def test_invalid_sweep_time_logs_and_uses_default(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("VARDE_LEARN_SWEEP_TIME", "24:00")
    app, _, _ = setup_app(tmp_path, monkeypatch)
    assert app.state.sweep_job.schedule_time == "03:00"
    assert "Invalid VARDE_LEARN_SWEEP_TIME" in caplog.text


def test_open_mailbox_tolerates_sparse_store_message_rows(tmp_path, monkeypatch):
    app, _, _ = setup_app(tmp_path, monkeypatch)
    dashboard = app.state.dashboard
    dashboard.inbox_cache = SimpleNamespace(
        read=lambda: SimpleNamespace(
            messages=[{"id": "sparse", "kind": "needs-user"}],
            acknowledged_ids=set(),
            concluded_addresses=set(),
        )
    )
    dashboard.orchestrators = lambda: asyncio.sleep(0, result={"plans": [], "past": []})

    items = asyncio.run(dashboard.open_mailbox_items([]))

    assert items == []


def test_work_item_reports_unavailable_planner_role_as_service_unavailable(
    tmp_path, monkeypatch
):
    app, _, _ = setup_app(tmp_path, monkeypatch)

    async def fail_to_start(*_args):
        raise ConfigError("unknown role: planner")

    app.state.work_item_start = fail_to_start
    response = app_request(
        app,
        "POST",
        "/api/work-items",
        content=json.dumps(
            {
                "text": "Plan this change",
                "project": str(tmp_path),
                "idempotency_key": "missing-planner-role",
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 503
    assert "planner role" in response.json()["error"]
    assert "runner.toml" in response.json()["error"]
    work_items = WorkItemStore(tmp_path)
    item = work_items.list()[0]
    assert item.state == "new"
    work_items.close()


def test_get_pages_do_not_append_decision_audit_or_message_rows(
    tmp_path, monkeypatch, runner_ui_built
):
    client, cli, store = setup_app(tmp_path, monkeypatch)
    before = (
        store.db.execute("select count(*) from decisions").fetchone()[0],
        len(store.audit_rows()),
        len(cli.sent),
        store.db.execute("select count(*) from answers").fetchone()[0],
    )
    assert app_request(client, "GET", "/plans").status_code == 200
    assert app_request(client, "GET", "/thread/agent-1").status_code == 200
    mailbox = app_request(client, "GET", "/mailbox")
    threads = app_request(client, "GET", "/threads")
    assert mailbox.status_code == threads.status_code == 307
    assert mailbox.headers["location"] == threads.headers["location"] == "/"
    after = (
        store.db.execute("select count(*) from decisions").fetchone()[0],
        len(store.audit_rows()),
        len(cli.sent),
        store.db.execute("select count(*) from answers").fetchone()[0],
    )
    assert after == before
    store.close()


def test_orchestrator_payload_budget_and_agent_projection(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    dashboard = app.state.dashboard
    dashboard.snapshot = {
        "plans": [],
        "past": [],
        "infrastructure": [],
        "agents": [
            {
                "id": f"agent-{index}",
                "title": f"Agent {index}",
                "status": "idle",
                "last_activity": "2026-10-23T10:00:00Z",
                "payload": "x" * 4096,
            }
            for index in range(100)
        ],
        "activity_agents": [{"large": "x" * 100_000}],
    }
    dashboard.snapshot_loaded_at = time.monotonic()

    response = app_request(app, "GET", "/api/orchestrators")
    payload = response.json()

    assert "activity_agents" not in payload
    assert len(response.content) < 20_000
    assert payload["agents"][0] == {
        "id": "agent-0",
        "title": "Agent 0",
        "status": "idle",
        "last_activity": "2026-10-23T10:00:00Z",
    }
    assert "activity_agents" in dashboard.snapshot
    store.close()


def test_unjoined_orchestrator_skips_plan_task_reads(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [{"address": "unjoined-orchestrator", "wake_context": {}}]
    task_reads = []
    monkeypatch.setattr(
        cli,
        "read_plan_tasks",
        lambda plan_id: task_reads.append(plan_id) or [],
        raising=False,
    )

    response = app_request(app, "GET", "/api/orchestrators")

    assert response.status_code == 200
    assert task_reads == ["plan-1"]
    store.close()


def test_api_orchestrators_supports_gzip(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    dashboard = app.state.dashboard
    dashboard.snapshot = {
        "plans": [],
        "past": [],
        "infrastructure": [],
        "agents": [{"id": "agent-1", "title": "x" * 2000}],
        "activity_agents": [],
    }
    dashboard.snapshot_loaded_at = time.monotonic()
    response = app_request(
        app,
        "GET",
        "/api/orchestrators",
        headers={"accept-encoding": "gzip"},
    )
    assert response.headers["content-encoding"] == "gzip"
    store.close()


def test_events_does_not_support_gzip(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "GET",
        "/events",
        headers={"accept-encoding": "gzip"},
    )
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    store.close()


def test_needs_you_count_endpoint_matches_orchestrator_count(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.messages = [
        {
            "id": "count-question",
            "from": "plan-1",
            "kind": "needs-user",
            "ts": "2026-10-23T10:00:00Z",
        }
    ]
    count = app_request(app, "GET", "/api/needs-you-count").json()
    snapshot = app_request(app, "GET", "/api/orchestrators").json()
    assert count == {"needs_you_count": snapshot["needs_you_count"]}
    assert count["needs_you_count"] == 1
    store.close()


def test_needs_you_count_matches_open_items_and_excludes_acked_items(
    tmp_path, monkeypatch
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.messages = [
        {
            "id": "open-1",
            "from": "plan-1",
            "kind": "needs-user",
            "ts": "2026-10-28T10:00:00Z",
        },
        {
            "id": "open-2",
            "from": "plan-1",
            "kind": "needs-user",
            "ts": "2026-10-28T11:00:00Z",
        },
        {
            "id": "stale-1",
            "from": "plan-1",
            "kind": "needs-user",
            "ts": "2026-10-28T12:00:00Z",
        },
    ]
    cli.message_status = {
        "messages": [{"id": "stale-1", "acked": "2026-10-28T12:30:00Z"}]
    }
    count = app_request(app, "GET", "/api/needs-you-count").json()["needs_you_count"]
    threads = app_request(app, "GET", "/api/threads").json()
    orchestrators = app_request(app, "GET", "/api/orchestrators").json()

    assert count == 2
    assert sum(thread["open_count"] for thread in threads) == count
    assert orchestrators["needs_you_count"] == count
    assert (
        next(thread for thread in threads if thread["sender"] == "plan-1")[
            "stale_count"
        ]
        == 1
    )
    store.close()


def test_request_timing_logs_and_sets_server_timing(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(app, "GET", "/api/orchestrators?token=secret")
    assert response.headers["server-timing"].startswith("app;dur=")
    assert "HTTP GET /api/orchestrators status=200" in caplog.text
    assert "token=secret" not in caplog.text
    store.close()


def test_request_timing_logs_500_when_route_raises(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO")
    app, _, store = setup_app(tmp_path, monkeypatch)

    async def raise_error(request):
        raise RuntimeError("route failed")

    app.router.routes.append(Route("/raises", raise_error))
    with pytest.raises(RuntimeError, match="route failed"):
        app_request(app, "GET", "/raises")

    assert "HTTP GET /raises status=500" in caplog.text
    store.close()


def test_cross_origin_queue_post_is_rejected_by_create_app(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "POST",
        "/api/queue/move",
        content=b'{"plan":"alpha","direction":"up"}',
        headers={"origin": "http://evil.example"},
    )
    assert response.status_code == 403
    store.close()


def test_views_render_orchestrators_and_needs_context(
    tmp_path, monkeypatch, runner_ui_built
):
    client, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [{"address": "builder"}]
    client.state.dashboard.read_cache.clear()
    assert "Varde Runner" in app_request(client, "GET", "/plans").text
    mailbox_page = app_request(client, "GET", "/mailbox")
    assert mailbox_page.status_code == 307
    assert mailbox_page.headers["location"] == "/"
    queue_view = app_request(client, "GET", "/queue")
    assert queue_view.status_code == 200
    assert "Varde Runner" in queue_view.text
    mailbox = app_request(client, "GET", "/api/mailbox").json()
    assert mailbox["open"] == []
    store.close()


def test_orchestrators_split_live_and_past_and_status_request(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta
    from pathlib import Path

    app, cli, store = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "cwd", tmp_path, raising=False)
    now = datetime.now(UTC).isoformat()
    cli.plan = {
        "plans": [
            {"id": "active-plan", "assigned_to": "active-orch", "status": "active"}
        ]
    }
    retired = [f"old-{index}" for index in range(16)]
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    relay = inbox / "relay"
    relay.mkdir()
    (relay / "state.json").write_text(
        json.dumps({"retired": dict.fromkeys(retired, now)})
    )
    slots = inbox / "slots"
    slots.mkdir()
    (slots / "orchestrator-1.json").write_text(
        json.dumps({"slot": "slot-orch", "aliases": []})
    )
    cli.extra_bindings = [
        *(
            {
                "address": address,
                "last_seen": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            }
            for address in retired
        ),
        {
            "address": "slot-orch",
            "last_seen": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
        },
        {"address": "active-orch", "plan_id": "active-plan", "last_seen": now},
        {"address": "recent-orch", "last_seen": now},
        {
            "address": "agent-only",
            "last_seen": (datetime.now(UTC) - timedelta(days=1)).isoformat(),
            "wake_context": {"paseo_id": "agent-only-id"},
        },
    ]
    cli.read_address_bindings = lambda: cli.extra_bindings
    app.state.dashboard.snapshot_loaded_at = 0
    app.state.dashboard.read_cache.clear()

    snapshot = app_request(app, "GET", "/api/orchestrators").json()
    assert len(snapshot["past"]) == 17
    assert {row["address"] for row in snapshot["plans"]} == {
        "slot-orch",
        "active-orch",
        "recent-orch",
    }, {
        row["address"]: (row.get("plan_joined"), row.get("status"), row.get("live"))
        for row in snapshot["plans"]
    }
    assert {row["address"] for row in snapshot["past"]} == {*retired, "agent-only"}
    assert all("_binding" not in row for row in [*snapshot["plans"], *snapshot["past"]])

    # Make a joined live plan idle and verify the endpoint uses the CLI wrapper.
    cli.plan["plans"][0]["last_event_at"] = "2020-01-01T00:00:00Z"
    cli.extra_bindings[-1]["wake_context"] = {"paseo_id": "active-agent"}
    app.state.dashboard.agent_reader = lambda: [
        {"id": "active-agent", "status": "idle"},
        {"id": "agent-only-id", "status": "idle"},
    ]
    app.state.dashboard.snapshot_loaded_at = 0
    app.state.dashboard.agents_initialized = False
    response = app_request(app, "POST", "/api/orchestrators/active-orch/status")
    assert response.status_code == 200
    notes_path = cli.sent[-1]["notes"]
    assert notes_path.startswith(str(tmp_path / "status-request-"))
    assert notes_path.endswith(".json")
    assert (tmp_path / Path(notes_path).name).is_file()
    assert cli.sent[-1] == {
        "sender": "main",
        "recipient": "active-orch",
        "kind": "info",
        "text": "status?",
        "notes": notes_path,
    }
    second = app_request(app, "POST", "/api/orchestrators/active-orch/status")
    assert second.status_code == 200
    assert cli.sent[-1]["notes"] != notes_path
    assert Path(cli.sent[-1]["notes"]).is_file()
    missing = app_request(app, "POST", "/api/orchestrators/not-live/status")
    assert missing.status_code == 404

    def fail_send(**kwargs):
        raise RuntimeError("delivery failed")

    cli.send = fail_send
    app.state.dashboard.snapshot_loaded_at = 0
    failed = app_request(app, "POST", "/api/orchestrators/active-orch/status")
    assert failed.status_code == 502
    store.close()


def test_past_sender_keeps_plan_chip_in_mailbox_threads(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.plan = {
        "plans": [
            {
                "id": "finished-plan",
                "assigned_to": "finished-orch",
                "status": "completed",
                "title": "Finished plan",
            }
        ]
    }
    cli.extra_bindings = [{"address": "finished-orch", "plan_id": "finished-plan"}]
    cli.messages = [
        {
            "id": "finished-question",
            "from": "finished-orch",
            "kind": "needs-user",
            "notes": None,
        }
    ]
    app.state.dashboard.snapshot_loaded_at = 0
    app.state.dashboard.read_cache.clear()

    threads = app_request(app, "GET", "/api/threads").json()

    thread = next(row for row in threads if row["plan_id"] == "finished-plan")
    assert thread["thread_id"] == "plan:finished-plan"
    assert thread["plan_title"] == "Finished plan"
    store.close()


def test_mailbox_threads_only_include_needs_user_and_user_addressed_messages(
    tmp_path, monkeypatch
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.messages = [
        {
            "id": "request",
            "from": "builder",
            "kind": "needs-user",
            "text": "Please decide",
        },
        {
            "id": "worker-milestone",
            "from": "builder",
            "to": "main",
            "kind": "info",
            "text": "Build finished",
        },
        {
            "id": "response",
            "from": "builder",
            "to": "user",
            "kind": "info",
            "text": "Build finished for you",
        },
        {
            "id": "user-own-message",
            "from": "user",
            "kind": "info",
            "text": "Thanks, that works",
        },
        {
            "id": "agent-chat",
            "from": "builder",
            "to": "reviewer",
            "kind": "info",
            "text": "Internal note",
        },
        {
            "id": "relay-notice",
            "from": "relay",
            "kind": "info-failure",
            "text": "Delivery retry",
        },
    ]
    app.state.dashboard.snapshot_loaded_at = 0
    app.state.dashboard.read_cache.clear()

    threads = app_request(app, "GET", "/api/threads").json()

    by_id = {thread["thread_id"]: thread for thread in threads}
    assert set(by_id) == {"sender:builder", "sender:user"}
    assert set(by_id["sender:builder"]["decision_ids"]) == {"request", "response"}
    assert by_id["sender:user"]["decision_ids"] == ["user-own-message"]
    assert all("worker-milestone" not in thread["decision_ids"] for thread in threads)
    assert all(thread["thread_id"] != "sender:relay" for thread in threads)
    store.close()


def test_live_past_rows_and_thread_names_carry_label_and_group(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.plan = {
        "plans": [
            {
                "id": "finished-plan",
                "assigned_to": "finished-orch",
                "status": "completed",
                "title": "A very long finished plan title",
                "label": "Finished card",
                "group_name": "Dashboard",
            },
            {
                "id": "plain-plan",
                "assigned_to": "plain-orch",
                "status": "active",
                "title": "Plain full title",
            },
        ]
    }
    cli.extra_bindings = [
        {"address": "finished-orch", "plan_id": "finished-plan"},
        {"address": "plain-orch", "plan_id": "plain-plan"},
    ]
    cli.messages = [
        {"id": "q", "from": "finished-orch", "kind": "needs-user", "notes": None}
    ]
    app.state.dashboard.snapshot_loaded_at = 0
    app.state.dashboard.read_cache.clear()

    snapshot = app_request(app, "GET", "/api/orchestrators").json()
    rows = {row["id"]: row for row in [*snapshot["plans"], *snapshot["past"]]}
    assert rows["finished-plan"]["title"] == "A very long finished plan title"
    assert rows["finished-plan"]["label"] == "Finished card"
    assert rows["finished-plan"]["group_name"] == "Dashboard"
    assert rows["plain-plan"]["label"] == "Plain full title"
    assert rows["plain-plan"]["group_name"] == ""

    threads = app_request(app, "GET", "/api/threads").json()
    thread = next(row for row in threads if row["plan_id"] == "finished-plan")
    assert thread["plan_title"] == "Finished card"
    store.close()


def test_unbuilt_spa_shows_build_instructions(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr("varde_runner.web.app.UI_DIR", tmp_path / "missing-ui")
    response = app_request(app, "GET", "/plans")
    assert response.status_code == 503
    assert "Dashboard UI not built" in response.text
    assert "npm ci --prefix runner/ui" in response.text
    store.close()


def test_root_serves_ui_shell_without_redirect(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr("varde_runner.web.app.UI_DIR", tmp_path / "missing-ui")

    response = app_request(app, "GET", "/")

    assert response.status_code == 503
    assert "Dashboard UI not built" in response.text
    assert "location" not in response.headers
    store.close()


@pytest.mark.parametrize("path", ["/thread/builder", "/profile/builder"])
def test_queue_page_shell_routes_are_registered(tmp_path, monkeypatch, path):
    app, _, store = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr("varde_runner.web.app.UI_DIR", tmp_path / "missing-ui")

    response = app_request(app, "GET", path)

    assert response.status_code == 503
    assert "Dashboard UI not built" in response.text
    store.close()


def test_chats_redirects_to_chat_list(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    monkeypatch.setattr("varde_runner.web.app.UI_DIR", tmp_path / "missing-ui")

    redirect = app_request(app, "GET", "/chats")
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/"
    shell = app_request(app, "GET", redirect.headers["location"])
    assert shell.status_code == 503
    assert "Dashboard UI not built" in shell.text
    store.close()


def test_chat_pin_preferences_persist_and_validate(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    assert app_request(app, "GET", "/api/pins").json() == {
        "pins": ["manager", "builder", "reviewer"]
    }
    saved = app_request(
        app,
        "PUT",
        "/api/pins",
        content=b'{"pins":["manager","builder"]}',
        headers={"content-type": "application/json"},
    )
    assert saved.json() == {"pins": ["manager", "builder"]}
    assert app_request(app, "GET", "/api/pins").json() == saved.json()
    cleared = app_request(
        app,
        "PUT",
        "/api/pins",
        content=b'{"pins":[]}',
        headers={"content-type": "application/json"},
    )
    assert cleared.json() == {"pins": []}
    assert app_request(app, "GET", "/api/pins").json() == cleared.json()
    invalid = app_request(
        app,
        "PUT",
        "/api/pins",
        content=b'{"pins":["manager","manager"]}',
        headers={"content-type": "application/json"},
    )
    assert invalid.status_code == 400
    assert app_request(app, "GET", "/api/pins").json() == cleared.json()
    too_many = app_request(
        app,
        "PUT",
        "/api/pins",
        content=json.dumps(
            {"pins": [f"agent-{index}" for index in range(101)]}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    too_long = app_request(
        app,
        "PUT",
        "/api/pins",
        content=json.dumps({"pins": ["a" * 201]}).encode(),
        headers={"content-type": "application/json"},
    )
    assert too_many.status_code == 400
    assert too_long.status_code == 400
    oversized = app_request(
        app,
        "PUT",
        "/api/pins",
        content=b'{"pins":[]}' + b" " * 32768,
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413
    assert app_request(app, "GET", "/api/pins").json() == cleared.json()
    home = app_request(app, "GET", "/home")
    assert home.status_code == 307
    assert home.headers["location"] == "/"
    store.close()


def test_answer_option_and_free_text_use_decision_transition(tmp_path, monkeypatch):
    client, cli, store = setup_app(tmp_path, monkeypatch)
    option = app_request(
        client,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": "yes", "idempotency_key": "option-key"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert option.status_code == 200
    assert option.json()["status"] == "delivered"
    assert option.json()["reply"] == "yes"
    assert option.json()["sent_at"]
    mailbox = app_request(client, "GET", "/api/mailbox").json()
    answered = next(item for item in mailbox["all"] if item["msg_id"] == "question-1")
    assert answered["reply"] == "yes"
    assert answered["sent_at"] == option.json()["sent_at"]
    assert all(item["msg_id"] != "question-1" for item in mailbox["open"])
    # A second item shows that free text follows the same 1A transition.
    cli.messages.append(
        {"id": "question-2", "from": "builder", "kind": "needs-user", "notes": None}
    )
    free = app_request(
        client,
        "POST",
        "/mailbox/question-2/answer",
        content=json.dumps(
            {"text": "Because the second option fits.", "idempotency_key": "free-key"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert free.status_code == 200
    assert len(cli.sent) == 2
    assert store.db.execute("select count(*) from answers").fetchone()[0] == 2
    store.close()


@pytest.mark.parametrize(
    ("decision_type", "option", "text", "expected"),
    [
        ("design", "yes", "", "yes"),
        ("choice", "yes", "", "yes"),
        ("decision", "yes", "", "yes"),
        ("question", "yes", "", "yes"),
        ("design_decision", "yes", "", "yes"),
        ("approval", "approve", "", "APPROVED"),
        ("approval", "ask-more", "Please explain", "ASK-MORE: Please explain"),
    ],
)
def test_file_decision_answer_writes_and_notifies_owner(
    tmp_path, monkeypatch, decision_type, option, text, expected
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.__dict__["cwd"] = tmp_path
    plan_dir = tmp_path / "plans" / "plan-1"
    notes_dir = plan_dir / "notes"
    notes_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\ntype: plan\nid: plan-1\nstatus: active\n"
        "assigned_to: orchestrator-1\n---\n",
        encoding="utf-8",
    )
    path = notes_dir / "decision-file.json"
    options = [{"id": option, "label": option}]
    path.write_text(
        json.dumps({"type": decision_type, "asked": "Choose", "options": options}),
        encoding="utf-8",
    )
    dashboard = app.state.dashboard
    cli.extra_bindings = [{"address": "orchestrator-1", "plan_id": "plan-1"}]

    async def no_plans():
        return {
            "plans": [
                {
                    "id": "plan-1",
                    "status": "active",
                    "plan_joined": True,
                    "activity": "idle",
                }
            ],
            "past": [],
        }

    dashboard.orchestrators = no_plans
    open_items = asyncio.run(dashboard.open_mailbox_items([]))
    assert len(open_items) == 1
    decision_id = open_items[0]["msg_id"]
    assert open_items[0]["notes"] == str(path.resolve())

    async def projected_items(_dashboard):
        from varde_runner.web.app import _plan_decision_items

        return await asyncio.to_thread(_plan_decision_items, _dashboard, [], [], set())

    monkeypatch.setattr(
        "varde_runner.web.app._projected_mailbox_items", projected_items
    )
    response = app_request(
        app,
        "POST",
        f"/mailbox/{decision_id}/answer",
        content=json.dumps(
            {"option": option, "text": text, "idempotency_key": "file-answer"}
        ).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    answered = json.loads(path.read_text(encoding="utf-8"))["answered"]
    assert answered["choice"] == expected
    assert answered["ts"]
    assert answered["idempotency_key"] == "file-answer"
    assert cli.sent[-1]["recipient"] == "orchestrator-1"
    assert cli.sent[-1]["kind"] == "info"
    retry = app_request(
        app,
        "POST",
        f"/mailbox/{decision_id}/answer",
        content=json.dumps(
            {"option": option, "text": text, "idempotency_key": "file-answer"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert retry.status_code == 200
    assert len(cli.sent) == 1
    conflict = app_request(
        app,
        "POST",
        f"/mailbox/{decision_id}/answer",
        content=json.dumps(
            {"option": option, "text": text, "idempotency_key": "other-key"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert conflict.status_code == 409
    assert len(cli.sent) == 1
    store.close()


@pytest.mark.parametrize("contents", ["not-json", "[]"])
def test_invalid_file_decision_returns_not_found(tmp_path, monkeypatch, contents):
    app, _, store = setup_app(tmp_path, monkeypatch)
    path = tmp_path / "invalid-decision.json"
    path.write_text(contents, encoding="utf-8")
    item = {
        "msg_id": "file-invalid",
        "sender": "orchestrator-1",
        "kind": "needs-user",
        "state": "pending",
        "type": "choice",
        "options": ["yes"],
        "notes": str(path),
    }

    async def projected_items(_dashboard):
        return [item]

    monkeypatch.setattr(
        "varde_runner.web.app._projected_mailbox_items", projected_items
    )
    response = app_request(
        app,
        "POST",
        "/mailbox/file-invalid/answer",
        content=json.dumps(
            {"option": "yes", "idempotency_key": "invalid-answer"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 404
    store.close()


def test_file_answer_is_not_recorded_when_owner_notification_fails(
    tmp_path, monkeypatch
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    path = tmp_path / "decision.json"
    path.write_text(
        json.dumps({"type": "choice", "options": ["yes"]}), encoding="utf-8"
    )
    item = {
        "msg_id": "file-send-fail",
        "sender": "orchestrator-1",
        "kind": "needs-user",
        "state": "pending",
        "type": "choice",
        "options": ["yes"],
        "notes": str(path),
    }

    def fail_send(**_kwargs):
        raise OSError("send unavailable")

    cli.send = fail_send

    async def projected_items(_dashboard):
        return [item]

    monkeypatch.setattr(
        "varde_runner.web.app._projected_mailbox_items", projected_items
    )
    response = app_request(
        app,
        "POST",
        "/mailbox/file-send-fail/answer",
        content=json.dumps({"option": "yes", "idempotency_key": "send-fail"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 502
    assert "answered" not in json.loads(path.read_text(encoding="utf-8"))
    store.close()


def test_answer_succeeds_when_post_action_mailbox_refresh_fails(
    tmp_path, monkeypatch, caplog
):
    app, _, store = setup_app(tmp_path, monkeypatch)

    def fail_refresh(_dashboard):
        raise RuntimeError("mailbox refresh unavailable")

    monkeypatch.setattr("varde_runner.web.app._refresh_mailbox", fail_refresh)

    response = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps(
            {"text": "yes", "idempotency_key": "refresh-fails"}
        ).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "delivered"
    assert "Post-answer mailbox refresh failed" in caplog.text
    store.close()


def test_dismiss_refreshes_mailbox_list_and_succeeds_when_refresh_fails(
    tmp_path, monkeypatch, caplog
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [{"address": "builder"}]

    def fail_refresh(_dashboard):
        raise RuntimeError("mailbox refresh unavailable")

    monkeypatch.setattr("varde_runner.web.app._refresh_mailbox", fail_refresh)
    dismissed = app_request(app, "POST", "/api/mailbox/question-1/dismiss")
    assert dismissed.status_code == 200
    assert "Post-dismiss mailbox refresh failed" in caplog.text

    store.close()


def test_dismiss_refreshes_next_mailbox_list_read(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [{"address": "builder"}]
    dismissed = app_request(app, "POST", "/api/mailbox/question-1/dismiss")
    assert dismissed.status_code == 200

    mailbox = app_request(app, "GET", "/api/mailbox").json()
    assert all(item["msg_id"] != "question-1" for item in mailbox["open"])
    store.close()


def test_sse_endpoint_is_available(tmp_path, monkeypatch):
    client, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(client, "GET", "/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    store.close()


def test_sse_snapshot_includes_pending_permissions(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    permission_notes = tmp_path / "permission.json"
    permission_notes.write_text(
        json.dumps(
            {"kind": "permission", "asked": "Permission?", "options": ["allow"]}
        ),
        encoding="utf-8",
    )
    cli.messages.append(
        {
            "id": "permission-1",
            "from": "builder",
            "kind": "permission",
            "notes": str(permission_notes),
        }
    )
    app.state.projector.project()
    work_items = WorkItemStore(tmp_path)
    snapshot = asyncio.run(_events_snapshot(app.state.dashboard, work_items, {}))
    assert [item["msg_id"] for item in snapshot["permissions"]] == ["permission-1"]
    work_items.close()
    store.close()


def test_sse_frame_from_real_large_snapshot_is_small_and_skips_unchanged(
    tmp_path, monkeypatch
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.messages.extend(
        {
            "id": f"mail-{index}",
            "from": "builder",
            "kind": "needs-user",
            "text": "Mailbox item " + ("body " * 80),
        }
        for index in range(100)
    )
    dashboard = app.state.dashboard
    dashboard.agent_reader = lambda: [
        {"id": f"agent-{index}", "status": "running", "title": f"Agent {index}"}
        for index in range(100)
    ]
    dashboard.agents_initialized = False
    dashboard.snapshot_loaded_at = 0
    dashboard.read_cache.clear()
    app.state.projector.project()
    work_items = WorkItemStore(tmp_path / "event-work-items")

    async def take_snapshot():
        orchestrators = await _sse_orchestrators(dashboard)
        return await _events_snapshot(dashboard, work_items, orchestrators)

    snapshot = asyncio.run(take_snapshot())
    frame, hashes = _event_update_frame(snapshot, None)
    unchanged, same_hashes = _event_update_frame(snapshot, hashes)

    assert len(snapshot["agents"]) >= 100
    assert len(snapshot["items"]) >= 100
    assert frame is not None
    assert len(frame) < 1024
    assert unchanged is None
    assert same_hashes == hashes
    assert json.loads(frame.decode().split("data: ", 1)[1]) == {
        "topics": ["orchestrators", "mailbox", "work_items", "queue"],
        "needs_you_count": len(snapshot["needs_you"]),
    }
    work_items.close()
    store.close()


def test_sse_keepalive_decision_uses_elapsed_interval():
    from varde_runner.web.app import SSE_KEEPALIVE_INTERVAL

    assert not _event_keepalive_due(10, 10 + SSE_KEEPALIVE_INTERVAL - 0.1)
    assert _event_keepalive_due(10, 10 + SSE_KEEPALIVE_INTERVAL)


def test_sse_update_frame_skips_unchanged_snapshot_and_names_only_changed_topic():
    snapshot = {
        "plans": [],
        "past": [],
        "infrastructure": {},
        "agents": [],
        "agents_error": None,
        "needs_you": [],
        "items": [],
        "mailbox": {},
        "permissions": [],
        "work_items": [],
    }
    initial, hashes = _event_update_frame(snapshot, None)
    unchanged, same_hashes = _event_update_frame(snapshot, hashes)
    changed_snapshot = {**snapshot, "work_items": [{"id": "changed"}]}
    changed, changed_hashes = _event_update_frame(changed_snapshot, same_hashes)

    assert initial is not None
    assert unchanged is None
    assert changed is not None
    assert json.loads(changed.decode().split("data: ", 1)[1]) == {
        "topics": ["work_items"],
        "needs_you_count": 0,
    }
    assert changed_hashes != same_hashes


def test_sse_update_frame_ignores_nested_orchestrator_churn_but_keeps_status():
    snapshot = {
        "plans": [
            {
                "id": "plan-1",
                "status": "running",
                "activity": "running",
                "idle_for": 9,
                "last_message_age": "12s ago",
                "last_activity": "2026-10-23T12:00:00Z",
                "now": "Implementing the event change",
                "now_at": "2026-10-23T11:58:00Z",
                "queue": [],
                "tasks": [
                    {
                        "id": "task-1",
                        "status": "in_progress",
                        "status_at": "2026-10-23T11:50:00Z",
                    }
                ],
            }
        ],
        "past": [],
        "infrastructure": [
            {
                "address": "main",
                "paseo_id": "agent-main",
                "title": "Main",
                "status": "running",
                "stale": False,
                "last_activity": "2026-10-23T12:00:00Z",
            }
        ],
        "agents": [
            {
                "id": "agent-1",
                "title": "Builder",
                "status": "running",
                "lastActivity": "2026-10-23T12:00:00Z",
                "lastActivityAt": "2026-10-23T12:00:00Z",
                "last_activity": "2026-10-23T12:00:00Z",
                "updatedAt": "2026-10-23T12:00:00Z",
            }
        ],
        "agents_error": None,
        "needs_you": [],
    }
    _, hashes = _event_update_frame(snapshot, None)
    churned = {
        **snapshot,
        "plans": [
            {
                **snapshot["plans"][0],
                "idle_for": 10,
                "last_message_age": "13s ago",
                "last_activity": "2026-10-23T12:00:01Z",
            }
        ],
        "infrastructure": [
            {**snapshot["infrastructure"][0], "last_activity": "2026-10-23T12:00:01Z"}
        ],
        "agents": [
            {
                **snapshot["agents"][0],
                "lastActivity": "2026-10-23T12:00:01Z",
                "lastActivityAt": "2026-10-23T12:00:01Z",
                "last_activity": "2026-10-23T12:00:01Z",
                "updatedAt": "2026-10-23T12:00:01Z",
            }
        ],
    }
    unchanged, same_hashes = _event_update_frame(churned, hashes)
    status_changed = {
        **churned,
        "plans": [{**churned["plans"][0], "status": "blocked"}],
    }
    changed, _ = _event_update_frame(status_changed, same_hashes)

    assert unchanged is None
    assert changed is not None
    assert json.loads(changed.decode().split("data: ", 1)[1])["topics"] == [
        "orchestrators",
        "queue",
    ]

    now_rewritten = {
        **churned,
        "plans": [{**churned["plans"][0], "now_at": "2026-10-23T12:00:02Z"}],
    }
    now_frame, _ = _event_update_frame(now_rewritten, same_hashes)
    assert now_frame is not None


def test_answer_rejects_non_object_json(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps(["not", "an", "object"]).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400
    store.close()


def test_post_requires_loopback_host_with_bound_port(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    payload = json.dumps({"text": "yes", "idempotency_key": "host-check"}).encode()
    post_paths = (
        "/mailbox/question-1/answer",
        "/entries/key/retry",
        "/new-item",
        "/new-item/item/decision",
        "/new-item/item/plan-ready",
        "/new-item/item/questions/question/answer",
        "/roles/preview",
    )
    for path in post_paths:
        for host in (
            "example.com:8765",
            "localhost:8766",
            "127.0.0.1",
            "[::1]:8766",
            "localhost:invalid",
        ):
            response = app_request(
                app,
                "POST",
                path,
                content=payload,
                headers={"host": host, "content-type": "application/json"},
            )
            assert response.status_code == 403, (path, host)
    store.close()


def test_post_accepts_loopback_host_and_same_origin(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": "yes", "idempotency_key": "origin-check"}).encode(),
        headers={
            "host": "[::1]:8765",
            "origin": "http://[::1]:8765",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 200
    store.close()


def test_allowed_tailnet_host_and_origin_binding(tmp_path, monkeypatch):
    app, _cli, store = setup_app(
        tmp_path,
        monkeypatch,
        allowed_hosts=frozenset({"machine.tailnet.ts.net"}),
        bound_port=8765,
    )
    good = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": "yes", "idempotency_key": "tailnet"}).encode(),
        headers={
            "host": "machine.tailnet.ts.net:443",
            "origin": "https://machine.tailnet.ts.net",
            "content-type": "application/json",
        },
    )
    assert good.status_code == 200
    for host, origin in (
        ("other.tailnet.ts.net:443", "https://other.tailnet.ts.net"),
        ("machine.tailnet.ts.net:443", "https://evil.example"),
    ):
        response = app_request(
            app,
            "POST",
            "/mailbox/question-1/answer",
            content=json.dumps({"text": "yes", "idempotency_key": host}).encode(),
            headers={
                "host": host,
                "origin": origin,
                "content-type": "application/json",
            },
        )
        assert response.status_code == 403
    store.close()


def test_serve_entrypoint_binds_only_to_loopback(monkeypatch, tmp_path):
    import sys

    import varde_runner

    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["varde-runner", "serve", "--port", "8765"])
    captured = {}
    monkeypatch.setattr(
        varde_runner.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs)
    )
    monkeypatch.setattr(
        "varde_runner.web.create_app",
        lambda **kwargs: captured.update({"app_options": kwargs}) or object(),
    )

    varde_runner.main()

    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8765
    assert (
        captured["timeout_graceful_shutdown"] == varde_runner.GRACEFUL_SHUTDOWN_TIMEOUT
    )
    assert captured["app_options"]["bound_port"] == 8765


def test_post_rejects_cross_origin_and_sse_checks_host(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": "yes", "idempotency_key": "bad-origin"}).encode(),
        headers={
            "host": "localhost:8765",
            "origin": "http://evil.example:8765",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403
    sse = app_request(app, "GET", "/events", headers={"host": "evil.example:8765"})
    assert sse.status_code == 403
    store.close()


def test_string_option_and_hostile_question_render_as_text(tmp_path, monkeypatch):
    app, cli, store = setup_app(
        tmp_path,
        monkeypatch,
        option_context={
            "asked": '<img src=x onerror="alert(1)">',
            "why": "Choose safely",
            "options": ["yes"],
        },
    )
    cli.extra_bindings = [{"address": "builder"}]
    app.state.dashboard.read_cache.clear()
    response = app_request(app, "GET", "/api/mailbox")
    assert response.status_code == 200
    assert response.json()["open"] == []
    item = next(
        row for row in response.json()["all"] if row["msg_id"] == "question-options"
    )
    assert item["asked"] == '<img src=x onerror="alert(1)">'
    assert item["options"] == ["yes"]
    store.close()


def test_mailbox_list_projects_messages_added_after_startup(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [{"address": "builder"}]
    app.state.dashboard.read_cache.clear()
    cli.messages.append(
        {"id": "question-later", "from": "builder", "kind": "needs-user"}
    )

    response = app_request(app, "GET", "/api/mailbox")

    assert response.status_code == 200
    assert response.json()["open"] == []
    store.close()


def test_mailbox_open_items_exclude_replied_acked_unbound_and_concluded(
    tmp_path, monkeypatch
):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.plan["plans"][0]["status"] = "completed"
    cli.extra_bindings = [
        {"address": "builder"},
        {"address": "open-agent"},
        {"address": "ack-agent"},
    ]
    app.state.dashboard.read_cache.clear()
    cli.messages.extend(
        [
            {
                "id": "q-open",
                "from": "open-agent",
                "kind": "needs-user",
                "ts": "2026-10-20T10:00:00Z",
            },
            {
                "id": "q-replied",
                "from": "builder",
                "kind": "needs-user",
                "ts": "2026-10-20T11:00:00Z",
            },
            {
                "id": "reply",
                "from": "main",
                "to": "builder",
                "kind": "info",
                "ts": "2026-10-20T11:30:00Z",
            },
            {
                "id": "q-acked",
                "from": "ack-agent",
                "kind": "needs-user",
                "ts": "2026-10-20T12:00:00Z",
            },
            {
                "id": "q-unbound",
                "from": "unbound-agent",
                "kind": "needs-user",
                "ts": "2026-10-20T12:00:00Z",
            },
            {
                "id": "q-concluded",
                "from": "plan-1",
                "kind": "needs-user",
                "ts": "2026-10-20T12:00:00Z",
            },
        ]
    )
    cli.message_status = {
        "messages": [{"id": "q-acked", "acked": "2026-10-20T12:01:00Z"}]
    }

    response = app_request(app, "GET", "/api/mailbox")

    open_ids = {item["msg_id"] for item in response.json()["open"]}
    assert not open_ids
    all_items = {item["msg_id"]: item for item in response.json()["all"]}
    assert len(all_items) >= 5
    assert all_items["q-acked"]["mailbox_open"] is False
    assert all_items["q-concluded"]["mailbox_open"] is False
    store.close()


def test_mailbox_pages_displayed_items_and_keeps_open_items_complete(
    tmp_path, monkeypatch
):
    import varde_runner.web.app as web_app

    app, _, store = setup_app(tmp_path, monkeypatch)
    first_ts = datetime(2026, 10, 1, tzinfo=UTC)
    items = [
        {
            "msg_id": f"item-{index:04}",
            "kind": "needs-user",
            "state": "delivered",
            "ts": (first_ts + timedelta(seconds=index // 2)).isoformat(),
            "body": "x" * 1200,
        }
        for index in range(500)
    ]
    opened = [
        {
            "msg_id": f"open-{index}",
            "kind": "needs-user",
            "state": "pending",
            "ts": (first_ts - timedelta(days=1)).isoformat(),
        }
        for index in range(3)
    ]
    all_items = [*items, *opened]

    async def projected(_dashboard):
        return all_items

    async def open_items(_items):
        return opened

    monkeypatch.setattr(web_app, "_projected_mailbox_items", projected)
    monkeypatch.setattr(app.state.dashboard, "open_mailbox_items", open_items)

    response = app_request(app, "GET", "/api/mailbox")
    first = response.json()
    assert len(first["all"]) == 50
    assert first["total"] == 503
    assert len(json.dumps(first).encode()) < 70_000
    assert [item["msg_id"] for item in first["all"]] == [
        f"item-{index:04}" for index in range(499, 449, -1)
    ]
    assert len(first["open"]) == 3
    assert len(first["permissions"]) == 0

    seen = [item["msg_id"] for item in first["all"]]
    previous_item = first["all"][-1]
    cursor = first["next_before"]
    while cursor is not None:
        page = app_request(app, "GET", f"/api/mailbox?before={cursor}").json()
        assert len({item["msg_id"] for item in page["all"]}) == len(page["all"])
        assert all(
            (item["ts"], item["msg_id"])
            < (previous_item["ts"], previous_item["msg_id"])
            for item in page["all"]
        )
        if page["all"]:
            previous_item = page["all"][-1]
        seen.extend(item["msg_id"] for item in page["all"])
        assert len(page["open"]) == 3
        cursor = page["next_before"]
    assert seen == [
        *[f"item-{index:04}" for index in range(499, -1, -1)],
        "open-2",
        "open-1",
        "open-0",
    ]
    store.close()


def test_mailbox_cursor_survives_item_removal_and_limits_are_validated(
    tmp_path, monkeypatch
):
    import varde_runner.web.app as web_app

    app, _, store = setup_app(tmp_path, monkeypatch)
    items = [
        {
            "msg_id": f"item-{index:04}",
            "kind": "needs-user",
            "state": "delivered",
            "ts": (
                datetime(2026, 10, 1, tzinfo=UTC) + timedelta(seconds=index)
            ).isoformat(),
        }
        for index in range(250)
    ]

    async def projected(_dashboard):
        return items

    async def no_open_items(_items):
        return []

    monkeypatch.setattr(web_app, "_projected_mailbox_items", projected)
    monkeypatch.setattr(app.state.dashboard, "open_mailbox_items", no_open_items)

    first = app_request(app, "GET", "/api/mailbox?before=").json()
    assert first["all"][0]["msg_id"] == "item-0249"
    assert app_request(app, "GET", "/api/mailbox?limit=wat").status_code == 400
    assert len(app_request(app, "GET", "/api/mailbox?limit=999").json()["all"]) == 200
    assert len(app_request(app, "GET", "/api/mailbox?limit=0").json()["all"]) == 1

    del items[
        items.index(next(item for item in items if item["msg_id"] == "item-0200"))
    ]
    next_page = app_request(
        app, "GET", f"/api/mailbox?before={first['next_before']}"
    ).json()
    assert next_page["all"][0]["msg_id"] == "item-0199"
    assert all(item["msg_id"] != "item-0200" for item in next_page["all"])
    store.close()


def test_mailbox_ids_query_returns_compact_current_thread_items(tmp_path, monkeypatch):
    import varde_runner.web.app as web_app

    app, _, store = setup_app(tmp_path, monkeypatch)
    items = [
        {
            "msg_id": "thread-item",
            "kind": "needs-user",
            "state": "pending",
            "ts": "2026-10-01T00:00:00Z",
            "sender": "builder",
            "title": "Thread item",
            "asked": "A question",
            "body": "x" * 1200,
        }
    ]

    async def projected(_dashboard):
        return items

    async def open_items(_items):
        return items

    monkeypatch.setattr(web_app, "_projected_mailbox_items", projected)
    monkeypatch.setattr(app.state.dashboard, "open_mailbox_items", open_items)

    response = app_request(app, "GET", "/api/mailbox?ids=thread-item")

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "msg_id": "thread-item",
            "kind": "needs-user",
            "state": "pending",
            "ts": "2026-10-01T00:00:00Z",
            "sender": "builder",
            "title": "Thread item",
            "asked": "A question",
            "mailbox_open": True,
            "summary_only": True,
        }
    ]
    assert len(response.content) < 1000
    store.close()


def test_answer_limit_is_20000_and_preserves_full_body(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    allowed = "🙂" * 10_000
    accepted = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": allowed, "idempotency_key": "twenty-k"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert accepted.status_code == 200
    entry = store.get_entry("twenty-k")
    assert entry is not None
    assert entry.body == allowed
    rejected = app_request(
        app,
        "POST",
        "/mailbox/question-options/answer",
        content=json.dumps(
            {"text": "x" * 20_001, "idempotency_key": "too-long-2"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert rejected.status_code == 413
    assert store.get_entry("too-long-2") is None
    assert len(cli.sent) == 1
    store.close()


def test_failed_delivery_is_visible_and_retry_delivers(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    send = cli.send
    fail = True

    def flaky_send(**kwargs):
        nonlocal fail
        if fail:
            fail = False
            raise RuntimeError("temporarily unavailable")
        return send(**kwargs)

    store.send = flaky_send
    failed = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps(
            {"text": "keep me", "idempotency_key": "retry-key"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert failed.json()["status"] == "failed"
    entry = store.get_entry("retry-key")
    assert entry is not None
    assert entry.body == "keep me"
    retried = app_request(app, "POST", "/entries/retry-key/retry")
    assert retried.json()["status"] == "delivered"
    assert len(cli.sent) == 1
    store.close()


def test_permission_failure_retries_sidecar_once_and_rejects_free_text(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "varde_runner.intake.InboxProjector._read_context",
        staticmethod(
            lambda _notes: {
                "type": "permission",
                "asked": "Allow?",
                "why": "Needs access",
                "options": [
                    {"id": "approve", "label": "Always allow", "kind": "allow"},
                    {"id": "reject", "label": "No", "kind": "deny"},
                ],
            }
        ),
    )

    class Plugin:
        attempts = 0

        async def respond_permission(self, _ref, request_id, decision):
            assert request_id == "permission-1"
            assert decision == "allow"
            self.attempts += 1
            if self.attempts == 1:
                raise RuntimeError("temporary sidecar failure")

        async def close(self):
            pass

    plugin = Plugin()
    monkeypatch.setattr(
        "varde_runner.web.registry.PaseoPlugin.from_environment", lambda: plugin
    )
    app, cli, store = setup_app(tmp_path, monkeypatch)

    async def respond(session_id, request_id, decision, _harness=None):
        await plugin.respond_permission(
            SimpleNamespace(session_id=session_id), request_id, decision
        )
        return "responded"

    app.state.dashboard.respond = respond
    cli.messages.append(
        {
            "id": "permission-1",
            "from": "builder",
            "kind": "permission",
            "notes": "permission.json",
        }
    )
    app.state.dashboard.projector.project()
    permission_item = next(
        item for item in app.state.dashboard.inbox() if item["msg_id"] == "permission-1"
    )
    assert permission_item["options"] == [
        {"id": "approve", "label": "Always allow", "kind": "allow"},
        {"id": "reject", "label": "No", "kind": "deny"},
    ]
    free = app_request(
        app,
        "POST",
        "/mailbox/permission-1/answer",
        content=json.dumps(
            {"text": "allow", "idempotency_key": "permission-key"}
        ).encode(),
    )
    assert free.status_code == 400
    first = app_request(
        app,
        "POST",
        "/mailbox/permission-1/answer",
        content=json.dumps(
            {"option": "approve", "idempotency_key": "permission-key"}
        ).encode(),
    )
    assert first.status_code == 200, first.json()
    assert plugin.attempts == 1
    assert first.json()["status"] == "failed"
    retry = app_request(app, "POST", "/entries/permission-key/retry")
    assert retry.json()["status"] == "delivered"
    replay = app_request(
        app,
        "POST",
        "/mailbox/permission-1/answer",
        content=json.dumps(
            {"option": "approve", "idempotency_key": "permission-key"}
        ).encode(),
    )
    assert replay.json()["status"] == "delivered"
    assert plugin.attempts == 2
    store.close()


def test_default_rejects_tailnet_host(tmp_path, monkeypatch):
    app, _, _ = setup_app(tmp_path, monkeypatch, bound_port=8765)
    response = app_request(
        app,
        "POST",
        "/mailbox/question-1/answer",
        content=json.dumps({"text": "yes", "idempotency_key": "default"}).encode(),
        headers={
            "host": "machine.tailnet.ts.net:443",
            "origin": "https://machine.tailnet.ts.net",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403


def test_brand_assets_are_served_from_site_root(tmp_path, monkeypatch, runner_ui_built):
    app, _, store = setup_app(tmp_path, monkeypatch)
    expected_types = {
        "/favicon.svg": "image/svg+xml",
        "/favicon-32.png": "image/png",
        "/favicon-16.png": "image/png",
        "/apple-touch-icon.png": "image/png",
        "/manifest.webmanifest": "application/manifest+json",
        "/icon-192.png": "image/png",
        "/icon-512.png": "image/png",
    }
    for path, content_type in expected_types.items():
        response = app_request(app, "GET", path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(content_type)
    ico = app_request(app, "GET", "/favicon.ico")
    assert ico.status_code == 200
    assert ico.headers["content-type"].startswith("image/png")
    store.close()


def test_settings_api_normalizes_legacy_icon_and_serves_brand_assets(
    tmp_path, monkeypatch, runner_ui_built
):
    from pathlib import Path

    app, _, store = setup_app(tmp_path, monkeypatch)
    app.state.settings_path.write_text('{"app_icon":"26a"}')
    assert app_request(app, "GET", "/api/settings").json() == {
        "app_icon": "slate-bronze",
        "options": [
            {"id": "slate-bronze", "name": "Slate bronze"},
            {"id": "dark", "name": "Dark slate bronze"},
        ],
    }
    response = app_request(
        app,
        "POST",
        "/api/settings",
        content=b'{"app_icon":"dark"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"app_icon": "dark"}
    root = Path(__file__).parents[1] / "ui" / "static"
    for name in (
        "favicon.svg",
        "favicon-32.png",
        "favicon-16.png",
        "apple-touch-icon.png",
        "icon-192.png",
        "icon-512.png",
    ):
        response = app_request(app, "GET", f"/{name}")
        assert response.content == (root / name).read_bytes()
        assert response.headers["cache-control"] == "no-cache"
    light = app_request(app, "GET", "/favicon-32.png")
    dark = app_request(app, "GET", "/icons/dark/favicon-32.png")
    assert dark.content == (root / "icons/dark/favicon-32.png").read_bytes()
    assert dark.content != light.content
    store.close()


def test_pins_post_rejects_invalid_json_and_host(tmp_path, monkeypatch):
    app, _, store = setup_app(tmp_path, monkeypatch)
    response = app_request(
        app,
        "POST",
        "/api/pins",
        content=b"{}",
        headers={
            "host": "example.com",
            "origin": "https://example.com",
            "content-type": "application/json",
        },
    )
    assert response.status_code == 403
    store.close()


def test_app_html_links_brand_assets():
    from pathlib import Path

    app_html = Path("runner/ui/src/app.html").read_text()
    for link in (
        'rel="icon" type="image/svg+xml" href="/favicon.svg"',
        'rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png"',
        'rel="icon" type="image/png" sizes="16x16" href="/favicon-16.png"',
        'rel="apple-touch-icon" href="/apple-touch-icon.png"',
        'rel="manifest" href="/manifest.webmanifest"',
        'name="theme-color"',
    ):
        assert link in app_html
    assert 'href="/icons/dark/favicon-32.png"' not in app_html


def test_real_needs_you_projection_agrees_across_dashboard_apis(tmp_path, monkeypatch):
    app, cli, _ = setup_app(tmp_path, monkeypatch)
    plans = [
        {
            "id": "live-plan",
            "status": "active",
            "assigned_to": "orch-live",
            "title": "Live",
            "open_questions": 1,
        },
        {
            "id": "acked-plan",
            "status": "active",
            "assigned_to": "orch-acked",
            "title": "Acked",
            "open_questions": 1,
        },
        {
            "id": "concluded-plan",
            "status": "completed",
            "assigned_to": "orch-concluded",
            "title": "Concluded",
        },
        {
            "id": "pstack-measure",
            "status": "completed",
            "assigned_to": "orch-completed",
            "title": "Completed",
        },
    ]
    cli.plan = {"plans": plans}
    cli.extra_bindings = [
        {
            "address": f"orch-{name}",
            "plan_id": plan_id,
            "wake_context": {"paseo_id": f"agent-{name}"},
        }
        for name, plan_id in [
            ("live", "live-plan"),
            ("acked", "acked-plan"),
            ("concluded", "concluded-plan"),
            ("completed", "pstack-measure"),
        ]
    ] + [
        {"address": "qs-call-resolver", "wake_context": {"paseo_id": "agent-unjoined"}}
    ]
    cli.messages = [
        {
            "id": "live-question",
            "from": "orch-live",
            "kind": "needs-user",
            "ts": "2026-10-22T10:00:00Z",
        },
        {
            "id": "sweep-failure",
            "from": "varde-runner",
            "kind": "info-failure",
            "ts": "2026-10-22T10:01:00Z",
            "text": "Daily learn sweep failed",
        },
        {
            "id": "acked-question",
            "from": "orch-acked",
            "kind": "needs-user",
            "ts": "2026-10-22T10:00:00Z",
        },
        {
            "id": "concluded-question",
            "from": "orch-concluded",
            "kind": "needs-user",
            "ts": "2026-10-22T10:00:00Z",
        },
        {
            "id": "unjoined-question",
            "from": "qs-call-resolver",
            "kind": "needs-user",
            "ts": "2026-10-22T10:00:00Z",
        },
        {
            "id": "completed-question",
            "from": "orch-completed",
            "kind": "needs-user",
            "ts": "2026-10-22T10:00:00Z",
        },
    ]
    cli.message_status = {"messages": [{"id": "acked-question", "acked": True}]}

    threads = app_request(app, "GET", "/api/threads").json()
    mailbox = app_request(app, "GET", "/api/mailbox").json()
    snapshot = app_request(app, "GET", "/api/orchestrators").json()

    assert [thread["plan_id"] for thread in threads if thread["open_count"]] == [
        "live-plan"
    ]
    assert [item["msg_id"] for item in mailbox["open"]] == ["live-question"]
    assert [
        item["msg_id"] for item in mailbox["all"] if item["kind"] == "info-failure"
    ] == ["sweep-failure"]
    assert [
        plan["id"] for plan in snapshot["plans"] if plan["activity"] == "waiting"
    ] == ["live-plan"]
    assert snapshot["needs_you"] == [
        thread for thread in threads if thread["open_count"]
    ]
    assert (
        snapshot["needs_you_count"]
        == sum(bool(thread["open_count"]) for thread in threads)
        == 1
    )


def _now_line_through_ui(row):
    import subprocess
    from pathlib import Path

    ui = Path(__file__).parents[1] / "ui"
    script = (
        "import { nowLine } from './src/lib/plans.ts';"
        "console.log(nowLine(JSON.parse(process.argv[1])));"
    )
    return subprocess.run(  # noqa: S603 - fixed argv in test
        [  # noqa: S607 - fixed executable from test PATH
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            script,
            json.dumps(row),
        ],
        cwd=ui,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_now_at_reaches_ui_and_decides_derived_line(tmp_path, monkeypatch):
    import subprocess
    from datetime import datetime, timedelta

    from varde_runner.varde_cli import VardeCLI

    app, cli, store = setup_app(tmp_path, monkeypatch)
    cli.extra_bindings = [
        {"address": "p1-orch", "wake_context": {"paseo_id": "p1-agent"}}
    ]
    app.state.dashboard.paseo_agents = lambda: [{"id": "p1-agent", "status": "running"}]
    plan_dir = tmp_path / "working" / "plans" / "p1"
    plan_dir.mkdir(parents=True)
    (plan_dir / "plan.md").write_text(
        "---\ntype: plan\nid: p1\nstatus: active\n---\n", encoding="utf-8"
    )
    task_path = plan_dir / "tasks" / "t1.md"
    task_path.parent.mkdir(parents=True)
    task_path.write_text(
        "---\ntype: task\nid: t1\ntitle: Build parser\nstatus: todo\n---\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    subprocess.run(  # noqa: S603 - fixed argv in test
        ["varde", "plan", "task", "set", str(task_path), "building"],  # noqa: S607 - fixed executable from test PATH
        check=True,
        capture_output=True,
        text=True,
    )

    task_reader = VardeCLI(
        cwd=tmp_path, env={"VARDE_WORKING_DIR": str(plan_dir.parents[1])}
    )
    monkeypatch.setattr(
        cli, "read_plan_tasks", task_reader.read_plan_tasks, raising=False
    )
    cli.plan = {
        "plans": [
            {
                "id": "p1",
                "assigned_to": "p1-orch",
                "status": "active",
                "now": "next: integrating wave 1",
            }
        ]
    }
    status_at = datetime.fromisoformat(
        task_reader.read_plan_tasks("p1")[0]["status_at"]
    )

    def plan_row(now_at):
        cli.plan["plans"][0]["now_at"] = now_at
        app.state.dashboard.snapshot_loaded_at = 0
        app.state.dashboard.read_cache.clear()
        rows = app_request(app, "GET", "/api/orchestrators").json()["plans"]
        return next(row for row in rows if row["id"] == "p1")

    older_at = (status_at - timedelta(minutes=1)).isoformat()
    older = plan_row(older_at)
    assert older["now_at"] == older_at
    assert older["queue"][0]["status_at"] == status_at.isoformat().replace(
        "+00:00", "Z"
    )
    assert _now_line_through_ui(older) == "Build parser building"
    newer = plan_row((status_at + timedelta(minutes=1)).isoformat())
    assert _now_line_through_ui(newer) == "integrating wave 1"
    store.close()
