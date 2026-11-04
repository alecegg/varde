"""Deliver stored decision answers and reconcile ambiguous sends."""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from varde_data.records.decisions import AnswerEntry, DecisionProjection
from varde_data.repos.decisions import (
    MAX_PLAN_WRITEBACK_ATTEMPTS,
    AlreadyAnswered,
    DecisionRepository,
    IdempotencyConflict,
)

MAX_ENTRY_CHARS = 20_000
DELIVERY_ERRORS = (OSError, RuntimeError, ValueError, subprocess.SubprocessError)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EntryResult:
    entry_id: str | None
    status: str
    notes_path: str | None = None
    delivery_msg_id: str | None = None
    status_code: int = 200


class AnswerFlow:
    def __init__(
        self,
        repo: DecisionRepository,
        send: Callable[..., dict[str, Any]],
        read_messages: Callable[[], list[dict[str, Any]]],
        write_back: Callable[[str, str, str], Any] | None = None,
        recorder: Callable[[str, dict[str, Any]], None] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.repo = repo
        self.send = send
        self.read_messages = read_messages
        self.write_back = write_back
        self.recorder = recorder
        self.clock = clock
        # Callers may replace this hook to observe or intercept write-back attempts.
        self.write_back_entry: Callable[[str], None] = self._write_back_entry

    def submit_answer(
        self, decision_id: str, idempotency_key: str, recipient: str, body: str
    ) -> EntryResult:
        if len(body) > MAX_ENTRY_CHARS:
            return EntryResult(None, "rejected", status_code=413)
        try:
            submission = self.repo.submit_answer(
                decision_id, idempotency_key, recipient, body
            )
        except IdempotencyConflict:
            return EntryResult(None, "idempotency_conflict", status_code=409)
        except AlreadyAnswered:
            return EntryResult(None, "already_answered", status_code=409)
        answer = submission.entry
        if submission.replayed:
            return self._entry_result(answer)
        decision = self.repo.get_decision(decision_id)
        if decision is not None and decision.kind == "permission":
            return self._entry_result(answer)
        return self._deliver_initial(answer)

    def project(self, projection: DecisionProjection) -> bool:
        written = self.repo.project(projection)
        if not written:
            return False
        decision = self.repo.get_decision(projection.decision_id)
        if decision is not None:
            self._record("created", decision.record)
        return True

    def _deliver_initial(self, answer: AnswerEntry) -> EntryResult:
        try:
            self.repo.write_answer_note(answer.entry_id, answer.body.encode("utf-8"))
        except OSError:
            self.repo.transition_entry(
                answer.entry_id, "failed", "stored", "notes write failed"
            )
            return EntryResult(answer.entry_id, "failed", answer.notes_path)
        return self._deliver_stored(answer, "delivery started")

    def _deliver_stored(self, answer: AnswerEntry, reason: str) -> EntryResult:
        claimed = self.repo.transition_entry(
            answer.entry_id,
            "sending",
            answer.status,
            reason,
        )
        if not claimed:
            current = self.repo.get_entry_by_id(answer.entry_id)
            return self._entry_result(current or answer)
        return self._send_entry(answer.entry_id)

    def _send_entry(self, entry_id: str) -> EntryResult:
        row = self._entry(entry_id)
        if row is None:
            raise KeyError(entry_id)
        try:
            decision = self.repo.get_decision(row.decision_id)
            context = decision.record.get("context") if decision else None
            source_kind = (
                context.get("source_kind", "decision")
                if isinstance(context, dict)
                else "decision"
            )
            relay_text = f"re {source_kind} {row.decision_id}: {row.body}"
            response = self.send(
                sender="dashboard",
                recipient=row.recipient,
                kind="info",
                text=self._summary(relay_text, row.notes_path),
                notes=row.notes_path,
            )
        except DELIVERY_ERRORS:
            self.repo.transition_entry(entry_id, "failed", "sending", "delivery failed")
            return EntryResult(entry_id, "failed", row.notes_path)
        message_id = response.get("id") if isinstance(response, dict) else None
        delivered = self.repo.transition_entry(
            entry_id,
            "delivered",
            "sending",
            "answer delivered",
            [message_id] if message_id else [],
            message_id,
        )
        if delivered:
            self._record_answer(entry_id)
            self.write_back_entry(entry_id)
        else:
            current = self.repo.get_entry_by_id(entry_id)
            return self._entry_result(current or row)
        return EntryResult(entry_id, "delivered", row.notes_path, message_id)

    def retry(self, idempotency_key: str) -> EntryResult:
        row = self.repo.get_entry(idempotency_key)
        if row is None:
            raise KeyError(idempotency_key)
        if row.status not in {"failed", "stored"}:
            return self._entry_result(row)
        message, read_ok = self._find_message(row.notes_path)
        if not read_ok:
            return self._entry_result(row)
        if message is not None:
            message_id = message.get("id")
            delivered = self.repo.transition_entry(
                row.entry_id,
                "delivered",
                row.status,
                "delivery reconciled",
                [message_id] if message_id else [],
                message_id,
            )
            if delivered:
                self._record_answer(row.entry_id)
                self.write_back_entry(row.entry_id)
            else:
                current = self.repo.get_entry_by_id(row.entry_id)
                return self._entry_result(current or row)
            return EntryResult(row.entry_id, "delivered", row.notes_path, message_id)
        return self._deliver_stored(row, "retry started")

    def recover_sending(self) -> list[EntryResult]:
        rows = self.repo.entries_by_status("sending")
        if not rows:
            self.retry_plan_writebacks()
            return []
        try:
            messages = self.read_messages()
        except DELIVERY_ERRORS:
            self.retry_plan_writebacks()
            return [self._entry_result(row) for row in rows]
        results: list[EntryResult] = []
        for row in rows:
            message = next(
                (item for item in messages if item.get("notes") == row.notes_path), None
            )
            if message is None:
                results.append(self._entry_result(row))
                continue
            message_id = message.get("id")
            delivered = self.repo.transition_entry(
                row.entry_id,
                "delivered",
                "sending",
                "delivery recovered",
                [message_id] if message_id else [],
                message_id,
            )
            if delivered:
                self._record_answer(row.entry_id)
            else:
                current = self.repo.get_entry_by_id(row.entry_id)
                results.append(self._entry_result(current or row))
                continue
            results.append(
                EntryResult(row.entry_id, "delivered", row.notes_path, message_id)
            )
        self.retry_plan_writebacks()
        return results

    def retry_plan_writebacks(self) -> None:
        for row in self.repo.writeback_candidates(MAX_PLAN_WRITEBACK_ATTEMPTS):
            self.write_back_entry(row.entry_id)

    def _write_back_entry(self, entry_id: str) -> None:
        if self.write_back is None:
            return
        row = self._entry(entry_id)
        if row is None or row.status != "delivered":
            return
        decision = self.repo.get_decision(row.decision_id)
        if decision is None:
            return
        record = decision.record
        context = record.get("context")
        if not isinstance(context, dict):
            return
        plan_id, question = record.get("plan_id"), context.get("question")
        if (
            not isinstance(plan_id, str)
            or not plan_id
            or not isinstance(question, str)
            or not question
        ):
            return
        decision_type = context.get("type", record.get("kind"))
        resolves = decision_type in {"question", "agent_question"}
        approves = decision_type == "approval" and (
            row.body == "APPROVED" or row.body.startswith("APPROVED:")
        )
        if not resolves and not approves:
            return
        if any(
            audit.new_state == "plan-written"
            and audit.reason.startswith(row.entry_id + ":")
            for audit in self.repo.audit_rows(row.decision_id)
        ):
            return
        try:
            self.write_back(plan_id, question, row.body)
        except DELIVERY_ERRORS as exc:
            self.repo.record_writeback_audit(
                row.decision_id,
                "plan-write-failed",
                row.entry_id,
                f"plan answer write-back failed: {exc}",
            )
            return
        self.repo.record_writeback_audit(
            row.decision_id, "plan-written", row.entry_id, "plan answer written"
        )

    def _find_message(self, notes_path: str) -> tuple[dict[str, Any] | None, bool]:
        try:
            messages = self.read_messages()
        except DELIVERY_ERRORS:
            return None, False
        return next(
            (item for item in messages if item.get("notes") == notes_path), None
        ), True

    def _entry(self, entry_id: str) -> AnswerEntry | None:
        return self.repo.get_entry_by_id(entry_id)

    def _record_answer(self, entry_id: str) -> None:
        if self.recorder is None:
            return
        row = self._entry(entry_id)
        if row is None:
            return
        decision = self.repo.get_decision(row.decision_id)
        if decision is None:
            return
        payload = dict(decision.record)
        payload["answer"] = row.body
        self._record("answered", payload)

    def _record(self, event: str, decision: dict[str, Any]) -> None:
        if self.recorder is None or decision.get("kind") == "permission":
            return
        try:
            self.recorder(event, decision)
        except Exception:
            logger.exception("Could not record decision metric event %s", event)

    @staticmethod
    def _entry_result(row: AnswerEntry) -> EntryResult:
        return EntryResult(
            row.entry_id, row.status, row.notes_path, row.delivery_msg_id
        )

    @staticmethod
    def _summary(body: str, notes: str) -> str:
        fallback = "(long reply, see notes)"
        budget = min(300, max(0, 850 - len(notes.encode("utf-8"))))
        summary = " ".join(body.replace("\r", " ").replace("\n", " ").split())
        output = ""
        for char in summary:
            if len((output + char).encode("utf-8")) > budget:
                break
            output += char
        return output or fallback
