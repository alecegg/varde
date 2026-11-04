"""Pure grouping of live agent rows into role identities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from varde_runner.identity_profile import Profile
from varde_runner.registry import SessionBinding

EXPANDED_ROLES = frozenset({"orchestrator"})
_STATE_ORDER = {"needs you": 0, "failed": 1, "running": 2, "idle": 3}


def _state(row: Mapping[str, Any]) -> str:
    if (
        row.get("pending_requests")
        or row.get("lifecycle")
        in {
            "awaiting_permission",
            "awaiting_question",
        }
        or row.get("idle_status") in {"awaiting_permission", "awaiting_question"}
    ):
        return "needs you"
    if row.get("lifecycle") in {"failed", "rate_limited"}:
        return "failed"
    if row.get("lifecycle") == "idle":
        return "idle"
    return "running"


def group(
    agent_rows: Sequence[Mapping[str, Any]],
    bindings: Mapping[str, SessionBinding],
    profiles: Mapping[str, Profile],
) -> list[dict[str, Any]]:
    """Group live rows; bindings map session ids to registry bindings."""
    groups: dict[str, list[dict[str, str]]] = {}
    for row in agent_rows:
        if row.get("lifecycle") in {"completed", "archived"}:
            continue
        role = row.get("role")
        identity_id = (
            "manager"
            if role == "manager-bot"
            else role
            if isinstance(role, str)
            else "other"
        )
        if identity_id not in profiles:
            identity_id = "other"
        session_id = str(row.get("session_id", row.get("id", row.get("agent_id", ""))))
        binding = bindings.get(session_id)
        label = str(binding.plan_id) if binding and binding.plan_id else ""
        groups.setdefault(identity_id, []).append(
            {
                "agent_id": str(row.get("agent_id", "")),
                "label": label,
                "state": _state(row),
            }
        )

    result = []
    for identity_id, profile in profiles.items():
        instances = groups.get(identity_id, [])
        result.append(_identity(profile, instances))
    other = groups.get("other", [])
    if other:
        result.append(_identity(None, other))
    return result


def _identity(
    profile: Profile | None,
    rows: list[dict[str, str]],
) -> dict[str, Any]:
    identity_id = profile.id if profile else "other"
    role_name = profile.label.title() if profile else "Other"
    instances = []
    for index, row in enumerate(rows, start=1):
        name = row["label"] or role_name
        duplicates = sum(
            1 for candidate in rows if (candidate["label"] or role_name) == name
        )
        label = f"{name} {index}" if len(rows) > 1 and duplicates == len(rows) else name
        instances.append({**row, "label": label})
    states = [row["state"] for row in rows]
    worst_state = min(states, key=lambda state: _STATE_ORDER[state], default=None)
    return {
        "id": identity_id,
        "name": profile.name if profile else "Other",
        "label": profile.label if profile else "Other",
        "description": profile.description if profile else "",
        "role": profile.role if profile else "other",
        "kind": "manager" if identity_id == "manager" else "role",
        "count": len(rows),
        "worst_state": worst_state,
        "instances": instances,
    }
