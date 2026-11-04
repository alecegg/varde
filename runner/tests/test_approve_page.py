from __future__ import annotations

import json

from starlette.applications import Starlette
from test_web import app_request
from varde_runner.approvals import MergeApprovals
from varde_runner.web.approvals_route import create_approval_routes
from varde_runner.web.approve_page import create_approve_page_routes


def test_approve_page_lists_unapproved_and_escapes_text(tmp_path):
    plans = {
        "plans": [
            {
                "id": "later",
                "title": "<script>x</script>",
                "status": "active",
                "awaiting_user": None,
                "merge_state": "absent",
            },
            {
                "id": "ready",
                "title": "Ready & safe",
                "status": "active",
                "awaiting_user": "Merge?",
                "merge_state": "absent",
            },
            {
                "id": "done",
                "title": "Done",
                "status": "done",
                "awaiting_user": None,
                "merge_state": "absent",
            },
        ]
    }
    app = Starlette(routes=create_approve_page_routes(lambda: plans))
    response = app_request(app, "GET", "/approve")
    assert response.status_code == 200
    assert response.text.index("ready") < response.text.index("later")
    assert "&lt;script&gt;" in response.text
    assert "<script>x</script>" not in response.text
    assert "done" not in response.text


def test_approve_page_posts_through_approval_route(tmp_path):
    plans = {"plans": [{"id": "p1", "status": "active", "merge_state": "absent"}]}
    app = Starlette(
        routes=[
            *create_approve_page_routes(lambda: plans),
            *create_approval_routes(MergeApprovals(tmp_path)),
        ]
    )
    response = app_request(app, "GET", "/approve")
    assert "/api/plans/" in response.text
    assert "merge-approval" in response.text
    assert "method:'POST'" in response.text
    posted = app_request(
        app,
        "POST",
        "/api/plans/p1/merge-approval",
        content=json.dumps({"note": "Looks good"}).encode(),
        headers={"content-type": "application/json"},
    )
    assert posted.status_code == 201
    assert posted.json()["approval"]["note"] == "Looks good"
