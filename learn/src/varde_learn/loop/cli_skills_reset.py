"""`varde learn skills reset <skill>`: propose slimming after a model change."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error

from varde_learn.docs.flow.scan import text_tokens
from varde_learn.memory import store

from .help import help_text
from .improve import extract, promotion, reset, tool_entry
from .improve import record as rec

Demand = Callable[[str], dict[str, Any]]
_USAGE = (
    "usage: skills reset <skill> --model <id> --harness-version <v> "
    "[--no-pointer] [--dry-run] | skills reset <skill> --to-baseline "
    "--baselines <dir> [--gen <g>] [--root <dir>] [--dry-run]"
)
Planner = Callable[[str, Path, str, Path, set[str]], extract.Plan]


def run(
    args: list[str],
    io: object | None = None,
    roots: Sequence[Path] | None = None,
    demand: Demand | None = None,
    sync: Path | None = None,
) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        write(io, help_text("skills reset"))
        return 0
    as_json = "--json" in args
    if "--to-baseline" in args:
        from . import cli_skills_baseline

        return cli_skills_baseline.run(args, io, roots, sync)
    parsed = _parse(args)
    if parsed is None:
        return fail(_USAGE, as_json, io)
    name, model, harness, dry_run = parsed
    planner = reset.plan_skill_plain_reset if "--no-pointer" in args else None
    try:
        memory = store.memory_root(Path.cwd())
        counts = _counts(name, demand or promotion.read_demand_report)
        previous = _previous_reset(memory, name)
        try:
            plan = _plan(name, roots, sync or _sync_dir(roots), planner)
        except reset.AlreadySlim:
            if previous is None:
                raise
            return _compare_only(io, previous, counts, as_json)
        created = datetime.now(UTC).isoformat()
        route = text_tokens(plan.changes[0].old or "")
        fields = reset.count_fields(counts, route, route + plan.token_delta)
        record, diff = reset.build_record(name, model, harness, plan, fields, created)
        if not dry_run:
            rec.write_record(memory, record, diff)
    except (extract.ExtractError, rec.RecordError, OSError, ValueError) as error:
        return fail(str(error), as_json, io)
    comparison = reset.compare(previous, counts) if previous else {}
    report(io, record, diff, comparison, dry_run=dry_run, as_json=as_json)
    return 0


def _compare_only(
    io: object | None, previous: rec.LoopRecord, counts: dict[str, int], as_json: bool
) -> int:
    comparison = reset.compare(previous, counts)
    if as_json:
        body = json.dumps(
            success(
                {"id": previous.id, "comparison": comparison}, {"truncated": False}
            ),
            separators=(",", ":"),
        )
        write(io, body + "\n")
    else:
        lines = [f"already slim; comparison with reset {previous.id}:"]
        lines += [f"{n}: before {a}, now {b}" for n, (a, b) in comparison.items()]
        write(io, "\n".join(lines) + "\n")
    return 0


def _parse(args: list[str]) -> tuple[str, str, str, bool] | None:
    values: dict[str, str] = {}
    operands: list[str] = []
    queue = [arg for arg in args if arg not in {"--json", "--dry-run", "--no-pointer"}]
    while queue:
        arg = queue.pop(0)
        if arg in {"--model", "--harness-version"} and queue:
            values[arg] = queue.pop(0)
        elif arg.startswith("-"):
            return None
        else:
            operands.append(arg)
    if len(operands) != 1 or set(values) != {"--model", "--harness-version"}:
        return None
    return (
        operands[0],
        values["--model"],
        values["--harness-version"],
        "--dry-run" in args,
    )


def _sync_dir(roots: Sequence[Path] | None) -> Path | None:
    return None if roots is not None else tool_entry.require_sync_target()


def _plan(
    name: str,
    roots: Sequence[Path] | None,
    sync: Path | None,
    planner: Planner | None = None,
) -> extract.Plan:
    """A skill is slimmed at the sync target; agents come from package roots."""
    plan_skill = planner or reset.plan_skill_reset
    skill_dir = tool_entry.installed_skill(sync, name) if sync else None
    if skill_dir is not None:
        skill_md = skill_dir / "SKILL.md"
        how_dir = skill_dir / "how"
        return plan_skill(
            name, skill_md, rec.read_raw(skill_md), how_dir, _stems(how_dir)
        )
    for root in roots if roots is not None else tool_entry.package_roots():
        plan = _package_plan(root, name, plan_skill, from_roots=roots is not None)
        if plan is not None:
            return plan
    raise extract.ExtractError(f"no skill or agent '{name}'")


def _package_plan(
    root: Path, name: str, plan_skill: Planner, *, from_roots: bool
) -> extract.Plan | None:
    skill_md = root / "skills" / name / "SKILL.md"
    if from_roots and skill_md.is_file():
        how_dir = root / "how" / name
        return plan_skill(
            name, skill_md, rec.read_raw(skill_md), how_dir, _stems(how_dir)
        )
    agent_dir = root / "agents" / name
    caps = root / "agents" / "capabilities.json"
    if agent_dir.is_dir() and caps.is_file():
        return reset.plan_agent_reset(
            name, caps, rec.read_raw(caps), agent_dir, _stems(agent_dir / "how")
        )
    return None


def _stems(directory: Path) -> set[str]:
    return (
        {path.stem for path in directory.glob("*.md")} if directory.is_dir() else set()
    )


def _counts(name: str, demand: Demand) -> dict[str, int]:
    try:
        report = demand(name)
    except OSError, ValueError, KeyError:
        return {"requests": 0, "failures": 0, "friction": 0}
    rows = report.get("steps", [])
    return {
        key: sum(row[key] for row in rows)
        for key in ("requests", "failures", "friction")
    }


def _previous_reset(memory: Path, name: str) -> rec.LoopRecord | None:
    done = [
        r
        for r in rec.list_records(memory)
        if r.direction == "reset" and r.skill == name and r.state == "applied"
    ]
    return max(done, key=lambda r: r.created, default=None)


def report(
    io: object | None,
    record: rec.LoopRecord,
    diff: str,
    comparison: dict[str, tuple[int, int]],
    *,
    dry_run: bool,
    as_json: bool,
) -> None:
    if as_json:
        data = {
            "dry_run": dry_run,
            "id": record.id,
            "token_delta": record.token_delta,
            "counts": record.later_demand,
            "comparison": comparison,
            "diff": diff,
        }
        body = json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
        write(io, body + "\n")
        return
    lines = [diff] if dry_run else []
    verb = "dry run, nothing written" if dry_run else f"proposal {record.id} written"
    lines.append(f"{verb}; token delta {record.token_delta:+d}")
    lines += [f"{name}: before {a}, now {b}" for name, (a, b) in comparison.items()]
    write(io, "\n".join(lines) + "\n")


def fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error("skills_reset_failed", message), separators=(",", ":")
        )
        write(io, body + "\n", error=True)
    else:
        write(io, f"error: {message}\n", error=True)
    return 2


def write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
