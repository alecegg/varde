"""Find write declaration overlaps between sibling plans."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_learn.knowledge.frontmatter import parse

from .commands.status import collect_plan_paths, status_bucket
from .execution_wave import _list, _load_tasks
from .execution_wave_paths import declarations_overlap


def _plan_writes(plan_dir: Path) -> set[str]:
    tasks = _load_tasks(plan_dir)
    writes = {
        declaration
        for task in tasks.values()
        if task["status"] != "done"
        for declaration in task["writes"]
    }
    plan_file = plan_dir / "plan.md"
    if plan_file.exists():
        frontmatter, _ = parse(plan_file.read_bytes())
        writes.update(
            declaration.strip().removeprefix("./")
            for key in ("shared", "generated")
            for declaration in _list(frontmatter, key)
        )
    return writes


def _overlapping_files(left: set[str], right: set[str]) -> list[str]:
    overlaps: set[str] = set()
    for left_path in left:
        for right_path in right:
            if not declarations_overlap(left_path, right_path):
                continue
            left_is_pattern = "*" in left_path or left_path.endswith("/")
            right_is_pattern = "*" in right_path or right_path.endswith("/")
            if left_is_pattern and not right_is_pattern:
                overlaps.add(right_path)
            elif right_is_pattern and not left_is_pattern:
                overlaps.add(left_path)
            else:
                overlaps.update((left_path, right_path))
    return sorted(overlaps)


def _sibling_writes(plan_dir: Path, sibling: Path) -> set[str] | None:
    if sibling == plan_dir or not (sibling / "tasks").is_dir():
        return None
    try:
        frontmatter, _ = parse((sibling / "plan.md").read_bytes())
        status: Any = frontmatter.get("status", "")
        if not isinstance(status, str) or status_bucket(status) == "terminal":
            return None
        return _plan_writes(sibling)
    except OSError, ValueError, TypeError:
        return None


def sibling_plan_dirs(plan_path: Path) -> list[Path]:
    """Return plan directories beside the plan at the same directory depth."""
    root = plan_path.parent.parent
    paths: list[Path] = []
    collect_plan_paths(root, paths, [0])
    return [
        candidate.parent
        for candidate in paths
        if candidate.name == "plan.md" and candidate.parent.parent == root
    ]


def plan_overlaps(plan_dir: Path, others: list[Path]) -> list[dict[str, Any]]:
    """Return non-terminal sibling plans and their sorted overlapping paths."""
    if not (plan_dir / "tasks").is_dir():
        return []

    try:
        own_writes = _plan_writes(plan_dir)
    except OSError, ValueError, TypeError:
        return []
    warnings = []
    for sibling in others:
        sibling_writes = _sibling_writes(plan_dir, sibling)
        if sibling_writes is None:
            continue
        files = _overlapping_files(own_writes, sibling_writes)
        if files:
            warnings.append({"plan": sibling.name, "files": files})
    return sorted(warnings, key=lambda warning: warning["plan"])
