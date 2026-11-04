"""SubagentStart `memory` provider: the pointer for the subagent that is starting."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .memory_hook import agent_from_payload, pointer_text, role_agent_names

PREFIX = "varde-"


def subagent_names(agent_type: str) -> tuple[str, ...]:
    """Agent entries keyed `<name>` or `varde-<name>`: both match the agent type."""
    names = role_agent_names(agent_type.removeprefix(PREFIX))
    return names or ()


def subagent_section(raw: bytes) -> str:
    """Pointer text for the payload's `agent_type`; empty without one."""
    try:
        payload: Any = json.loads(raw)
    except ValueError:
        return ""
    agent_type = agent_from_payload(payload)
    if agent_type is None:
        return ""
    cwd = payload.get("cwd")
    return pointer_text(
        Path(cwd) if isinstance(cwd, str) and cwd else Path.cwd(),
        subagent_names(agent_type),
    )
