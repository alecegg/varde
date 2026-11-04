"""Report how-topic requests, friction and fills (`learn skills demand`)."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_core.envelope import success, tool_error

from . import analyzed
from .calls import (
    FAILURE,
    SUCCESS,
    CallRow,
    parse_timestamp,
    parse_window,
    read_calls_strict,
)
from .calls_retention import note_calls_used, report_meta
from .errors import StoreConfig, StoreIo
from .friction_repository import open_repository
from .help import help_text
from .store.paths import resolve_store_dir

_HOW_COMMANDS = frozenset(
    {"doc how", "learn how"}
)  # recorded command strings: history, then the renamed command
_TOOL_PREFIX = "tool "  # `tool <skill>` rows from counted step tools
_TARGET_PREFIX = "how/"
_CUT_TAG = re.compile(r"st-g[0-9]+-[0-9]{3}")
_PAGE = 1_000
_CANDIDATE_CAP = 20
_HOW_SKIP_TAG = "how-skip"


def run(argv: list[str], io: object | None = None) -> int:
    args = list(argv)
    if args[:2] == ["skills", "demand"]:
        args = args[2:]
    if any(token in {"-h", "--help"} for token in args):
        _write(io, help_text("skills demand"))
        return 0
    json_requested = "--json" in args
    try:
        window, changelog, skill = _parse(args)
        duration = None if window is None else parse_window(window)
        cutoff = None if duration is None else datetime.now(UTC) - duration
        lines = _read_changelog(changelog)
        calls = [row for row in read_calls_strict() if _in_window(row["ts"], cutoff)]
        items = [
            item
            for item in _read_friction(open_repository())
            if _in_window(item.created_at, cutoff)
        ]
        ledger = [
            row
            for row in analyzed.read_all(resolve_store_dir())
            if _in_window(row.get("analyzed_at", ""), cutoff)
        ]
        report = for_skill(build_report(calls, items, lines, ledger), skill)
        note_calls_used(calls)
        meta = report_meta(window or "all", duration)
        if json_requested:
            _write(io, _dump(success(report, meta)))
        else:
            _write(io, _format(report))
    except (StoreConfig, StoreIo, ValueError, OSError) as error:
        _error(io, error, json_requested)
        return 2
    return 0


def _parse(args: list[str]) -> tuple[str | None, Path | None, str | None]:
    window: str | None = None
    changelog: Path | None = None
    skill: str | None = None
    queue = [value for value in args if value != "--json"]
    while queue:
        argument = queue.pop(0)
        if argument in {"--window", "--changelog"} and not queue:
            raise ValueError(f"{argument} requires a value")
        if argument == "--window":
            window = queue.pop(0)
        elif argument == "--changelog":
            changelog = Path(queue.pop(0))
        elif argument.startswith("-") or skill is not None:
            raise ValueError(f"unexpected argument '{argument}'")
        else:
            skill = argument
    return window, changelog, skill


def for_skill(report: dict[str, Any], skill: str | None) -> dict[str, Any]:
    """Keep only one skill's step rows and skill row; no skill keeps the report."""
    if skill is None:
        return report
    return report | {
        "steps": [row for row in report["steps"] if _skill_of(row["step"]) == skill],
        "skills": [row for row in report["skills"] if row["skill"] == skill],
    }


def _in_window(timestamp: str, cutoff: datetime | None) -> bool:
    if cutoff is None:
        return True
    when = parse_timestamp(timestamp)
    return when is not None and when >= cutoff


