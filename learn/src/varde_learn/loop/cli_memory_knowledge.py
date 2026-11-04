"""Report data and text for `memory migrate --knowledge` (dry run, apply, undo)."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from varde_learn.memory import migrate_knowledge as mk


def plan_data(root: Path, bundle: Path, scope_key: str, *, apply: bool) -> dict:
    plan = mk.plan_migration(bundle, root, scope_key)
    result = mk.apply_migration(root, plan) if apply else None
    data = {
        "bundle": str(bundle),
        "applied": apply,
        "files": plan.files,
        "entries": len(plan.planned),
        "types": plan.type_counts(),
        "collisions": [asdict(r) for r in plan.collisions],
        "rejects": [asdict(r) for r in plan.rejects],
        "links": [asdict(c) for c in plan.links],
        "created": [str(p) for p in result.created] if result else [],
        "unchanged": [str(p) for p in result.unchanged] if result else [],
        "record": str(result.record) if result and result.record else "",
    }
    return data | {"text": _plan_text(plan, data)}


def undo_data(root: Path, bundle: Path) -> dict:
    result = mk.undo_migration(root, bundle)
    data = {
        "bundle": str(bundle),
        "removed": [str(p) for p in result.removed],
        "skipped": [str(p) for p in result.skipped],
        "missing": [str(p) for p in result.missing],
        "record_removed": result.record_removed,
        "record_kept": result.record_kept,
    }
    lines = [f"removed {len(result.removed)} entries"]
    lines += [f"skipped (changed or outside the root): {p}" for p in result.skipped]
    lines += [f"already gone: {p}" for p in result.missing]
    if result.record_kept:
        lines.append(
            "migration record kept: changed entries stay in the store and the "
            "bundle still reads from it; restore or delete them, then undo again"
        )
    elif not result.record_removed:
        lines.append("no migration record found")
    return data | {"text": "\n".join(lines)}


def _plan_text(plan: mk.Plan, data: dict) -> str:
    verb = "applied" if data["applied"] else "dry run (nothing written)"
    types = ", ".join(f"{k}: {v}" for k, v in plan.type_counts().items())
    lines = [
        f"{verb}: {plan.bundle}",
        f"files: {plan.files}",
        f"entries: {len(plan.planned)}" + (f" ({types})" if types else ""),
        f"collisions: {len(plan.collisions)}",
        f"secret rejects: {sum(r.kind == 'secret' for r in plan.rejects)}",
        f"other rejects: {sum(r.kind != 'secret' for r in plan.rejects)}",
    ]
    lines += [f"  {r.kind} {r.slug}: {r.reason}" for r in plan.rejects]
    lines += [f"  collision {r.slug}: {r.reason}" for r in plan.collisions]
    rewritten = [c for c in plan.links if c.target]
    broken = [c for c in plan.links if not c.target]
    lines.append(f"links rewritten: {len(rewritten)}")
    lines += [f"  {c.slug}: {c.link} -> {c.target}" for c in rewritten]
    lines.append(f"links left broken: {len(broken)}")
    lines += [f"  {c.slug}: {c.link}" for c in broken]
    lines += [f"created {path}" for path in data["created"]]
    if data["record"]:
        lines.append(f"record {data['record']}")
    return "\n".join(lines)
