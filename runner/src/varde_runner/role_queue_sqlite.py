"""Role queue rows read from the plan queue store."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_data.errors import Invalid, NotFound
from varde_data.plan_state import (
    PlanStateRepository,
    canonical_plan_dir,
    open_plan_state,
)
from varde_data.queue import open_queue
from varde_data.queue_paths import QUEUE_DATABASE
from varde_data.records.queue import QueueItem

from varde_runner.role_queue import QueueRowState, RoleQueueRow, RoleQueues
from varde_runner.role_queue_source import (
    role_identities,
    sources_working_directory,
    summarize_roles,
)

_DATABASE = QUEUE_DATABASE
_ROW_STATES: dict[str, QueueRowState] = {
    "queued": "waiting",
    "claimed": "running",
    "building": "running",
    "in_review": "running",
    "blocked": "blocked",
    "merged": "done",
}
_OMITTED_STATES = frozenset({"cancelled"})


def sqlite_role_queue(sources: Any) -> RoleQueues:
    """Build the role queue from store items grouped by their role."""
    working = sources_working_directory(sources)
    if working is None:
        raise Invalid("role queue store needs a working directory")
    identities = role_identities(sources)
    items = open_queue(working).list()
    assigned = _plan_roles(open_plan_state(working), working, items)
    return summarize_roles(identities, _rows(identities, items, assigned))


def _rows(
    identities: Sequence[Mapping[str, Any]],
    items: Sequence[QueueItem],
    assigned: Mapping[str, str],
) -> dict[str, list[RoleQueueRow]]:
    rows: dict[str, list[RoleQueueRow]] = {
        str(identity["role"]): [] for identity in identities
    }
    for item in items:
        row = _row(item)
        role = item.role or assigned.get(item.plan_dir)
        if row is not None and role in rows:
            rows[role].append(row)
    return rows


def _row(item: QueueItem) -> RoleQueueRow | None:
    if item.state in _OMITTED_STATES:
        return None
    task = (item.extra or {}).get("task")
    row_id = task if isinstance(task, str) and task else item.id
    plan_id = Path(item.plan_dir).name or None
    return RoleQueueRow(
        id=row_id,
        title=item.findings or row_id,
        plan_id=plan_id,
        state=_ROW_STATES.get(item.state, "waiting"),
    )


def _plan_roles(
    state_store: PlanStateRepository, working: Path, items: Sequence[QueueItem]
) -> dict[str, str]:
    """Map each role-less item's plan directory to its stored assigned role."""
    roles: dict[str, str | None] = {}
    for item in items:
        plan_dir = item.plan_dir
        if item.role or not plan_dir or plan_dir in roles:
            continue
        roles[plan_dir] = _assigned_role(state_store, working, plan_dir)
    return {plan_dir: role for plan_dir, role in roles.items() if role is not None}


def _assigned_role(
    state_store: PlanStateRepository, working: Path, plan_dir: str
) -> str | None:
    """Read the plan's role from a path relative to working or to plans/."""
    for candidate in (working / plan_dir, working / "plans" / plan_dir):
        try:
            return state_store.plan_state(canonical_plan_dir(candidate)).assigned_to
        except NotFound:
            continue
    return None