def _read_changelog(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    lines = []
    for number, text in enumerate(path.read_text().splitlines(), 1):
        if not text.strip():
            continue
        try:
            value = json.loads(text)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: invalid JSON line") from error
        if isinstance(value, dict):
            lines.append(value)
    return lines


def _read_friction(repository: Any) -> list[Any]:
    """Page through every friction item; the target filter is client-side."""
    items: list[Any] = []
    while True:
        page = repository.list_items(offset=len(items), limit=_PAGE)
        items.extend(page.items)
        if not page.items or len(items) >= page.total:
            return items


def _cut_steps(lines: list[dict[str, Any]]) -> dict[str, str]:
    """Map a cut id (the `st-g<k>-<nnn>` tag) to its step id."""
    return {
        str(line["id"]): str(line["step"])
        for line in lines
        if line.get("kind") == "cut" and line.get("id") and line.get("step")
    }


def friction_step(item: Any, cut_steps: dict[str, str]) -> str | None:
    """Return the step a friction item is about; target wins over the cut tag."""
    target = item.target or ""
    if target.startswith(_TARGET_PREFIX):
        return target.removeprefix(_TARGET_PREFIX)
    for tag in item.tags:
        if _CUT_TAG.fullmatch(tag) and tag in cut_steps:
            return cut_steps[tag]
    return None


def fill_counts(lines: list[dict[str, Any]]) -> dict[str, int]:
    """Count active fills per step; a fill without a step takes its cut's step."""
    cuts = _cut_steps(lines)
    counts: dict[str, int] = defaultdict(int)
    for line in lines:
        if line.get("kind") != "fill" or line.get("status", "active") != "active":
            continue
        step = line.get("step") or cuts.get(str(line.get("cut_id")))
        if step:
            counts[str(step)] += 1
    return dict(counts)


def _is_demand_row(command: str) -> bool:
    return command in _HOW_COMMANDS or command.startswith(_TOOL_PREFIX)


def _skill_of(step: str) -> str:
    return step.split("/", 1)[0]


def _ledger_skill_stats(
    ledger: Sequence[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Aggregate ledger `metrics["skills"]` per skill; rows without it add nothing."""
    stats: dict[str, dict[str, Any]] = {}
    for row in ledger:
        skills = (row.get("metrics") or {}).get("skills")
        if not isinstance(skills, dict):
            continue
        for skill, found in skills.items():
            if not isinstance(found, dict):
                continue
            entry = stats.setdefault(
                skill,
                {"runs": 0, "with_load": 0, "skips": 0, "candidates": []},
            )
            entry["runs"] += 1
            if found.get("loads"):
                entry["with_load"] += 1
            if found.get("suspected_skip"):
                entry["skips"] += 1
                entry["candidates"].append(
                    {
                        "session": row.get("session"),
                        "harness": row.get("harness"),
                        "post_errors": found.get("post_errors", 0),
                        "first_error": found.get("first_error"),
                    }
                )
    return stats


def _how_skip_counts(items: Sequence[Any]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        source = getattr(item, "source", None)
        if source and _HOW_SKIP_TAG in item.tags:
            counts[source] += 1
    return dict(counts)


def build_report(
    calls: list[CallRow],
    items: list[Any],
    lines: list[dict[str, Any]],
    ledger: Sequence[dict[str, Any]] = (),
) -> dict[str, Any]:
    cut_steps = _cut_steps(lines)
    steps: dict[str, dict[str, Any]] = {}
    sessions: dict[str, set[str]] = defaultdict(set)
    skill_sessions: dict[str, set[str]] = defaultdict(set)

    def entry(step: str) -> dict[str, Any]:
        return steps.setdefault(
            step,
            {
                "step": step,
                "requests": 0,
                "failures": 0,
                "unknown_session_requests": 0,
                "sessions": 0,
                "friction": 0,
                "friction_ids": [],
                "fills": 0,
            },
        )

    for row in calls:
        step = row.get("arg")
        if not _is_demand_row(row["command"]) or step is None:
            continue
        if row["status"] == FAILURE:
            entry(step)["failures"] += 1
        elif row["status"] == SUCCESS:
            entry(step)["requests"] += 1
            _note_session(row.get("session"), step, entry(step), sessions)
        session = row.get("session")
        if row["status"] in {SUCCESS, FAILURE} and session:
            skill_sessions[_skill_of(step)].add(session)
    unknown_by_skill: dict[str, int] = defaultdict(int)
    for step, row in steps.items():
        unknown_by_skill[_skill_of(step)] += row["unknown_session_requests"]
    friction_items: dict[str, int] = defaultdict(int)
    for item in items:
        step = friction_step(item, cut_steps)
        if step is not None:
            entry(step)["friction"] += 1
            entry(step)["friction_ids"].append(item.id)
            friction_items[_skill_of(step)] += 1
    for step, count in fill_counts(lines).items():
        entry(step)["fills"] = count
    for step, found in sessions.items():
        steps[step]["sessions"] = len(found)
    ledger_stats = _ledger_skill_stats(ledger)
    how_skip = _how_skip_counts(items)
    requested = {_skill_of(step) for step, row in steps.items() if row["requests"]}
    names = {_skill_of(step) for step in steps} | set(ledger_stats) | set(how_skip)
    skills = [
        _skill_row(
            skill,
            ledger_stats.get(skill),
            observed_load=skill in requested
            or bool(ledger_stats.get(skill, {}).get("with_load")),
        )
        | {
            "sessions_with_request": len(skill_sessions.get(skill, ())),
            "unknown_session_requests": unknown_by_skill.get(skill, 0),
            "friction_items": friction_items.get(skill, 0),
            "how_skip_friction": how_skip.get(skill, 0),
        }
        for skill in sorted(names)
    ]
    return {
        "steps": [steps[step] for step in sorted(steps)],
        "skills": skills,
        "swept_sessions": len(ledger),
    }


def _skill_row(
    skill: str, stats: dict[str, Any] | None, *, observed_load: bool
) -> dict[str, Any]:
    stats = stats or {"runs": 0, "with_load": 0, "skips": 0, "candidates": []}
    return {
        "skill": skill,
        "runs": stats["runs"],
        "runs_with_load": stats["with_load"],
        "suspected_skips": stats["skips"] if observed_load else None,
        "suspected_skip_candidates": stats["candidates"][:_CANDIDATE_CAP],
    }


def _note_session(
    session: str | None,
    step: str,
    row: dict[str, Any],
    sessions: dict[str, set[str]],
) -> None:
    if session is None:
        row["unknown_session_requests"] += 1
    else:
        sessions[step].add(session)


def _format(report: dict[str, Any]) -> str:
    rows = report["steps"]
    if not rows:
        return "No how topics recorded.\n"
    lines = []
    for row in rows:
        unknown = row["unknown_session_requests"]
        extra = f", {unknown} with unknown session" if unknown else ""
        lines.append(
            f"{row['step']}: {row['requests']} requests ({row['failures']} failed)"
            f", {row['sessions']} sessions{extra}, {row['friction']} friction"
            f", {row['fills']} fills"
        )
    lines.append(f"Swept sessions: {report['swept_sessions']}")
    lines.append("Skills (sessions with a how call, friction items):")
    for skill in report["skills"]:
        skips = skill["suspected_skips"]
        shown = "n/a" if skips is None else skips
        lines.append(
            f"  {skill['skill']}: {skill['sessions_with_request']} sessions, "
            f"{skill['friction_items']} friction, {skill['runs']} runs, "
            f"{skill['runs_with_load']} with load, {shown} suspected skips, "
            f"{skill['how_skip_friction']} how-skip friction"
        )
    return "\n".join(lines) + "\n"


def _dump(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"


def _error(io: object | None, error: Exception, as_json: bool) -> None:
    if as_json:
        code = getattr(error, "code", "usage_error")
        _write(io, json.dumps(tool_error(code, str(error))) + "\n", True)
    else:
        _write(io, f"error: {error}\n", True)


def _write(io: object | None, value: str, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    (stream or getattr(sys, "stderr" if error else "stdout")).write(value)
