"""Role queue adapter: the plan store in sqlite mode, plan files otherwise.

The web route passes the same ``sources`` object in both store modes, so this
module selects the backend and keeps the route unchanged. Store reads live in
``role_queue_sqlite.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_data.queue_mode_lock import operation

from varde_runner.config import ROLE_NAMES
from varde_runner.identity_groups import group as _group
from varde_runner.identity_profile import defaults as _defaults
from varde_runner.role_queue import (
    RoleQueueRow as _RoleQueueRow,
)
from varde_runner.role_queue import (
    RoleQueues as _RoleQueues,
)
from varde_runner.role_queue import (
    RoleState as _RoleState,
)
from varde_runner.role_queue import (
    RoleSummary as _RoleSummary,
)


def read_role_queue(sources: Any) -> _RoleQueues:
    """Build the role queue from the plan store, or from plan files in markdown."""
    working = sources_working_directory(sources)
    if working is not None:
        with operation(working) as mode:
            if mode == "sqlite":
                # Imported here so the store module can share this module's helpers.
                from varde_runner.role_queue_sqlite import sqlite_role_queue

                return sqlite_role_queue(sources)
    return _file_role_queue(sources)


def sources_working_directory(sources: Any) -> Path | None:
    """Resolve the working directory from the route's dashboard-bound sources.

    The web route passes one sources object and no working directory; its
    ``queue_inputs`` method is bound to the dashboard, whose CLI holds the path.
    """
    dashboard = getattr(getattr(sources, "queue_inputs", None), "__self__", None)
    cli = getattr(dashboard, "cli", None)
    environment = getattr(cli, "env", None)
    configured = (
        environment.get("VARDE_WORKING_DIR")
        if isinstance(environment, Mapping)
        else None
    )
    if isinstance(configured, str) and configured:
        return Path(configured).expanduser()
    cwd = getattr(cli, "cwd", None)
    return cwd if isinstance(cwd, Path) else None


def role_identities(sources: Any) -> list[dict[str, Any]]:
    """Group live agent rows, session bindings, and profiles into identities."""
    agent_rows = _source_value(sources, "agent_rows", [])
    bindings = _source_value(sources, "bindings", {})
    profiles = _source_value(sources, "profiles", _defaults(ROLE_NAMES))
    identities = _group(agent_rows, bindings, profiles)
    requests_by_agent = {
        str(row.get("agent_id", "")): row["pending_requests"]
        for row in agent_rows
        if isinstance(row, Mapping) and "pending_requests" in row
    }
    for identity in identities:
        for instance in identity.get("instances") or ():
            agent_id = instance.get("agent_id")
            if agent_id in requests_by_agent:
                instance["pending_requests"] = requests_by_agent[agent_id]
    return identities


def needs_you_count(
    identity: Mapping[str, Any], role_rows: Sequence[_RoleQueueRow]
) -> int:
    """Approvals pending on the role's agents plus its blocked queue rows."""
    instances = identity.get("instances") or ()
    pending = sum(
        len(instance["pending_requests"])
        if isinstance(instance.get("pending_requests"), Sequence)
        and not isinstance(instance.get("pending_requests"), (str, bytes))
        else int(instance.get("state") == "needs you")
        for instance in instances
    )
    blocked = sum(row.state == "blocked" for row in role_rows)
    return pending + blocked


def role_state(
    instance_state: str | None,
    role_rows: Sequence[_RoleQueueRow],
    needs_you: int,
) -> _RoleState:
    """The role's state: pending approvals and failed agents outrank the queue."""
    if needs_you or instance_state == "needs you":
        return "needs_you"
    if instance_state == "failed":
        return "failed"
    if instance_state == "running" or any(row.state == "running" for row in role_rows):
        return "running"
    if not role_rows or any(row.state == "waiting" for row in role_rows):
        return "idle"
    return "done"


def summarize_roles(
    identities: Sequence[Mapping[str, Any]],
    rows: Mapping[str, Sequence[_RoleQueueRow]],
) -> _RoleQueues:
    """Build per-role summaries and row groups from identities and their rows."""
    grouped: dict[str, list[_RoleQueueRow]] = {}
    roles: list[_RoleSummary] = []
    for identity in identities:
        role = str(identity["role"])
        role_rows = list(rows.get(role, ()))
        grouped[role] = role_rows
        current = next((row for row in role_rows if row.state == "running"), None)
        needs_you = needs_you_count(identity, role_rows)
        state = role_state(identity.get("worst_state"), role_rows, needs_you)
        roles.append(
            _RoleSummary(
                role=role,
                agent_id=(identity.get("instances") or [{}])[0].get("agent_id"),
                state=state,
                current=current,
                queued=sum(row.state == "waiting" for row in role_rows),
                needs_you=needs_you,
            )
        )
    return _RoleQueues(roles=roles, rows=grouped)


def _file_role_queue(sources: Any) -> _RoleQueues:
    statuses, _bindings = sources.queue_inputs()
    identities = role_identities(sources)
    plans = statuses.get("plans", []) if isinstance(statuses, dict) else []
    rows = {
        str(identity["role"]): [
            _plan_row(plan)
            for plan in plans
            if isinstance(plan, dict) and plan.get("assigned_to") == identity["role"]
        ]
        for identity in identities
    }
    return summarize_roles(identities, rows)


def _source_value(sources: Any, name: str, default: Any) -> Any:
    value = getattr(sources, name, default)
    return value() if callable(value) else value


def _plan_row(plan: dict[str, Any]) -> _RoleQueueRow:
    status = plan.get("status")
    state = (
        "running"
        if status in {"active", "running"}
        else "blocked"
        if status in {"blocked", "needs_you"}
        else "done"
        if status in {"done", "complete", "completed"}
        else "waiting"
    )
    plan_id = str(plan.get("id", ""))
    return _RoleQueueRow(
        id=plan_id,
        title=str(plan.get("title") or plan_id),
        plan_id=plan_id or None,
        state=state,
    )
