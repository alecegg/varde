from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from varde_data.backends.memory.workitems import MemoryWorkItems
from varde_data.errors import NotFound
from varde_data.records.messages import Message, NoteRef
from varde_data.repos.messages import MessageRepository
from varde_data.workitem_sync import recovery_context, sync_workitem_message


class Notes:
    def __init__(self, notes: dict[str, str]) -> None:
        self.notes = notes

    def read_note(self, ref: NoteRef) -> str:
        try:
            return self.notes[str(ref)]
        except KeyError as exc:
            raise NotFound(str(ref)) from exc


def test_recovery_context_preserves_store_format() -> None:
    assert recovery_context([]) == ""
    questions = [{"msg_id": "q1", "payload": {"asked": "Choose?"}, "answer": "A"}]
    assert recovery_context(questions) == (
        "Previous mailbox questions and answers (do not duplicate pending questions):\n"
        '[{"question_id": "q1", "context": {"asked": "Choose?"}, "answer": "A"}]'
    )


def test_question_sync_uses_message_repository_note_reader(tmp_path: Path) -> None:
    items = MemoryWorkItems(tmp_path / "notes")
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    message = Message(
        "now", address, "main", "needs-user", "question", "note.json", "q1"
    )
    messages = cast(
        "MessageRepository", Notes({"note.json": json.dumps({"asked": "Choose?"})})
    )
    assert sync_workitem_message(items, messages, message, address)
    assert items.questions(item.id)[0].payload == {"asked": "Choose?"}


def test_plan_ready_sync_requires_existing_plan_file(tmp_path: Path) -> None:
    items = MemoryWorkItems(tmp_path / "notes")
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    plan = tmp_path / "plan.md"
    plan.write_text("Plan", encoding="utf-8")
    message = Message("now", address, "main", "done", "ready", "note.json", "ready1")
    messages = cast(
        "MessageRepository",
        Notes(
            {
                "note.json": json.dumps(
                    {"work_item_event": "plan_ready", "plan_path": str(plan)}
                )
            }
        ),
    )
    assert sync_workitem_message(items, messages, message, address)
    assert items.get(item.id).plan_ready_id == "ready1"


def test_sync_ignores_invalid_messages_and_missing_notes(tmp_path: Path) -> None:
    items = MemoryWorkItems(tmp_path / "notes")
    item = items.create("key", "request", "project")
    items.start_planning(item.id, "planner")
    address = f"workitem-{item.id[:40]}"
    message = Message("now", address, "main", "needs-user", "question", "missing", "q1")
    messages = cast("MessageRepository", Notes({}))
    assert not sync_workitem_message(items, messages, message, address)

    payloads = {
        "wrong.json": json.dumps({"asked": "ignored"}),
        "launch.json": json.dumps({"work_item_event": "launch_request"}),
        "list.json": "[]",
        "plan.json": json.dumps(
            {"work_item_event": "plan_ready", "plan_path": str(tmp_path / "absent")}
        ),
    }
    messages = cast("MessageRepository", Notes(payloads))
    for note in payloads:
        candidate = Message(
            "now",
            "someone-else" if note == "wrong.json" else address,
            "main",
            "needs-user",
            "question",
            note,
            note,
        )
        assert not sync_workitem_message(items, messages, candidate, address)
    assert items.questions(item.id) == []
