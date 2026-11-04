import asyncio
import json
import subprocess
import threading
import time

import pytest
import varde_runner.web.queue as queue_module
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from test_web import app_request
from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_runner.queue import (
    CATEGORY_LIMITS,
    category_for_plan,
    has_saved_order,
    move_plan,
    next_up,
    ordered_ids,
    parse_frontmatter,
    slot_usage,
)
from varde_runner.web.queue import (
    _plan_activity_for_queue,
    _plan_detail_record,
    _plan_metadata,
    _readiness,
    _readiness_label,
    _resolve_group,
    create_queue_routes,
)


def test_category_rules_and_limits():
    assert category_for_plan("fix-thing", "new-feature") == "new-feature"
    assert category_for_plan("friction-thing", None) == "friction"
    assert category_for_plan("fix-thing", None) == "fixes"
    assert category_for_plan("other", "fixes") == "fixes"
    assert category_for_plan("other") == "uncategorized"
    assert CATEGORY_LIMITS == {"new-feature": 2, "fixes": 1, "friction": 1}


def test_shelled_title_is_not_held():
    assert (
        _readiness_label(
            {
                "status": "backlog",
                "title": "Handle shelled commands",
                "reviewed_commit": "abc",
            },
            0,
            1,
        )
        == "ready"
    )


def test_ordering_discards_unknown_and_appends_missing_sorted():
    assert ordered_ids(["b", "a", "c"], ["c", "gone"]) == ["c", "a", "b"]
    assert next_up(["first", "second"]) == "first"
    assert next_up([]) is None


def test_missing_queue_order_has_no_priority(tmp_path):
    assert has_saved_order(tmp_path / "queue-order.json") is False
    path = tmp_path / "queue-order.json"
    path.write_text('{"version":1,"order":{}}', encoding="utf-8")
    assert has_saved_order(path) is True


def test_queue_snapshot_warm_and_stale_requests_are_fast_with_many_plans(tmp_path):
    plans = tmp_path / "plans"
    plan_ids = [f"plan-{index:03}" for index in range(114)]
    for plan_id in plan_ids:
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(
            "---\ncategory: friction\nstatus: backlog\n---\n", encoding="utf-8"
        )
    refresh_started = threading.Event()

    class SlowCLI:
        calls = 0

        def read_plan_status(self):
            self.calls += 1
            if self.calls > 1:
                refresh_started.set()
            time.sleep(0.5)
            return {
                "plans": [{"id": plan_id, "status": "backlog"} for plan_id in plan_ids]
            }

        def read_address_bindings(self):
            return []

    revision = [0]
    cli = SlowCLI()
    app = Starlette(
        routes=create_queue_routes(
            cli, tmp_path, activity_signature=lambda: revision[0]
        )
    )

    async def request_queue():
        route = next(
            route
            for route in app.routes
            if isinstance(route, Route) and route.path == "/api/queue"
        )
        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/queue",
                "raw_path": b"/api/queue",
                "query_string": b"",
                "headers": [],
                "server": ("127.0.0.1", 8000),
                "client": ("127.0.0.1", 1234),
                "app": app,
            }
        )
        return await route.endpoint(request)

    async def measure_requests():
        start = time.perf_counter()
        cold = await request_queue()
        cold_ms = (time.perf_counter() - start) * 1000
        assert cold.status_code == 200

        start = time.perf_counter()
        warm = await request_queue()
        warm_ms = (time.perf_counter() - start) * 1000
        assert warm.status_code == 200
        assert warm_ms < 250

        revision[0] += 1
        start = time.perf_counter()
        stale = await request_queue()
        stale_ms = (time.perf_counter() - start) * 1000
        assert stale.status_code == 200
        assert stale_ms < 250
        assert await asyncio.to_thread(refresh_started.wait, 1)
        return cold_ms, warm_ms, stale_ms

    cold_ms, warm_ms, stale_ms = asyncio.run(measure_requests())
    print(
        f"114 plans: cold {cold_ms:.1f} ms, warm {warm_ms:.1f} ms, "
        f"stale {stale_ms:.1f} ms"
    )


async def _queue_route_call(app, *, method="GET", body=None):
    path = "/api/queue/move" if method == "POST" else "/api/queue"
    route = next(
        route for route in app.routes if isinstance(route, Route) and route.path == path
    )
    payload = json.dumps(body).encode() if body is not None else b""
    received = False

    async def receive():
        nonlocal received
        if received:
            return {"type": "http.disconnect"}
        received = True
        return {"type": "http.request", "body": payload, "more_body": False}

    request = Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
            "server": ("127.0.0.1", 8000),
            "client": ("127.0.0.1", 1234),
            "app": app,
        },
        receive,
    )
    return await route.endpoint(request)


def _queue_order(snapshot):
    category = next(item for item in snapshot["categories"] if item["id"] == "fixes")
    return [row["id"] for row in category["waiting"]]


