"""Set or clear the optional plan owner."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Never

from varde_core.frontmatter import frontmatter_bounds, parse
from varde_core.yamlio import dump_yaml
from varde_data.errors import DataError
from varde_learn.knowledge.memory import MemoryPaths


def run(args: Any) -> int:
    if getattr(args, "json", False):
        import sys

        usage = (
            "varde plan owner --clear <PLAN> [HARNESS:ID]"
            if getattr(args, "clear", False)
            else "varde plan owner <PLAN> <HARNESS:ID>"
        )
        print(
            "error: unexpected argument '--json' found\n\n"
            "  tip: to pass '--json' as a value, use '-- --json'\n\n"
            f"Usage: {usage}\n\n"
            "For more information, try '--help'.",
            file=sys.stderr,
        )
        return 2
    cwd = Path.cwd()
    try:
        working = MemoryPaths.resolve(cwd).working.path
        plan = resolve_plan(args.plan, cwd, working / "plans")
        raw = plan.read_bytes()
        mapping, _ = parse(raw)
        if mapping.get("artifact_type", mapping.get("type", "plan")) != "plan":
            _raise_plan_error(plan)
        owner = getattr(args, "owner", None)
        from varde_workflow.commands.plan_write_errors import plan_repository

        repo = plan_repository(working, plan)
        record = repo.get_by_path(str(plan))
        if owner is None:
            repo.set_owner(record, None)
            message = f"Cleared owner for {plan}."
        else:
            validate_owner(owner)
            repo.set_owner(record, owner)
            message = f"Set owner for {plan}."
        print(message)
    except (DataError, OSError, ValueError) as exc:
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(
            exc, getattr(args, "json", False), (OSError, ValueError)
        )
    else:
        return 0


def register_branch(args: Any) -> int:
    """Register a task branch on a plan."""
    cwd = Path.cwd()
    try:
        working = MemoryPaths.resolve(cwd).working.path
        tip = _git_commit(cwd, args.branch)
        main = _git_commit(cwd, "main")
        if tip is None:
            raise ValueError(f"branch {args.branch} does not exist")  # noqa: TRY301
        if args.branch == "main" or (main and _is_ancestor(cwd, tip, main)):
            raise ValueError(  # noqa: TRY301
                "cannot register main or a branch already contained in main"
            )
        plan = resolve_plan(args.plan, cwd, working / "plans")
        raw = plan.read_bytes()
        data = set_branches_line(raw, args.branch)
        plan.write_bytes(data)
        print(f"Registered branch {args.branch} for {plan}.")
    except (DataError, OSError, ValueError) as exc:
        from varde_workflow.commands.plan_write_errors import (
            report_plan_write_exception,
        )

        return report_plan_write_exception(exc, False, (OSError, ValueError))
    return 0


def _git_commit(cwd: Path, rev: str) -> str | None:
    result = subprocess.run(  # noqa: S603 - fixed git argv.
        [  # noqa: S607 - git is resolved from PATH.
            "git",
            "-C",
            str(cwd),
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/heads/{rev}^{{commit}}",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _is_ancestor(cwd: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(  # noqa: S603 - fixed git argv.
        [  # noqa: S607 - git is resolved from PATH.
            "git",
            "-C",
            str(cwd),
            "merge-base",
            "--is-ancestor",
            ancestor,
            descendant,
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _raise_plan_error(plan: Path) -> Never:
    raise ValueError(f"{plan} is not a plan")


def validate_owner(owner: str) -> None:
    parts = owner.split(":", 1)
    if len(parts) != 2:
        raise ValueError("owner must use `<harness>:<id>` form")
    if (
        not parts[0]
        or not parts[1]
        or any(
            character.isspace() or ord(character) < 32 or ord(character) == 127
            for character in owner
        )
    ):
        raise ValueError(
            "owner harness and id must be non-empty and contain no whitespace or "
            "control characters"
        )


def resolve_plan(argument: Path | str, cwd: Path, plans_dir: Path) -> Path:
    argument = Path(argument)
    direct = argument if argument.is_absolute() else cwd / argument
    candidate = direct if direct.is_file() else plans_dir / argument
    try:
        plans_root = plans_dir.resolve(strict=True)
        canonical = candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError(f"could not read plan {candidate}: {exc}") from exc
    if canonical.name != "plan.md":
        raise ValueError(f"{candidate} is not a plan.md file")
    if not canonical.is_relative_to(plans_root):
        raise ValueError(f"plan path must be inside {plans_dir}")
    return canonical


def set_owner_line(data: bytes, owner: str) -> bytes:
    start, end = frontmatter_bounds(data)
    rendered = dump_yaml(owner).splitlines()[1]
    encoded = f"owner: {rendered}".encode()
    current = owner_bounds(data, start, end)
    if current is None:
        return data[:end] + encoded + b"\n" + data[end:]
    line_start, line_end = current
    remove_end = continuation_end(data, line_end, end)
    return data[:line_start] + encoded + b"\n" + data[remove_end:]


def remove_owner_line(data: bytes) -> bytes:
    start, end = frontmatter_bounds(data)
    current = owner_bounds(data, start, end)
    if current is None:
        return data
    line_start, line_end = current
    return data[:line_start] + data[continuation_end(data, line_end, end) :]


def set_branches_line(data: bytes, branch: str) -> bytes:
    """Register a task branch in plan frontmatter, preserving other content."""
    start, end = frontmatter_bounds(data)
    mapping, _ = parse(data)
    branches = mapping.get("branches", [])
    if not isinstance(branches, list) or any(
        not isinstance(item, str) for item in branches
    ):
        raise ValueError("branches must be a list of strings")
    if branch not in branches:
        branches.append(branch)
    rendered = dump_yaml(branches).splitlines()[1:]
    encoded = (
        "branches:\n" + "\n".join(f"  {line}" for line in rendered) + "\n"
    ).encode()
    current = field_bounds(data, start, end, b"branches:")
    if current is None:
        return data[:end] + encoded + data[end:]
    return data[: current[0]] + encoded + data[current[1] :]


def field_bounds(
    data: bytes, start: int, end: int, key: bytes
) -> tuple[int, int] | None:
    line_start = start
    while line_start < end:
        line_end = data.find(b"\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        if data[line_start:line_end].startswith(key):
            return line_start, continuation_end(data, line_end, end)
        line_start = line_end + 1
    return None


def owner_bounds(data: bytes, start: int, end: int) -> tuple[int, int] | None:
    line_start = start
    while line_start < end:
        line_end = data.find(b"\n", line_start, end)
        line_end = end if line_end < 0 else line_end
        if data[line_start:line_end].startswith(b"owner:"):
            return line_start, line_end
        line_start = line_end + 1
    return None


def continuation_end(data: bytes, line_end: int, frontmatter_end: int) -> int:
    next_line = line_end + (data[line_end : line_end + 1] == b"\n")
    while next_line < frontmatter_end and data[next_line : next_line + 1] in (
        b" ",
        b"\t",
    ):
        end = data.find(b"\n", next_line, frontmatter_end)
        next_line = frontmatter_end if end < 0 else end + 1
    return next_line
