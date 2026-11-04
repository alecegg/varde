from __future__ import annotations

import json

from starlette.applications import Starlette
from test_web import app_request
from varde_runner.web.queue import create_queue_routes


class _CLI:
    def __init__(self, bindings=()):
        self.bindings = list(bindings)
        self.sent = []

    def read_address_bindings(self):
        return self.bindings

    def send(self, **message):
        self.sent.append(message)
        return {}


def _app(tmp_path, cli):
    folder = tmp_path / "plans" / "alpha"
    folder.mkdir(parents=True)
    (folder / "plan.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
    return Starlette(routes=create_queue_routes(cli, tmp_path))


def test_plan_comments_can_be_resolved_as_append_only_event(tmp_path):
    app = _app(tmp_path, _CLI())
    headers = {"content-type": "application/json"}
    created = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=b'{"target":"plan","text":"Please clarify"}',
        headers=headers,
    )
    comment_id = created.json()["comment"]["id"]

    resolved = app_request(
        app,
        "POST",
        f"/api/plans/alpha/comments/{comment_id}",
        content=b'{"state":"resolved"}',
        headers=headers,
    )

    assert resolved.status_code == 200
    assert resolved.json()["comment"]["state"] == "resolved"
    reopened = app_request(
        app,
        "POST",
        f"/api/plans/alpha/comments/{comment_id}",
        content=b'{"state":"open"}',
        headers=headers,
    )
    assert reopened.json()["comment"]["state"] == "open"
    events = [
        json.loads(line)
        for line in (tmp_path / "plans" / "alpha" / "comments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert events[-2]["id"] == comment_id
    assert events[-2]["state"] == "resolved"
    assert events[-1]["id"] == comment_id
    assert events[-1]["state"] == "open"


def test_bound_plan_comment_response_says_delivered(tmp_path):
    cli = _CLI([{"address": "alpha", "plan_id": "alpha"}])
    app = _app(tmp_path, cli)

    response = app_request(
        app,
        "POST",
        "/api/plans/alpha/comments",
        content=b'{"target":"plan","text":"Please clarify"}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 201
    assert response.json()["comment"]["kind"] == "delivered"
    stored = json.loads(
        (tmp_path / "plans" / "alpha" / "comments.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert stored["kind"] == "sent"
    detail = app_request(app, "GET", "/api/plans/alpha").json()
    assert detail["comments"][0]["kind"] == "delivered"