def _two_plan_queue(tmp_path):
    for plan_id in ("alpha", "beta"):
        folder = tmp_path / "plans" / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(
            "---\nstatus: backlog\ncategory: fixes\n---\n", encoding="utf-8"
        )
    (tmp_path / "queue-order.json").write_text(
        '{"version":1,"order":{"fixes":["alpha","beta"]}}',
        encoding="utf-8",
    )


def test_queue_move_wins_over_inflight_snapshot_refresh(tmp_path, monkeypatch):
    _two_plan_queue(tmp_path)
    original_to_thread = asyncio.to_thread
    build_ready = asyncio.Event()
    release_build = asyncio.Event()
    builds = 0

    async def gate_build(func, *args, **kwargs):
        nonlocal builds
        result = await original_to_thread(func, *args, **kwargs)
        if func.__name__ == "build_snapshot":
            builds += 1
            if builds == 2:
                build_ready.set()
                await release_build.wait()
        return result

    monkeypatch.setattr(queue_module.asyncio, "to_thread", gate_build)
    monkeypatch.setattr(queue_module, "QUEUE_CACHE_TTL", 0)

    class CLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {"id": item, "status": "backlog"} for item in ("alpha", "beta")
                ]
            }

        def read_address_bindings(self):
            return []

    async def scenario():
        app = Starlette(routes=create_queue_routes(CLI(), tmp_path))
        await _queue_route_call(app)
        await _queue_route_call(app)
        await asyncio.wait_for(build_ready.wait(), timeout=1)
        moved = await _queue_route_call(
            app, method="POST", body={"plan": "beta", "direction": "up"}
        )
        assert moved.status_code == 200
        release_build.set()
        await asyncio.sleep(0.02)
        snapshot = await _queue_route_call(app)
        assert _queue_order(json.loads(snapshot.body)) == ["beta", "alpha"]

    asyncio.run(scenario())


def test_queue_signature_change_discards_inflight_refresh(tmp_path, monkeypatch):
    folder = tmp_path / "plans" / "alpha"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nstatus: active\ncategory: fixes\n---\n", encoding="utf-8"
    )
    original_to_thread = asyncio.to_thread
    build_ready = asyncio.Event()
    release_build = asyncio.Event()
    builds = 0
    revision = [0]
    activity_calls = 0

    async def gate_build(func, *args, **kwargs):
        nonlocal builds
        result = await original_to_thread(func, *args, **kwargs)
        if func.__name__ == "build_snapshot":
            builds += 1
            if builds == 2:
                build_ready.set()
                await release_build.wait()
        return result

    monkeypatch.setattr(queue_module.asyncio, "to_thread", gate_build)
    monkeypatch.setattr(queue_module, "QUEUE_CACHE_TTL", 0)

    class CLI:
        def read_plan_status(self):
            return {"plans": [{"id": "alpha", "status": "active"}]}

        def read_address_bindings(self):
            return []

    async def activity():
        nonlocal activity_calls
        activity_calls += 1
        return {
            "plans": [
                {
                    "id": "alpha",
                    "activity": "running" if revision[0] else "backlog",
                    "agent_status": "idle",
                }
            ]
        }

    async def scenario():
        app = Starlette(
            routes=create_queue_routes(
                CLI(),
                tmp_path,
                activity_reader=activity,
                activity_signature=lambda: revision[0],
            )
        )
        await _queue_route_call(app)
        await _queue_route_call(app)
        await asyncio.wait_for(build_ready.wait(), timeout=1)
        revision[0] = 1
        await _queue_route_call(app)
        monkeypatch.setattr(queue_module, "QUEUE_CACHE_TTL", 100)
        release_build.set()

        async def wait_for_latest_snapshot():
            while True:
                latest = await _queue_route_call(app)
                if json.loads(latest.body)["slots"]["used"] == 1:
                    return latest
                await asyncio.sleep(0)

        latest = await asyncio.wait_for(wait_for_latest_snapshot(), timeout=5)
        assert activity_calls >= 3
        assert json.loads(latest.body)["slots"]["used"] == 1

    asyncio.run(scenario())


def test_queue_stale_value_survives_refresh_failure(tmp_path, monkeypatch):
    _two_plan_queue(tmp_path)
    monkeypatch.setattr(queue_module, "QUEUE_CACHE_TTL", 0)
    calls = 0

    class CLI:
        fail = False

        def read_plan_status(self):
            nonlocal calls
            calls += 1
            if self.fail:
                raise RuntimeError("refresh failed")
            return {
                "plans": [
                    {"id": item, "status": "backlog"} for item in ("alpha", "beta")
                ]
            }

        def read_address_bindings(self):
            return []

    async def scenario():
        cli = CLI()
        app = Starlette(routes=create_queue_routes(cli, tmp_path))
        first = await _queue_route_call(app)
        assert _queue_order(json.loads(first.body)) == ["alpha", "beta"]
        cli.fail = True
        stale = await _queue_route_call(app)
        assert _queue_order(json.loads(stale.body)) == ["alpha", "beta"]
        await asyncio.sleep(0.02)
        again = await _queue_route_call(app)
        assert _queue_order(json.loads(again.body)) == ["alpha", "beta"]
        assert calls == 2

    asyncio.run(scenario())


