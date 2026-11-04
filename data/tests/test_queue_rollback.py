from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.queue_migrate import migrate
from varde_data.queue_mode_lock import operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_rollback import rollback

FIXTURE = Path(__file__).parent / "fixtures/queue_md/ux-audit-fixes-1.md"
LINE_QUEUE = "# Queue\na-task | fix:yes | esc:1 | worktree:-\n\nNotes stay here.\n"


def _working(tmp_path: Path) -> Path:
    root = tmp_path / "working"
    plan_dir = root / "plans/bundle"
    (plan_dir / "tasks").mkdir(parents=True)
    (plan_dir / "notes").mkdir()
    (plan_dir / "queue.md").write_text(FIXTURE.read_text())
    (plan_dir / "plan.md").write_text(
        "---\nstatus: active\nstatus_at: '2026-10-26'\nowner: alec\n---\n"
    )
    (plan_dir / "tasks/one.md").write_text("---\nstatus: todo\nstatus_at: null\n---\n")
    (plan_dir / "notes/queue.md").write_text(LINE_QUEUE)
    return root


def _state(root: Path) -> tuple[list[tuple], list[tuple], list[tuple]]:
    with sqlite3.connect(root / QUEUE_DATABASE) as db:
        queue_rows = db.execute(
            "SELECT id, plan_dir, findings, owned_files, depends_cell, depends_on, "
            "serialize_with, priority, state, planned_at, plan_reviewed_at, "
            "build_started_at, build_done_at, merged_at, role, claimed_by, "
            "claim_expires_at, claim_generation, claim_epoch, queue_name, row_order "
            "FROM queue_items "
            "ORDER BY queue_name, row_order"
        ).fetchall()
        plans = db.execute(
            "SELECT plan_dir, status, status_at, owner, assigned_to, "
            "merge_approved_at FROM plan_state ORDER BY plan_dir"
        ).fetchall()
        tasks = db.execute(
            "SELECT plan_dir, task_id, status, status_at FROM task_state "
            "ORDER BY plan_dir, task_id"
        ).fetchall()
    return queue_rows, plans, tasks


def test_rollback_exports_mutations_and_migrate_restores_same_store(
    tmp_path: Path,
) -> None:
    root = _working(tmp_path)
    line_file = root / "plans/bundle/notes/queue.md"
    original_line_queue = line_file.read_text()
    migrate(root)

    queue = SQLiteQueue(root / QUEUE_DATABASE)
    plan = SQLitePlanState(root / QUEUE_DATABASE)
    with operation(root):
        queue.transition(
            "plans/bundle/queue.md",
            "A",
            "building",
            actor="test",
            expect_state="merged",
        )
        plan.set_plan_state(str(root / "plans/bundle"), status="paused")
        plan.set_task_state(str(root / "plans/bundle"), "one", "done", actor="test")

    expected = _state(root)
    report = rollback(root)

    assert report.backup.is_file()
    assert line_file.read_text() == original_line_queue
    assert "| A |" in (root / "plans/bundle/queue.md").read_text()
    assert "| building |" in (root / "plans/bundle/queue.md").read_text()
    assert "status: paused" in (root / "plans/bundle/plan.md").read_text()
    assert "status: done" in (root / "plans/bundle/tasks/one.md").read_text()
    with sqlite3.connect(root / QUEUE_DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("markdown",)

    migrate(root)

    assert _state(root) == expected
    with sqlite3.connect(root / QUEUE_DATABASE) as db:
        assert db.execute(
            "SELECT value FROM queue_store_meta WHERE key='store_mode'"
        ).fetchone() == ("sqlite",)


def test_rollback_imports_hand_edited_plan_and_task_state(tmp_path: Path) -> None:
    root = _working(tmp_path)
    migrate(root)
    plan_file = root / "plans/bundle/plan.md"
    task_file = root / "plans/bundle/tasks/one.md"
    plan_file.write_text(
        plan_file.read_text()
        .replace("status: active", "status: hand-edited")
        .replace("owner: alec", "owner: new-owner")
    )
    task_file.write_text(
        task_file.read_text().replace("status: todo", "status: hand-edited-task")
    )

    rollback(root)

    assert "status: hand-edited" in plan_file.read_text()
    assert "owner: new-owner" in plan_file.read_text()
    assert "status: hand-edited-task" in task_file.read_text()
    migrate(root)
    _, plans, tasks = _state(root)
    assert plans[0][1:4] == ("hand-edited", "2026-10-26", "new-owner")
    assert tasks[0][2] == "hand-edited-task"
