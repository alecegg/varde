"""Check a plan's merge approval record (read-only)."""

from pathlib import Path
from typing import Any

from varde_data.errors import DataError
from varde_learn.knowledge.formats import dump_yaml
from varde_learn.knowledge.frontmatter import parse
from varde_learn.knowledge.memory import MemoryPaths

from varde_workflow.commands.error import CliError, report_cli_error
from varde_workflow.commands.owner import (
    frontmatter_bounds,
    resolve_plan,
)
from varde_workflow.merge_approval import (
    ApprovalUnavailable,
    plan_identity,
    require_approval,
)


def approve_line(data: bytes, timestamp: str) -> bytes:
    start, end = frontmatter_bounds(data)
    mapping, _ = parse(data)
    if mapping.get("merge_approved_at"):
        return data
    rendered = dump_yaml(timestamp).splitlines()[1]
    encoded = f"merge_approved_at: {rendered}".encode()
    line_start = start
    while line_start < end:
        line_end = data.find(b"\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        if data[line_start:line_end].startswith(b"merge_approved_at:"):
            return data
        line_start = line_end + 1
    return data[:end] + encoded + b"\n" + data[end:]


def sync_display(plan: Path, plans: Path, approved_at: str) -> None:
    """Copy the approval time into frontmatter (display; first write wins)."""
    from varde_workflow.commands.plan_write_errors import plan_repository

    repo = plan_repository(plans.parent, plan)
    repo.set_merge_approved_at(repo.get_by_path(str(plan)), approved_at)


def run(args: Any) -> int:
    """Check the approval record; never records an approval."""
    cwd = Path.cwd()
    try:
        plans = MemoryPaths.resolve(cwd).working.path / "plans"
        plan = resolve_plan(args.plan, cwd, plans)
        metadata, _ = parse(plan.read_bytes())
        identifier, _ = plan_identity(metadata, plan.parent.name)
        reviewed = metadata.get("reviewed_commit")
        approval = require_approval(
            identifier, reviewed if isinstance(reviewed, str) else ""
        )
        sync_display(plan, plans, approval.approved_at)
    except (ApprovalUnavailable, CliError, DataError, OSError, ValueError) as exc:
        if isinstance(exc, (ApprovalUnavailable, CliError)):
            error = exc if isinstance(exc, CliError) else CliError(str(exc))
            return report_cli_error(error, json=getattr(args, "json", False))
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(
            exc, getattr(args, "json", False), (OSError, ValueError)
        )
    else:
        print(f"Approved merge for {plan}.")
        return 0