def test_queue_cold_failure_uses_negative_cache_window(tmp_path, monkeypatch):
    monkeypatch.setattr(queue_module, "QUEUE_CACHE_TTL", 0)
    calls = 0

    class CLI:
        def read_plan_status(self):
            nonlocal calls
            calls += 1
            raise RuntimeError("cold read failed")

        def read_address_bindings(self):
            return []

    async def scenario():
        app = Starlette(routes=create_queue_routes(CLI(), tmp_path))
        for _ in range(2):
            response = await _queue_route_call(app)
            assert response.status_code == 200
            assert json.loads(response.body)["degraded"] is True
        assert calls == 1
        await asyncio.sleep(1.01)
        response = await _queue_route_call(app)
        assert response.status_code == 200
        assert json.loads(response.body)["degraded"] is True
        assert calls == 2

    asyncio.run(scenario())


def test_move_and_slot_usage():
    assert move_plan(["a", "b", "c"], "b", "up") == ["b", "a", "c"]
    assert move_plan(["b", "a", "c"], "b", "down") == ["a", "b", "c"]
    assert slot_usage(["active", "done"], {"active"}, 2) == {"used": 1, "limit": 2}


def test_queue_move_and_running_comment_delivery(tmp_path):
    plans = tmp_path / "plans"
    for plan_id in ("alpha", "beta"):
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(
            f"---\ntitle: {plan_id}\nstatus: backlog\n---\nPlan body", encoding="utf-8"
        )

    class FakeCLI:
        def __init__(self):
            self.sent = []
            self.bindings = []

        def read_plan_status(self):
            return {
                "plans": [
                    {"id": "alpha", "status": "backlog"},
                    {"id": "beta", "status": "backlog"},
                ]
            }

        def read_address_bindings(self):
            return self.bindings

        def send(self, **kwargs):
            self.sent.append(kwargs)

    cli = FakeCLI()
    app = Starlette(routes=create_queue_routes(cli, tmp_path))
    moved = app_request(
        app,
        "POST",
        "/api/queue/move",
        content=json.dumps({"plan": "beta", "direction": "up"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert moved.status_code == 200
    assert moved.json() == {"category": "uncategorized", "order": ["beta", "alpha"]}
    assert json.loads((tmp_path / "queue-order.json").read_text())["order"][
        "uncategorized"
    ] == ["beta", "alpha"]
    immediate = app_request(app, "GET", "/api/queue")
    assert [row["id"] for row in immediate.json()["categories"][3]["waiting"]] == [
        "beta",
        "alpha",
    ]
    cli.bindings = [{"address": "beta"}]
    sent = app_request(
        app,
        "POST",
        "/api/plans/beta/comments",
        content=json.dumps({"target": "plan", "text": "Please check this"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert sent.status_code == 201
    assert sent.json()["comment"]["actor"] == "main"
    assert cli.sent[0]["sender"] == "main"
    assert cli.sent[0]["recipient"] == "beta"
    assert cli.sent[0]["kind"] == "info"
    assert cli.sent[0]["text"] == "Comment on plan: Please check this"
    assert cli.sent[0]["notes"].endswith("plans/beta/plan.md")

    from varde_runner.bot_tokens import BotIdentity

    async def bot_app(scope, receive, send):
        scope["bot_identity"] = BotIdentity("bot:manager/session-1", "session-1")
        await app(scope, receive, send)

    bot_comment = app_request(
        bot_app,
        "POST",
        "/api/plans/beta/comments",
        content=json.dumps({"target": "plan", "text": "Manager note"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert bot_comment.status_code == 201
    assert bot_comment.json()["comment"]["actor"] == "bot:manager/session-1"
    assert cli.sent[1]["sender"] == "manager"


def test_queue_move_uses_cached_waiting_list_without_rebuilding_snapshot(tmp_path):
    plans = tmp_path / "plans"
    for plan_id in ("alpha", "beta"):
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\nstatus: backlog\n---\n", encoding="utf-8")

    class FakeCLI:
        status_reads = 0
        binding_reads = 0

        def read_plan_status(self):
            self.status_reads += 1
            return {
                "plans": [
                    {"id": item, "status": "backlog"} for item in ("alpha", "beta")
                ]
            }

        def read_address_bindings(self):
            self.binding_reads += 1
            return []

    cli = FakeCLI()
    app = Starlette(routes=create_queue_routes(cli, tmp_path))
    assert app_request(app, "GET", "/api/queue").status_code == 200
    calls = (cli.status_reads, cli.binding_reads)
    moved = app_request(
        app,
        "POST",
        "/api/queue/move",
        content=b'{"plan":"beta","direction":"up"}',
        headers={"content-type": "application/json"},
    )
    assert moved.status_code == 200
    assert moved.json() == {"category": "uncategorized", "order": ["beta", "alpha"]}
    assert (cli.status_reads, cli.binding_reads) == calls
    refreshed = app_request(app, "GET", "/api/queue")
    assert [row["id"] for row in refreshed.json()["categories"][3]["waiting"]] == [
        "beta",
        "alpha",
    ]


def test_failed_running_comment_delivery_returns_502(tmp_path):
    folder = tmp_path / "plans" / "alpha"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text("---\nstatus: backlog\n---\n", encoding="utf-8")

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "alpha", "status": "backlog"}]}

        def read_address_bindings(self):
            return [{"address": "alpha"}]

        def send(self, **kwargs):
            raise subprocess.CalledProcessError(1, "varde msg send")

    app = Starlette(routes=create_queue_routes(FakeCLI(), tmp_path))
    response = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=json.dumps({"target": "plan", "text": "Try again"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 502
    assert not (folder / "comments.jsonl").exists()


def test_uncategorized_and_unknown_category_and_terminal_plans(tmp_path):
    plans = tmp_path / "plans"
    records = {
        "fix-active": ("fixes", "active"),
        "unknown": (None, "backlog"),
        "finished": (None, "done"),
    }
    for plan_id, (category, status) in records.items():
        folder = plans / plan_id
        folder.mkdir(parents=True)
        category_line = f"category: {category}\n" if category else ""
        (folder / "plan.md").write_text(
            f"---\nstatus: {status}\n{category_line}---\n", encoding="utf-8"
        )

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {"id": plan_id, "status": status}
                    for plan_id, (_, status) in records.items()
                ]
            }

        def read_address_bindings(self):
            return []

    app = Starlette(routes=create_queue_routes(FakeCLI(), tmp_path))
    response = app_request(app, "GET", "/api/queue")
    assert response.status_code == 200
    payload = json.loads(response.text)
    assert payload["slots"]["used"] == 0
    fixes = next(
        category for category in payload["categories"] if category["id"] == "fixes"
    )
    assert fixes["used"] == 0
    assert all(
        row["id"] != "finished"
        for category in payload["categories"]
        for row in category["waiting"]
    )
    uncategorized = next(
        category
        for category in payload["categories"]
        if category["id"] == "uncategorized"
    )
    assert uncategorized["waiting"][0]["id"] == "unknown"
    assert uncategorized["used"] == 0


@pytest.fixture
def queue_activity_cases():
    return {
        "dashboard-ux": {
            "queue_status": "backlog",
            "activity_status": "backlog",
            "agent_status": "idle",
        },
        "running-worker": {
            "queue_status": "backlog",
            "worktree": "/work/worker-plan",
        },
        "concluded": {"queue_status": "backlog", "activity_status": "done"},
    }


def test_running_workers_or_orchestrators_and_concluded_are_not_waiting(
    tmp_path, queue_activity_cases
):
    plans = tmp_path / "plans"
    for plan_id in queue_activity_cases:
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(
            "---\nstatus: backlog\ncategory: new-feature\n---\n", encoding="utf-8"
        )

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {
                        "id": key,
                        "status": queue_activity_cases[key]["queue_status"],
                        **(
                            {"worktree": queue_activity_cases[key]["worktree"]}
                            if "worktree" in queue_activity_cases[key]
                            else {}
                        ),
                    }
                    for key in queue_activity_cases
                ]
            }

        def read_address_bindings(self):
            return [{"address": "dashboard-ux"}]

    async def activity():
        return {
            "plans": [
                {
                    "id": key,
                    "status": case["activity_status"],
                    **(
                        {"agent_status": case["agent_status"]}
                        if "agent_status" in case
                        else {}
                    ),
                }
                for key, case in queue_activity_cases.items()
                if "activity_status" in case
            ],
            "activity_agents": [
                {"id": "worker", "cwd": "/work/worker-plan/child", "status": "running"}
            ],
        }

    app = Starlette(
        routes=create_queue_routes(FakeCLI(), tmp_path, activity_reader=activity)
    )
    payload = app_request(app, "GET", "/api/queue").json()
    waiting_ids = {
        row["id"] for category in payload["categories"] for row in category["waiting"]
    }
    assert waiting_ids == set()
    assert "dashboard-ux" not in waiting_ids
    assert payload["slots"]["used"] == 1
    new_features = next(
        category
        for category in payload["categories"]
        if category["id"] == "new-feature"
    )
    assert new_features["used"] == 1


def test_real_shape_queue_counts_idle_dashboard_and_relay_once(tmp_path):
    plans_dir = tmp_path / "plans"
    plan_frontmatter = {
        "2026-10-20-dashboard-ux": "status: backlog\ncategory: new-feature\n",
        "relay-restart": "status: backlog\n",
        "uncategorized-active": "status: active\n",
        "dashboard-design": "status: backlog\ncategory: new-feature\n",
        "concluded-plan": "status: completed\ncategory: fixes\n",
    }
    for plan_id, fields in plan_frontmatter.items():
        folder = plans_dir / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(f"---\n{fields}---\n", encoding="utf-8")

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {"id": "2026-10-20-dashboard-ux", "status": "backlog"},
                    {"id": "relay-restart", "status": "backlog"},
                    {"id": "uncategorized-active", "status": "active"},
                    {"id": "missing-file", "status": "backlog"},
                ]
            }

        def read_address_bindings(self):
            return [{"address": "dashboard-ux"}, {"address": "relay-restart"}]

    async def activity():
        return {
            "plans": [
                {
                    "id": "2026-10-20-dashboard-ux",
                    "status": "backlog",
                    "agent_status": "idle",
                    "agent_id": "dashboard-agent",
                },
                {
                    "id": "relay-restart",
                    "status": "backlog",
                    "agent_status": "idle",
                    "agent_id": "relay-agent",
                },
                {
                    "id": "uncategorized-active",
                    "status": "active",
                    "activity": "stalled",
                    "agent_status": "idle",
                    "agent_id": "active-agent",
                },
            ],
            "activity_agents": [
                {
                    "id": "dashboard-agent",
                    "status": "idle",
                    "title": "Orchestrator: dashboard-ux (new-feature)",
                },
                {
                    "id": "relay-agent",
                    "status": "idle",
                    "title": "Orchestrator: relay-restart (fixes)",
                },
            ],
        }

    payload = app_request(
        Starlette(
            routes=create_queue_routes(FakeCLI(), tmp_path, activity_reader=activity)
        ),
        "GET",
        "/api/queue",
    ).json()
    categories = {category["id"]: category for category in payload["categories"]}
    assert payload["slots"] == {"used": 3, "limit": 4}
    assert categories["new-feature"]["used"] == 1
    assert categories["fixes"]["used"] == 1
    assert categories["uncategorized"]["used"] == 1
    waiting = {
        row["id"] for category in payload["categories"] for row in category["waiting"]
    }
    assert waiting == {"dashboard-design"}
    hidden = {row["id"]: row for row in payload["hidden"]}
    assert "missing-file" not in hidden
    assert hidden["concluded-plan"]["reason"] == "concluded"


@pytest.mark.parametrize(
    ("category", "expected_category"),
    [("new-feature", "new-feature"), (None, "uncategorized")],
)
def test_taskless_backlog_plan_is_enumerated_and_waiting(
    tmp_path, category, expected_category
):
    folder = tmp_path / "plans" / "stub-plan"
    folder.mkdir(parents=True)
    category_line = f"category: {category}\n" if category else ""
    (folder / "plan.md").write_text(
        f"---\ntitle: Stub plan\nstatus: backlog\n{category_line}---\n",
        encoding="utf-8",
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": []}

        def read_address_bindings(self):
            return []

    payload = app_request(
        Starlette(routes=create_queue_routes(FakeCLI(), tmp_path)),
        "GET",
        "/api/queue",
    ).json()
    category_rows = next(
        row for row in payload["categories"] if row["id"] == expected_category
    )
    assert category_rows["waiting"] == [
        {
            "id": "stub-plan",
            "title": "Stub plan",
            "label": "Stub plan",
            "purpose": "",
            "group_name": "",
            "status": "backlog",
            "open_comments": 0,
            "readiness": "draft",
            "task_count": 0,
        }
    ]


@pytest.mark.parametrize(
    ("frontmatter", "comments", "inline_tasks", "expected"),
    [
        ({"status": "backlog", "reviewed_commit": "abc"}, 0, "- Task one", "ready"),
        ({"status": "backlog"}, 0, "- Task one", "needs-review"),
        (
            {"status": "backlog", "reviewed_commit": "abc"},
            1,
            "- Task one",
            "needs-review",
        ),
        ({"status": "backlog"}, 0, "", "draft"),
        ({"status": "held"}, 0, "- Task one", "held"),
    ],
)
def test_readiness_labels_include_review_state_and_inline_tasks(
    tmp_path, frontmatter, comments, inline_tasks, expected
):
    plan_file = tmp_path / "plan.md"
    metadata = "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
    plan_file.write_text(
        f"---\n{metadata}\n---\n## Tasks\n\n{inline_tasks}\n",
        encoding="utf-8",
    )

    result = _readiness(plan_file, comments, frontmatter)

    assert result["readiness"] == expected
    assert result["task_count"] == int(bool(inline_tasks))


def test_taskless_cancelled_plan_is_hidden(tmp_path):
    folder = tmp_path / "plans" / "cancelled-plan"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\ntitle: Cancelled\nstatus: cancelled\n---\n", encoding="utf-8"
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "cancelled-plan", "status": "backlog"}]}

        def read_address_bindings(self):
            return []

    payload = app_request(
        Starlette(routes=create_queue_routes(FakeCLI(), tmp_path)),
        "GET",
        "/api/queue",
    ).json()
    assert payload["hidden"] == [
        {
            "id": "cancelled-plan",
            "title": "Cancelled",
            "label": "Cancelled",
            "group_name": "",
            "status": "cancelled",
            "reason": "concluded",
        }
    ]


