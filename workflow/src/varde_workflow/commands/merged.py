"""Check whether a plan branch has merged into main."""

import sys
from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.owner import resolve_plan
from varde_workflow.merge_approval import (
    ApprovalUnavailable,
    fetch_approval,
    plan_identity,
    raise_unapproved_item,
)
from varde_workflow.merge_state import branch_exists, is_merged

UNAPPROVED_EXIT = 2


def run(args: Any) -> int:
    cwd = Path.cwd()
    try:
        plans = MemoryPaths.resolve(cwd).working.path / "plans"
        plan = resolve_plan(args.plan, cwd, plans)
        metadata, _ = parse(plan.read_bytes())
        identifier, branch = plan_identity(metadata, plan.parent.name)
        if metadata.get("status") == "completed" and not branch_exists(cwd, branch):
            return 0
        if not is_merged(cwd, branch):
            return 1
        reviewed = metadata.get("reviewed_commit")
        return _flag_unapproved(
            identifier,
            branch,
            cwd,
            reviewed if isinstance(reviewed, str) else "",
        )
    except (OSError, ValueError) as exc:
        from varde_workflow.commands.error import CliError, report_cli_error

        return report_cli_error(CliError(str(exc)), json=getattr(args, "json", False))


def _flag_unapproved(
    identifier: str, branch: str, cwd: Path, reviewed_commit: str
) -> int:
    """Report a merge with no valid approval and raise a Mailbox item."""
    try:
        approval = fetch_approval(identifier, reviewed_commit)
        if approval is not None:
            return 0
    except ApprovalUnavailable as exc:
        print(f"warning: {exc}; approval not checked", file=sys.stderr)
        return 0
    print(
        f"error: no user merge approval is recorded for merged branch {branch}",
        file=sys.stderr,
    )
    try:
        raise_unapproved_item(MemoryPaths.resolve(cwd).working.path, identifier, branch)
    except (OSError, ValueError) as exc:
        print(f"warning: could not raise the Mailbox item: {exc}", file=sys.stderr)
    return UNAPPROVED_EXIT
