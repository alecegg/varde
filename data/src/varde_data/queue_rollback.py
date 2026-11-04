"""Export queue and plan state to Markdown and return the store to file mode."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from varde_data.backends.sqlite.plan_state import SQLitePlanState
from varde_data.backends.sqlite.queue import SQLiteQueue
from varde_data.errors import Conflict
from varde_data.locking import atomic_write
from varde_data.plan_state_sync import export_plan_dir, import_plan_dir
from varde_data.queue_line_sync import export_line_queue
from varde_data.queue_migrate import verify
from varde_data.queue_mode_lock import barrier, operation
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.queue_store import create_backup
from varde_data.queue_sync import export_queue_md, record_queue_md_export

_DATABASE = QUEUE_DATABASE


@dataclass(frozen=True)
class RollbackReport:
    backup: Path


def _queue_names(working: Path) -> list[str]:
    store = SQLiteQueue(working / _DATABASE)
    with store._connection() as db:
        rows = db.execute("SELECT queue_name FROM queue_meta ORDER BY queue_name")
        return [str(row[0]) for row in rows]


def _export_queues(working: Path) -> None:
    for queue_name in _queue_names(working):
        if queue_name.startswith("line:"):
            plan_dir = working / queue_name.removeprefix("line:")
            rendered = export_line_queue(plan_dir)
            path = plan_dir / "notes" / "queue.md"
            atomic_write(
                path,
                rendered.encode("utf-8"),
                mode=path.stat().st_mode & 0o777,
            )
            continue

        path = working / queue_name
        rendered = export_queue_md(working, queue_name)
        atomic_write(path, rendered.encode("utf-8"), mode=path.stat().st_mode & 0o777)
        record_queue_md_export(working, queue_name, rendered)


def _export_plans(working: Path) -> None:
    store = SQLitePlanState(working / _DATABASE)
    with store._connection() as db:
        rows = db.execute("SELECT plan_dir FROM plan_state ORDER BY plan_dir")
        plan_dirs = [Path(str(row[0])) for row in rows]
    for plan_dir in plan_dirs:
        import_plan_dir(working, plan_dir)
        export_plan_dir(working, plan_dir)


def rollback(working: str | Path, *, timeout: float = 30) -> RollbackReport:
    """Back up, export, verify, then atomically switch to Markdown mode."""
    root = Path(working).resolve()
    with barrier(root, timeout=timeout):
        with operation(root, timeout=timeout) as mode:
            if mode != "sqlite":
                raise Conflict("queue store is already in markdown mode")

        with operation(root, timeout=timeout) as mode:
            if mode != "sqlite":
                raise Conflict("queue store mode changed during rollback")
            saved = create_backup(root)
            _export_queues(root)
            _export_plans(root)

        with operation(root, timeout=timeout) as mode:
            if mode != "sqlite":
                raise Conflict("queue store mode changed during rollback")
            differences = verify(root)
        if differences:
            raise Conflict(
                "queue rollback verification failed: " + "; ".join(differences[:10])
            )

        with operation(root, timeout=timeout) as mode:
            if mode != "sqlite":
                raise Conflict("queue store mode changed during rollback")
            with sqlite3.connect(root / _DATABASE) as db:
                db.execute(
                    "UPDATE queue_store_meta SET value='markdown' "
                    "WHERE key='store_mode'"
                )

        return RollbackReport(saved)
