"""Compatibility facade for the shared decision repository."""

from __future__ import annotations

import json
import uuid  # noqa: F401 - compatibility hook for deterministic golden IDs
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.answer_flow import (
    DELIVERY_ERRORS,
    MAX_ENTRY_CHARS,
    MAX_PLAN_WRITEBACK_ATTEMPTS,
    AnswerFlow,
    EntryResult,
)
from varde_data.decisions import open_sqlite_decisions
from varde_data.errors import NotFound
from varde_data.records.decisions import (
    AnswerEntry,
    DecisionProjection,
)

from varde_runner.varde_cli import VardeCLI

__all__ = [
    "MAX_ENTRY_CHARS",
    "MAX_PLAN_WRITEBACK_ATTEMPTS",
    "AnswerEntry",
    "DecisionProjection",
    "DecisionStore",
    "EntryResult",
]


class DecisionStore:
    """Keep the runner API while delegating persistence and delivery to varde-data."""

    def __init__(
        self,
        data_dir: Path,
        *,
        send,
        read_messages=None,
        write_back=None,
        recorder=None,
    ) -> None:
        self.data_dir = data_dir

        def clock() -> datetime:
            return datetime.now(UTC)

        self.clock = clock
        self.repository = open_sqlite_decisions(data_dir, clock)
        self.notes_dir = data_dir / "notes"
        self.audit_path = self.repository.audit_path
        self.send = send
        self.write_back = write_back
        self.recorder = recorder
        self.read_messages = read_messages or VardeCLI().read_messages
        self.flow = AnswerFlow(
            self.repository,
            send,
            self.read_messages,
            write_back=write_back,
            recorder=recorder,
            clock=clock,
        )
        self.flow.write_back_entry = self._dispatch_write_back
        self.lock = self.repository._lock
        # Kept for callers/tests that inspect the backing sqlite connection.
        self.db = self.repository.db

    def dismiss(self, decision_id: str) -> bool:
        return self.repository.dismiss(decision_id)

    def restore(self, decision_id: str) -> bool:
        return self.repository.restore(decision_id)

    def _dispatch_write_back(self, entry_id: str) -> None:
        # Looked up per call so tests can replace `_write_back_entry`.
        self._write_back_entry(entry_id)

    def _write_back_entry(self, entry_id: str) -> None:
        self.flow._write_back_entry(entry_id)

    def _sync_flow_callbacks(self) -> None:
        self.flow.send = self.send
        self.flow.write_back = self.write_back

    def project(self, projection: DecisionProjection) -> None:
        with self.lock:
            decision = self.repository.get_decision(projection.decision_id)
            if decision is not None and decision.state != "pending":
                self.clock()
            self.flow.project(projection)

    def get_decision(self, decision_id: str) -> dict[str, Any] | None:
        decision = self.repository.get_decision(decision_id)
        if decision is None:
            return None
        return {
            "decision_id": decision.decision_id,
            "state": decision.state,
            "source_msg_ids": decision.source_msg_ids,
            "answer_key": decision.answer_key,
            "kind": decision.kind,
            "record_json": json.dumps(decision.record, ensure_ascii=False),
            **decision.record,
        }

    def submit_answer(
        self, decision_id: str, idempotency_key: str, recipient: str, body: str
    ) -> EntryResult:
        with self.lock:
            self._sync_flow_callbacks()
            decision = self.repository.get_decision(decision_id)
            is_new_permission = (
                decision is not None
                and decision.kind == "permission"
                and self.repository.get_entry(idempotency_key) is None
            )
            result = self.flow.submit_answer(
                decision_id, idempotency_key, recipient, body
            )
            if is_new_permission and result.status == "stored":
                return EntryResult(result.entry_id, "stored")
            return result

    def retry(self, idempotency_key: str) -> EntryResult:
        with self.lock:
            self._sync_flow_callbacks()
            row = self.repository.get_entry(idempotency_key)
            if row is None:
                raise KeyError(idempotency_key)
            if row.status not in {"failed", "stored"}:
                return self._entry_result(row)
            try:
                messages = self.read_messages()
            except DELIVERY_ERRORS:
                return self._entry_result(row)
            if any(message.get("notes") == row.notes_path for message in messages):
                return self.flow.retry(idempotency_key)
            try:
                self.repository.write_answer_note(
                    row.entry_id, row.body.encode("utf-8")
                )
            except OSError:
                return self._entry_result(row)
            return self.flow.retry(idempotency_key)

    def resolve_permission(self, entry_id: str, success: bool) -> EntryResult:
        try:
            row = self.repository.resolve_permission(entry_id, success)
        except NotFound as exc:
            raise KeyError(entry_id) from exc
        return EntryResult(
            row.entry_id, row.status, row.notes_path, row.delivery_msg_id
        )

    def recover_sending(self) -> list[EntryResult]:
        with self.lock:
            self._sync_flow_callbacks()
            return self.flow.recover_sending()

    def retry_plan_writebacks(self) -> None:
        with self.lock:
            self._sync_flow_callbacks()
            self.flow.retry_plan_writebacks()

    def get_entry(self, idempotency_key: str) -> AnswerEntry | None:
        return self.repository.get_entry(idempotency_key)

    def permission_entry(self, idempotency_key: str) -> bool:
        return self.repository.permission_entry(idempotency_key)

    def latest_delivered_reply(self, decision_id: str):
        return self.repository.latest_delivered_reply(decision_id)

    def audit_rows(self) -> list[dict[str, Any]]:
        return [asdict(row) for row in self.repository.audit_rows()]

    @staticmethod
    def _entry_result(row: AnswerEntry) -> EntryResult:
        return EntryResult(
            row.entry_id, row.status, row.notes_path, row.delivery_msg_id
        )

    def close(self) -> None:
        self.repository.close()
