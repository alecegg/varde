"""Idempotent inbox projection for decision messages."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any

from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.varde_cli import VardeCLI

NOTES_TEXT_CACHE_LIMIT = 64


def _validated_notes_file(notes: object) -> tuple[Path, os.stat_result] | None:
    if not isinstance(notes, str):
        return None
    try:
        candidate = Path(notes)
        if not candidate.is_absolute():
            return None
        path = Path(os.path.normpath(str(candidate)))
        if any(part.startswith(".") for part in path.parts if part != "/"):
            return None
        if path.suffix.lower() not in {".md", ".json", ".txt"}:
            return None
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.resolve(strict=True) != path:
            return None
    except OSError, RuntimeError, ValueError:
        return None
    return path, metadata


@dataclass(frozen=True)
class InboxItem:
    msg_id: str
    sender: str
    kind: str
    ts: str | None
    plan_id: str | None
    asked: str
    why: str
    options: list[dict[str, str]]
    recommendation: dict[str, str] | str | None
    sources: list[Any]
    needs_context: bool
    to: str = ""
    subject: str = ""
    body: str = ""
    notes_text: str = ""
    type: str = "question"
    approval: str | None = None
    title: str = ""
    evidence: list[dict[str, Any]] | None = None


class InboxProjector:
    def __init__(
        self,
        database: Path,
        *,
        read_messages: Callable[[], list[dict[str, Any]]] | None = None,
        messages_repository: Any = None,
        read_plan: Callable[[], dict[str, Any]] | None = None,
        decision_store: DecisionStore | None = None,
    ) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(database, check_same_thread=False)
        self.db_lock = RLock()
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS inbox_projection ("
            "msg_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
        )
        self.db.commit()
        cli = VardeCLI()
        self.read_messages = read_messages or cli.read_messages
        self.messages_repository = messages_repository
        self.last_messages: list[dict[str, Any]] = []
        self._notes_text_cache: OrderedDict[tuple[str, int, int], str] = OrderedDict()
        self.read_plan = read_plan or cli.read_plan
        self._owns_decision_store = decision_store is None
        self.decision_store = decision_store or DecisionStore(
            database.parent / "decisions",
            send=cli.send,
            read_messages=self.read_messages,
        )

    def project(self) -> list[InboxItem]:
        with self.db_lock:
            return self._project_locked()

    def _project_locked(self) -> list[InboxItem]:
        plan_state = self.read_plan()
        self._project_plan_events(plan_state)
        messages = self.read_messages()
        self.last_messages = messages
        for message in messages:
            msg_id = message.get("id")
            is_watch_merge_notice = (
                message.get("kind") == "merge-ready"
                and message.get("from") == "varde-watch"
            )
            is_user_response = str(message.get("to", "")).lower() == "user"
            is_user_message = str(message.get("from", "")).lower() == "user"
            projectable = not is_watch_merge_notice and (
                message.get("kind")
                in {
                    "needs-user",
                    "needs-decision",
                    "merge-ready",
                    "permission",
                    "info-failure",
                }
                or is_user_response
                or is_user_message
            )
            if not projectable:
                if msg_id:
                    self.db.execute(
                        "DELETE FROM inbox_projection WHERE msg_id=?", (msg_id,)
                    )
                continue
            if not msg_id:
                continue
            existing = self.db.execute(
                "SELECT payload FROM inbox_projection WHERE msg_id=?", (msg_id,)
            ).fetchone()
            previous = json.loads(existing["payload"]) if existing else None
            if (
                previous
                and not previous["needs_context"]
                and previous.get("kind") == message.get("kind")
                and "ts" in previous
            ):
                continue
            context = self._read_context(message.get("notes"))
            message_text = message.get("text") or message.get("body") or ""
            asked = context.get("asked", "")
            why = context.get("why", "")
            options = context.get("options", [])
            decision_type = context.get("type", "question")
            if is_user_response and message.get("kind") not in {
                "needs-user",
                "needs-decision",
                "merge-ready",
                "permission",
            }:
                decision_type = "info"
            if is_user_message:
                decision_type = "info"
            if message.get("kind") == "merge-ready":
                decision_type = context.get("type", "approval")
                asked = asked or message_text
                why = why or "The plan is ready for a merge decision."
            if message.get("kind") == "info-failure":
                decision_type = "info"
            if decision_type == "approval":
                options = [
                    {"id": "approve", "label": "Approve"},
                    {"id": "hold", "label": "Hold"},
                    {"id": "ask-more", "label": "Ask more"},
                ]
            complete = decision_type == "info" or (
                isinstance(asked, str)
                and bool(asked.strip())
                and isinstance(why, str)
                and bool(why.strip())
                and isinstance(options, list)
                and bool(options)
            )
            payload = {
                "msg_id": msg_id,
                "sender": message.get("from", ""),
                "to": message.get("to", ""),
                "kind": message.get("kind", "needs-user"),
                "ts": message.get("ts"),
                "plan_id": context.get("plan_id"),
                "asked": asked if isinstance(asked, str) else "",
                "subject": message.get("subject") or "",
                "body": message_text if isinstance(message_text, str) else "",
                "notes_text": (
                    self._read_notes_text(message.get("notes")) if not complete else ""
                ),
                "why": why if isinstance(why, str) else "",
                "options": options if isinstance(options, list) else [],
                "recommendation": context.get("recommendation"),
                "sources": context.get("sources", []),
                "type": decision_type,
                "approval": context.get("approval"),
                "title": context.get("title") or asked,
                "evidence": _project_evidence(context.get("evidence")),
                "needs_context": not complete,
            }
            self.db.execute(
                """
                INSERT INTO inbox_projection(msg_id, payload) VALUES (?, ?)
                ON CONFLICT(msg_id) DO UPDATE SET payload=excluded.payload
                """,
                (msg_id, json.dumps(payload, ensure_ascii=False)),
            )
            decision_kind = decision_type
            if message.get("kind") == "permission":
                decision_kind = "permission"
            elif message.get("kind") == "info-failure":
                decision_kind = "info"
            if decision_kind == "question":
                decision_kind = "agent_question"
            self.decision_store.project(
                DecisionProjection(
                    source_id=msg_id,
                    decision_id=msg_id,
                    kind=decision_kind,
                    source_agent=payload["sender"],
                    plan_id=payload["plan_id"],
                    title=payload["title"]
                    or payload["asked"]
                    or str(message.get("text", "")),
                    body=str(message.get("text", "")),
                    context={
                        "asked": payload["asked"],
                        "why": payload["why"],
                        "options": payload["options"],
                        "recommendation": payload["recommendation"],
                        "sources": payload["sources"],
                        "needs_context": payload["needs_context"],
                        "type": payload["type"],
                        "source_kind": payload["kind"],
                        "approval": payload["approval"],
                        "title": payload["title"],
                        "evidence": payload["evidence"],
                        **(
                            {"question": context["question"]}
                            if isinstance(context.get("question"), str)
                            else {}
                        ),
                    },
                )
            )
        self.db.commit()
        self.decision_store.retry_plan_writebacks()
        return [
            InboxItem(**json.loads(row[0]))
            for row in self.db.execute(
                "SELECT payload FROM inbox_projection ORDER BY rowid"
            )
        ]

    def _project_plan_events(self, plan_state: dict[str, Any]) -> None:
        # These rows remain in decision history but never render in the mailbox.
        events = plan_state.get("events", [])
        if not isinstance(events, list):
            return
        kinds = {
            "blocked": "blocked",
            "needs-decision": "agent_question",
            "merge-ready": "merge_ready",
        }
        for event in events:
            if not isinstance(event, dict):
                continue
            event_kind = event.get("kind")
            if not isinstance(event_kind, str):
                continue
            decision_kind = kinds.get(event_kind)
            plan_id = event.get("plan")
            if not decision_kind or not isinstance(plan_id, str) or not plan_id:
                continue
            detail = str(event.get("detail", ""))
            source_id = f"plan-watch:{plan_id}:{event_kind}"
            decision_id = f"{plan_id}:{event_kind}"
            self.decision_store.project(
                DecisionProjection(
                    source_id=source_id,
                    decision_id=decision_id,
                    kind=decision_kind,
                    plan_id=plan_id,
                    source_agent=event.get("owner"),
                    title=f"{event_kind} in {plan_id}",
                    body=detail,
                    context={
                        "asked": detail,
                        "why": "Plan state needs review",
                        "options": [],
                        "sources": [source_id],
                        "needs_context": True,
                    },
                )
            )

    @staticmethod
    def _read_context(notes: object) -> dict[str, Any]:
        if not isinstance(notes, str):
            return {}
        try:
            with Path(notes).open(encoding="utf-8") as stream:
                loaded = json.loads(stream.read(20_000))
            return loaded if isinstance(loaded, dict) else {}
        except OSError, UnicodeError, json.JSONDecodeError:
            return {}

    def _read_notes_text(self, notes: object) -> str:
        validated = _validated_notes_file(notes)
        if validated is None:
            return ""
        path, metadata = validated

        key = (str(path), metadata.st_mtime_ns, metadata.st_size)
        if key in self._notes_text_cache:
            self._notes_text_cache.move_to_end(key)
            return self._notes_text_cache[key]
        try:
            with path.open(encoding="utf-8") as stream:
                text = stream.read(20_000)
        except OSError, UnicodeError:
            return ""
        if any(
            character == "\x00" or (ord(character) < 32 and character not in "\t\n\r")
            for character in text
        ):
            text = ""
        for old_key in tuple(self._notes_text_cache):
            if old_key[0] == key[0] and old_key != key:
                del self._notes_text_cache[old_key]
        self._notes_text_cache[key] = text
        while len(self._notes_text_cache) > NOTES_TEXT_CACHE_LIMIT:
            self._notes_text_cache.popitem(last=False)
        return text

    def row_count(self) -> int:
        return int(
            self.db.execute("SELECT count(*) FROM inbox_projection").fetchone()[0]
        )

    def close(self) -> None:
        self.db.close()
        if self._owns_decision_store:
            self.decision_store.close()


def _project_evidence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed_keys = {"kind", "caption", "path", "text"}
    return [
        {key: entry[key] for key in allowed_keys if key in entry}
        for entry in value
        if isinstance(entry, dict)
    ]
