from __future__ import annotations

import json

from test_web import app_request
from varde_runner.varde_cli import VardeCLI
from varde_runner.web import create_app


def test_plans_list_projects_store_records_without_agent_fields(tmp_path, monkeypatch):
    working = tmp_path / "working"
    plans = working / "plans"
    plans.mkdir(parents=True)
    for plan_id, title, status in (
        ("active-plan", "Active", "active"),
        ("queued-plan", "Queued", "backlog"),
        ("held-plan", "Held", "held"),
    ):
        folder = plans / plan_id
        folder.mkdir()
        (folder / "plan.md").write_text(
            f"---\ntype: plan\nid: {plan_id}\ntitle: {title}\nstatus: {status}\n---\n",
            encoding="utf-8",
        )
    (plans / "queued-plan" / "comments.jsonl").write_text(
        json.dumps({"id": "c1", "text": "Please clarify", "state": "open"}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    env = {"VARDE_PLANS_BACKEND": "sqlite", "VARDE_WORKING_DIR": str(working)}
    cli = VardeCLI(cwd=working, env=env)
    app = create_app(data_dir=tmp_path / "runner-data", cli=cli, agents=list)
    app.state.dashboard.plan_reads.refresh_once()

    response = app_request(app, "GET", "/api/plans")

    assert response.status_code == 200
    rows = {row["id"]: row for row in response.json()}
    assert rows["active-plan"]["status"] == "in_progress"
    assert rows["queued-plan"]["status"] == "queued"
    assert rows["queued-plan"]["queue_position"] == 1
    assert rows["held-plan"]["status"] == "needs_review"
    assert rows["queued-plan"]["open_comments"] == 1
    assert set(rows["queued-plan"]) == {
        "id",
        "title",
        "label",
        "status",
        "queue_position",
        "open_comments",
        "updated",
    }