def test_taskless_active_plan_is_not_waiting(tmp_path):
    folder = tmp_path / "plans" / "active-plan"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nstatus: in-progress\ncategory: fixes\n---\n", encoding="utf-8"
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": []}

        def read_address_bindings(self):
            return []

    payload = app_request(
        Starlette(routes=create_queue_routes(FakeCLI(), tmp_path)),
        "GET",
        "/api/queue",
    ).json()
    assert all(
        row["id"] != "active-plan"
        for category in payload["categories"]
        for row in category["waiting"]
    )


def test_shared_frontmatter_stringifier_keeps_strip_quote_semantics():
    assert parse_frontmatter('---\nlabel: "abc\n---\n') == {"label": "abc"}


def test_plan_metadata_enumerates_files_and_merges_status_rows(tmp_path):
    plan_root = tmp_path / "plans"
    for plan_id in ("taskless", "with-status"):
        folder = plan_root / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text(
            f"---\ntitle: {plan_id}\nstatus: backlog\n---\n", encoding="utf-8"
        )

    rows, files, fields, _ = _plan_metadata(
        tmp_path,
        [
            {
                "id": "with-status",
                "status": "active",
                "progress": 1,
                "purpose": "Keep the dashboard clear.",
            }
        ],
    )
    assert set(files) == {"taskless", "with-status"}
    assert {row["id"] for row in rows} == set(files)
    assert next(row for row in rows if row["id"] == "with-status") == {
        "id": "with-status",
        "title": "with-status",
        "label": "with-status",
        "purpose": "Keep the dashboard clear.",
        "group_name": "",
        "status": "active",
        "frontmatter_status": "backlog",
        "progress": 1,
    }
    assert fields["taskless"]["status"] == "backlog"


