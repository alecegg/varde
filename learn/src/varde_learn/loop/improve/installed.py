"""Edits to synced skills: which paths `accept` may write and the sidecar update.

A synced skill dir `<sync target>/<skill>/` holds SKILL.md, references, assets,
`how/` and `step_tools/`. Proposals may only touch those, in skills carrying the
sidecar. After a write the sidecar's `loop-hash` records the new tree.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path

from varde_core import skill_props

EDITABLE = ("SKILL.md", "references", "assets", "how", "step_tools")
OUTSIDE = "outside the installed skill directory"
FOREIGN = "not a synced skill (no sidecar)"


def skill_name(path: str, skills_dir: Path) -> str | None:
    """The skill dir name `path` lies in, or None outside editable skill files."""
    candidate = Path(path)
    if not candidate.is_absolute() or ".." in candidate.parts:
        return None
    target = candidate.resolve()
    base = skills_dir.resolve()
    if not target.is_relative_to(base):
        return None
    parts = target.relative_to(base).parts
    return parts[0] if len(parts) > 1 and parts[1] in EDITABLE else None


def problem(paths: Iterable[str], skills_dir: Path) -> str | None:
    """Why `paths` cannot be edited at the sync target, or None when they can."""
    for path in sorted(paths):
        name = skill_name(path, skills_dir)
        if name is None:
            return f"{OUTSIDE}: {path}"
        sidecar = skills_dir / name / skill_props.SIDECAR
        if not sidecar.is_file() or sidecar.is_symlink():
            return f"{FOREIGN}: {name}"
    return None


def _touched(paths: Iterable[str], skills_dir: Path) -> list[str]:
    names = {skill_name(path, skills_dir) for path in paths}
    return sorted(name for name in names if name)


def _tree_digest(directory: Path) -> str:
    return skill_props.tree_hash(skill_props.disk_tree(directory))


def loop_tracked(paths: Iterable[str], skills_dir: Path) -> frozenset[str]:
    """Touched skills whose tree is still the packaged or last loop-written one.

    Call before writing: a skill with hand edits is not tracked, so its edits stay
    visible as `hand-modified` after the accept.
    """
    tracked = set()
    for name in _touched(paths, skills_dir):
        directory = skills_dir / name
        props = skill_props.parse((directory / skill_props.SIDECAR).read_text())
        digest = _tree_digest(directory)
        if digest in {props.packaged_hash, props.loop_hash}:
            tracked.add(name)
    return frozenset(tracked)


def refresh_sidecars(
    paths: Iterable[str],
    skills_dir: Path,
    tracked: frozenset[str],
    baseline_hash: str | None = None,
) -> list[str]:
    """Record the on-disk tree hash as `loop-hash` of each tracked skill touched.

    After a baseline restore, `baseline_hash` (already verified equal to the disk
    tree) is recorded for every touched skill, hand-edited or not. Returns the
    touched skills left unrecorded because they had hand edits.
    """
    skipped = []
    for name in _touched(paths, skills_dir):
        if name not in tracked and baseline_hash is None:
            skipped.append(name)
            continue
        sidecar = skills_dir / name / skill_props.SIDECAR
        props = skill_props.parse(sidecar.read_text())
        digest = baseline_hash or _tree_digest(skills_dir / name)
        sidecar.write_text(skill_props.render(replace(props, loop_hash=digest)))
    return skipped


def installed_mismatch(
    paths: Iterable[str], skills_dir: Path, expected: str
) -> list[str]:
    """Touched skills whose on-disk tree does not hash to `expected`."""
    return [
        name
        for name in _touched(paths, skills_dir)
        if _tree_digest(skills_dir / name) != expected
    ]
