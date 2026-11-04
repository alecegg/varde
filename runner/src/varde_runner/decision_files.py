"""Project decision files.

Dashboard answers store choice, ts, and idempotency key in ``answered``.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from varde_core.decision_files import DECISION_FILE_TYPES
from varde_data.views import classify_status


def decision_file_items(
    plans: list[dict[str, Any]],
    mail_items: list[dict[str, Any]],
    mail_messages: list[dict[str, Any]] | None = None,
    acknowledged_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return open decision files for live plans, excluding mail duplicates."""
    result = project_decision_files(plans)
    return dedupe_decision_file_items(
        result, mail_items, mail_messages or [], acknowledged_ids or set()
    )


def project_decision_files(
    plans: list[dict[str, Any]], *, include_answered: bool = False
) -> list[dict[str, Any]]:
    """Read unanswered decision files from plan records."""
    result = []
    for plan in plans:
        if classify_status(str(plan.get("status", ""))) == "terminal":
            continue
        directory = plan.get("directory")
        owner = plan.get("assigned_to")
        if not isinstance(directory, Path) or not isinstance(owner, str) or not owner:
            continue
        for path in directory.rglob("*.json"):
            item = _decision_file_item(path, plan, owner, include_answered)
            if item is None:
                continue
            result.append(item)
    return result


def _decision_file_item(
    path: Path, plan: dict[str, Any], owner: str, include_answered: bool = False
) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError, json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or value.get("type") not in DECISION_FILE_TYPES:
        return None
    answer_record = value.get("answered")
    if (value.get("answer") or answer_record) and (
        not include_answered or not isinstance(answer_record, dict)
    ):
        return None
    options = value.get("options")
    if not isinstance(options, list) or not options:
        return None
    try:
        modified = path.stat().st_mtime
    except OSError:
        return None
    identifier = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
    return {
        "msg_id": f"file-{identifier}",
        "sender": owner,
        "kind": "needs-user",
        "state": "answered" if isinstance(answer_record, dict) else "pending",
        "type": value["type"],
        "asked": value.get("title") or value.get("asked") or path.stem,
        "why": value.get("why", ""),
        "options": options,
        "recommendation": value.get("recommendation"),
        "notes": str(path.resolve()),
        "plan_id": plan.get("id"),
        "_plan_directory": str(plan.get("directory", "")),
        "_answer_record": answer_record if isinstance(answer_record, dict) else None,
        "agent_title": owner,
        "ts": value.get("created_at") or modified,
    }


def _referenced_notes(
    mail_items: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    acknowledged_ids: set[str],
) -> set[str]:
    referenced = set()
    for item in mail_items:
        notes = item.get("notes")
        if isinstance(notes, str) and notes:
            referenced.add(_mail_note_key(notes))
    for message in messages:
        notes = message.get("notes")
        if not isinstance(notes, str) or not notes:
            continue
        if (
            message.get("answer")
            or message.get("reply")
            or (message.get("from") == "main" and message.get("kind") == "info")
            or message.get("state") in {"answered", "replied"}
            or str(message.get("id", "")) in acknowledged_ids
        ):
            referenced.add(_mail_note_key(notes))
    return referenced


def _notes_match(path: Path, base: Path, mail_notes: set[str]) -> bool:
    return (
        _normalized_path(path, base) in mail_notes
        or f"relative:{path.relative_to(base).as_posix()}" in mail_notes
    )


def dedupe_decision_file_items(
    file_items: list[dict[str, Any]],
    mail_items: list[dict[str, Any]],
    mail_messages: list[dict[str, Any]],
    acknowledged_ids: set[str],
) -> list[dict[str, Any]]:
    mail_notes = _referenced_notes(mail_items, mail_messages, acknowledged_ids)
    result = []
    for item in file_items:
        notes = item.get("notes")
        base = item.get("_plan_directory")
        if not isinstance(notes, str) or not isinstance(base, str):
            continue
        if item.get("state") != "answered" and _notes_match(
            Path(notes), Path(base), mail_notes
        ):
            continue
        result.append(
            {
                key: value
                for key, value in item.items()
                if key not in {"_plan_directory", "_answer_record"}
            }
            | (
                {"answer_record": item["_answer_record"]}
                if item.get("state") == "answered"
                else {}
            )
        )
    return result


def _mail_note_key(notes: str) -> str:
    path = Path(notes)
    if path.is_absolute():
        return _normalized_path(path)
    return f"relative:{os.path.normpath(path.as_posix())}"


def _normalized_path(path: Path, base: Path | None = None) -> str:
    if not path.is_absolute() and base is not None:
        path = base / path
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())