def test_plan_metadata_resolves_label_and_inherited_group_without_changing_title(
    tmp_path,
):
    parent = tmp_path / "plans" / "parent"
    child = parent / "child"
    child.mkdir(parents=True)
    (parent / "plan.md").write_text(
        "---\ntitle: Parent full title\nlabel: Parent card\ngroup: Quality\n---\n"
    )
    child_plan = child / "plan.md"
    child_plan.write_text("---\ntitle: Child full title\nlabel: Child card\n---\n")

    rows, _, _, _ = _plan_metadata(tmp_path, [])
    row = next(item for item in rows if item["id"] == "child")
    assert row["title"] == "Child full title"
    assert row["label"] == "Child card"
    assert row["group_name"] == "Quality"

    records = open_data(tmp_path, load_data_config()).plans.list().records
    child_record = next(record for record in records if record.id == "child")
    detail = _plan_detail_record(child_record, "child", records)
    assert detail["title"] == "Child full title"
    assert detail["label"] == "Child card"
    assert detail["group_name"] == "Quality"


@pytest.mark.parametrize(
    ("own", "parent", "expected"),
    [("  Local  ", "Parent", "Local"), ("  ", "Parent", "Parent"), (None, "", "")],
)
def test_resolve_group_mirrors_workflow_semantics(own, parent, expected):
    assert _resolve_group(own, parent) == expected


