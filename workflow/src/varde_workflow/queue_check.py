"""Read-only task build-queue ordering, escalation, and blocker checks."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_data.plan_state import canonical_plan_dir, open_plan_state
from varde_data.queue import open_queue
from varde_data.queue_line import line_queue_format_error, validate_line_queue
from varde_data.queue_line_sync import line_queue_name
from varde_data.queue_mode_lock import operation
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.commands.validate import TASK_STATUSES
from varde_workflow.execution_wave_paths import declarations_overlap

_QUEUE_LINE = re.compile(
    r"^\s*(?P<task>[^|]+?)\s*\|\s*fix:(?P<fix>yes|no)\s*\|\s*"
    r"esc:(?P<escalations>\d+)\s*\|\s*worktree:(?P<worktree>[^|]+?)\s*$"
)


@dataclass(frozen=True)
class QueueItem:
    task_id: str
    fix: bool
    escalation_count: int
    worktree: str
    status: str
    owns: tuple[str, ...]
    depends_on: tuple[str, ...]


def check_queue(plan_dir: str | Path) -> dict[str, Any]:
    """Read queue state and task metadata, then report order and blockers."""
    plan = Path(plan_dir).resolve()
    working = _working_directory(plan)
    with operation(working) as mode:
        return _check_queue(plan, working, mode)


def _working_directory(plan: Path) -> Path:
    for parent in (plan, *plan.parents):
        if parent.name == "plans":
            return parent.parent
    raise ValueError(f"plan path has no plans ancestor: {plan}")


def _check_queue(plan: Path, working: Path, mode: str) -> dict[str, Any]:
    queue_path = plan / "notes" / "queue.md"
    if not (plan / "plan.md").is_file():
        raise ValueError(f"not a plan directory: {plan}")
    tasks = _load_tasks(plan / "tasks")
    if mode == "sqlite":
        entries = _read_store_queue(plan, working, tasks)
    else:
        if not queue_path.is_file():
            raise ValueError(f"queue file not found: {queue_path}")
        entries = _read_queue(queue_path, queue_path.read_text(encoding="utf-8"), tasks)
    ordered = sorted(entries, key=lambda item: not item.fix)
    results = []
    for index, item in enumerate(ordered):
        blockers = _dependency_blockers(item, tasks)
        blockers.extend(_overlap_blockers(item, ordered[:index]))
        results.append(
            {
                "task_id": item.task_id,
                "fix": item.fix,
                "escalation_count": item.escalation_count,
                "worktree": item.worktree,
                "status": item.status,
                "blocked": bool(blockers),
                "blocked_by": blockers,
            }
        )
    plan_mapping, _ = parse((plan / "plan.md").read_bytes())
    return {
        "plan": str(plan),
        "plan_id": plan_mapping.get("id", plan.name),
        "items": results,
    }


def _read_store_queue(
    plan: Path, working: Path, tasks: dict[str, QueueItem]
) -> list[QueueItem]:
    plan_key = canonical_plan_dir(plan)
    plan_dir = plan.relative_to(working).as_posix()
    queue_name = line_queue_name(plan)
    repository = open_queue(working)
    rows = [row for row in repository.list(queue_name) if row.queue_name == queue_name]
    state_store = open_plan_state(working)
    states = {item.task_id: item.status for item in state_store.task_states(plan_key)}
    for task_id, status in states.items():
        if status not in TASK_STATUSES:
            raise ValueError(f"invalid task status in store: {status}")
        task = tasks.get(task_id)
        if task is not None:
            tasks[task_id] = QueueItem(
                task.task_id,
                task.fix,
                task.escalation_count,
                task.worktree,
                status,
                task.owns,
                task.depends_on,
            )
    entries: list[QueueItem] = []
    for row in rows:
        values = (row.extra or {}).get("markdown_values", {})
        if not isinstance(values, dict):
            values = {}
        if (row.extra or {}).get("strict") is False:
            raise line_queue_format_error(
                str(plan / "notes" / "queue.md"), row.row_order + 1
            )
        task_id = str(
            (row.extra or {}).get("task", row.id.removeprefix(f"{queue_name}#"))
        )
        task = tasks.get(task_id)
        if task is None:
            raise ValueError(f"task not found in {plan / 'tasks'}: {task_id}")
        entries.append(
            QueueItem(
                task_id,
                str(values.get("fix", "no")).strip().lower() == "yes",
                _integer_value(values.get("esc", values.get("escalation_count", "0"))),
                str(values.get("worktree", "-")),
                states.get(task_id, task.status),
                task.owns,
                task.depends_on,
            )
        )
    if not rows:
        raise ValueError(f"no queue items found for plan: {plan_dir}")
    return entries


def _integer_value(value: object) -> int:
    try:
        return int(str(value))
    except ValueError as error:
        raise ValueError(f"invalid queue escalation count: {value}") from error


def _load_tasks(directory: Path) -> dict[str, QueueItem]:
    if not directory.is_dir():
        raise ValueError(f"task directory not found: {directory}")
    tasks: dict[str, QueueItem] = {}
    for path in sorted(directory.glob("*.md")):
        try:
            mapping, _ = parse(path.read_bytes())
        except Exception as error:
            raise ValueError(f"{path}: {error}") from error
        task_id = mapping.get("id", path.stem)
        status = mapping.get("status", "todo")
        owns = _string_tuple(mapping, "owns", path)
        depends_on = _string_tuple(mapping, "depends_on", path)
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"{path}: id must be a non-empty string")
        if not isinstance(status, str):
            raise TypeError(f"{path}: status must be a string")
        item = QueueItem(task_id, False, 0, "-", status, owns, depends_on)
        for alias in {path.stem, task_id}:
            if alias in tasks:
                raise ValueError(f"duplicate task id `{alias}` in {directory}")
            tasks[alias] = item
    return tasks


def _string_tuple(mapping: dict[str, Any], key: str, path: Path) -> tuple[str, ...]:
    value = mapping.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path}: {key} must be a list of strings")
    return tuple(item.strip().removeprefix("./") for item in value if item.strip())


def _read_queue(path: Path, text: str, tasks: dict[str, QueueItem]) -> list[QueueItem]:
    entries: list[QueueItem] = []
    seen: set[str] = set()
    validate_line_queue(text, str(path))
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _QUEUE_LINE.fullmatch(line)
        if match is None:
            raise line_queue_format_error(str(path), line_number)
        task_id = match.group("task").strip()
        task = tasks.get(task_id)
        if task is None:
            raise ValueError(f"{path}:{line_number}: task not found: {task_id}")
        if task_id in seen:
            raise ValueError(f"{path}:{line_number}: duplicate task: {task_id}")
        seen.add(task_id)
        worktree = match.group("worktree").strip()
        if not worktree:
            raise ValueError(f"{path}:{line_number}: worktree path is empty")
        entries.append(
            QueueItem(
                task_id,
                match.group("fix") == "yes",
                int(match.group("escalations")),
                worktree,
                task.status,
                task.owns,
                task.depends_on,
            )
        )
    return entries


def _dependency_blockers(
    item: QueueItem, tasks: dict[str, QueueItem]
) -> list[dict[str, str]]:
    blockers = []
    for dependency in item.depends_on:
        task = tasks.get(dependency)
        if task is None or task.status != "done":
            blockers.append(
                {
                    "kind": "depends_on",
                    "task_id": dependency,
                    "status": task.status if task is not None else "missing",
                }
            )
    return blockers


def _overlap_blockers(
    item: QueueItem, earlier: list[QueueItem]
) -> list[dict[str, str]]:
    blockers = []
    for previous in earlier:
        if previous.task_id == item.task_id or previous.status == "done":
            continue
        if any(
            declarations_overlap(left, right)
            for left in item.owns
            for right in previous.owns
        ):
            blockers.append(
                {
                    "kind": "owns_overlap",
                    "task_id": previous.task_id,
                    "status": previous.status,
                }
            )
    return blockers
