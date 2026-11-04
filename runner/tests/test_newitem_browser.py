from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from stop_server import stop_server
from varde_runner import GRACEFUL_SHUTDOWN_TIMEOUT
from varde_runner.config import default_toml
from varde_runner.delivery import DeliveryLoop
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.registry import SessionBinding, SessionRegistry
from varde_runner.supervisor import SendOutcome
from varde_runner.web import create_app
from varde_runner.workitems import WorkItemStore

pytestmark = pytest.mark.slow


def contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [
            int(value) / 255
            for value in color.removeprefix("rgb(").removesuffix(")").split(",")
        ]
        linear = [
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
            for value in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    light, dark = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


@pytest.fixture
def newitem_browser(tmp_path, browser_session, shared_browser_page, monkeypatch):
    calls = []

    class FakeCLI:
        paseo_models: Callable[[], Any] | None = None

        def __init__(self):
            self.messages = []
            self.extra_bindings = []

        def read_messages(self):
            return list(self.messages)

        def read_plan(self):
            return {
                "plans": [
                    {
                        "id": "dashboard-plan",
                        "status": "active",
                        "assigned_to": "builder",
                        "title": "Dashboard plan",
                        "tasks": [],
                    }
                ]
            }

        def read_address_bindings(self):
            return [
                {"address": "builder", "plan_id": "dashboard-plan"},
                *self.extra_bindings,
            ]

        def send(self, *, sender, recipient, kind, text, notes):
            message = {
                "id": f"message-{len(self.messages) + 1}",
                "from": sender,
                "to": recipient,
                "kind": kind,
                "text": text,
                "notes": str(Path(notes).resolve()),
            }
            self.messages.append(message)
            return {"id": message["id"]}

        def acknowledge(self, message_id, *, address):
            calls.append(("ack", message_id, address))

    cli = FakeCLI()
    cli.paseo_models = lambda: {
        "codex": {
            "provider": "codex",
            "models": [
                {"provider": "codex", "id": "gpt-6-luna", "label": "Luna"},
                {
                    "provider": "codex",
                    "id": "gpt-6-astra-test[1m]",
                    "label": "Astra Test 1M",
                },
            ],
        },
        "pi": {
            "provider": "pi",
            "models": [
                {
                    "provider": "pi",
                    "id": "deepseek/deepseek-v4-flash",
                    "label": "DeepSeek",
                }
            ],
        },
        "claude": {
            "provider": "claude",
            "models": [
                {
                    "provider": "claude",
                    "id": "claude-sonnet-5-5",
                    "label": "Sonnet",
                }
            ],
        },
    }

    async def start_planner(item_id, notes_path, project):
        calls.append((item_id, notes_path.read_bytes(), project))
        return "planner-session"

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "runner.toml").write_text(default_toml())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))

    class FakePlugin:
        async def list_workspaces(self):
            return [
                {"id": name, "title": name, "cwd": f"/work/{name}"}
                for name in ("workspace", "dashboard-test", "agent-memory")
            ]

    monkeypatch.setattr(PaseoPlugin, "from_environment", FakePlugin)
    app = create_app(data_dir=tmp_path, cli=cli)
    app.state.work_item_start = start_planner
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
        lifespan="off",
        timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_TIMEOUT,
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    page = shared_browser_page
    origin = f"http://127.0.0.1:{port}"
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    try:
        yield page, browser_session, origin, calls, cli, app, tmp_path
    finally:
        page.goto("about:blank")
        stop_server(server, thread)


