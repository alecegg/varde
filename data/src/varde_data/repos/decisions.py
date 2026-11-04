"""Backend-neutral decision repository API."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from varde_data.errors import Conflict, Invalid
from varde_data.records.decisions import (
    AnswerEntry,
    AuditEntry,
    DecisionProjection,
    DecisionRecord,
    DeliveredReply,
    SubmitResult,
)
from varde_data.version import Version

MAX_PLAN_WRITEBACK_ATTEMPTS = 3


def validate_decision_id(decision_id: str) -> None:
    if not isinstance(decision_id, str) or not decision_id:
        raise Invalid("decision_id is required")


class IdempotencyConflict(Conflict):
    """An idempotency key was reused with different answer data."""


class AlreadyAnswered(Conflict):
    """The decision is no longer pending and cannot accept an answer."""


class DecisionRepository(Protocol):
    def project(self, projection: DecisionProjection) -> bool: ...
    def get_decision(self, decision_id: str) -> DecisionRecord | None: ...
    def list_decisions(
        self, state: str | None = None, kinds: Iterable[str] | None = None
    ) -> list[DecisionRecord]: ...
    def dismiss(self, decision_id: str) -> bool: ...
    def restore(self, decision_id: str) -> bool: ...
    def submit_answer(
        self, decision_id: str, idempotency_key: str, recipient: str, body: str
    ) -> SubmitResult: ...
    def transition_entry(
        self,
        entry_id: str,
        new_state: str,
        expected_state: str | set[str],
        reason: str,
        msg_ids: list[str] | None = None,
        delivery_msg_id: str | None = None,
    ) -> bool: ...
    def resolve_permission(self, entry_id: str, success: bool) -> AnswerEntry: ...
    def entries_by_status(self, status: str) -> list[AnswerEntry]: ...
    def get_entry_by_id(self, entry_id: str) -> AnswerEntry | None: ...
    def get_entry(self, idempotency_key: str) -> AnswerEntry | None: ...
    def permission_entry(self, idempotency_key: str) -> bool: ...
    def latest_delivered_reply(self, decision_id: str) -> DeliveredReply | None: ...
    def writeback_candidates(self, attempt_cap: int = 3) -> list[AnswerEntry]: ...
    def record_writeback_audit(
        self, decision_id: str, state: str, entry_id: str, reason: str
    ) -> None: ...
    def audit_rows(self, decision_id: str | None = None) -> list[AuditEntry]: ...
    def write_answer_note(self, entry_id: str, body: bytes) -> str: ...
    def notes_path(self, entry_id: str) -> str: ...
    def version(self) -> Version: ...
    def close(self) -> None: ...
