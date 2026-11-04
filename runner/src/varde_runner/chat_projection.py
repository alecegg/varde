"""Project runner output into persisted chat messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class Projection:
    action: Literal["delta", "text", "finish"]
    text: str = ""


def project_event(
    thread_kind: str,
    *,
    turn_agent_id: str,
    first_event_seq: int,
    event: dict[str, Any],
) -> Projection | None:
    """Return a projection action only for events inside a chat-owned main turn."""
    if thread_kind != "main" or event.get("seq", 0) < first_event_seq:
        return None
    if event.get("agent_id", turn_agent_id) != turn_agent_id:
        return None

    kind = event.get("kind")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return None
    if kind in {"text", "text_delta"}:
        text = payload.get("text")
        if isinstance(text, str) and text:
            return Projection("text" if kind == "text" else "delta", text)
    if kind == "session_end" or (kind == "status" and payload.get("status") == "idle"):
        return Projection("finish")
    return None
