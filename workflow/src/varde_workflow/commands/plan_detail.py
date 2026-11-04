"""Plan list, plan detail and task detail as plain library functions."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse

from varde_workflow.commands.status import (
    add_open_comments,
    artifact_id,
    collect_plan_paths,
    plan_status_report,
)


def plan_list(working: Path, repository: Path, stall_minutes: int) -> dict[str, Any]:
    """The same report as `varde plan status --json`."""
    report, handle = plan_status_report(working, repository, stall_minutes)
    return add_open_comments(report, working, handle.list(include_tasks=False).records)


def find_plan_file(working: Path, plan_id: str) -> Path | None:
    paths: list[Path] = []
    collect_plan_paths(working / "plans", paths, [0])
    for path in paths:
        if path.name != "plan.md":
            continue
        try:
            fields, _ = parse(path.read_bytes())
        except OSError, ValueError:
            continue
        if artifact_id(path, fields) == plan_id:
            return path
    return None


def _document(path: Path) -> dict[str, Any] | None:
    try:
        fields, body = parse(path.read_bytes())
    except OSError, ValueError:
        return None
    return {"id": artifact_id(path, fields), "fields": fields, "body": body}


def plan_detail(working: Path, plan_id: str) -> dict[str, Any] | None:
    """Plan fields, body and its task list, or None when the plan is unknown."""
    plan_file = find_plan_file(working, plan_id)
    document = _document(plan_file) if plan_file else None
    if plan_file is None or document is None:
        return None
    tasks = []
    for path in sorted((plan_file.parent / "tasks").glob("*.md")):
        task = _document(path)
        if task is not None:
            tasks.append({"id": task["id"], **_summary(task["fields"])})
    return {**document, "tasks": tasks}


def _summary(fields: dict[str, Any]) -> dict[str, Any]:
    return {key: fields.get(key) for key in ("status", "depends_on", "owns", "risk")}


def task_detail(working: Path, plan_id: str, task_id: str) -> dict[str, Any] | None:
    """One task's fields and body, or None when plan or task is unknown."""
    plan_file = find_plan_file(working, plan_id)
    if plan_file is None or "/" in task_id or task_id.startswith("."):
        return None
    return _document(plan_file.parent / "tasks" / f"{task_id}.md")
