from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from pathlib import Path
from time import perf_counter

import pytest
from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.queue_migrate import migrate, verify
from varde_data.queue_rollback import rollback

NOTES = Path(__file__).with_name("rehearsal_notes.md")
DATABASE = Path(".cache/data/queue.sqlite3")


def _tree_counts(root: Path) -> tuple[int, int]:
    files = [path for path in root.rglob("*") if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def _store_counts(database: Path) -> tuple[int, int, int]:
    with sqlite3.connect(database) as db:
        items = int(db.execute("SELECT COUNT(*) FROM queue_items").fetchone()[0])
        plans = int(db.execute("SELECT COUNT(*) FROM plan_state").fetchone()[0])
        tasks = int(db.execute("SELECT COUNT(*) FROM task_state").fetchone()[0])
    return items, plans, tasks


def test_live_plans_copy_migration_rollback_rehearsal() -> None:
    live_plans = os.environ.get("VARDE_REHEARSAL_PLANS")
    if not live_plans:
        pytest.skip("set VARDE_REHEARSAL_PLANS to the live plans tree to run rehearsal")

    source = Path(live_plans).resolve()
    if not source.is_dir():
        pytest.fail(f"VARDE_REHEARSAL_PLANS is not a directory: {source}")

    started = perf_counter()
    with tempfile.TemporaryDirectory(prefix="varde-live-plans-rehearsal-") as tmp:
        working = Path(tmp)
        copied_plans = working / "plans"
        shutil.copytree(source, copied_plans)
        copied_files, copied_bytes = _tree_counts(copied_plans)

        migration_started = perf_counter()
        first_migration = migrate(working)
        first_migration_s = perf_counter() - migration_started
        assert verify(working) == []
        items, plans, tasks = _store_counts(working / DATABASE)
        assert plans > 0, "live plans copy contains no importable plan state"

        with sqlite3.connect(working / DATABASE) as db:
            plan_dir = str(
                db.execute(
                    "SELECT plan_dir FROM plan_state ORDER BY plan_dir LIMIT 1"
                ).fetchone()[0]
            )
            original_status = str(
                db.execute(
                    "SELECT status FROM plan_state WHERE plan_dir=?", (plan_dir,)
                ).fetchone()[0]
            )
        SQLitePlanState(working / DATABASE).set_plan_state(
            plan_dir, status=f"{original_status}-rehearsal"
        )

        rollback_started = perf_counter()
        rollback_report = rollback(working)
        rollback_s = perf_counter() - rollback_started
        assert rollback_report.backup.is_file()
        assert verify(working) == []

        remigration_started = perf_counter()
        second_migration = migrate(working)
        remigration_s = perf_counter() - remigration_started
        assert verify(working) == []
        assert first_migration.diffs == ()
        assert second_migration.diffs == ()

        migration_backup = (
            "created"
            if first_migration.backup
            else "not applicable (copy had no database)"
        )
        report = (
            "# Live plans copy rehearsal\n\n"
            f"- Source: `{source}` (read only)\n"
            f"- Copied Markdown files: {copied_files}; bytes: {copied_bytes}\n"
            f"- Imported rows: {items} queue items, {plans} plans, {tasks} tasks\n"
            f"- First migration: {first_migration_s:.3f}s; diffs: 0; "
            f"migration backup: {migration_backup}\n"
            f"- Rollback: {rollback_s:.3f}s; verified backup: "
            f"`{rollback_report.backup.name}`; diffs: 0\n"
            f"- Mutation: copied plan `{plan_dir}` status changed from "
            f"`{original_status}` to `{original_status}-rehearsal`; "
            "rollback exported it\n"
            f"- Second migration: {remigration_s:.3f}s; diffs: 0\n"
            f"- Total rehearsal: {perf_counter() - started:.3f}s\n"
            "- Outcome: passed; operations used a temporary copy and left "
            "the source read only.\n"
        )
        NOTES.write_text(report, encoding="utf-8")
