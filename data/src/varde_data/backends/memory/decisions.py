"""Thread-safe in-memory decision repository for contracts and tests."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable, Iterable
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from varde_data.errors import Invalid, NotFound
from varde_data.records.decisions import (
    AnswerEntry,
    AuditEntry,
    DecisionProjection,
    DecisionRecord,
    DeliveredReply,
    SubmitResult,
)
from varde_data.repos.decisions import (
    MAX_PLAN_WRITEBACK_ATTEMPTS,
    AlreadyAnswered,
    IdempotencyConflict,
    validate_decision_id,
)
from varde_data.version import Version


class MemoryDecisions:
    def __init__(
        self,
        notes_root: str | Path,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.notes_root = Path(notes_root).resolve()
        self.notes_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._clock = clock
        self._decisions: dict[str, DecisionRecord] = {}
        self._entries: dict[str, AnswerEntry] = {}
        self._keys: dict[str, str] = {}
        self._audit: list[AuditEntry] = []
        self._version = 0

    def _write(self) -> None:
        self._version += 1

    def _audit_row(
        self, decision_id: str, prior: str, new: str, reason: str, msg_ids: list[str]
    ) -> None:
        self._audit.append(
            AuditEntry(
                len(self._audit) + 1,
                decision_id,
                prior,
                new,
                "user",
                self._clock().isoformat(),
                reason,
                list(msg_ids),
            )
        )

    def project(self, projection: DecisionProjection) -> bool:
        validate_decision_id(projection.decision_id)
        with self._lock:
            previous = self._decisions.get(projection.decision_id)
            if previous is not None and previous.state != "pending":
                return False
            old = deepcopy(previous.record) if previous else {}
            now = self._clock().isoformat()
            source_ids = list(previous.source_msg_ids) if previous else []
            if projection.source_id and projection.source_id not in source_ids:
                source_ids.append(projection.source_id)
            old.update(
                {
                    "decision_id": projection.decision_id,
                    "kind": projection.kind,
                    "source_agent": projection.source_agent or old.get("source_agent"),
                    "plan_id": projection.plan_id or old.get("plan_id"),
                    "title": projection.title or old.get("title", ""),
                    "body": projection.body or old.get("body", ""),
                    "context": deepcopy(projection.context),
                    "created_at": old.get("created_at", now),
                    "updated_at": now,
                }
            )
            self._decisions[projection.decision_id] = DecisionRecord(
                projection.decision_id,
                "pending",
                source_ids,
                previous.answer_key if previous else None,
                projection.kind,
                old,
            )
            self._write()
            return True

    def get_decision(self, decision_id: str) -> DecisionRecord | None:
        with self._lock:
            decision = self._decisions.get(decision_id)
            return deepcopy(decision)

    def list_decisions(
        self, state: str | None = None, kinds: Iterable[str] | None = None
    ) -> list[DecisionRecord]:
        allowed = set(kinds) if kinds is not None else None
        with self._lock:
            return [
                d
                for d in deepcopy(list(self._decisions.values()))
                if (state is None or d.state == state)
                and (allowed is None or d.kind in allowed)
            ]

    def _move(self, decision_id: str, prior: str, new: str, reason: str) -> bool:
        validate_decision_id(decision_id)
        with self._lock:
            row = self._decisions.get(decision_id)
            if row is None or row.state != prior:
                return False
            self._decisions[decision_id] = replace(row, state=new)
            self._audit_row(decision_id, prior, new, reason, row.source_msg_ids)
            self._write()
            return True

    def dismiss(self, decision_id: str) -> bool:
        return self._move(
            decision_id, "pending", "dismissed", "dismissed from the dashboard"
        )

    def restore(self, decision_id: str) -> bool:
        return self._move(
            decision_id, "dismissed", "pending", "restored from the dashboard"
        )

    def submit_answer(
        self, decision_id: str, idempotency_key: str, recipient: str, body: str
    ) -> SubmitResult:
        with self._lock:
            existing_id = self._keys.get(idempotency_key)
            if existing_id:
                existing = self._entries[existing_id]
                if (existing.decision_id, existing.recipient, existing.body) != (
                    decision_id,
                    recipient,
                    body,
                ):
                    raise IdempotencyConflict(
                        "idempotency key conflicts with stored answer"
                    )
                return SubmitResult(deepcopy(existing), True)
            decision = self._decisions.get(decision_id)
            if decision is None:
                decision = DecisionRecord(decision_id, "pending")
            if decision.state != "pending":
                raise AlreadyAnswered("decision is not pending")
            entry_id = uuid.uuid4().hex
            path = self.notes_path(entry_id)
            row = AnswerEntry(
                entry_id, decision_id, idempotency_key, recipient, body, "stored", path
            )
            self._decisions[decision_id] = replace(
                decision, state="answered", answer_key=idempotency_key
            )
            self._entries[entry_id] = row
            self._keys[idempotency_key] = entry_id
            self._audit_row(
                decision_id,
                "pending",
                "answered",
                "answer stored",
                decision.source_msg_ids,
            )
            self._write()
            return SubmitResult(deepcopy(row), False)

    def transition_entry(
        self,
        entry_id: str,
        new_state: str,
        expected_state: str | set[str],
        reason: str,
        msg_ids: list[str] | None = None,
        delivery_msg_id: str | None = None,
    ) -> bool:
        if not entry_id:
            raise Invalid("entry_id is required")
        with self._lock:
            row = self._entries.get(entry_id)
            expected = (
                {expected_state} if isinstance(expected_state, str) else expected_state
            )
            if row is None or row.status not in expected:
                return False
            decision = self._decisions[row.decision_id]
            linked = list(decision.source_msg_ids)
            if delivery_msg_id and delivery_msg_id not in linked:
                linked.append(delivery_msg_id)
            self._decisions[row.decision_id] = replace(decision, source_msg_ids=linked)
            self._entries[entry_id] = replace(
                row,
                status=new_state,
                delivery_msg_id=delivery_msg_id or row.delivery_msg_id,
            )
            audit_ids = list(linked)
            audit_ids.extend(mid for mid in (msg_ids or []) if mid not in audit_ids)
            self._audit_row(row.decision_id, row.status, new_state, reason, audit_ids)
            self._write()
            return True

    def resolve_permission(self, entry_id: str, success: bool) -> AnswerEntry:
        if not entry_id:
            raise Invalid("entry_id is required")
        with self._lock:
            row = self._entries.get(entry_id)
            if row is None:
                raise NotFound(entry_id)
            if row.status not in {"stored", "failed"}:
                return deepcopy(row)
            state = "delivered" if success else "failed"
            reason = (
                "permission response sent" if success else "permission response failed"
            )
            self.transition_entry(entry_id, state, {"stored", "failed"}, reason)
            decision = self._decisions[row.decision_id]
            if not success and decision.state == "answered":
                self._decisions[row.decision_id] = replace(
                    decision, state="pending", answer_key=None
                )
                self._audit_row(
                    row.decision_id,
                    "answered",
                    "pending",
                    "permission response failed; request remains open",
                    decision.source_msg_ids,
                )
                self._write()
            elif success and decision.state == "pending":
                self._decisions[row.decision_id] = replace(
                    decision, state="answered", answer_key=row.idempotency_key
                )
                self._audit_row(
                    row.decision_id,
                    "pending",
                    "answered",
                    "permission response sent",
                    decision.source_msg_ids,
                )
                self._write()
            return deepcopy(self._entries[entry_id])

    def entries_by_status(self, status: str) -> list[AnswerEntry]:
        with self._lock:
            return deepcopy([e for e in self._entries.values() if e.status == status])

    def get_entry(self, idempotency_key: str) -> AnswerEntry | None:
        with self._lock:
            entry_id = self._keys.get(idempotency_key)
            return deepcopy(self._entries.get(entry_id)) if entry_id else None

    def get_entry_by_id(self, entry_id: str) -> AnswerEntry | None:
        with self._lock:
            return deepcopy(self._entries.get(entry_id))

    def permission_entry(self, idempotency_key: str) -> bool:
        with self._lock:
            entry = self.get_entry(idempotency_key)
            decision = self._decisions.get(entry.decision_id) if entry else None
            return bool(decision and decision.kind == "permission")

    def latest_delivered_reply(self, decision_id: str) -> DeliveredReply | None:
        with self._lock:
            delivered = [
                audit
                for audit in self._audit
                if audit.decision_id == decision_id and audit.new_state == "delivered"
            ]
            if not delivered:
                return None
            entry = next(
                (
                    e
                    for e in reversed(list(self._entries.values()))
                    if e.decision_id == decision_id and e.status == "delivered"
                ),
                None,
            )
            return DeliveredReply(entry.body, delivered[-1].at) if entry else None

    def writeback_candidates(
        self, attempt_cap: int = MAX_PLAN_WRITEBACK_ATTEMPTS
    ) -> list[AnswerEntry]:
        with self._lock:
            candidates = []
            for entry in self._entries.values():
                if entry.status != "delivered":
                    continue
                failures = sum(
                    a.decision_id == entry.decision_id
                    and a.new_state == "plan-write-failed"
                    and a.reason.startswith(entry.entry_id + ":")
                    for a in self._audit
                )
                if (
                    failures > 0
                    and failures < attempt_cap
                    and not any(
                        a.decision_id == entry.decision_id
                        and a.reason.startswith(entry.entry_id + ":")
                        and a.new_state == "plan-written"
                        for a in self._audit
                    )
                ):
                    candidates.append(entry)
            return deepcopy(candidates)

    def record_writeback_audit(
        self, decision_id: str, state: str, entry_id: str, reason: str
    ) -> None:
        validate_decision_id(decision_id)
        with self._lock:
            decision = self._decisions.get(decision_id)
            if decision is None:
                raise NotFound(decision_id)
            self._audit_row(
                decision_id,
                "delivered",
                state,
                f"{entry_id}: {reason}",
                decision.source_msg_ids,
            )
            self._write()

    def audit_rows(self, decision_id: str | None = None) -> list[AuditEntry]:
        with self._lock:
            return deepcopy(
                [
                    a
                    for a in self._audit
                    if decision_id is None or a.decision_id == decision_id
                ]
            )

    def write_answer_note(self, entry_id: str, body: bytes) -> str:
        with self._lock:
            entry = self._entries.get(entry_id)
            if entry is None:
                raise NotFound(entry_id)
            target = Path(entry.notes_path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            self._write()
        return str(target)

    def notes_path(self, entry_id: str) -> str:
        return str((self.notes_root / f"{entry_id}.md").resolve())

    def version(self) -> Version:
        with self._lock:
            return Version(self._version)

    def close(self) -> None:
        return None
