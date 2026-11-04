"""Pure work item message synchronization decisions."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from varde_data.errors import NotFound
from varde_data.records.messages import Message, NoteRef
from varde_data.records.workitems import Question
from varde_data.repos.messages import MessageRepository
from varde_data.repos.workitems import WorkItemRepository


def recovery_context(
    questions: Iterable[Question | Mapping[str, Any]],
) -> str:
    rows = list(questions)
    if not rows:
        return ""
    context = [
        {
            "question_id": _field(row, "msg_id"),
            "context": _field(row, "payload"),
            "answer": _field(row, "answer"),
        }
        for row in rows
    ]
    return (
        "Previous mailbox questions and answers (do not duplicate pending questions):\n"
        + json.dumps(context, ensure_ascii=False)
    )


def sync_workitem_message(
    items: WorkItemRepository,
    messages: MessageRepository,
    message: Message,
    address: str,
) -> bool:
    if (
        message.from_ != address
        or not isinstance(message.id, str)
        or message.notes is None
    ):
        return False
    try:
        payload = json.loads(messages.read_note(NoteRef(message.notes)))
    except OSError, UnicodeError, ValueError, NotFound:
        return False
    if not isinstance(payload, dict):
        return False
    item_id = _item_id_for_address(items, address)
    if item_id is None:
        return False
    if payload.get("work_item_event") == "plan_ready":
        plan_path = payload.get("plan_path")
        if not isinstance(plan_path, str) or not Path(plan_path).is_file():
            return False
        items.plan_ready(item_id, plan_path, message.id)
        return True
    if (
        message.kind != "needs-user"
        or payload.get("work_item_event") == "launch_request"
    ):
        return False
    return items.record_question(item_id, message.id, payload)


def _item_id_for_address(items: WorkItemRepository, address: str) -> str | None:
    prefix = "workitem-"
    if not address.startswith(prefix):
        return None
    item_id = address[len(prefix) :]
    try:
        item = items.get(item_id)
    except NotFound:
        return None
    return item.id if address == f"workitem-{item.id[:40]}" else None


def _field(row: Question | Mapping[str, Any], name: str) -> Any:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)
