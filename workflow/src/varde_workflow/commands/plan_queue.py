"""Read-only plan queue command."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_data.plan_state_sync import export_plan_dir
from varde_data.queue_mode_lock import operation
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.errors import InternalError, report_error
from varde_workflow.output import print_cli_success
from varde_workflow.queue_check import check_queue


def run(args: Any) -> int:
    try:
        cwd = Path.cwd()
        working = MemoryPaths.resolve(cwd).working.path
        from varde_workflow.commands.now import resolve_plan

        plan_path = resolve_plan(args.plan, cwd, working / "plans")
        with operation(working) as mode:
            if mode == "sqlite":
                export_plan_dir(
                    working,
                    plan_path.parent,
                )
            data = check_queue(plan_path.parent)
    except Exception as error:  # noqa: BLE001 - Report resolver/parser errors cleanly.
        return report_error(InternalError(str(error)), getattr(args, "json", False))
    if args.json:
        print_cli_success(data)
    else:
        for item in data["items"]:
            state = "blocked" if item["blocked"] else "ready"
            print(
                f"{item['task_id']} {state} ({item['status']}) "
                f"esc={item['escalation_count']} worktree={item['worktree']}"
            )
            for blocker in item["blocked_by"]:
                print(
                    f"  blocked by {blocker['kind']} {blocker['task_id']} "
                    f"({blocker['status']})"
                )
    return 0