def test_plans_page_is_independent_of_large_mailbox(newitem_browser):
    page, _, origin, *_ = newitem_browser
    questions = [
        {
            "msg_id": f"mail-{index}",
            "asked": f"Realistic mailbox question {index:02d}",
            "sender": "builder",
            "plan_id": "dashboard-plan",
        }
        for index in range(78)
    ]
    page.route(
        "**/api/mailbox",
        lambda route: route.fulfill(json={"open": questions, "permissions": []}),
    )
    page.route(
        "**/api/orchestrators",
        lambda route: route.fulfill(
            json={"plans": [], "past": [], "infrastructure": [], "agents": []}
        ),
    )
    page.route(
        "**/api/queue",
        lambda route: route.fulfill(
            json={"categories": [], "slots": {"used": 0, "limit": 4}, "hidden": []}
        ),
    )
    page.route(
        "**/api/plans",
        lambda route: route.fulfill(
            json=[
                {
                    "id": "plan-first",
                    "title": "Plan-first fixture",
                    "label": "Plan-first fixture",
                    "status": "queued",
                    "queue_position": 1,
                    "open_comments": 0,
                    "updated": "2026-10-28T00:00:00Z",
                }
            ]
        ),
    )
    page.route(
        "**/events",
        lambda route: route.fulfill(content_type="text/event-stream", body=""),
    )
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    page.get_by_role("link", name="Plan-first fixture").wait_for()
    assert page.get_by_text("Realistic mailbox question", exact=False).count() == 0
    assert page.get_by_role("button", name="Plan this").count() == 0
    for width in (390, 1440):
        page.set_viewport_size({"width": width, "height": 844 if width == 390 else 900})
        assert page.locator("body").evaluate("el => el.scrollWidth") <= width
    for path in ("**/api/mailbox", "**/api/orchestrators", "**/api/queue", "**/events"):
        page.unroute(path)


def test_plan_list_does_not_mix_mailbox_or_work_item_events(newitem_browser):
    page, _, origin, *_ = newitem_browser
    mailbox = {
        "open": [
            {
                "msg_id": "valid-question",
                "sender": "builder",
                "kind": "needs-user",
                "asked": "Keep me",
            },
            {
                "msg_id": "launch-1",
                "sender": "workitem-launch",
                "kind": "needs-user",
                "asked": "Launch request",
            },
            {
                "msg_id": "plan-ready-1",
                "sender": "workitem-planner",
                "kind": "needs-user",
                "asked": "Plan ready",
            },
            {
                "msg_id": "perm:grant",
                "sender": "builder",
                "kind": "needs-user",
                "asked": "Permission marker",
            },
        ],
        "permissions": [
            {
                "msg_id": "permission-1",
                "sender": "builder",
                "kind": "permission",
                "asked": "Permission",
            }
        ],
    }
    page.route("**/api/mailbox", lambda route: route.fulfill(json=mailbox))
    page.route(
        "**/api/plans",
        lambda route: route.fulfill(
            json=[
                {
                    "id": "only-plan",
                    "title": "Only plan",
                    "label": "Only plan",
                    "status": "in_progress",
                    "queue_position": None,
                    "open_comments": 0,
                    "updated": "2026-10-28T00:00:00Z",
                }
            ]
        ),
    )
    event_payload = json.dumps(
        {"topics": ["mailbox", "work_items"], "needs_you_count": 0}
    )
    page.route(
        "**/events",
        lambda route: route.fulfill(
            content_type="text/event-stream",
            body=f"event: update\ndata: {event_payload}\n\n",
        ),
    )
    try:
        page.goto(f"{origin}/plans")
        page.get_by_role("link", name="Only plan").wait_for()
        assert page.get_by_text("Keep me").count() == 0
        assert page.get_by_text("Launch request").count() == 0
        assert page.get_by_text("Plan ready").count() == 0
        assert page.get_by_text("Permission marker").count() == 0
        assert page.get_by_role("button", name="Plan this").count() == 0
    finally:
        page.unroute("**/api/mailbox")
        page.unroute("**/events")


def test_ready_and_queued_work_item_json_includes_current_bounded_plan_text(
    newitem_browser,
):
    page, _, origin, _, _, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("plan-text", "request", "workspace")
    store.start_planning(item.id, "planner-session")
    plan_path = data_dir / "draft-plan.md"
    plan_path.write_text("# Draft plan\nOriginal", encoding="utf-8")
    store.plan_ready(item.id, plan_path, "plan-ready")

    detail = page.request.get(f"{origin}/api/work-items/{item.id}").json()
    listed = page.request.get(f"{origin}/api/work-items").json()["work_items"][0]
    assert detail["plan_text"] == listed["plan_text"] == "# Draft plan\nOriginal"

    plan_path.write_text("Updated plan", encoding="utf-8")
    assert (
        page.request.get(f"{origin}/api/work-items/{item.id}").json()["plan_text"]
        == "Updated plan"
    )

    plan_path.write_text("x" * 20_001, encoding="utf-8")
    bounded = page.request.get(f"{origin}/api/work-items/{item.id}").json()["plan_text"]
    assert bounded == "x" * 20_000 + "\n\n[Plan truncated at 20,000 characters.]"

    store.decide(item.id, True)
    assert (
        page.request.get(f"{origin}/api/work-items/{item.id}").json()["plan_text"]
        == bounded
    )


