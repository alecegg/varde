"""Persist and project per-agent conversation threads."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import quote

from varde_data.errors import Invalid
from varde_data.records.chat import ChatMessage
from varde_data.records.messages import NoteRef
from varde_data.repos.chat import ChatRepository

from varde_runner.registry import SessionBinding, SessionRegistry

HANDOFF_POLL_SECONDS = 5.0


def plan_for_agent(
    agent: Mapping[str, Any],
    bindings: Mapping[str, SessionBinding],
    sessions: Sequence[Mapping[str, Any]],
    plan_ids: Sequence[str],
) -> str | None:
    """Resolve a plan through its binding, workspace, or launch parent."""
    by_key = _sessions_by_key(sessions)
    direct = _bound_plan(agent, bindings) or _workspace_plan(agent, plan_ids)
    if direct:
        return direct

    parent_id = agent.get("parent_id")
    visited = {str(agent.get("id", agent.get("session_id", "")))}
    while isinstance(parent_id, str) and parent_id and parent_id not in visited:
        visited.add(parent_id)
        parent = by_key.get(parent_id)
        if parent is None:
            return None
        parent_plan = _bound_plan(parent, bindings) or _workspace_plan(parent, plan_ids)
        if parent_plan:
            return parent_plan
        parent_id = parent.get("parent_id")
    return None


def _sessions_by_key(
    sessions: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    return {
        key: row
        for row in sessions
        for key in (str(row.get("id", "")), str(row.get("agent_id", "")))
        if key
    }


def _bound_plan(
    agent: Mapping[str, Any], bindings: Mapping[str, SessionBinding]
) -> str | None:
    session_id = str(agent.get("id", agent.get("session_id", "")))
    binding = bindings.get(session_id)
    return binding.plan_id if binding else None


def _workspace_plan(agent: Mapping[str, Any], plan_ids: Sequence[str]) -> str | None:
    workspace = str(agent.get("workspace_id", agent.get("workspace", "")))
    normalized = workspace.replace("\\", "/").rstrip("/")
    candidates = sorted((item for item in plan_ids if item), key=len, reverse=True)
    for plan_id in candidates:
        if normalized == plan_id or normalized.endswith(f"/{plan_id}"):
            return plan_id
        if f"worktree/{plan_id}-" in normalized:
            return plan_id
        if normalized.startswith(f"{plan_id}-"):
            return plan_id
    return None


class InstanceThreads:
    """Reconcile runner sessions and their durable event logs into chat threads."""

    def __init__(
        self,
        repository: ChatRepository,
        plan_ids: Sequence[str] = (),
        *,
        messages: Any | None = None,
        poll_seconds: float = 1.0,
    ) -> None:
        self.repository = repository
        self.plan_ids = tuple(plan_ids)
        self.messages = messages
        self.poll_seconds = poll_seconds
        self._event_sequences: dict[str, int] = {}
        self._event_sequences_initialized = False
        self._streaming: dict[str, tuple[int, str]] = {}
        self._messages_version: Any | None = None
        self._event_cache: dict[str, set[tuple[str | None, str, str | None]]] = {}
        self._store_change_count: int | None = None
        self._registry_signature: tuple[int, int] | None = None
        self._has_snapshot = False
        self._cached_sessions: list[dict[str, Any]] = []
        self._cached_results: list[dict[str, Any]] = []
        self._last_handoff_poll = 0.0

    async def run(self, get_supervisor: Callable[[], Any]) -> None:
        await asyncio.sleep(self.poll_seconds)
        while True:
            supervisor = get_supervisor()
            if hasattr(supervisor, "__await__"):
                supervisor = await supervisor
            if supervisor is not None:
                await self.refresh(supervisor)
            await asyncio.sleep(self.poll_seconds)

    async def refresh(self, supervisor: Any) -> list[dict[str, Any]]:
        if not self._event_sequences_initialized:
            self._event_sequences.update(self.repository.processed_event_sequences())
            self._event_sequences_initialized = True
        change_count = supervisor.store.change_count()
        registry_path = supervisor.data_dir / "registry.json"
        registry_signature = _file_signature(registry_path)
        if (
            self._has_snapshot
            and change_count == self._store_change_count
            and registry_signature == self._registry_signature
        ):
            self._project_handoffs_if_due(supervisor)
            return self._cached_results

        sessions = supervisor.store.sessions()
        registry = SessionRegistry(registry_path)
        bindings = registry.bindings_by_session_id()
        role_counts: dict[str, int] = {}
        role_totals: dict[str, int] = {}
        for session in sessions:
            role = str(session.get("role") or "other")
            is_visible_role = role != "manager-bot"
            is_live_session = session.get("lifecycle") not in {"archived", "completed"}
            if is_visible_role and is_live_session:
                role_totals[role] = role_totals.get(role, 0) + 1
        results = []
        for session in sessions:
            if session.get("role") == "manager-bot":
                continue
            session_id = str(session["id"])
            agent_id = str(session.get("agent_id") or session_id)
            plan_id = plan_for_agent(session, bindings, sessions, self.plan_ids)
            role = str(session.get("role") or "other")
            role_counts[role] = role_counts.get(role, 0) + 1
            label = _thread_label(agent_id, role, plan_id)
            has_plan_title = role == "orchestrator" and bool(plan_id)
            if role_totals.get(role, 0) > 1 and not has_plan_title:
                label = f"{label} {role_counts[role]}"
            thread_key = f"instance:{agent_id}"
            thread = self.repository.create_thread(
                thread_key,
                agent_id=agent_id,
                plan_id=plan_id,
                label=label,
            )
            if session.get("lifecycle") == "archived":
                thread = self.repository.archive_thread(thread_key)
            events = supervisor.store.events_after(
                session_id, self._event_sequences.get(agent_id, 0)
            )
            if events:
                try:
                    self._project_new_events(thread_key, agent_id, events)
                    cursor = int(events[-1]["seq"])
                    self.repository.save_processed_event_sequence(
                        agent_id, _durable_cursor(cursor, self._streaming.get(agent_id))
                    )
                except Exception:
                    self._streaming.pop(agent_id, None)
                    raise
                self._event_sequences[agent_id] = cursor
            results.append(
                {
                    "thread_key": thread.thread_key,
                    "agent_id": agent_id,
                    "plan_id": thread.plan_id,
                    "role": str(session.get("role") or "other"),
                    "label": thread.label,
                    "state": "archived"
                    if thread.archived_at
                    else str(session.get("lifecycle") or "unknown"),
                    "last_activity": supervisor.store.last_event_at(session_id),
                }
            )
        self._project_handoffs(supervisor, sessions)
        self._store_change_count = supervisor.store.change_count()
        self._registry_signature = registry_signature
        self._has_snapshot = True
        self._cached_sessions = sessions
        self._cached_results = results
        self._last_handoff_poll = time.monotonic()
        return results

    def _project_handoffs_if_due(self, supervisor: Any) -> None:
        now = time.monotonic()
        if now - self._last_handoff_poll < HANDOFF_POLL_SECONDS:
            return
        self._project_handoffs(supervisor, self._cached_sessions)
        self._last_handoff_poll = now

    def _project_handoffs(
        self, supervisor: Any, sessions: Sequence[Mapping[str, Any]]
    ) -> None:
        messages: Any = self.messages
        if callable(messages):
            messages = messages()
        if messages is None:
            return
        version_reader = getattr(messages, "version", None)
        current_version = version_reader() if callable(version_reader) else None
        if current_version is not None and current_version == self._messages_version:
            return
        registry = SessionRegistry(supervisor.data_dir / "registry.json")
        sessions_by_id = {str(row["id"]): row for row in sessions}
        records = messages.read_all().records
        self._messages_version = current_version
        for message in records:
            if message.kind != "info" or message.text.strip() != "handoff":
                continue
            binding = registry.resolve(message.from_)
            session = sessions_by_id.get(binding.session_id) if binding else None
            if session is None or not message.notes:
                continue
            try:
                note = messages.read_note(NoteRef(message.notes))
            except OSError, Invalid, ValueError:
                continue
            summary = next(
                (
                    line.strip()
                    for line in note.splitlines()
                    if line.strip().startswith("Summary:")
                ),
                "",
            )
            if not summary:
                continue
            agent_id = str(session.get("agent_id") or session["id"])
            thread_key = f"instance:{agent_id}"
            self._append_event_once(
                thread_key, ("handoff", summary[:120], message.notes)
            )

    def _project_new_events(
        self, thread_key: str, agent_id: str, events: Sequence[dict[str, Any]]
    ) -> None:
        if not events:
            return
        event_keys = self._known_events(thread_key)
        question_links = {link for kind, _, link in event_keys if kind == "question"}
        active = self._streaming.get(agent_id)
        bot_changes: dict[int, tuple[str, str]] = {}

        for event in events:
            seq = int(event["seq"])
            kind = str(event.get("kind", ""))
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            if kind == "text_delta":
                text = payload.get("text")
                if isinstance(text, str) and text:
                    active = (active[0], active[1] + text) if active else (seq, text)
                    bot_changes[active[0]] = (active[1], "streaming")
            elif kind == "text":
                text = payload.get("text")
                if not isinstance(text, str) or not text:
                    continue
                if active and text.startswith(active[1]):
                    active = (active[0], text)
                    bot_changes[active[0]] = (active[1], "final")
                    active = None
                else:
                    bot_changes[seq] = (text, "final")
            elif kind == "session_end" or (
                kind == "status" and payload.get("status") == "idle"
            ):
                if active:
                    bot_changes[active[0]] = (active[1], "final")
                    active = None
            else:
                projected = _event_row(agent_id, seq, kind, payload)
                if projected is not None and projected not in event_keys:
                    row_kind, _summary, link = projected
                    if row_kind == "question" and link in question_links:
                        continue
                    self._append_event_once(thread_key, projected)
                    if row_kind == "question" and link is not None:
                        question_links.add(link)
        if active:
            bot_changes[active[0]] = (active[1], "streaming")
            self._streaming[agent_id] = active
        else:
            self._streaming.pop(agent_id, None)
        for seq, (text, state) in bot_changes.items():
            self._save_bot(thread_key, agent_id, seq, text, state)

    def _known_events(self, thread_key: str) -> set[tuple[str | None, str, str | None]]:
        if thread_key not in self._event_cache:
            self._event_cache[thread_key] = {
                (row.kind, row.text, row.link)
                for row in _messages(self.repository, thread_key)
                if row.role == "event"
            }
        return self._event_cache[thread_key]

    def _append_event_once(
        self, thread_key: str, event: tuple[str, str, str | None]
    ) -> None:
        event_keys = self._known_events(thread_key)
        kind, text, link = event
        if event in event_keys:
            return
        self.repository.append_event(kind, text, link, thread_key)
        event_keys.add(event)

    def _save_bot(
        self,
        thread_key: str,
        agent_id: str,
        source_event_seq: int,
        text: str,
        state: str,
    ) -> None:
        row = self.repository.append_bot(
            thread_key, agent_id, source_event_seq, text, state=state
        )
        if row.text != text or row.state != state:
            self.repository.update_bot_text(thread_key, row.id, text, state)


def _durable_cursor(last_seq: int, streaming: tuple[int, str] | None) -> int:
    """Resume point that never skips an unfinished turn's first event.

    The streaming accumulator is memory only, so a restart replays the open
    turn from its first event; bot rows are keyed by that event and updated in
    place.
    """
    return streaming[0] - 1 if streaming else last_seq


def _messages(repository: ChatRepository, thread_key: str) -> list[ChatMessage]:
    rows: list[ChatMessage] = []
    before = None
    while True:
        page = repository.page(thread_key, before, 100)
        rows[0:0] = page
        if len(page) < 100:
            return rows
        before = page[0].seq


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _thread_label(agent_id: str, role: str, plan_id: str | None) -> str:
    if role == "orchestrator" and plan_id:
        return f"Orchestrator {plan_id}"
    role_label = role.replace("-", " ").title()
    if role_label == "Other":
        role_label = "Agent"
    return role_label


def _event_row(
    agent_id: str, seq: int, event_kind: str, payload: dict[str, Any]
) -> tuple[str, str, str | None] | None:
    if event_kind in {
        "permission_requested",
        "question_requested",
        "wait_created",
        "awaiting_question",
    }:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return None
        summary = (
            payload.get("summary") or payload.get("question") or payload.get("tool")
        )
        if isinstance(summary, list):
            summary = "; ".join(
                str(item.get("question", ""))
                for item in summary
                if isinstance(item, dict) and item.get("question")
            )
        elif isinstance(summary, dict):
            summary = summary.get("question") or summary.get("title")
        if not isinstance(summary, str):
            summary = None
        text = str(summary or "A response is requested")
        path = f"/api/agents/{quote(agent_id, safe='')}/respond"
        link = f"{path}?request_id={quote(request_id, safe='')}"
        return "question", text, link
    if event_kind in {"permission_resolved", "wait_resolved"}:
        request_id = payload.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return None
        decision = payload.get("decision")
        text = f"Answered: {decision}" if decision else "Answered"
        return "answer", text, f"request:{quote(request_id, safe='')}"
    if event_kind in {"tool_intent", "tool_result"}:
        tool = payload.get("tool") or "tool"
        phase = payload.get("phase") or (
            "started" if event_kind == "tool_intent" else "finished"
        )
        return "agent_log", f"{tool}: {phase}", None
    if event_kind == "handoff":
        summary = payload.get("summary")
        link = payload.get("link")
        if not isinstance(summary, str):
            summary = payload.get("text")
        if isinstance(summary, str):
            summary = next(
                (
                    line.strip()
                    for line in summary.splitlines()
                    if line.strip().startswith("Summary:")
                ),
                "",
            )
        if isinstance(summary, str) and summary:
            return (
                "handoff",
                summary[:120],
                link if isinstance(link, str) else None,
            )
    return None
