"""Set a task status after checking its workflow transition."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from varde_data.errors import DataError, NotFound
from varde_data.plan_state import canonical_plan_dir, open_plan_state
from varde_data.plan_state_sync import export_plan_dir
from varde_data.queue_mode_lock import operation
from varde_data.records.plans import TaskRecord
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.output import print_cli_success
from varde_workflow.schema import built_in, can_transition


def run(args: Any) -> int:
    try:
        cwd = Path.cwd()
        task_path = resolve_task(args.task, getattr(args, "plan", None), cwd)
        raw = task_path.read_bytes()
        mapping, _ = parse(raw)
        if mapping.get("artifact_type", mapping.get("type")) != "task":
            _raise_not_task(task_path)
        target = args.state
        machine = built_in().artifact_type("task")
        if target not in machine.states:
            _raise_unknown_status(target)
        working = MemoryPaths.resolve(cwd).working.path
        with operation(working) as mode:
            if mode == "sqlite":
                store = open_plan_state(working)
                plan_dir = canonical_plan_dir(task_path.parent.parent)
                try:
                    current = store.task_states(plan_dir)
                    stored = next(
                        (item for item in current if item.task_id == task_path.stem),
                        None,
                    )
                except NotFound:
                    stored = None
                source = (
                    stored.status if stored is not None else current_status(mapping)
                )
                if not isinstance(source, str) or not can_transition(
                    machine, source, target
                ):
                    _raise_invalid_transition(str(source), target)
                store.set_task_state(plan_dir, task_path.stem, target, actor="cli")
                export_plan_dir(working, task_path.parent.parent)
            else:
                current = current_status(mapping)
                if not isinstance(current, str) or not can_transition(
                    machine, current, target
                ):
                    _raise_invalid_transition(current, target)
                _set_markdown_task(task_path, mapping, target, machine, working)
    except (DataError, OSError, ValueError) as exc:
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(
            exc, getattr(args, "json", False), (OSError, ValueError)
        )
    else:
        if getattr(args, "json", False):
            print_cli_success({"path": str(task_path), "status": target})
        else:
            print(f"Set {task_path} to {target}.")
        return 0


def _raise_not_task(task_path: Path) -> None:
    raise ValueError(f"{task_path} is not a task")


def _raise_unknown_status(target: str) -> None:
    raise ValueError(f"unknown task status `{target}`")


def _raise_invalid_transition(current: object, target: str) -> None:
    raise ValueError(f"task status cannot transition from `{current}` to `{target}`")


def current_status(mapping: dict[str, Any]) -> object:
    return mapping.get("status", "todo")


def _set_markdown_task(
    task_path: Path, mapping: dict[str, Any], target: str, machine: Any, working: Path
) -> None:
    from varde_workflow.commands.plan_write_errors import plan_repository

    repo = plan_repository(working, task_path)
    try:
        record = repo.get_by_path(str(task_path))
    except NotFound:
        record = TaskRecord(
            task_path.stem,
            mapping,
            task_path.read_bytes(),
            task_path.stat().st_mtime,
            str(task_path),
        )
    repo.set_task_status(
        record,
        target,
        status_at=dt.datetime.now(dt.UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
        transitions={
            key: frozenset(value) for key, value in machine.transitions.items()
        },
    )


def resolve_task(
    argument: str | Path, plan_argument: str | Path | None, cwd: Path
) -> Path:
    candidate = Path(argument)
    if candidate.is_file():
        return candidate.resolve()
    if plan_argument is None:
        raise ValueError("task id requires --plan <PLAN>")
    from varde_workflow.commands.now import resolve_plan

    plans_dir = MemoryPaths.resolve(cwd).working.path / "plans"
    plan = resolve_plan(plan_argument, cwd, plans_dir)
    task = plan.parent / "tasks" / f"{candidate}.md"
    if not task.is_file():
        raise ValueError(f"task not found: {candidate}")
    return task.resolve()
