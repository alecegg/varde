"""Pure fingerprint and idle decisions for plan pulse."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def fingerprint(facts: dict[str, Any]) -> str:
    """Return a stable digest for the facts shown by one plan pulse."""
    encoded = json.dumps(facts, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def fingerprint_facts(plan: dict[str, Any]) -> str:
    """Fingerprint stable plan facts, including all scanned file mtimes."""
    keys = ("id", "status", "tasks", "now", "owner", "unread", "worktree")
    facts = {key: plan.get(key) for key in keys}
    facts["files"] = plan.get("_all_files", {})
    facts["events"] = [event.get("kind") for event in plan.get("events", [])]
    return fingerprint(facts)


def is_idle(current: dict[str, str], previous: dict[str, str]) -> bool:
    """Whether every reported plan has the same fingerprint as last pulse."""
    return bool(current) and all(
        previous.get(plan) == value for plan, value in current.items()
    )


def merge_state(
    previous: dict[str, Any],
    updates: dict[str, Any],
    retained: set[str] | None = None,
) -> dict[str, Any]:
    """Merge one pulse's state, optionally pruning plans absent from a full scan."""
    merged = (
        dict(previous)
        if retained is None
        else {plan: value for plan, value in previous.items() if plan in retained}
    )
    merged.update(updates)
    return merged