def test_unreadable_work_item_plan_text_stays_out_of_plan_list(
    newitem_browser,
):
    page, _, origin, _, _, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    missing = store.create("missing-plan", "request", "workspace")
    store.start_planning(missing.id, "planner-session")
    store.plan_ready(missing.id, data_dir / "missing.md", "missing-plan-ready")
    assert (
        page.request.get(f"{origin}/api/work-items/{missing.id}").json()["plan_text"]
        == ""
    )

    visible = store.create("visible-plan", "request", "workspace")
    store.start_planning(visible.id, "planner-session")
    plan_path = data_dir / "visible-plan.md"
    plan_path.write_text("# Plan visible before approval", encoding="utf-8")
    store.plan_ready(visible.id, plan_path, "visible-plan-ready")
    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    assert page.locator(f"#work-item-{visible.id}").count() == 0
    assert page.get_by_text("# Plan visible before approval").count() == 0
    for width in (390, 1440):
        page.set_viewport_size({"width": width, "height": 844 if width == 390 else 900})
        assert page.locator("body").evaluate("el => el.scrollWidth") <= width


def test_plan_page_does_not_embed_work_item_history_or_decisions(newitem_browser):
    page, _, origin, _, _, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("ready-plan", "request", "workspace")
    store.start_planning(item.id, "planner-session")
    path = data_dir / "ready.md"
    path.write_text("# Ready draft", encoding="utf-8")
    store.plan_ready(item.id, path, "plan-ready")

    page.goto(f"{origin}/plans")
    page.get_by_role("heading", name="Plans", level=1).wait_for()
    assert page.locator(f"#work-item-{item.id}").count() == 0
    assert page.get_by_role("button", name="Approve plan").count() == 0
    assert page.get_by_role("button", name="Reject").count() == 0
    assert "Ready draft" not in page.locator("body").inner_text()
    assert page.get_by_role("link", name="ready-plan").count() == 0


def test_submit_creates_one_work_item_and_planner_session(newitem_browser):
    page, _, origin, calls, *_ = newitem_browser
    text = ("first line 🧭\r\n" * 2200)[:20_000]
    payload = json.dumps(
        {"text": text, "project": "workspace", "idempotency_key": "http-submit-once"}
    )
    first = page.request.post(
        f"{origin}/api/work-items",
        data=payload,
        headers={"content-type": "application/json"},
    )
    second = page.request.post(
        f"{origin}/api/work-items",
        data=payload,
        headers={"content-type": "application/json"},
    )
    assert first.status == second.status == 200
    assert len(calls) == 1
    assert calls[0][1] == text.encode("utf-8")
    assert len(page.request.get(f"{origin}/api/work-items").json()["work_items"]) == 1


