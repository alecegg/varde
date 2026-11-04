"""`varde learn skills reset <skill> --to-baseline`: propose restoring a baseline.

The proposal diffs the current skill tree against the generation's `slim/` copy,
so accepting it leaves exactly the baseline file set. No how pointer is added.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from varde_core import skill_props

from varde_learn.docs import baseline_cmd
from varde_learn.docs.flow.scan import text_tokens
from varde_learn.memory import store

from .cli_skills_reset import fail, report
from .improve import baseline_store as bs
from .improve import extract, reset, tool_entry
from .improve import record as rec

_VALUES = {"--baselines": "baselines", "--gen": "gen", "--root": "root"}
_USAGE = (
    "usage: skills reset <skill> --to-baseline --baselines <dir> "
    "[--gen <g>] [--root <dir>] [--dry-run]"
)


def run(
    args: list[str],
    io: object | None,
    roots: Sequence[Path] | None,
    sync: Path | None,
) -> int:
    as_json = "--json" in args
    parsed = _parse(args)
    if parsed is None:
        return fail(_USAGE, as_json, io)
    name, options = parsed
    try:
        package_roots = roots or (
            [Path(options["root"])] if "root" in options else None
        )
        record, diff = _proposal(name, options, package_roots, sync)
        if "--dry-run" not in args:
            rec.write_record(store.memory_root(Path.cwd()), record, diff)
    except (
        bs.BaselineStoreError,
        baseline_cmd.BaselineError,
        extract.ExtractError,
        rec.RecordError,
        OSError,
        ValueError,
    ) as error:
        return fail(str(error), as_json, io)
    report(io, record, diff, {}, dry_run="--dry-run" in args, as_json=as_json)
    return 0


def _parse(args: list[str]) -> tuple[str, dict[str, str]] | None:
    options: dict[str, str] = {}
    operands: list[str] = []
    queue = [a for a in args if a not in {"--json", "--dry-run", "--to-baseline"}]
    while queue:
        arg = queue.pop(0)
        if arg in _VALUES and queue:
            options[_VALUES[arg]] = queue.pop(0)
        elif arg.startswith("-"):
            return None
        else:
            operands.append(arg)
    if len(operands) != 1 or "baselines" not in options:
        return None
    return operands[0], options


def _proposal(
    name: str,
    options: dict[str, str],
    roots: Sequence[Path] | None,
    sync: Path | None,
) -> tuple[rec.LoopRecord, str]:
    manifest = baseline_cmd.find_manifest(Path(options["baselines"]))
    skills = baseline_cmd.read_json(manifest).get("skills") or {}
    if name not in skills:
        raise bs.BaselineStoreError(f"no baseline for skill '{name}'")
    entry = bs.newest_entry(skills[name], options.get("gen"))
    gen = str(entry["gen"])
    wanted = _baseline_tree(manifest, gen, name, entry)
    current, place = _current(name, roots, sync)
    changes = bs.restore_changes(bs.texts(current), bs.texts(wanted), place)
    if not changes:
        raise extract.ExtractError(f"{name} is already at baseline {gen}")
    plan = extract.Plan(tuple(changes), _route_delta(current, wanted))
    created = datetime.now(UTC).isoformat()
    route = text_tokens(current.get("SKILL.md", b"").decode("utf-8"))
    record = rec.LoopRecord(
        id=reset.reset_id(name, created),
        skill=name,
        direction="reset",
        change=reset.baseline_change(name, gen, skill_props.tree_hash(wanted)),
        created=created,
        token_delta=plan.token_delta,
        later_demand=reset.count_fields({}, route, route + plan.token_delta),
        pre_hashes=extract.pre_hashes(plan.changes),
    )
    return record, extract.render_diff(plan.changes)


def _baseline_tree(
    manifest: Path, gen: str, name: str, entry: dict
) -> dict[str, bytes]:
    for directory in baseline_cmd.generation_dirs(manifest, gen):
        try:
            return bs.verified_tree(entry, bs.baseline_tree(directory, name))
        except bs.BaselineStoreError as error:
            if "no slim copy" not in str(error):
                raise
    raise bs.BaselineStoreError(f"no slim copy of {name} for generation {gen}")


def _current(name: str, roots: Sequence[Path] | None, sync: Path | None):
    """The current tree of the skill and the file each layout path maps to."""
    if roots is not None:
        for root in roots:
            skill_dir = root / "skills" / name
            if (skill_dir / "SKILL.md").is_file():
                how_dir = root / "how" / name
                return bs.layout_tree(skill_dir, how_dir), _placer(skill_dir, how_dir)
        raise extract.ExtractError(f"no skill '{name}' under the given roots")
    skill_dir = tool_entry.installed_skill(
        sync or tool_entry.require_sync_target(), name
    )
    if skill_dir is None:
        raise extract.ExtractError(f"no synced skill '{name}'")
    return skill_props.disk_tree(skill_dir), _placer(skill_dir, skill_dir / "how")


def _placer(skill_dir: Path, how_dir: Path):
    def place(rel: str) -> str:
        if rel.startswith("how/"):
            return str(how_dir / rel.removeprefix("how/"))
        return str(skill_dir / rel)

    return place


def _route_delta(current: dict[str, bytes], wanted: dict[str, bytes]) -> int:
    return text_tokens(wanted.get("SKILL.md", b"").decode("utf-8")) - text_tokens(
        current.get("SKILL.md", b"").decode("utf-8")
    )