def test_blank_label_falls_back_to_title_in_rows_and_detail(tmp_path):
    folder = tmp_path / "plans" / "blank"
    folder.mkdir(parents=True)
    plan_file = folder / "plan.md"
    plan_file.write_text('---\ntitle: Full title\nlabel: ""\n---\n')

    rows, _, _, _ = _plan_metadata(tmp_path, [])
    row = next(item for item in rows if item["id"] == "blank")
    assert row["label"] == "Full title"
    records = open_data(tmp_path, load_data_config()).plans.list().records
    blank_record = next(record for record in records if record.id == "blank")
    assert _plan_detail_record(blank_record, "blank", records)["label"] == "Full title"


def test_group_resolves_through_grandparent_and_container_without_plan_file(
    tmp_path,
):
    root = tmp_path / "plans"
    grand = root / "grand"
    container = grand / "container"  # no plan.md here
    leaf = container / "leaf"
    own = grand / "own"
    leaf.mkdir(parents=True)
    own.mkdir()
    (grand / "plan.md").write_text("---\ntitle: G\ngroup: Quality\n---\n")
    (leaf / "plan.md").write_text("---\ntitle: Leaf\n---\n")
    (own / "plan.md").write_text("---\ntitle: Own\ngroup: Dashboard\n---\n")

    groups = {row["id"]: row["group_name"] for row in _plan_metadata(tmp_path, [])[0]}
    assert groups == {"grand": "Quality", "leaf": "Quality", "own": "Dashboard"}


