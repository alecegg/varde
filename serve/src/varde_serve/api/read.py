"""Read handlers: plain functions returning JSON-safe data."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_data.config_keys import read_allowed
from varde_data.errors import Invalid
from varde_data.queue import open_queue
from varde_data.queue_order import read_order
from varde_learn.loop import friction_repository
from varde_learn.loop.store import read as friction_read
from varde_learn.loop.store.paths import resolve_store_dir
from varde_learn.loop.store.types import (
    FrictionListRequest,
    FrictionStatus,
    PageRequest,
)
from varde_workflow.commands.plan_detail import plan_detail, plan_list, task_detail
from varde_workflow.inbox import read_all

from varde_serve.api.docs import list_docs, search_docs
from varde_serve.api.errors import ApiError, plain
from varde_serve.project import Project

QUEUE_CATEGORY = "queue"
SEARCH_DOMAINS = ("plans", "friction", "docs", "mail")


def stall_minutes(project: Project) -> int:
    rows = {r["key"]: r["value"] for r in read_allowed(project.config_dir)}
    return int(rows["orchestration.stall_minutes"])


def get_plans(project: Project) -> dict[str, Any]:
    return plain(plan_list(project.working, project.repository, stall_minutes(project)))


def get_plan(project: Project, plan_id: str) -> dict[str, Any]:
    found = plan_detail(project.working, plan_id)
    if found is None:
        raise ApiError(404, "not_found", "no such plan")
    return plain(found)


def get_task(project: Project, plan_id: str, task_id: str) -> dict[str, Any]:
    found = task_detail(project.working, plan_id, task_id)
    if found is None:
        raise ApiError(404, "not_found", "no such task")
    return plain(found)


def order_file(project: Project) -> Path:
    return project.config_dir / "serve" / "queue-order.json"


def queue_items(project: Project, state: str | None = None) -> list[Any]:
    """Queue rows; a queue that is not set up yet is 409, not a crash."""
    try:
        return open_queue(project.working).list(state=state)
    except Invalid as error:
        raise ApiError(409, "queue_unavailable", str(error)) from error


def queued_ids(project: Project) -> list[str]:
    return [item.id for item in queue_items(project, "queued")]


def get_queue(project: Project) -> dict[str, Any]:
    items = {item.id: item for item in queue_items(project)}
    queued = [i for i, item in items.items() if item.state == "queued"]
    order = read_order(order_file(project), {QUEUE_CATEGORY: queued})[QUEUE_CATEGORY]
    return {
        "order": order,
        "items": plain(
            [asdict(items[i]) for i in order]
            + [asdict(i) for i in items.values() if i.state != "queued"]
        ),
    }


def get_friction(
    project: Project, status: str | None, tag: str | None, limit: int
) -> dict[str, Any]:
    parsed = FrictionStatus.parse(status) if status else None
    if status and parsed is None:
        raise ApiError(400, "bad_request", f"unknown friction status {status}")
    request = FrictionListRequest(
        parsed, None, None, False, None, project.repository, PageRequest(0, limit), tag
    )
    page = friction_repository.with_repository(
        lambda repository: friction_read.list_items(repository, request),
        resolve_store_dir(project.config_dir),
    )
    return plain({"items": page.items, "total": page.total})


def get_mail(project: Project) -> dict[str, Any]:
    return {"messages": [m.to_dict() for m in read_all(project.working)]}


def get_config(project: Project) -> dict[str, Any]:
    return {"keys": read_allowed(project.config_dir)}


def search(
    project: Project, needle: str, domain: str | None, limit: int
) -> dict[str, Any]:
    if domain is not None and domain not in SEARCH_DOMAINS:
        raise ApiError(400, "bad_request", f"domain must be one of {SEARCH_DOMAINS}")
    lowered = needle.lower()
    domains = [domain] if domain else list(SEARCH_DOMAINS)
    results: dict[str, list[Any]] = {}
    if "plans" in domains:
        plans = get_plans(project).get("plans", [])
        results["plans"] = [
            p
            for p in _flatten(plans)
            if lowered in f"{p.get('id')} {p.get('title')}".lower()
        ][:limit]
    if "docs" in domains:
        results["docs"] = search_docs(project, lowered, limit)
    if "mail" in domains:
        messages = get_mail(project)["messages"]
        results["mail"] = [m for m in messages if lowered in m["text"].lower()][:limit]
    if "friction" in domains:
        items = get_friction(project, None, None, 1000)["items"]
        results["friction"] = [
            i for i in items if lowered in f"{i.get('title')} {i.get('slug')}".lower()
        ][:limit]
    return {"results": results}


def _flatten(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    flat = []
    for plan in plans:
        flat.append(plan)
        flat.extend(_flatten(plan.get("children", [])))
    return flat


__all__ = ["list_docs"]
