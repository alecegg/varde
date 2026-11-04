"""Merge a plan branch into main only when a valid approval record exists."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.approve_merge import sync_display
from varde_workflow.commands.error import CliError, report_cli_error
from varde_workflow.commands.owner import resolve_plan
from varde_workflow.merge_approval import (
    ApprovalUnavailable,
    plan_identity,
    require_approval,
)

BASE_BRANCH = "main"


def require_main_checkout(cwd: Path) -> None:
    if _current_branch(cwd) != BASE_BRANCH:
        raise CliError(f"run `varde plan merge` from a {BASE_BRANCH} checkout")


def _current_branch(cwd: Path) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv.
        ["git", "-C", str(cwd), "rev-parse", "--abbrev-ref", "HEAD"],  # noqa: S607 - git from PATH.
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def run(args: Any) -> int:
    cwd = Path.cwd()
    try:
        plans = MemoryPaths.resolve(cwd).working.path / "plans"
        plan = resolve_plan(args.plan, cwd, plans)
        metadata, _ = parse(plan.read_bytes())
        identifier, branch = plan_identity(metadata, plan.parent.name)
        reviewed = metadata.get("reviewed_commit")
        approval = require_approval(
            identifier, reviewed if isinstance(reviewed, str) else ""
        )
        require_main_checkout(cwd)
        sync_display(plan, plans, approval.approved_at)
        merged = subprocess.run(  # noqa: S603 - fixed git argv, branch from the plan.
            ["git", "-C", str(cwd), "merge", "--no-ff", "--no-edit", branch],  # noqa: S607 - git from PATH.
            check=False,
        )
    except (ApprovalUnavailable, CliError, OSError, ValueError) as exc:
        error = exc if isinstance(exc, CliError) else CliError(str(exc))
        return report_cli_error(error, json=getattr(args, "json", False))
    else:
        return merged.returncode
