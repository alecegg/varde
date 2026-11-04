"""Map changed files to plan tasks and blocks and flag drift. Pure given inputs."""

from dataclasses import dataclass

from varde_learn.docs.recap.gitdiff import FileChange
from varde_learn.docs.recap.owns import matches
from varde_learn.docs.recap.plan import Plan, Task

HUNK_CAP_PER_FILE = 8 * 1024
HUNK_CAP_TOTAL = 256 * 1024


@dataclass(frozen=True)
class Caps:
    per_file: int = HUNK_CAP_PER_FILE
    total: int = HUNK_CAP_TOTAL


def _paths(change: FileChange) -> list[str]:
    return [change.path] + ([change.old_path] if change.old_path else [])


def _owning_tasks(change: FileChange, tasks: tuple[Task, ...]) -> list[str]:
    paths = _paths(change)
    return sorted(
        t.id for t in tasks if any(matches(e, p) for e in t.owns for p in paths)
    )


def _is_shared(change: FileChange, shared: tuple[str, ...]) -> bool:
    return any(matches(e, p) for e in shared for p in _paths(change))


def _task_blocks(plan: Plan, task: Task) -> set[str]:
    linked = set(task.blocks)
    refs = {task.id, task.short_id}
    linked |= {b for b, covers in plan.covers.items() if refs & set(covers)}
    return linked & set(plan.block_ids)


def _blocks_for(plan: Plan, task_ids: list[str]) -> list[str]:
    by_id = {t.id: t for t in plan.tasks}
    found: set[str] = set()
    for task_id in task_ids:
        found |= _task_blocks(plan, by_id[task_id])
    return sorted(found)


def _hunk_text(change: FileChange, cap: int, budget: int) -> tuple[str, bool]:
    text = "\n".join(change.hunk_lines)
    limit = max(0, min(cap, budget))
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", errors="ignore"), True


def _row(plan: Plan, change: FileChange, hunk: str, truncated: bool) -> dict:
    tasks = _owning_tasks(change, plan.tasks)
    shared = not tasks and _is_shared(change, plan.shared)
    return {
        "file": change.path,
        "old_file": change.old_path,
        "status": change.status,
        "binary": change.binary,
        "tasks": tasks,
        "shared": shared,
        "blocks": _blocks_for(plan, tasks),
        "added": change.added,
        "removed": change.removed,
        "hunk": hunk,
        "truncated": truncated,
        "drift": [] if tasks or shared else ["unplanned"],
    }


def _untouched(plan: Plan, changes: list[FileChange]) -> list[dict]:
    paths = [p for c in changes for p in _paths(c)]
    return sorted(
        (
            {"task": t.id, "owns": e}
            for t in plan.tasks
            for e in t.owns
            if not any(matches(e, p) for p in paths)
        ),
        key=lambda d: (d["task"], d["owns"]),
    )


def build_recap(
    plan: Plan,
    changes: list[FileChange],
    base: str,
    head: str,
    plan_name: str,
    caps: Caps | None = None,
) -> dict:
    caps = caps or Caps()
    rows: list[dict] = []
    budget = caps.total
    for change in sorted(changes, key=lambda c: c.path):
        hunk, truncated = _hunk_text(change, caps.per_file, budget)
        budget -= len(hunk.encode("utf-8"))
        rows.append(_row(plan, change, hunk, truncated))
    verified = {b for r in rows for b in r["blocks"]}
    unverified = sorted(set(plan.block_ids) - verified)
    untouched = _untouched(plan, changes)
    unplanned = [r["file"] for r in rows if "unplanned" in r["drift"]]
    return {
        "base": base,
        "head": head,
        "plan": plan_name,
        "rows": rows,
        "untouched": untouched,
        "unverified": unverified,
        "summary": {
            "files": len(rows),
            "unplanned": len(unplanned),
            "untouched": len(untouched),
            "unverified": len(unverified),
        },
    }
