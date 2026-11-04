"""`varde learn skills extract <skill> <step>`: propose a counted-tool extraction."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from varde_core.envelope import success, tool_error

from varde_learn.memory import store

from .help import help_text
from .improve import extract, tool_entry
from .improve import record as rec


def run(
    args: list[str],
    io: object | None = None,
    roots: Sequence[Path] | None = None,
    sync: Path | None = None,
) -> int:
    if any(arg in {"-h", "--help"} for arg in args):
        _write(io, help_text("skills extract"))
        return 0
    as_json = "--json" in args
    dry_run = "--dry-run" in args
    operands = [arg for arg in args if arg not in {"--json", "--dry-run"}]
    if len(operands) not in {1, 2} or any(arg.startswith("-") for arg in operands):
        usage = "usage: skills extract <skill> [<step>] [--dry-run]"
        return _fail(usage, as_json, io)
    if len(operands) == 1:
        return _list_steps(operands[0], roots, sync, io, as_json=as_json)
    name, step = operands
    try:
        plan = _plan(name, step, roots, sync or _sync_dir(roots))
        created = datetime.now(UTC).isoformat()
        record, diff = extract.build_record(name, step, plan, created)
        if not dry_run:
            rec.write_record(store.memory_root(Path.cwd()), record, diff)
    except (extract.ExtractError, rec.RecordError, OSError, ValueError) as error:
        return _fail(str(error), as_json, io)
    _report(io, record, diff, dry_run=dry_run, as_json=as_json)
    return 0


def _sync_dir(roots: Sequence[Path] | None) -> Path | None:
    return None if roots is not None else tool_entry.require_sync_target()


def _plan(
    name: str, step: str, roots: Sequence[Path] | None, sync: Path | None
) -> extract.Plan:
    """A skill step is read from the synced skill; agents from package roots."""
    skill_dir = tool_entry.installed_skill(sync, name) if sync else None
    topic = skill_dir / "how" / f"{step}.md" if skill_dir else None
    if skill_dir and topic and topic.is_file():
        return _skill_plan(skill_dir, name, step, topic)
    for root in roots if roots is not None else tool_entry.package_roots():
        plan = _package_plan(root, name, step, from_roots=roots is not None)
        if plan is not None:
            return plan
    steps = _step_names(name, roots, sync)
    raise extract.ExtractError(extract.unknown_step_message(name, step, steps))


def _list_steps(
    name: str,
    roots: Sequence[Path] | None,
    sync: Path | None,
    io: object | None,
    *,
    as_json: bool,
) -> int:
    try:
        steps = _step_names(name, roots, _sync_dir(roots) if sync is None else sync)
    except (OSError, ValueError) as error:
        return _fail(str(error), as_json, io)
    if not steps:
        return _fail(f"no steps for '{name}'. {extract.NO_HOW_HINT}", as_json, io)
    if as_json:
        body = success({"steps": sorted(steps)}, {"truncated": False})
        _write(io, json.dumps(body, separators=(",", ":")) + "\n")
    else:
        _write(io, extract.format_steps(steps))
    return 0


def _step_names(
    name: str, roots: Sequence[Path] | None, sync: Path | None
) -> list[str]:
    """Step names: how topics of the synced skill, else the package; agent sections."""
    skill_dir = tool_entry.installed_skill(sync, name) if sync else None
    topics = [skill_dir / "how"] if skill_dir else []
    package = roots if roots is not None else tool_entry.package_roots()
    topics += [root / "how" / name for root in package]
    for directory in topics:
        stems = sorted(path.stem for path in directory.glob("*.md"))
        if stems:
            return stems
    return [step for root in package for step in _agent_slugs(root, name)]


def _agent_slugs(root: Path, name: str) -> list[str]:
    caps = root / "agents" / "capabilities.json"
    if not (root / "agents" / name).is_dir() or not caps.is_file():
        return []
    for profile in json.loads(caps.read_text()).get("profiles", []):
        if profile.get("name") == name:
            return extract.section_slugs(profile.get("instructions", ""))
    return []


def _package_plan(
    root: Path, name: str, step: str, *, from_roots: bool
) -> extract.Plan | None:
    topic = root / "how" / name / f"{step}.md"
    if from_roots and topic.is_file():
        return _skill_plan(root, name, step, topic)
    agent_dir = root / "agents" / name
    if agent_dir.is_dir() and (root / "agents" / "capabilities.json").is_file():
        return _agent_plan(root, name, step, agent_dir)
    return None


def _read(path: Path) -> str | None:
    return rec.read_raw(path) if path.is_file() else None


def _skill_plan(root: Path, name: str, step: str, topic: Path) -> extract.Plan:
    script = root / tool_entry.TOOLS_DIR / tool_entry.entry_for(name, step)
    return extract.plan_skill_step(
        name,
        step,
        topic,
        rec.read_raw(topic),
        root,
        extract.Existing(_read(tool_entry.registry_path(root)), _read(script)),
    )


def _agent_plan(root: Path, name: str, step: str, agent_dir: Path) -> extract.Plan:
    script = agent_dir / tool_entry.TOOLS_DIR / tool_entry.entry_for(name, step)
    capabilities = root / "agents" / "capabilities.json"
    return extract.plan_agent_step(
        name,
        step,
        capabilities,
        rec.read_raw(capabilities),
        agent_dir,
        extract.Existing(
            _read(tool_entry.registry_path(agent_dir)),
            _read(script),
            _read(agent_dir / "how" / f"{step}.md"),
        ),
    )


def _report(
    io: object | None,
    record: rec.LoopRecord,
    diff: str,
    *,
    dry_run: bool,
    as_json: bool,
) -> None:
    if as_json:
        data = {
            "dry_run": dry_run,
            "id": record.id,
            "token_delta": record.token_delta,
            "diff": diff,
        }
        _write(
            io,
            json.dumps(success(data, {"truncated": False}), separators=(",", ":"))
            + "\n",
        )
    elif dry_run:
        _write(
            io,
            diff + f"token delta: {record.token_delta:+d} (dry run, nothing written)\n",
        )
    else:
        _write(
            io, f"proposal {record.id} written; token delta {record.token_delta:+d}\n"
        )


def _fail(message: str, as_json: bool, io: object | None) -> int:
    if as_json:
        body = json.dumps(
            tool_error("skills_extract_failed", message), separators=(",", ":")
        )
        _write(io, body + "\n", error=True)
    else:
        _write(io, f"error: {message}\n", error=True)
    return 2


def _write(io: object | None, text: str, *, error: bool = False) -> None:
    stream = getattr(io, "stderr" if error else "stdout", None) if io else None
    print(text, end="", file=stream or (sys.stderr if error else sys.stdout))