def test_bound_idle_backlog_plan_is_exposed_as_hidden_active(tmp_path):
    folder = tmp_path / "plans" / "dashboard-design"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nstatus: backlog\ncategory: new-feature\n---\n", encoding="utf-8"
    )

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {
                        "id": "dashboard-design",
                        "title": "Dashboard design",
                        "status": "backlog",
                    }
                ]
            }

        def read_address_bindings(self):
            return [{"address": "dashboard-design"}]

    async def activity():
        return {
            "plans": [
                {
                    "id": "dashboard-design",
                    "status": "backlog",
                    "agent_status": "idle",
                }
            ],
            "activity_agents": [],
        }

    payload = app_request(
        Starlette(
            routes=create_queue_routes(FakeCLI(), tmp_path, activity_reader=activity)
        ),
        "GET",
        "/api/queue",
    ).json()
    assert payload["slots"]["used"] == 1
    category = next(
        item for item in payload["categories"] if item["id"] == "new-feature"
    )
    assert category["used"] == 1
    assert category["waiting"] == []
    assert {
        "id": "dashboard-design",
        "title": "Dashboard design",
        "label": "Dashboard design",
        "group_name": "",
        "status": "backlog",
        "reason": "active",
    } in payload["hidden"]


def test_idle_non_archived_orchestrator_is_active_unless_plan_is_concluded():
    row = {"id": "dashboard-ux", "status": "backlog"}
    idle = {"id": "dashboard-ux", "status": "backlog", "agent_status": "idle"}
    archived = {**idle, "agent_status": "archived"}

    assert _plan_activity_for_queue(row, {"dashboard-ux": idle}, []) == "idle"
    assert _plan_activity_for_queue(row, {"dashboard-ux": archived}, []) == "backlog"
    assert (
        _plan_activity_for_queue(
            {**row, "status": "completed"},
            {"dashboard-ux": {**idle, "status": "completed"}},
            [],
        )
        == "done"
    )
    assert (
        _plan_activity_for_queue(
            row,
            {"dashboard-ux": {**idle, "activity": "waiting", "open_questions": []}},
            [],
        )
        == "waiting"
    )


@pytest.mark.parametrize(
    "activity", ["running", "waiting", "idle", "stalled", "blocked"]
)
def test_slots_count_live_orchestrators_in_active_activity_states(tmp_path, activity):
    folder = tmp_path / "plans" / "dashboard-ux"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nstatus: active\ncategory: new-feature\n---\n", encoding="utf-8"
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "dashboard-ux", "status": "active"}]}

        def read_address_bindings(self):
            return []

    async def snapshot():
        return {
            "plans": [
                {
                    "id": "dashboard-ux",
                    "activity": activity,
                    "agent_status": "idle",
                }
            ]
        }

    payload = app_request(
        Starlette(
            routes=create_queue_routes(FakeCLI(), tmp_path, activity_reader=snapshot)
        ),
        "GET",
        "/api/queue",
    ).json()
    assert payload["slots"] == {"used": 1, "limit": 4}


@pytest.mark.parametrize(
    "agent_status", ["", "archived", "closed", "missing", "unknown"]
)
def test_slots_ignore_non_live_orchestrator_statuses(tmp_path, agent_status):
    folder = tmp_path / "plans" / "dashboard-ux"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\nstatus: active\ncategory: new-feature\n---\n", encoding="utf-8"
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "dashboard-ux", "status": "active"}]}

        def read_address_bindings(self):
            return []

    async def snapshot():
        return {
            "plans": [
                {
                    "id": "dashboard-ux",
                    "activity": "waiting",
                    "agent_status": agent_status,
                }
            ]
        }

    payload = app_request(
        Starlette(
            routes=create_queue_routes(FakeCLI(), tmp_path, activity_reader=snapshot)
        ),
        "GET",
        "/api/queue",
    ).json()
    assert payload["slots"]["used"] == 0


def test_queue_without_order_has_no_next_up_and_is_alphabetical(tmp_path):
    plans = tmp_path / "plans"
    for plan_id in ("zeta", "alpha"):
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\nstatus: backlog\n---\n", encoding="utf-8")

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {"id": "zeta", "status": "backlog"},
                    {"id": "alpha", "status": "backlog"},
                ]
            }

        def read_address_bindings(self):
            return []

    payload = app_request(
        Starlette(routes=create_queue_routes(FakeCLI(), tmp_path)), "GET", "/api/queue"
    ).json()
    category = next(
        row for row in payload["categories"] if row["id"] == "uncategorized"
    )
    assert [row["id"] for row in category["waiting"]] == ["alpha", "zeta"]
    assert category["next_up"] is None
    assert category["priority_set"] is False


