"""Backend-neutral chat repository API."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from varde_data.records.chat import (
    ChatBot,
    ChatMessage,
    ChatThread,
    ChatTurn,
    Takeover,
    TakeoverQueueItem,
)


class ChatRepository(Protocol):
    def append_user(
        self, thread_key: str, message_id: str, text: str, reply_to: str | None = None
    ) -> ChatMessage: ...

    def append_user_once(
        self, thread_key: str, message_id: str, text: str, reply_to: str | None = None
    ) -> tuple[ChatMessage, bool]: ...

    def pending_user_messages(self) -> Sequence[ChatMessage]: ...

    def mark_user_delivered(self, thread_key: str, message_id: str) -> bool: ...

    def append_bot(
        self,
        thread_key: str,
        source_agent_id: str,
        source_event_seq: int,
        text: str,
        state: str = "final",
    ) -> ChatMessage: ...

    def update_bot_text(
        self, thread_key: str, message_id: str, text: str, state: str | None = None
    ) -> ChatMessage: ...

    def append_event(
        self, kind: str, summary: str, link: str | None, thread_key: str = "main"
    ) -> ChatMessage: ...

    def page(
        self, thread_key: str, before: int | None = None, limit: int = 50
    ) -> Sequence[ChatMessage]: ...

    def latest_bot_event_sequences(self) -> dict[str, int]: ...

    def processed_event_sequences(self) -> dict[str, int]: ...

    def save_processed_event_sequence(self, agent_id: str, sequence: int) -> None: ...

    def changes_after(
        self, thread_key: str, change_seq: int
    ) -> Sequence[ChatMessage]: ...

    def create_thread(
        self,
        thread_key: str,
        kind: str = "instance",
        agent_id: str | None = None,
        plan_id: str | None = None,
        label: str | None = None,
    ) -> ChatThread: ...

    def get_thread(self, thread_key: str) -> ChatThread: ...

    def archive_thread(
        self, thread_key: str, archived_at: str | None = None
    ) -> ChatThread: ...

    def set_chat_bot(
        self,
        thread_key: str,
        agent_id: str,
        started_at: str,
        context_tokens: int | None,
        state: str,
        generation: int,
    ) -> ChatBot: ...

    def get_chat_bot(self, thread_key: str) -> ChatBot | None: ...

    def record_turn(
        self,
        thread_key: str,
        agent_id: str,
        first_event_seq: int,
        last_event_seq: int | None,
    ) -> ChatTurn: ...

    def acquire(
        self, thread_key: str, holder_client: str, now: str
    ) -> Takeover | None: ...

    def get_takeover(self, thread_key: str) -> Takeover | None: ...

    def heartbeat(self, thread_key: str, holder_client: str, now: str) -> bool: ...

    def release(self, thread_key: str, holder_client: str, now: str) -> bool: ...

    def enqueue(
        self,
        thread_key: str,
        sender: str,
        kind: str,
        text: str,
        queued_at: str,
        request_id: str | None = None,
    ) -> TakeoverQueueItem: ...

    def next_queued(self, thread_key: str) -> TakeoverQueueItem | None: ...

    def queued_count(self, thread_key: str) -> int: ...

    def mark_delivered(
        self, thread_key: str, queue_id: int, send_outcome: str, delivered_at: str
    ) -> bool: ...

    def drop(self, thread_key: str, queue_id: int, reason: str) -> bool: ...


__all__ = ["ChatRepository"]
