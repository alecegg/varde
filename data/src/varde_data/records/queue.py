"""Immutable queue store records."""

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueItemInput:
    id: str
    plan_dir: str
    findings: str = ""
    owned_files: str = ""
    depends_cell: str = ""
    depends_on: tuple[str, ...] = ()
    serialize_with: tuple[str, ...] = ()
    priority: int = 0
    state: str = "queued"
    planned_at: str | None = None
    plan_reviewed_at: str | None = None
    build_started_at: str | None = None
    build_done_at: str | None = None
    merged_at: str | None = None
    role: str | None = None
    queue_name: str = "default"
    row_order: int = 0
    extra: dict[str, object] | None = None
    followup_depth: int = 0


@dataclass(frozen=True)
class QueueItem(QueueItemInput):
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    claim_generation: int = 0
    claim_epoch: int | None = None


@dataclass(frozen=True)
class QueueEvent:
    seq: int
    item_id: str
    at: str
    actor: str
    kind: str
    from_state: str | None = None
    to_state: str | None = None
    source: str = "cli"


@dataclass(frozen=True)
class CycleTime:
    item_id: str
    planned_to_merged: float | None = None
    build_duration: float | None = None


@dataclass(frozen=True)
class PlanState:
    plan_dir: str
    status: str
    status_at: str | None = None
    owner: str | None = None
    assigned_to: str | None = None
    merge_approved_at: str | None = None


@dataclass(frozen=True)
class TaskState:
    plan_dir: str
    task_id: str
    status: str
    status_at: str | None = None
