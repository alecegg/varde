"""Assign a plan to a stable orchestrator slot."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_data.errors import DataError
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands import owner
from varde_workflow.commands.error import CliError, report_cli_error


def run(args: Any) -> int:
    cwd = Path.cwd()
    try:
        working = MemoryPaths.resolve(cwd).working.path
        plan = _resolve_plan(args.plan, cwd, working / "plans")
        raw = plan.read_bytes()
        mapping, _ = owner.parse(raw)
        if mapping.get("artifact_type", mapping.get("type", "plan")) != "plan":
            _raise_not_plan(plan)
        slot = getattr(args, "slot", None)
        plan_id = mapping.get("id")
        plan_id = plan_id if isinstance(plan_id, str) else plan.parent.name
        from varde_workflow.slots import add_alias, is_orchestrator_slot, remove_alias

        clearing = getattr(args, "clear", False)
        if not clearing and (
            not isinstance(slot, str) or not is_orchestrator_slot(slot)
        ):
            _raise_invalid_slot()
        assigned_slot = slot if isinstance(slot, str) else None
        remove_alias(working, plan_id)
        from varde_workflow.commands.plan_write_errors import plan_repository

        repo = plan_repository(working, plan)
        record = repo.get_by_path(str(plan))
        if clearing:
            repo.set_assigned_to(record, None)
            message = f"Cleared slot assignment for {plan}."
        else:
            if assigned_slot is None:
                return report_cli_error(
                    CliError("slot must use the `orchestrator-<n>` form"),
                    json=getattr(args, "json", False),
                )
            repo.set_assigned_to(record, assigned_slot)
            message = f"Assigned {plan} to {assigned_slot}."
            add_alias(working, assigned_slot, plan_id)
    except (DataError, OSError, TypeError, ValueError) as exc:
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(
            exc, getattr(args, "json", False), (OSError, ValueError, TypeError)
        )
    else:
        print(message)
        return 0


def _raise_not_plan(plan: Path) -> None:
    raise ValueError(f"{plan} is not a plan")


def _raise_invalid_slot() -> None:
    raise ValueError("slot must use the `orchestrator-<n>` form")


def _resolve_plan(argument: str, cwd: Path, plans_dir: Path) -> Path:
    candidate = Path(argument)
    direct = candidate if candidate.is_absolute() else cwd / candidate
    candidate = direct if direct.is_file() else plans_dir / candidate
    if candidate.is_dir():
        candidate = candidate / "plan.md"
    try:
        root = plans_dir.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"could not read plan {candidate}: {exc}") from exc
    if resolved.name != "plan.md" or not resolved.is_relative_to(root):
        raise ValueError(f"{candidate} is not a plan.md file inside {plans_dir}")
    return resolved
