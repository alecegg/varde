"""Normalized provider event envelope."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

EventKind = Literal[
    "status",
    "text",
    "text_delta",
    "tool",
    "tool_intent",
    "tool_result",
    "usage",
    "permission_requested",
    "permission_resolved",
    "wait_created",
    "wait_resolved",
    "session_end",
    "error",
    "resume",
    "parked",
    "activity",
    "question_requested",
]
SessionStatus = Literal["idle", "running", "error"]


@dataclass(frozen=True, slots=True)
class RunnerEvent:
    kind: EventKind
    session_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    provider_id: str = "unknown"
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    raw_event_ref: str | None = None
