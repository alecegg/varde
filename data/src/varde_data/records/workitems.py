"""Work item domain records shared by storage backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkItem:
    id: str
    idempotency_key: str
    text: str
    project: str
    state: str
    notes_path: str
    planner_session: str | None = None
    plan_path: str | None = None
    plan_ready_id: str | None = None
    launch_request_id: str | None = None
    launch_request_notes: str | None = None


@dataclass(frozen=True)
class Question:
    item_id: str
    msg_id: str
    payload: dict[str, Any]
    answer: str | None = None
    answer_key: str | None = None


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    item_id: str
    prior_state: str | None
    new_state: str
    detail: str