def test_answer_http_route_uses_notes_and_idle_delivery_once(newitem_browser):
    page, _, origin, _, cli, app, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("answer-item", "request", "workspace")
    store.start_planning(item.id, "planner-session")
    address = f"workitem-{item.id[:40]}"
    context = {
        "asked": "Which approach?",
        "why": "Blocks the plan",
        "options": [{"label": "A", "consequence": "Use A"}],
        "recommendation": "A",
        "sources": ["task-1"],
    }
    question_notes = store.item_notes_dir(item.id) / "question.json"
    question_notes.write_text(json.dumps(context), encoding="utf-8")
    store.question(item.id, "question-1", context)
    cli.messages.append(
        {
            "id": "question-1",
            "from": address,
            "to": "main",
            "kind": "needs-user",
            "text": "Which approach?",
            "notes": str(question_notes),
        }
    )
    store.close()
    page.request.get(f"{origin}/api/work-items")
    projected = app.state.decisions.get_decision("question-1")
    assert {
        key: projected["context"][key]
        for key in ("asked", "why", "options", "recommendation", "sources")
    } == context
    assert projected["title"] == context["asked"]
    with sqlite3.connect(data_dir / "inbox.sqlite3") as inbox_db:
        row = inbox_db.execute(
            "SELECT payload FROM inbox_projection WHERE msg_id=?", ("question-1",)
        ).fetchone()
    mailbox_item = json.loads(row[0])
    assert mailbox_item["asked"] == context["asked"]
    assert mailbox_item["why"] == context["why"]
    assert mailbox_item["options"] == context["options"]
    assert mailbox_item["recommendation"] == context["recommendation"]
    assert mailbox_item["sources"] == context["sources"]

    text = "answer 🧭\r\n" * 1800
    payload = json.dumps({"text": text, "idempotency_key": "answer-once"})
    response = page.request.post(
        f"{origin}/api/work-items/{item.id}/questions/question-1/answer",
        data=payload,
        headers={"content-type": "application/json"},
    )
    assert response.status == 200, response.text()
    assert response.json()["status"] == "delivered"
    answer_messages = [message for message in cli.messages if message["to"] == address]
    assert len(answer_messages) == 1
    assert Path(answer_messages[0]["notes"]).read_bytes() == text.encode("utf-8")

    class FakeAdapter:
        status = "running"

        def __init__(self):
            self.sent = []

        async def is_idle(self, session_id, harness=None):
            return self.status == "idle"

        async def send(self, session_id, prompt, harness=None):
            self.sent.append((session_id, prompt))
            return SendOutcome.SENT

    adapter = FakeAdapter()
    registry = SessionRegistry(data_dir / "answer-registry.json")
    registry.register(
        SessionBinding(
            address, "codex-app-server", "fake", "remote-planner", "planner", item.id
        )
    )
    loop = DeliveryLoop(
        data_dir / "answer-delivery.jsonl",
        registry,
        adapter,
        cli.read_messages,
    )

    def run_delivery() -> int:
        return asyncio.run(loop.deliver_once())

    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_delivery).result() == 0
    assert adapter.sent == []
    adapter.status = "idle"
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_delivery).result() == 1
        assert executor.submit(run_delivery).result() == 0
    assert len(adapter.sent) == 1
    repeated = page.request.post(
        f"{origin}/api/work-items/{item.id}/questions/question-1/answer",
        data=payload,
        headers={"content-type": "application/json"},
    )
    assert repeated.status == 200
    assert len([message for message in cli.messages if message["to"] == address]) == 1
    with ThreadPoolExecutor(max_workers=1) as executor:
        assert executor.submit(run_delivery).result() == 0


def test_plan_ready_requires_notes_in_own_directory(newitem_browser, tmp_path):
    page, _, origin, _, cli, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("plan-ready-item", "request", "workspace")
    store.start_planning(item.id, "planner")
    item_dir = store.item_notes_dir(item.id)
    plan_path = tmp_path / "plan.md"
    plan_path.write_text("plan", encoding="utf-8")
    payload = {
        "work_item_event": "plan_ready",
        "plan_path": str(plan_path),
        "asked": "Approve?",
        "why": "Plan is ready",
        "options": [{"label": "Approve", "consequence": "Queue"}],
        "recommendation": "Approve",
        "sources": [],
    }
    outside_notes = tmp_path / "outside.json"
    outside_notes.write_text(json.dumps(payload), encoding="utf-8")
    store.close()
    rejected = page.request.post(
        f"{origin}/api/work-items/{item.id}/plan-ready",
        data=json.dumps({"notes_path": str(outside_notes)}),
        headers={"content-type": "application/json"},
    )
    assert rejected.status in {400, 403}
    assert cli.messages == []

    allowed_notes = item_dir / "plan-ready.json"
    allowed_notes.write_text(json.dumps(payload), encoding="utf-8")
    accepted = page.request.post(
        f"{origin}/api/work-items/{item.id}/plan-ready",
        data=json.dumps({"notes_path": str(allowed_notes)}),
        headers={"content-type": "application/json"},
    )
    assert accepted.status == 200
    assert accepted.json()["state"] == "ready"
    assert cli.messages[-1]["kind"] == "needs-user"
    assert (
        json.loads(Path(cli.messages[-1]["notes"]).read_text())["work_item_event"]
        == "plan_ready"
    )


