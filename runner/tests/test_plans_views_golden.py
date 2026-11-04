from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from starlette.applications import Starlette

sys.path.insert(0, str(Path(__file__).parents[2] / "workflow" / "tests"))
from golden.plans.builder import build  # type: ignore[reportMissingImports]
from test_web import app_request
from varde_runner.varde_cli import VardeCLI
from varde_runner.web.queue import create_queue_routes


def test_runner_plan_views_golden(tmp_path: Path, monkeypatch) -> None:
    working, _ = build(tmp_path)
    shutil.rmtree(working / "plans/assigned/plan")
    plan_path = working / "plans/assigned/plan.md"
    plan_path.write_text(
        "---\ntype: plan\nid: assigned\ntitle: Assigned plan\n"
        "status: active\nassigned_to: agent-1\nbranch: worktree/assigned\n"
        "depends_on: [base-plan]\nshared: [uv.lock]\ngate: []\n---\n",
        encoding="utf-8",
    )
    task_path = working / "plans/assigned/tasks/active.md"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        "---\ntype: task\nid: active\ntitle: Active task\n"
        "status: done\nstatus_at: '2023-11-14T22:13:20Z'\n---\n",
        encoding="utf-8",
    )
    cli = VardeCLI(cwd=working, env={"VARDE_WORKING_DIR": str(working)})

    monkeypatch.setattr(cli, "read_address_bindings", list)

    original_run = subprocess.run
    golden_dir = Path(__file__).parent / "golden/plans"

    def run(args, **kwargs):
        if args[:3] == ["varde", "plan", "status"]:
            return SimpleNamespace(
                stdout=(golden_dir / "plan-status.stdout").read_text(encoding="utf-8"),
                returncode=0,
            )
        if args[:3] == ["varde", "plan", "watch"]:
            return SimpleNamespace(
                stdout=(golden_dir / "plan-watch.stdout").read_text(encoding="utf-8"),
                returncode=0,
            )
        return original_run(args, **kwargs)

    monkeypatch.setattr("varde_runner.varde_cli.subprocess.run", run)
    detail = app_request(
        Starlette(routes=create_queue_routes(cli, working)),
        "GET",
        "/api/plans/assigned",
    )
    queue = app_request(
        Starlette(routes=create_queue_routes(cli, working)), "GET", "/api/queue"
    )
    snapshot = {
        "assigned": cli.read_assigned_plans(),
        "tasks": cli.read_plan_tasks("assigned"),
        "summary": cli.read_plan_summary("assigned"),
        "status": cli.read_plan_status(),
        "watch": cli.read_plan_watch(),
        "queue": queue.json(),
        "detail": detail.json(),
    }
    normalized = (
        json.dumps(snapshot, indent=2, sort_keys=True).replace(str(tmp_path), "<TMP>")
        + "\n"
    )
    golden = golden_dir / "runner-plans-views.json"
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(normalized, encoding="utf-8")
    assert golden.read_text(encoding="utf-8") == normalized

    assigned = snapshot["assigned"][0]
    assert assigned["depends_on"] == ["base-plan"]
    assert assigned["shared"] == ["uv.lock"]
    assert assigned["gate"] == []
    assert isinstance(assigned["depends_on"], list)
    assert isinstance(assigned["shared"], list)
    assert isinstance(assigned["gate"], list)
    assert snapshot["watch"]["events"][0]["plan"] == "assigned"
    assert snapshot["watch"]["events"][0]["kind"] == "merge-ready"
