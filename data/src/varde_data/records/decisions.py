"""Decision repository records."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DecisionProjection:
    source_id: str
    decision_id: str
    kind: str
    title: str
    body: str
    context: dict[str, Any]
    plan_id: str | None = None
    source_agent: str | None = None


@dataclass(frozen=True)
class DecisionRecord:
    decision_id: str
    state: str
    source_msg_ids: list[str] = field(default_factory=list)
    answer_key: str | None = None
    kind: str = "agent_question"
    record: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AnswerEntry:
    entry_id: str
    decision_id: str
    idempotency_key: str
    recipient: str
    body: str
    status: str
    notes_path: str
    delivery_msg_id: str | None = None


@dataclass(frozen=True)
class SubmitResult:
    entry: AnswerEntry
    replayed: bool


@dataclass(frozen=True)
class DeliveredReply:
    body: str
    sent_at: str


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    decision_id: str
    prior_state: str
    new_state: str
    actor: str
    at: str
    reason: str
    msg_ids: list[str]
