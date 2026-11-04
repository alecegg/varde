from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from varde_data.plan_state import open_plan_state
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import initialize
from varde_workflow import cli
from varde_workflow.commands import task_set


def _sqlite_mode(working: Path) -> None:
    with operation(working):
        initialize(working)
        with closing(sqlite3.connect(working / QUEUE_DATABASE)) as db, db:
            db.execute(
                "UPDATE queue_store_meta SET value='sqlite' WHERE key='store_mode'"
            )


def test_task_set_writes_store_and_frontmatter(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "memory"
    task = working / "plans/sample/tasks/task.md"
    task.parent.mkdir(parents=True)
    task.write_text("---\ntype: task\nid: task\nstatus: todo\n---\n", encoding="utf-8")
    (task.parent.parent / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n", encoding="utf-8"
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    _sqlite_mode(working)

    assert task_set.run(SimpleNamespace(task=task, state="in_progress", json=True)) == 0

    with operation(working):
        state = open_plan_state(working).task_states(task.parent.parent)
    assert [(item.task_id, item.status) for item in state] == [("task", "in_progress")]
    assert "status: in_progress" in task.read_text(encoding="utf-8")
    assert any(item.status_at for item in state)


def test_task_set_rejects_unknown_status_in_sqlite_mode(
    tmp_path: Path, monkeypatch
) -> None:
    working = tmp_path / "memory"
    task = working / "plans/sample/tasks/task.md"
    task.parent.mkdir(parents=True)
    task.write_text("---\ntype: task\nid: task\nstatus: todo\n---\n", encoding="utf-8")
    (task.parent.parent / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n", encoding="utf-8"
    )
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)
    _sqlite_mode(working)

    assert task_set.run(SimpleNamespace(task=task, state="unknown", json=True)) == 1
    assert "status: todo" in task.read_text(encoding="utf-8")
    with operation(working):
        state = open_plan_state(working).task_states(task.parent.parent)
    assert state == []


def test_plan_store_import_reports_skipped_task_documents(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    working = tmp_path / "memory"
    plan = working / "plans/sample"
    tasks = plan / "tasks"
    tasks.mkdir(parents=True)
    (plan / "plan.md").write_text("---\nstatus: active\n---\n", encoding="utf-8")
    skipped = tasks / "explorer-brief.md"
    skipped.write_text("Shared brief for explorers.\n- Read only.\n", encoding="utf-8")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.chdir(working)

    assert cli.run(["plan", "store", "import", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["data"]["skipped_task_states"] == [str(skipped)]

    assert cli.run(["plan", "store", "import"]) == 0
    assert str(skipped) in capsys.readouterr().out
