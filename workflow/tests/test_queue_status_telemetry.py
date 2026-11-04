from __future__ import annotations

import json
import sqlite3
from typing import cast

from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_data.records.queue import QueueItemInput
from varde_data.repos.queue import QueueRepository
from varde_workflow import cli
from varde_workflow.commands import plan_queue_roles
from varde_workflow.conclusion import _append_route_decisions


def _set_sqlite_queue_mode(working) -> None:
    initialize(working)
    with sqlite3.connect(working / QUEUE_DATABASE) as connection:
        connection.execute(
            "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
        )


def test_status_includes_per_item_wait_and_wave_critical_path(
    monkeypatch, tmp_path
) -> None:
    _set_sqlite_queue_mode(tmp_path)
    repo = open_queue(tmp_path)
    repo.enqueue(
        QueueItemInput(
            "first",
            "plan",
            role="builder",
            queue_name="roles/global",
            build_started_at="2026-10-27T10:00:10+00:00",
            build_done_at="2026-10-27T10:00:20+00:00",
        )
    )
    repo.claim(
        "roles/global",
        worker="worker-1",
        lease_s=120,
        now="2030-01-01T00:00:00+00:00",
    )
    repo.enqueue(
        QueueItemInput(
            "next",
            "plan",
            role="builder",
            queue_name="roles/global",
            depends_on=("first",),
            build_started_at="2026-10-27T10:00:20+00:00",
            build_done_at="2026-10-27T10:00:35+00:00",
        )
    )
    monkeypatch.setattr(
        plan_queue_roles,
        "_snapshot",
        lambda _working: None,
    )
    monkeypatch.setattr(plan_queue_roles, "load_limits", lambda _path: (None, "none"))

    status = plan_queue_roles._status(
        cast("QueueRepository", repo), tmp_path, "roles/global"
    )

    telemetry = status["telemetry"]
    assert isinstance(telemetry["queue_wait_seconds"]["first"], float)
    assert telemetry["queue_wait_seconds"]["first"] > 0
    assert telemetry["queue_wait_seconds"]["next"] is None
    assert telemetry["run_seconds"] == {"first": 10.0, "next": 15.0}
    assert telemetry["critical_path_seconds"] == 25.0
    assert telemetry["delegated_count"] == 2
    assert telemetry["coordinator_count"] == 0


def test_conclusion_records_only_enqueued_routes_and_is_idempotent(tmp_path) -> None:
    plan_dir = tmp_path / "plans" / "plan-a"
    plan_dir.mkdir(parents=True)
    _set_sqlite_queue_mode(tmp_path)
    repo = open_queue(tmp_path)
    args = cli._parser().parse_args(
        [
            "plan",
            "queue",
            "enqueue",
            "--plan-dir",
            str(plan_dir),
            "--id",
            "task-a",
            "--role",
            "builder",
            "--kind",
            "build",
            "--route",
            "builder",
        ]
    )
    plan_queue_roles._run(args, tmp_path)
    repo.enqueue(
        QueueItemInput(
            "task-a-review",
            str(plan_dir),
            role="reviewer",
            queue_name="roles/global",
            extra={"kind": "review", "inputs": {}},
        )
    )

    _append_route_decisions(plan_dir, "approved")
    _append_route_decisions(plan_dir, "approved")

    lines = (plan_dir / "notes/route-decisions.jsonl").read_text().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0]) == {
        "baseline_failures": None,
        "cost": None,
        "input_tokens": None,
        "model": None,
        "output_tokens": None,
        "provider": None,
        "pyright_errors": None,
        "retries": None,
        "review_findings": None,
        "review_verdict": "approved",
        "reviewers": None,
        "route_tier": "builder",
        "task_id": "task-a",
    }


def test_conclusion_skips_missing_or_invalid_route(tmp_path) -> None:
    plan_dir = tmp_path / "plans" / "plan-a"
    plan_dir.mkdir(parents=True)
    _set_sqlite_queue_mode(tmp_path)
    repo = open_queue(tmp_path)
    for task_id, route in (("missing", None), ("invalid", "unknown")):
        repo.enqueue(
            QueueItemInput(
                task_id,
                str(plan_dir),
                role="builder",
                queue_name="roles/global",
                extra={"kind": "build", "inputs": {"route_tier": route}},
            )
        )
    _append_route_decisions(plan_dir, "approved")
    assert not (plan_dir / "notes/route-decisions.jsonl").exists()
