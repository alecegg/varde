"""Implementation of the check-task-ownership command."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from varde_learn.knowledge.cmdbase.output import Fix

from varde_workflow.errors import report_error, report_failure_with_fix
from varde_workflow.execution_wave import serial_plan
from varde_workflow.output import print_cli_success
from varde_workflow.task_ownership import OwnershipError, check


def run(args: Any) -> int:
    task_path = Path(args.task).resolve()
    plan_dir = task_path.parent.parent
    if (plan_dir / "plan.md").is_file() and serial_plan(plan_dir):
        details = {"status": "skipped", "detail": "serial plan: gated by scope"}
        if args.json:
            print_cli_success(details)
        else:
            print(json.dumps(details, indent=2, sort_keys=True))
        return 0
    try:
        audit = check(
            Path(args.task),
            args.commit,
            Path(args.repo_root),
            getattr(args, "trusted_tips", []),
        )
    except OwnershipError as error:
        return report_error(error, bool(getattr(args, "json", False)))
    details = asdict(audit)
    if not details["blockers"]:
        details.pop("blockers")
    if audit.status == "stray":
        message = "task ownership found stray paths: " + ", ".join(audit.stray)
        fix = Fix.no_command(
            "add each stray path to the task's `owns:` or the plan's `shared:`, "
            "then rerun check-task-ownership"
        )
        if args.json:
            return report_failure_with_fix(
                "ownership_stray", 2, message, details, fix, True
            )
        print(f"error: {message}\nFix: {fix.text()}", file=sys.stderr)
        return 2
    if audit.status == "invalid":
        return report_failure_with_fix(
            "ownership_invalid",
            2,
            "task ownership has invalid paths: " + ", ".join(audit.blockers),
            details,
            Fix.no_command(
                "correct each invalid path or ownership declaration, then rerun "
                "plan validate and check-task-ownership"
            ),
            args.json,
        )
    if args.json:
        print_cli_success(details)
    else:
        print(json.dumps(details, indent=2, sort_keys=True))
    return 0