def test_approve_and_reject_api_actions_work(newitem_browser):
    page, _, origin, _, _, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    ids = []
    for key in ("approve-browser", "reject-browser"):
        item = store.create(key, "request", "workspace")
        store.start_planning(item.id, "planner")
        store.plan_ready(item.id, data_dir / "plan.md", f"ready-{key}")
        ids.append(item.id)
    store.close()
    assert (
        page.request.post(
            f"{origin}/api/work-items/{ids[0]}/decision", data={"approved": True}
        ).json()["state"]
        == "queued"
    )
    assert (
        page.request.post(
            f"{origin}/api/work-items/{ids[1]}/decision", data={"approved": False}
        ).json()["state"]
        == "rejected"
    )


def test_approval_publishes_one_launch_request_with_plan_context(newitem_browser):
    page, _, origin, _, cli, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("launch-request", "implement feature", "workspace")
    store.start_planning(item.id, "planner-session")
    plan_path = data_dir / "draft-plan.md"
    plan_path.write_text("Draft plan", encoding="utf-8")
    store.plan_ready(item.id, plan_path, "plan-ready")

    draft = page.request.get(f"{origin}/api/work-items/{item.id}").json()
    assert draft["state"] == "ready"
    assert draft["plan_path"] == str(plan_path)

    def approve():
        request = urllib.request.Request(  # noqa: S310 - Request URL comes from the local HTTP test server.
            f"{origin}/api/work-items/{item.id}/decision",
            data=b'{"approved":true}',
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 - Request targets the local HTTP test server.
            return response.status, json.loads(response.read())

    with ThreadPoolExecutor(max_workers=2) as executor:
        first, repeated = [
            future.result()
            for future in (executor.submit(approve), executor.submit(approve))
        ]

    assert first[0] == repeated[0] == 200
    assert first[1]["state"] == repeated[1]["state"] == "queued"
    request_messages = [
        message
        for message in cli.messages
        if message["text"] == "Orchestrator launch requested."
    ]
    assert len(request_messages) == 1
    message = request_messages[0]
    assert message["from"] == f"workitem-{item.id[:40]}"
    assert message["to"] == "main"
    assert message["kind"] == "needs-user"
    notes = json.loads(Path(message["notes"]).read_text(encoding="utf-8"))
    assert notes == {
        "work_item_event": "launch_request",
        "item_id": item.id,
        "plan_path": str(plan_path),
    }
    deadline = time.monotonic() + 2
    detail = page.request.get(f"{origin}/api/work-items/{item.id}").json()
    while detail["launch_request_id"] == "sending" and time.monotonic() < deadline:
        time.sleep(0.01)
        detail = page.request.get(f"{origin}/api/work-items/{item.id}").json()
    assert detail["launch_request_id"] == message["id"]
    assert detail["state"] == "queued"


def test_failed_launch_request_publish_can_be_retried(newitem_browser):
    page, _, origin, _, cli, _, data_dir = newitem_browser
    store = WorkItemStore(data_dir)
    item = store.create("launch-request-retry", "implement feature", "workspace")
    store.start_planning(item.id, "planner-session")
    plan_path = data_dir / "draft-plan.md"
    plan_path.write_text("Draft plan", encoding="utf-8")
    store.plan_ready(item.id, plan_path, "plan-ready")
    original_send = cli.send
    calls = 0

    def send(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise subprocess.CalledProcessError(1, "varde msg send")
        return original_send(**kwargs)

    cli.send = send
    url = f"{origin}/api/work-items/{item.id}/decision"
    failed = page.request.post(url, data={"approved": True})
    assert failed.status == 503
    assert store.get(item.id).launch_request_id is None

    retried = page.request.post(url, data={"approved": True})
    assert retried.status == 200
    assert retried.json()["launch_request_id"] == "message-1"
    assert calls == 2
    assert store.get(item.id).launch_request_id == "message-1"