def test_queue_snapshot_marks_store_failure_as_degraded(tmp_path):
    class FailingCLI:
        def read_plan_status(self):
            raise OSError("queue store unavailable")

        def read_address_bindings(self):
            return []

    response = app_request(
        Starlette(routes=create_queue_routes(FailingCLI(), tmp_path)),
        "GET",
        "/api/queue",
    )

    assert response.status_code == 200
    assert response.json()["degraded"] is True


def test_selected_queue_window_is_exposed_as_next_up(tmp_path):
    folder = tmp_path / "plans" / "deployment-window"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\ntitle: HELD deployment\nstatus: backlog\n---\n", encoding="utf-8"
    )
    (tmp_path / "queue-order.json").write_text(
        '{"version":1,"order":{"uncategorized":["deployment-window"]}}',
        encoding="utf-8",
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "deployment-window", "status": "backlog"}]}

        def read_address_bindings(self):
            return []

    payload = app_request(
        Starlette(routes=create_queue_routes(FakeCLI(), tmp_path)), "GET", "/api/queue"
    ).json()
    category = next(
        row for row in payload["categories"] if row["id"] == "uncategorized"
    )
    assert category["next_up"] == "deployment-window"


def test_active_unbound_comment_is_stored(tmp_path):
    folder = tmp_path / "plans" / "alpha"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "alpha", "status": "active"}]}

        def read_address_bindings(self):
            return []

    app = Starlette(routes=create_queue_routes(FakeCLI(), tmp_path))
    response = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=json.dumps({"target": "plan", "text": "Keep this"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 201
    payload = json.loads(response.text)
    assert payload["comment"]["kind"] == "stored"
    assert payload["comment"]["ts"].endswith("Z")


def test_queue_post_rejects_invalid_direction_and_boundary(tmp_path):
    plans = tmp_path / "plans"
    for plan_id in ("alpha", "beta"):
        folder = plans / plan_id
        folder.mkdir(parents=True)
        (folder / "plan.md").write_text("---\nstatus: backlog\n---\n", encoding="utf-8")

    class FakeCLI:
        def read_plan_status(self):
            return {
                "plans": [
                    {"id": item, "status": "backlog"} for item in ("alpha", "beta")
                ]
            }

        def read_address_bindings(self):
            return []

    app = Starlette(routes=create_queue_routes(FakeCLI(), tmp_path))
    headers = {"content-type": "application/json"}
    invalid = app_request(
        app,
        "POST",
        "/api/queue/move",
        content=b'{"plan":"alpha","direction":"sideways"}',
        headers=headers,
    )
    boundary = app_request(
        app,
        "POST",
        "/api/queue/move",
        content=b'{"plan":"alpha","direction":"up"}',
        headers=headers,
    )
    assert invalid.status_code == 400
    assert boundary.status_code == 400


def test_comment_post_validates_plan_target_text_and_detail(tmp_path):
    folder = tmp_path / "plans" / "alpha"
    (folder / "tasks").mkdir(parents=True)
    (folder / "plan.md").write_text(
        "---\ntitle: Alpha\nstatus: backlog\n---\nBody", encoding="utf-8"
    )
    (folder / "tasks" / "T1.md").write_text(
        (
            "---\ntype: task\nid: T1\ntitle: Task\nstatus: todo\n---\n"
            "## Acceptance criteria\n- Keep it"
        ),
        encoding="utf-8",
    )

    class FakeCLI:
        def read_plan_status(self):
            return {"plans": [{"id": "alpha", "status": "backlog"}]}

        def read_address_bindings(self):
            return []

    app = Starlette(routes=create_queue_routes(FakeCLI(), tmp_path))
    headers = {"content-type": "application/json"}
    unknown_plan = app_request(
        app,
        "POST",
        "/api/plans/missing/comments",
        content=b'{"target":"plan","text":"x"}',
        headers=headers,
    )
    unknown_task = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=b'{"target":"missing","text":"x"}',
        headers=headers,
    )
    empty_text = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=b'{"target":"plan","text":"  "}',
        headers=headers,
    )
    traversal = app_request(
        app,
        "POST",
        "/api/plans/%2e%2e/comments",
        content=b'{"target":"plan","text":"x"}',
        headers=headers,
    )
    detail = app_request(app, "GET", "/api/plans/alpha")
    assert unknown_plan.status_code == traversal.status_code == 404
    assert unknown_task.status_code == 404
    assert empty_text.status_code == 400
    assert detail.json()["tasks"][0]["acceptance_criteria"] == ["Keep it"]
