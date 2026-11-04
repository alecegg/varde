from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from starlette.applications import Starlette
from test_web import app_request
from varde_data.queue import open_queue
from varde_data.queue_line_sync import import_line_queue
from varde_data.queue_mode_lock import barrier
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_runner.web.queue_tasks_route import create_task_queue_routes


class Store:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.execute(
            "CREATE TABLE events (seq INTEGER PRIMARY KEY, session_id TEXT, "
            "kind TEXT, payload TEXT)"
        )
        self.connection.execute(
            "CREATE INDEX events_session_seq ON events(session_id, seq)"
        )
        self.connection.execute(
            "INSERT INTO events(session_id, kind, payload) VALUES (?, ?, ?)",
            ("builder-session", "usage", json.dumps({"context_tokens": 1250})),
        )
        self.connection.executemany(
            "INSERT INTO events(session_id, kind, payload) VALUES (?, ?, ?)",
            [
                ("builder-session", "activity", json.dumps({"index": index}))
                for index in range(150)
            ],
        )

    def sessions(self):
        return [
            {"id": "builder-session", "role": "builder", "workspace_id": "/work/item"},
            {"id": "other-session", "role": "reviewer", "workspace_id": "/work/other"},
        ]

    def latest_events(self, session_id, _limit):
        rows = self.connection.execute(
            "SELECT kind, payload FROM events WHERE session_id = ? "
            "ORDER BY seq DESC LIMIT ?",
            (session_id, _limit),
        )
        return [
            {"kind": row[0], "payload": json.loads(row[1])}
            for row in reversed(list(rows))
        ]


class Supervisor:
    store = Store()


def test_plan_task_queue_includes_state_worktree_and_matching_role_context(
    tmp_path: Path,
):
    plan = tmp_path / "plans" / "sample"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\nid: sample\n---\n", encoding="utf-8")
    (plan / "notes" / "queue.md").write_text(
        "task-one | fix:no | esc:0 | worktree:/work/item\n", encoding="utf-8"
    )
    (plan / "tasks" / "task-one.md").write_text(
        "---\nstatus: building\nowns: [runner]\n---\n", encoding="utf-8"
    )
    app = Starlette(routes=create_task_queue_routes(tmp_path, Supervisor))

    response = app_request(app, "GET", "/api/plans/sample/task-queue")

    assert response.status_code == 200
    payload = response.json()
    assert payload["items"] == [
        {
            "task_id": "task-one",
            "fix": False,
            "escalation_count": 0,
            "worktree": "/work/item",
            "status": "building",
            "blocked": False,
            "blocked_by": [],
            "claimed_by": None,
            "claim_expires_at": None,
        }
    ]
    assert payload["role_sessions"] == [
        {
            "role": "builder",
            "session_id": "builder-session",
            "worktree": "/work/item",
            "context_tokens": 1250,
        }
    ]


def test_plan_task_queue_includes_sqlite_claim_fields(tmp_path: Path):
    working = tmp_path
    plan = working / "plans" / "sample"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\nid: sample\n---\n", encoding="utf-8")
    (plan / "notes" / "queue.md").write_text(
        "task-one | fix:no | esc:0 | worktree:/work/item\n", encoding="utf-8"
    )
    (plan / "tasks" / "task-one.md").write_text(
        "---\nstatus: building\nowns: [runner]\n---\n", encoding="utf-8"
    )
    initialize(working)
    import_line_queue(plan)
    with (
        barrier(working),
        sqlite3.connect(working / QUEUE_DATABASE) as db,
    ):
        db.execute("UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'")
    repo = open_queue(working)
    claimed = repo.claim("line:plans/sample", worker="builder", lease_s=120)
    assert claimed is not None
    app = Starlette(routes=create_task_queue_routes(working, Supervisor))

    response = app_request(app, "GET", "/api/plans/sample/task-queue")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["claimed_by"] == "builder"
    assert item["claim_expires_at"] == claimed.claim_expires_at


def test_plan_task_queue_returns_not_found_for_missing_plan(tmp_path: Path):
    app = Starlette(routes=create_task_queue_routes(tmp_path, Supervisor))

    response = app_request(app, "GET", "/api/plans/missing/task-queue")

    assert response.status_code == 404


def test_plan_task_queue_rejects_queue_line_without_escalation(tmp_path: Path):
    plan = tmp_path / "plans" / "sample"
    (plan / "notes").mkdir(parents=True)
    (plan / "tasks").mkdir()
    (plan / "plan.md").write_text("---\nid: sample\n---\n", encoding="utf-8")
    (plan / "notes" / "queue.md").write_text(
        "task-one | fix:no | worktree:/work/item\n", encoding="utf-8"
    )
    (plan / "tasks" / "task-one.md").write_text(
        "---\nstatus: building\nowns: [runner]\n---\n", encoding="utf-8"
    )
    app = Starlette(routes=create_task_queue_routes(tmp_path, Supervisor))

    response = app_request(app, "GET", "/api/plans/sample/task-queue")

    assert response.status_code == 422
    assert "esc:<n>" in response.json()["error"]


def test_plan_without_pipeline_queue_returns_empty_items(tmp_path: Path):
    plan = tmp_path / "plans" / "ordinary"
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text("---\nid: ordinary\n---\n", encoding="utf-8")
    app = Starlette(routes=create_task_queue_routes(tmp_path, Supervisor))

    response = app_request(app, "GET", "/api/plans/ordinary/task-queue")

    assert response.status_code == 200
    assert response.json()["items"] == []
