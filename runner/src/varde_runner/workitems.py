"""Compatibility facade for the shared work item repository."""

from __future__ import annotations

import uuid  # noqa: F401 - compatibility hook for deterministic golden IDs
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.errors import Invalid, NotFound
from varde_data.open import open_data
from varde_data.records.messages import Message
from varde_data.records.workitems import WorkItem
from varde_data.repos.workitems import MAX_TEXT_LENGTH
from varde_data.workitem_sync import recovery_context, sync_workitem_message
from varde_data.workitems import open_workitems

__all__ = ["MAX_TEXT_LENGTH", "WorkItemStore"]


class WorkItemStore:
    """Preserve the runner API while storing state in ``varde-data``."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.repository = open_workitems(data_dir)
        self._messages_repository = None

    @property
    def messages_repository(self):
        if self._messages_repository is None:
            self._messages_repository = open_data(
                self.data_dir, load_data_config()
            ).messages
        return self._messages_repository

    def item_notes_dir(self, item_id: str) -> Path:
        """Compatibility path helper for callers reading existing item notes."""
        path = self.data_dir / "workitem-notes" / item_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def create(self, key: str, text: str, project: str) -> WorkItem:
        try:
            return self.repository.create(key, text, project)
        except Invalid as exc:
            raise ValueError(str(exc)) from exc

    def start_planning(self, item_id: str, session_id: str) -> WorkItem:
        return self._get(self.repository.start_planning, item_id, session_id)

    def claim_planner_start(self, item_id: str) -> bool:
        return self._get(self.repository.claim_planner_start, item_id)

    def attach_planner(self, item_id: str, session_id: str) -> WorkItem:
        return self._get(self.repository.attach_planner, item_id, session_id)

    def reset_planner_start(self, item_id: str) -> WorkItem:
        return self._get(self.repository.reset_planner_start, item_id)

    def for_planner_session(self, session_id: str) -> WorkItem | None:
        return self.repository.for_planner_session(session_id)

    def fail(self, item_id: str, detail: str) -> WorkItem:
        return self._get(self.repository.fail, item_id, detail)

    def question(self, item_id: str, msg_id: str, payload: dict[str, Any]) -> bool:
        try:
            return self.repository.record_question(item_id, msg_id, payload)
        except Invalid as exc:
            raise ValueError(str(exc)) from exc

    def sync_message(self, message: dict[str, Any], address: str) -> bool:
        """Compatibility shim for syncing a message in facade-based callers."""
        message_id = message.get("id")
        sender = message.get("from")
        notes = message.get("notes")
        if not isinstance(message_id, str) or not isinstance(sender, str):
            return False
        typed = Message(
            ts=str(message.get("ts", "")),
            from_=sender,
            to=str(message.get("to", "")),
            kind=str(message.get("kind", "")),
            text=str(message.get("text", "")),
            notes=notes if isinstance(notes, str) else None,
            id=message_id,
        )
        try:
            return sync_workitem_message(
                self.repository, self.messages_repository, typed, address
            )
        except Invalid as exc:
            raise ValueError(str(exc)) from exc

    def recovery_context(self, item_id: str) -> str:
        return recovery_context(self._get(self.repository.questions, item_id))

    def answer(self, item_id: str, msg_id: str, text: str, key: str) -> bool:
        return self._get(self.repository.answer, item_id, msg_id, text, key)

    def plan_ready(self, item_id: str, plan_path: Path, message_id: str) -> WorkItem:
        return self._get(
            self.repository.plan_ready, item_id, str(plan_path), message_id
        )

    def decide(self, item_id: str, approved: bool) -> WorkItem:
        return self._get(self.repository.decide, item_id, approved)

    def record_launch_request(
        self, item_id: str, message_id: str, notes_path: Path
    ) -> WorkItem:
        return self._get(
            self.repository.record_launch_request,
            item_id,
            message_id,
            str(notes_path),
        )

    def release_launch_request(self, item_id: str) -> None:
        self.repository.release_launch_request(item_id)

    def claim_launch_request(self, item_id: str, notes_path: Path) -> bool:
        return self._get(self.repository.claim_launch_request, item_id, str(notes_path))

    def reject(self, item_id: str) -> WorkItem:
        return self.decide(item_id, False)

    def get(self, item_id: str) -> WorkItem:
        return self._get(self.repository.get, item_id)

    def by_key(self, key: str) -> WorkItem | None:
        return self.repository.by_key(key)

    def list(self) -> list[WorkItem]:
        return self.repository.list()

    def questions(self, item_id: str) -> list[dict[str, Any]]:
        return [asdict(row) for row in self._get(self.repository.questions, item_id)]

    def audit(self, item_id: str) -> list[dict[str, Any]]:
        return [asdict(row) for row in self._get(self.repository.audit, item_id)]

    def write_note(self, item_id: str, name: str, text: str) -> str:
        return self._get(self.repository.write_note, item_id, name, text)

    def owns_note(self, item_id: str, path: str) -> bool:
        return self._get(self.repository.owns_note, item_id, path)

    def close(self) -> None:
        for repository in (self.repository, self._messages_repository):
            close = getattr(repository, "close", None)
            if close is not None:
                close()

    @staticmethod
    def _get(operation, *args):
        try:
            return operation(*args)
        except NotFound as exc:
            missing = str(exc).split(":", 1)[-1].strip().strip("'")
            raise KeyError(missing or str(exc)) from exc
        except Invalid as exc:
            raise ValueError(str(exc)) from exc
