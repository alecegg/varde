from __future__ import annotations

import asyncio
import json

from test_web import app_request, setup_app
from varde_runner.web.app import _projected_mailbox_items


def configure_merge_ready(app, cli, *, notes=None, blocked=False):
    cli.messages = [
        {
            "id": "merge-request",
            "from": "orchestrator",
            "to": "main",
            "kind": "merge-ready",
            "ts": "2026-10-23T10:00:00Z",
            "text": "Merge the completed plan?",
            "notes": notes,
        }
    ]
    plan = {
        "id": "plan-1",
        "status": "active",
        "assigned_to": "orchestrator",
        "title": "Plan one",
        "awaiting_user": "Merge the completed plan?",
        "tasks": [{"id": "task-1", "status": "blocked"}] if blocked else [],
    }
    cli.plan = {"plans": [plan]}
    cli.extra_bindings = [
        {"address": "orchestrator", "plan_id": "plan-1"},
    ]


def mailbox_items(app):
    return asyncio.run(_projected_mailbox_items(app.state.dashboard))


def needs_you(app):
    return asyncio.run(app.state.dashboard.needs_you_threads())


def test_merge_ready_card_without_notes_projects_and_replies(tmp_path, monkeypatch):
    app, cli, store = setup_app(tmp_path, monkeypatch)
    configure_merge_ready(app, cli)

    items = mailbox_items(app)
    card = next(item for item in items if item["msg_id"] == "merge-request")
    assert card["type"] == "approval"
    assert card["asked"] == "Merge the completed plan?"
    assert card["why"]
    assert [option["label"] for option in card["options"]] == [
        "Approve",
        "Hold",
        "Ask more",
    ]
    decision = store.get_decision("merge-request")
    assert decision is not None and decision["kind"] == "approval"
    assert [thread["plan_id"] for thread in needs_you(app)] == ["plan-1"]

    response = app_request(
        app,
        "POST",
        "/api/mailbox/merge-request/answer",
        content=json.dumps(
            {"option": "approve", "text": "", "idempotency_key": "approve-1"}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert cli.sent[-1]["recipient"] == "orchestrator"
    assert cli.sent[-1]["kind"] == "info"
    assert cli.sent[-1]["text"] == "re merge-ready merge-request: APPROVED"

    cli.messages.append(
        {
            "id": "main-reply",
            "from": "main",
            "to": "orchestrator",
            "kind": "info",
            "ts": "2026-10-23T10:01:00Z",
        }
    )
    app.state.dashboard.projector.project()
    assert asyncio.run(app.state.dashboard.open_mailbox_items(mailbox_items(app))) == []
    store.close()


def test_merge_ready_card_with_notes_and_blocked_task_is_visible(tmp_path, monkeypatch):
    notes = tmp_path / "merge.json"
    notes.write_text(
        json.dumps(
            {
                "asked": "May this plan merge?",
                "why": "All task work is ready.",
                "plan_id": "plan-1",
            }
        ),
        encoding="utf-8",
    )
    app, cli, store = setup_app(tmp_path, monkeypatch)
    configure_merge_ready(app, cli, notes=str(notes), blocked=True)

    card = next(
        item for item in mailbox_items(app) if item["msg_id"] == "merge-request"
    )
    assert card["type"] == "approval"
    assert card["asked"] == "May this plan merge?"
    assert [thread["plan_id"] for thread in needs_you(app)] == ["plan-1"]

    cli.messages.append(
        {
            "id": "watch-merge-request",
            "from": "varde-watch",
            "to": "main",
            "kind": "merge-ready",
            "ts": "2026-10-23T10:02:00Z",
            "text": "Watch duplicate",
        }
    )
    assert all(item["msg_id"] != "watch-merge-request" for item in mailbox_items(app))
    store.close()
