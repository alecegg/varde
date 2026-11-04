"""SQLite storage for plan and task workflow state."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime
from pathlib import Path

from varde_data.backends.sqlite.queue_schema import configure_store
from varde_data.errors import Locked, NotFound
from varde_data.records.queue import PlanState, TaskState


class _Unset:
    pass


_UNSET = _Unset()


def initialize_plan_state(path: Path) -> None:
    """Initialize the plan state tables in the queue database."""
    SQLitePlanState(path)


def canonical_plan_dir(plan_dir: str | Path) -> str:
    """Return one absolute key for a plan directory or its plan.md file."""
    path = Path(plan_dir)
    if path.name == "plan.md":
        path = path.parent
    return str(path.resolve())


class SQLitePlanState:
    """Persist plan/task state in the plan queue database."""

    def __init__(self, path: Path, *, busy_timeout: float = 30) -> None:
        self.path = path
        self.busy_timeout = busy_timeout
        with self._connection() as db:
            configure_store(db)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=self.busy_timeout)
        db.row_factory = sqlite3.Row
        try:
            with closing(db), db:
                yield db
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                raise Locked("queue database is busy; retry the operation") from exc
            raise

    def set_plan_state(
        self,
        plan_dir: str,
        *,
        status: str,
        status_at: str | None | _Unset = _UNSET,
        owner: str | None | _Unset = _UNSET,
        assigned_to: str | None | _Unset = _UNSET,
        merge_approved_at: str | None | _Unset = _UNSET,
    ) -> PlanState:
        plan_dir = canonical_plan_dir(plan_dir)
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT * FROM plan_state WHERE plan_dir=?", (plan_dir,)
            ).fetchone()
            values = {
                "status": status,
                "status_at": _field_value(status_at, previous, "status_at"),
                "owner": _field_value(owner, previous, "owner"),
                "assigned_to": _field_value(assigned_to, previous, "assigned_to"),
                "merge_approved_at": _field_value(
                    merge_approved_at, previous, "merge_approved_at"
                ),
            }
            db.execute(
                "INSERT INTO plan_state "
                "(plan_dir,status,status_at,owner,assigned_to,merge_approved_at) "
                "VALUES (?,?,?,?,?,?) ON CONFLICT(plan_dir) DO UPDATE SET "
                "status=excluded.status,status_at=excluded.status_at,"
                "owner=excluded.owner,assigned_to=excluded.assigned_to,"
                "merge_approved_at=excluded.merge_approved_at,"
                "last_export_hash=NULL",
                (
                    plan_dir,
                    values["status"],
                    values["status_at"],
                    values["owner"],
                    values["assigned_to"],
                    values["merge_approved_at"],
                ),
            )
            old_status = previous["status"] if previous is not None else None
            if old_status != status:
                _record_transition(
                    db,
                    f"plan:{plan_dir}",
                    old_status,
                    status,
                    actor="cli",
                    source="cli",
                )
            return self._plan(
                db.execute(
                    "SELECT * FROM plan_state WHERE plan_dir=?", (plan_dir,)
                ).fetchone()
            )

    def set_task_state(
        self, plan_dir: str, task_id: str, status: str, *, actor: str
    ) -> TaskState:
        plan_dir = canonical_plan_dir(plan_dir)
        stamp = datetime.now(UTC).isoformat()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute(
                "SELECT status FROM task_state WHERE plan_dir=? AND task_id=?",
                (plan_dir, task_id),
            ).fetchone()
            db.execute(
                "INSERT INTO task_state (plan_dir,task_id,status,status_at) "
                "VALUES (?,?,?,?) ON CONFLICT(plan_dir,task_id) DO UPDATE SET "
                "status=excluded.status,status_at=excluded.status_at,"
                "last_export_hash=NULL",
                (plan_dir, task_id, status, stamp),
            )
            old_status = previous["status"] if previous is not None else None
            if old_status != status:
                _record_transition(
                    db,
                    f"task:{plan_dir}:{task_id}",
                    old_status,
                    status,
                    actor=actor,
                    source="cli",
                )
            row = db.execute(
                "SELECT * FROM task_state WHERE plan_dir=? AND task_id=?",
                (plan_dir, task_id),
            ).fetchone()
            return self._task(row)

    def plan_state(self, plan_dir: str | Path) -> PlanState:
        plan_dir = canonical_plan_dir(plan_dir)
        with self._connection() as db:
            row = db.execute(
                "SELECT * FROM plan_state WHERE plan_dir=?", (plan_dir,)
            ).fetchone()
        if row is None:
            raise NotFound(plan_dir)
        return self._plan(row)

    def task_states(self, plan_dir: str | Path) -> list[TaskState]:
        plan_dir = canonical_plan_dir(plan_dir)
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM task_state WHERE plan_dir=? ORDER BY task_id",
                (plan_dir,),
            ).fetchall()
        return [self._task(row) for row in rows]

    @staticmethod
    def _plan(row: sqlite3.Row) -> PlanState:
        return PlanState(
            row["plan_dir"],
            row["status"],
            row["status_at"],
            row["owner"],
            row["assigned_to"],
            row["merge_approved_at"],
        )

    @staticmethod
    def _task(row: sqlite3.Row) -> TaskState:
        return TaskState(
            row["plan_dir"], row["task_id"], row["status"], row["status_at"]
        )


def _field_value(value: str | None | _Unset, row: sqlite3.Row | None, key: str):
    if value is not _UNSET:
        return value
    return row[key] if row is not None else None


def _record_transition(
    db: sqlite3.Connection,
    item_id: str,
    old: str | None,
    new: str,
    *,
    actor: str,
    source: str,
) -> None:
    db.execute(
        "INSERT INTO queue_events "
        "(item_id,at,actor,kind,from_state,to_state,source) "
        "VALUES (?,?,?,'transition',?,?,?)",
        (item_id, datetime.now(UTC).isoformat(), actor, old, new, source),
    )
