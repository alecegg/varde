"""Shared plan and orchestrator activity derivation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

STALE_AFTER = timedelta(minutes=20)


def plan_id_for_address(
    address: str, plans: list[dict[str, Any]], bindings: list[dict[str, Any]]
) -> str | None:
    """Join an orchestrator address to one plan using the canonical precedence."""
    for binding in bindings:
        if binding.get("address") == address and binding.get("plan_id"):
            return str(binding["plan_id"])
    ids = [str(row["id"]) for row in plans if row.get("id")]
    if address in ids:
        return address
    matches = [plan_id for plan_id in ids if plan_id.endswith(f"-{address}")]
    return matches[0] if len(matches) == 1 else None


def waiting_plan_ids(plans: list[dict[str, Any]]) -> set[str]:
    """Return joined plans whose shared activity projection needs a reply."""
    return {
        str(plan["id"])
        for plan in plans
        if plan.get("id")
        and plan.get("plan_joined") is True
        and plan.get("activity") == "waiting"
    }


def _agents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        agent
        for item in items
        if isinstance(item, dict)
        for agent in [item.get("agent", item)]
        if isinstance(agent, dict)
    ]


def _workers(
    plan: dict[str, Any], agents: list[dict[str, Any]], orchestrator_id: str
) -> list[dict[str, Any]]:
    normalized = _agents(agents)
    parents = {}
    for agent in normalized:
        labels = agent.get("labels", {})
        if isinstance(labels, list):
            labels = {
                item.get("name"): item.get("value")
                for item in labels
                if isinstance(item, dict)
            }
        if (
            isinstance(labels, dict)
            and agent.get("id")
            and labels.get("paseo.parent-agent-id")
        ):
            parents[str(agent["id"])] = str(labels["paseo.parent-agent-id"])
    plan_name = str(plan.get("id", ""))
    root = Path(str(plan.get("worktree"))).resolve() if plan.get("worktree") else None
    workers = []
    for agent in normalized:
        aid = str(agent.get("id") or "")
        labels = agent.get("labels", {})
        if isinstance(labels, list):
            labels = {
                item.get("name"): item.get("value")
                for item in labels
                if isinstance(item, dict)
            }
        parent, seen = parents.get(aid), set()
        descended = False
        while parent and parent not in seen:
            if parent == orchestrator_id:
                descended = True
                break
            seen.add(parent)
            parent = parents.get(parent)
        named = (
            isinstance(labels, dict)
            and labels.get("paseo.parent-agent-id") == "main"
            and plan_name
            and plan_name in str(agent.get("title", ""))
        )
        inside = False
        cwd = agent.get("cwd")
        if root and isinstance(cwd, str):
            candidate = Path(cwd).resolve()
            try:
                candidate.relative_to(root)
                inside = True
            except ValueError:
                inside = candidate.parent == root.parent and candidate.name.startswith(
                    f"{plan_name}-"
                )
        if (
            aid != orchestrator_id
            and (descended or named or inside)
            and str(agent.get("status", "")).lower() in {"running", "active", "error"}
        ):
            workers.append(
                {
                    "id": aid,
                    "title": agent.get("title") or aid,
                    "status": agent.get("status"),
                }
            )
    return workers


def _idle_for(
    plan: dict[str, Any], orchestrator: dict[str, Any], now: datetime
) -> int | None:
    stamps = []
    for value in (
        orchestrator.get("lastActivity") or orchestrator.get("last_activity"),
        plan.get("last_event_at"),
    ):
        try:
            stamp = datetime.fromisoformat(str(value))
            stamps.append(stamp.replace(tzinfo=UTC) if stamp.tzinfo is None else stamp)
        except ValueError, TypeError:
            continue
    return max(0, int((now - max(stamps)).total_seconds())) if stamps else None


def _awaiting_user(plan: dict[str, Any]) -> str | None:
    reason = plan.get("awaiting_user")
    return reason.strip() or None if isinstance(reason, str) else None


def plan_activity(
    plan: dict[str, Any],
    agents: list[dict[str, Any]],
    orchestrator: dict[str, Any],
    now: datetime | None = None,
    open_questions: int = 0,
) -> dict[str, Any]:
    """Compute the single dashboard activity state and its display fields."""
    now = now or datetime.now(UTC)
    oid = str(orchestrator.get("id") or "")
    workers = _workers(plan, agents, oid)
    status = str(plan.get("status") or plan.get("frontmatter_status") or "").lower()
    frontmatter_status = str(plan.get("frontmatter_status") or "").lower()
    terminal_statuses = {
        "done",
        "complete",
        "completed",
        "concluded",
        "cancelled",
        "finished",
    }
    if frontmatter_status in terminal_statuses and status not in terminal_statuses:
        status = frontmatter_status
    task_rows = plan.get("tasks", plan.get("queue", []))
    tasks = (
        [task for task in task_rows if isinstance(task, dict)]
        if isinstance(task_rows, list)
        else []
    )
    terminal = status in terminal_statuses
    awaiting_user = _awaiting_user(plan)
    blocked = (
        status in {"blocked", "error"}
        or str(orchestrator.get("status", "")).lower() == "error"
        or any(str(t.get("status", "")).lower() in {"blocked", "error"} for t in tasks)
        or any(worker["status"] == "error" for worker in workers)
    )
    idle_for = _idle_for(plan, orchestrator, now)
    active = status in {"active", "running", "in-progress", "in_progress"} or any(
        str(t.get("status", "")).lower()
        not in {"done", "complete", "completed", "cancelled"}
        for t in tasks
    )
    live = str(orchestrator.get("status", "")).lower() in {"running", "active"}
    live_orchestrator = str(orchestrator.get("status", "")).lower() in {
        "running",
        "active",
        "idle",
        "error",
    }
    running_worker = any(
        worker["status"] in {"running", "active"} for worker in workers
    )
    if terminal:
        activity = "done"
    elif awaiting_user:
        activity = "waiting"
    elif blocked:
        activity = "blocked"
    elif plan.get("stalled") is True:
        activity = "stalled"
    elif open_questions and plan.get("_joinable", bool(plan.get("id"))):
        activity = "waiting"
    elif live or running_worker:
        activity = "running"
    elif active and (
        idle_for is not None
        and idle_for > STALE_AFTER.total_seconds()
        or idle_for is None
        and not live_orchestrator
    ):
        activity = "stalled"
    elif active:
        activity = "idle"
    elif status in {"backlog", "todo", ""} and not orchestrator:
        activity = "backlog"
    else:
        unjoinable_plan = not plan.get("_joinable", bool(plan.get("id")))
        activity = "unknown" if unjoinable_plan else "idle"
    return {
        "activity": activity,
        "idle_for": idle_for,
        "workers": workers,
        "open_questions": open_questions,
        "awaiting_user": awaiting_user,
        "now": plan.get("now") or "unknown",
        "now_at": plan.get("now_at"),
    }
