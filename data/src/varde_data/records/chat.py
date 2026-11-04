"""Chat domain records shared by repository backends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ChatRole = Literal["user", "bot", "event"]
ThreadKind = Literal["main", "instance"]


@dataclass(frozen=True)
class ChatThread:
    thread_key: str
    kind: ThreadKind
    agent_id: str | None
    plan_id: str | None
    label: str | None
    created_at: str
    archived_at: str | None


@dataclass(frozen=True)
class ChatMessage:
    seq: int
    change_seq: int
    id: str
    thread_key: str
    reply_to: str | None
    role: ChatRole
    kind: str | None
    text: str
    link: str | None
    state: str
    source_agent_id: str | None
    source_event_seq: int | None
    created_at: str


@dataclass(frozen=True)
class ChatBot:
    key: str
    agent_id: str
    started_at: str
    context_tokens: int | None
    state: str
    generation: int


@dataclass(frozen=True)
class ChatTurn:
    agent_id: str
    first_event_seq: int
    last_event_seq: int | None


@dataclass(frozen=True)
class Takeover:
    agent_id: str
    holder_client: str
    acquired_at: str
    heartbeat_at: str
    released_at: str | None


@dataclass(frozen=True)
class TakeoverQueueItem:
    id: int
    agent_id: str
    sender: str
    kind: str
    text: str
    queued_at: str
    delivered_at: str | None
    dropped_reason: str | None
    request_id: str | None = None
