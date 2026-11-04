"""Ordered, per-thread delivery of accepted chat messages."""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections import defaultdict
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from varde_data.repos.chat import ChatRepository

from varde_runner.chat_projection import project_event
from varde_runner.clients import ClientRole
from varde_runner.supervisor import SendOutcome, Supervisor


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ChatDelivery:
    """Keep accepted rows ordered and retry them while their target is unavailable."""

    def __init__(
        self,
        repository: ChatRepository,
        get_supervisor: Callable[[], Any],
        *,
        retry_seconds: float = 0.1,
        bot_paused: Callable[[], bool] = lambda: False,
        ensure_bot: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self.repository = repository
        self.get_supervisor = get_supervisor
        self.retry_seconds = retry_seconds
        self.bot_paused = bot_paused
        self.ensure_bot = ensure_bot
        self._pending: dict[str, list[Any]] = defaultdict(list)
        self._accepted: set[tuple[str, str]] = set()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._projection_tasks: set[asyncio.Task[None]] = set()
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._closing = False

    async def accept(self, message: Any) -> None:
        key = (message.thread_key, message.id)
        if key in self._accepted:
            return
        self._accepted.add(key)
        pending = self._pending[message.thread_key]
        pending.append(message)
        pending.sort(key=lambda row: row.seq)
        task = self._tasks.get(message.thread_key)
        if task is None or task.done():
            self._tasks[message.thread_key] = asyncio.create_task(
                self._drain(message.thread_key)
            )

    async def start(self) -> None:
        """Resume messages durably queued by a previous runner process."""
        for message in self.repository.pending_user_messages():
            await self.accept(message)

    async def close(self) -> None:
        self._closing = True
        tasks = [*self._tasks.values(), *self._projection_tasks]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _drain(self, thread_key: str) -> None:
        async with self._locks[thread_key]:
            while self._pending[thread_key] and not self._closing:
                message = self._pending[thread_key][0]
                try:
                    sent = await self._send(thread_key, message)
                except KeyError, RuntimeError, OSError:
                    sent = False
                if sent:
                    self.repository.mark_user_delivered(thread_key, message.id)
                    self._pending[thread_key].pop(0)
                    continue
                await asyncio.sleep(self.retry_seconds)
            if not self._pending[thread_key]:
                self._pending.pop(thread_key, None)
                self._tasks.pop(thread_key, None)

    async def _send(self, thread_key: str, message: Any) -> bool:
        thread = self.repository.get_thread(thread_key)
        target_id = thread.agent_id
        if thread.kind == "main":
            bot = self.repository.get_chat_bot(thread_key)
            if bot is None and self.ensure_bot is not None:
                await self.ensure_bot()
                bot = self.repository.get_chat_bot(thread_key)
            if (
                self.bot_paused()
                or bot is None
                or bot.state in {"paused", "unavailable"}
            ):
                return False
            target_id = bot.agent_id
        if not target_id:
            return False

        supervisor: Supervisor = await self.get_supervisor()
        target = supervisor.resolve_session(target_id)
        if target is None:
            return False
        session_id = target["id"]
        session = supervisor.store.get_session(session_id)
        first_event_seq = int(session["last_event_seq"]) + 1 if session else 1
        if thread.kind == "instance" and message.role == "user":
            outcome = await supervisor.send(
                target_id,
                message.text,
                client_id="system:dashboard",
                takeover_holder=True,
            )
        else:
            outcome = await supervisor.send(
                target_id, message.text, client_id="system:dashboard"
            )
        if outcome != SendOutcome.SENT:
            return False
        if thread.kind == "main":
            self.repository.record_turn(thread_key, target_id, first_event_seq, None)
            task = asyncio.create_task(
                self._project_turn(supervisor, thread_key, target_id, first_event_seq)
            )
            self._projection_tasks.add(task)
            task.add_done_callback(self._projection_tasks.discard)
        return True

    async def _project_turn(
        self, supervisor: Supervisor, thread_key: str, agent_id: str, first_seq: int
    ) -> None:
        current_id: str | None = None
        current_text = ""
        client_id = f"chat-projection:{uuid.uuid4().hex}"
        async for item in supervisor.watch(
            agent_id,
            first_seq - 1,
            client_id=client_id,
            role=ClientRole.OBSERVER,
        ):
            for event in _events(item):
                action = project_event(
                    "main",
                    turn_agent_id=agent_id,
                    first_event_seq=first_seq,
                    event=event,
                )
                if action is None:
                    continue
                seq = int(event["seq"])
                if action.action == "delta":
                    if current_id is None:
                        row = self.repository.append_bot(
                            thread_key,
                            agent_id,
                            seq,
                            action.text,
                            state="streaming",
                        )
                        current_id, current_text = row.id, action.text
                    else:
                        current_text += action.text
                        self.repository.update_bot_text(
                            thread_key, current_id, current_text, state="streaming"
                        )
                elif action.action == "text":
                    if current_id is None:
                        self.repository.append_bot(
                            thread_key, agent_id, seq, action.text
                        )
                    else:
                        self.repository.update_bot_text(
                            thread_key, current_id, action.text, state="final"
                        )
                        current_id, current_text = None, ""
                elif current_id is not None:
                    self.repository.update_bot_text(
                        thread_key, current_id, current_text, state="final"
                    )
                    current_id, current_text = None, ""
                self.repository.record_turn(thread_key, agent_id, first_seq, seq)
                if action.action == "finish":
                    return


def _events(item: dict[str, Any]) -> list[dict[str, Any]]:
    if item.get("type") == "event":
        return [item]
    if item.get("type") == "snapshot":
        events = item.get("events")
        if isinstance(events, list):
            return [event for event in events if isinstance(event, dict)]
    return []
