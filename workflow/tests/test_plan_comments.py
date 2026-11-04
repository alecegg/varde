from __future__ import annotations

import json

from varde_workflow import cli
from varde_workflow.commands.readiness import readiness_data
from varde_workflow.commands.status import collect_from, render
from varde_workflow.plan_comments import open_comment_count, read_comments


def _plan(working):
    folder = working / "plans" / "sample"
    folder.mkdir(parents=True)
    plan = folder / "plan.md"
    plan.write_text(
        "---\ntype: plan\nid: sample\ntitle: Sample\nstatus: active\n---\n"
        "## Tasks\n- [ ] Implement comments\n",
        encoding="utf-8",
    )
    return plan


def test_open_comment_count_folds_resolved_events(tmp_path):
    plan = _plan(tmp_path / "working")
    comments = plan.parent / "comments.jsonl"
    comments.write_text(
        json.dumps({"id": "c1", "text": "Fix this", "state": "open"})
        + "\n"
        + json.dumps({"id": "c1", "state": "resolved"})
        + "\n"
        + json.dumps({"id": "c1", "state": "open"})
        + "\n",
        encoding="utf-8",
    )

    assert read_comments(comments)[0]["state"] == "open"
    assert open_comment_count(plan) == 1


def test_plan_comments_cli_lists_only_open_comments(tmp_path, monkeypatch, capsys):
    working = tmp_path / "working"
    plan = _plan(working)
    (plan.parent / "comments.jsonl").write_text(
        json.dumps(
            {
                "id": "open-1",
                "target": "plan",
                "text": "Open note",
                "state": "open",
                "kind": "stored",
            }
        )
        + "\n"
        + json.dumps(
            {
                "id": "done-1",
                "target": "plan",
                "text": "Done note",
                "state": "resolved",
                "kind": "stored",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(tmp_path)

    assert cli.run(["plan", "comments", "sample", "--open"]) == 0
    output = capsys.readouterr().out

    assert "open-1 [open]" in output
    assert "Open note" in output
    assert "Done note" not in output
    assert "saved for when work starts" in output


def test_readiness_and_status_report_open_comment_counts(tmp_path, monkeypatch, capsys):
    working = tmp_path / "working"
    plan = _plan(working)
    (plan.parent / "comments.jsonl").write_text(
        json.dumps({"id": "c1", "text": "Fix this", "state": "open"}) + "\n",
        encoding="utf-8",
    )

    assert readiness_data(str(plan))["open_comments"] == 1
    report = collect_from(working)
    assert report["open_comments"] == 1
    assert report["plans"][0]["open_comments"] == 1
    assert "1 open comment" in render(report, "now")

    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(tmp_path)
    assert cli.run(["plan", "status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["open_comments"] == 1
