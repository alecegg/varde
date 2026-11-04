"""Records for the manager-bot audit log and run state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

AuditPhase = Literal["call", "result"]
BotRunState = Literal["running", "paused", "killed"]


@dataclass(frozen=True)
class AuditRow:
    """One append-only gateway record. Rows are never updated or deleted."""

    id: int
    ts: str
    phase: AuditPhase
    action: str
    route: str
    args_digest: str
    redacted_args: str
    actor: str
    status: str
    reason: str | None
    agent_id: str | None
    plan_id: str | None


@dataclass(frozen=True)
class BotState:
    key: str
    state: str
    reason: str | None
    changed_at: str
    changed_by: str
