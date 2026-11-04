"""Shared readers for runner and legacy wake bindings."""

from __future__ import annotations

from typing import Any


def wake_agent_id(wake: Any) -> str | None:
    if not isinstance(wake, dict):
        return None
    agent_id = wake.get("agent_id") or wake.get("paseo_id")
    return agent_id if isinstance(agent_id, str) else None
