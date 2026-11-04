"""Public plan and task state repository."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from varde_data.backends.sqlite.plan_state import (
    SQLitePlanState,
    canonical_plan_dir,
)
from varde_data.queue_mode_lock import require_role_queue_ready
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.records.queue import PlanState, TaskState


class PlanStateRepository(Protocol):
    """Operations for stored plan and task workflow state."""

    def set_plan_state(
        self,
        plan_dir: str,
        *,
        status: str,
        status_at: str | None = None,
        owner: str | None = None,
        assigned_to: str | None = None,
        merge_approved_at: str | None = None,
    ) -> PlanState: ...
    def set_task_state(
        self, plan_dir: str, task_id: str, status: str, *, actor: str
    ) -> TaskState: ...
    def plan_state(self, plan_dir: str | Path) -> PlanState: ...
    def task_states(self, plan_dir: str | Path) -> list[TaskState]: ...


def open_plan_state(root: Path) -> PlanStateRepository:
    """Open plan/task state in the working directory's queue database."""
    require_role_queue_ready(root)
    return SQLitePlanState(root / QUEUE_DATABASE)


__all__ = ["PlanStateRepository", "canonical_plan_dir", "open_plan_state"]
