"""Thread-safe in-memory work item repository for contracts and tests."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path

from varde_data.errors import Invalid, NotFound
from varde_data.records.workitems import AuditEntry, Question, WorkItem
from varde_data.repos.workitems import validate_new_item
from varde_data.version import Version


class MemoryWorkItems:
    def __init__(self, notes_root: str | Path) -> None:
        self.notes_root = Path(notes_root).resolve()
        self._lock = threading.RLock()
        self._items: dict[str, WorkItem] = {}
        self._keys: dict[str, str] = {}
        self._questions: dict[str, list[Question]] = {}
        self._audit_rows: dict[str, list[AuditEntry]] = {}
        self._version = 0

    def _write(self) -> None:
        self._version += 1

    def _audit(self, item: WorkItem, prior: str | None, new: str, detail: str) -> None:
        rows = self._audit_rows.setdefault(item.id, [])
        rows.append(AuditEntry(len(rows) + 1, item.id, prior, new, detail))

    def create(self, key: str, text: str, project: str) -> WorkItem:
        validate_new_item(key, text, project)
        with self._lock:
            found = self.by_key(key)
            if found is not None:
                return found
            item_id = uuid.uuid4().hex
            note = (self.notes_root / item_id / "request.md").resolve()
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text(text, encoding="utf-8")
            item = WorkItem(item_id, key, text, project, "new", str(note))
            self._items[item_id] = item
            self._keys[key] = item_id
            self._audit(item, None, "new", "submitted")
            self._write()
            return item

    def get(self, item_id: str) -> WorkItem:
        with self._lock:
            try:
                return self._items[item_id]
            except KeyError as exc:
                raise NotFound(item_id) from exc

    def by_key(self, key: str) -> WorkItem | None:
        with self._lock:
            item_id = self._keys.get(key)
            return self._items.get(item_id) if item_id is not None else None

    def list(self) -> list[WorkItem]:
        with self._lock:
            return list(self._items.values())

    def for_planner_session(self, session_id: str) -> WorkItem | None:
        with self._lock:
            return next(
                (
                    item
                    for item in self._items.values()
                    if item.planner_session == session_id
                ),
                None,
            )

    def start_planning(self, item_id: str, session_id: str) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state == "new":
                self._items[item_id] = replace(
                    item, state="planning", planner_session=session_id
                )
                self._audit(item, "new", "planning", "planner started")
                self._write()
            return self.get(item_id)

    def claim_planner_start(self, item_id: str) -> bool:
        with self._lock:
            try:
                item = self.get(item_id)
            except NotFound:
                return False
            if item.state != "new":
                return False
            self._items[item_id] = replace(item, state="planning")
            self._audit(item, "new", "planning", "planner start claimed")
            self._write()
            return True

    def attach_planner(self, item_id: str, session_id: str) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state in {"planning", "asking"}:
                self._items[item_id] = replace(item, planner_session=session_id)
                self._write()
            return self.get(item_id)

    def reset_planner_start(self, item_id: str) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state == "planning" and item.planner_session is None:
                self._items[item_id] = replace(item, state="new")
                self._audit(
                    item, "planning", "new", "planner start recovered for retry"
                )
                self._write()
            return self.get(item_id)

    def fail(self, item_id: str, detail: str) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state not in {"rejected", "failed", "queued"}:
                self._items[item_id] = replace(item, state="failed")
                self._audit(item, item.state, "failed", detail)
                self._write()
            return self.get(item_id)

    def record_question(
        self, item_id: str, msg_id: str, payload: Mapping[str, object]
    ) -> bool:
        with self._lock:
            item = self.get(item_id)
            if item.state not in {"planning", "asking"}:
                raise Invalid("work item is not planning")
            rows = self._questions.setdefault(item_id, [])
            if any(row.msg_id == msg_id for row in rows):
                return False
            rows.append(Question(item_id, msg_id, dict(payload)))
            if item.state == "planning":
                self._items[item_id] = replace(item, state="asking")
                self._audit(item, "planning", "asking", f"question {msg_id}")
            self._write()
            return True

    def answer(self, item_id: str, msg_id: str, text: str, key: str) -> bool:
        with self._lock:
            rows = self._questions.get(item_id, [])
            index = next(
                (i for i, row in enumerate(rows) if row.msg_id == msg_id), None
            )
            if index is None:
                raise NotFound(msg_id)
            row = rows[index]
            if row.answer is not None or row.answer_key is not None:
                return False
            rows[index] = replace(row, answer=text, answer_key=key)
            if all(question.answer is not None for question in rows):
                item = self.get(item_id)
                self._items[item_id] = replace(item, state="planning")
                self._audit(item, "asking", "planning", f"question {msg_id} answered")
            self._write()
            return True

    def plan_ready(self, item_id: str, plan_path: str, message_id: str) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.plan_ready_id:
                return item
            if item.state not in {"planning", "asking"}:
                raise Invalid("work item cannot become ready from its current state")
            self._items[item_id] = replace(
                item, state="ready", plan_path=plan_path, plan_ready_id=message_id
            )
            self._audit(item, item.state, "ready", "plan ready")
            self._write()
            return self.get(item_id)

    def decide(self, item_id: str, approved: bool) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state in {"approved", "rejected", "queued", "failed"}:
                return item
            if item.state != "ready":
                raise Invalid("only a ready plan can be approved or rejected")
            target = "queued" if approved else "rejected"
            self._items[item_id] = replace(item, state=target)
            self._audit(item, "ready", target, "user decision")
            self._write()
            return self.get(item_id)

    def claim_launch_request(self, item_id: str, notes_path: str) -> bool:
        with self._lock:
            item = self.get(item_id)
            if (
                item.state not in {"ready", "queued"}
                or item.launch_request_id is not None
            ):
                return False
            self._items[item_id] = replace(
                item,
                state="queued",
                launch_request_id="sending",
                launch_request_notes=notes_path,
            )
            self._audit(item, "ready", "queued", "launch request claimed")
            self._write()
            return True

    def record_launch_request(
        self, item_id: str, message_id: str, notes_path: str
    ) -> WorkItem:
        with self._lock:
            item = self.get(item_id)
            if item.state == "queued" and item.launch_request_id == "sending":
                self._items[item_id] = replace(
                    item, launch_request_id=message_id, launch_request_notes=notes_path
                )
                self._write()
            return self.get(item_id)

    def release_launch_request(self, item_id: str) -> None:
        with self._lock:
            try:
                item = self.get(item_id)
            except NotFound:
                return
            if item.state == "queued" and item.launch_request_id == "sending":
                self._items[item_id] = replace(item, launch_request_id=None)
                self._write()

    def questions(self, item_id: str) -> list[Question]:
        with self._lock:
            return [
                replace(question, payload=dict(question.payload))
                for question in sorted(
                    self._questions.get(item_id, []),
                    key=lambda question: question.msg_id,
                )
            ]

    def audit(self, item_id: str) -> list[AuditEntry]:
        with self._lock:
            return list(self._audit_rows.get(item_id, []))

    def version(self) -> Version:
        with self._lock:
            return Version(self._version)

    def write_note(self, item_id: str, name: str, text: str) -> str:
        self.get(item_id)
        if not name or name == ".":
            raise Invalid("note name must identify a file")
        target = (self.notes_root / item_id / name).resolve()
        if not target.is_relative_to(self.notes_root / item_id):
            raise Invalid("note path must stay inside the work item")
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            self._write()
        return str(target)

    def owns_note(self, item_id: str, path: str) -> bool:
        try:
            return (
                Path(path)
                .resolve()
                .is_relative_to((self.notes_root / item_id).resolve())
                and self.get(item_id) is not None
            )
        except OSError, NotFound:
            return False
