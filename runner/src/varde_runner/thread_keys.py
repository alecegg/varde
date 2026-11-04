"""Pure parsing helpers for chat thread keys."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_AGENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


@dataclass(frozen=True)
class ThreadKey:
    key: str
    kind: Literal["main", "instance"]
    agent_id: str | None = None


def parse_thread_key(value: object) -> ThreadKey | None:
    """Parse a supported thread key, returning None for malformed keys."""
    if value == "main":
        return ThreadKey("main", "main")
    if not isinstance(value, str) or not value.startswith("instance:"):
        return None
    agent_id = value.removeprefix("instance:")
    if not _AGENT_ID.fullmatch(agent_id) or agent_id in {".", ".."}:
        return None
    return ThreadKey(value, "instance", agent_id)
