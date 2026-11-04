"""SessionStart `memory` provider: the memory pointer and index lines (no bodies)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def agent_from_payload(payload: Any) -> str | None:
    """The harness-provided `agent_type` (Claude Code SessionStart, SubagentStart)."""
    value = payload.get("agent_type") if isinstance(payload, dict) else None
    return value if isinstance(value, str) and value.strip() else None


def role_of_address(address: str | None) -> str | None:
    """Role of a bound address: `<role>:<q>`, `<q>-<role>` or `<role>`."""
    if not address:
        return None
    if ":" in address:
        return address.split(":", 1)[0] or None
    return address.rsplit("-", 1)[-1] or None


def role_agent_names(role: str | None) -> tuple[str, ...] | None:
    """Agent entries may be keyed `<role>` or `varde-<role>`; try both."""
    return (role, f"varde-{role}") if role else None


def agent_name(harness: str, raw: bytes) -> str | tuple[str, ...] | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if (named := agent_from_payload(payload)) is not None:
        return named
    session_id = payload.get("session_id") if isinstance(payload, dict) else None
    if not session_id:
        return None
    from .inbox_hook import resolve_address, runner_on

    if not runner_on():
        return None
    return role_agent_names(role_of_address(resolve_address(harness, session_id)))


def pointer_text(cwd: Path, agent: str | tuple[str, ...] | None) -> str:
    """Pointer section for a session start; empty when no entry applies."""
    from varde_learn.knowledge.memory_config import load_config
    from varde_learn.memory import share, store
    from varde_learn.memory.surface import render_surface

    root, project = store.memory_root_and_project(cwd)
    entries = list(store.load_entries(root))
    shared = share.load_shared()
    if not entries and not shared:
        return ""
    text, _ = render_surface(
        entries,
        agent=agent,
        skill=None,
        project=project,
        budget=load_config().memory.budget_chars()[0],
        root=str(root),
        shared=shared,
    )
    return text if "\n" in text else ""


def memory_section(harness: str, raw: bytes) -> str:
    return pointer_text(Path.cwd(), agent_name(harness, raw))
