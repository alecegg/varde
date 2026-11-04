"""Pure detection of permission requests that write agent memory."""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import PurePath
from typing import Any, Literal, TypedDict

Tier = Literal["user", "project", "role"]


class MemoryTierResult(TypedDict):
    outcome: Literal["decide", "flag"]
    target_tier: Tier | None
    reason: str


_MEMORY_ROOT = re.compile(r"(?:^|[/\\])agent-memory(?:[/\\]|$)", re.IGNORECASE)
_TIER_ROOTS: dict[str, Tier] = {
    "general": "user",
    "user": "user",
    "users": "user",
    "projects": "project",
    "project": "project",
    "agents": "role",
    "roles": "role",
}


def _path_values(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"path", "file_path", "directory", "target"}:
                if isinstance(child, str):
                    yield child
                elif isinstance(child, list):
                    yield from (item for item in child if isinstance(item, str))
            yield from _path_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _path_values(child)


def _tier_for_path(value: str) -> Tier | None:
    normalized = value.replace("\\", "/")
    match = _MEMORY_ROOT.search(normalized)
    if match is None:
        return None
    suffix = normalized[match.end() :]
    first = PurePath(suffix).parts[0].lower() if PurePath(suffix).parts else ""
    return _TIER_ROOTS.get(first)


def classify_memory_write(payload: dict[str, Any]) -> MemoryTierResult | None:
    """Classify an agent-memory target, or return None for unrelated requests."""
    for path in _path_values(payload):
        if not _MEMORY_ROOT.search(path.replace("\\", "/")):
            continue
        tier = _tier_for_path(path)
        if tier is None:
            return {
                "outcome": "flag",
                "target_tier": None,
                "reason": "agent-memory path has an unclear tier",
            }
        return {
            "outcome": "decide",
            "target_tier": tier,
            "reason": f"agent-memory path belongs to the {tier} tier",
        }
    return None
