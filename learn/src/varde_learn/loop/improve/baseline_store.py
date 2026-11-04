"""Baseline file sets: record a skill's no-how baseline and restore to it.

A skill's synced layout is `SKILL.md`, references, assets, `step_tools/` and
`how/<step>.md`. `layout_tree` builds that tree from a repo source (skill dir plus
how dir) or from a synced dir, so one `tree_hash` covers both. Baseline copies
sit in `<generation dir>/slim/`: `slim/<skill>/<path>` and
`slim/how/[<module>/]<skill>/<step>.md`.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path

from varde_core import skill_props

from .extract import FileChange

_VERSION = re.compile(r"^version:\s*(\S+)", re.MULTILINE)


class BaselineStoreError(ValueError):
    """The baseline cannot be recorded or restored."""


def layout_tree(skill_dir: Path, how_dir: Path | None) -> dict[str, bytes]:
    """Hashed files of a skill in synced layout; how topics land under `how/`."""
    tree = skill_props.disk_tree(skill_dir)
    if how_dir is not None and how_dir.is_dir():
        for path in sorted(how_dir.glob("*.md")):
            tree.setdefault(f"how/{path.name}", path.read_bytes())
    return tree


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_entry(
    skill: str,
    gen: str,
    tree: Mapping[str, bytes],
    all_files: Mapping[str, bytes],
    meta: Mapping[str, object],
) -> dict[str, object]:
    """A MANIFEST `baselines[]` entry: files, how topics and the tree hash."""
    how = {
        path.removeprefix("how/").removesuffix(".md"): {
            "version": _version(data.decode("utf-8")),
            "sha256": sha256_bytes(data),
        }
        for path, data in sorted(tree.items())
        if path.startswith("how/")
    }
    files = {
        f"{skill}/{path}": sha256_bytes(data)
        for path, data in sorted(all_files.items())
        if not path.startswith("how/")
    }
    return {
        "gen": gen,
        **meta,
        "files": files,
        "how": how,
        "tree_hash": skill_props.tree_hash(tree),
    }


def _version(text: str) -> int | str:
    found = _VERSION.search(text)
    if found is None:
        return 1
    return int(found[1]) if found[1].isdigit() else found[1]


def source_files(skill_dir: Path) -> dict[str, bytes]:
    """Every installable file under a skill dir, for `files` (no evals/)."""
    return {
        rel: path.read_bytes()
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file()
        and skill_props.is_hashed_path(rel := path.relative_to(skill_dir).as_posix())
    }


def write_slim(
    generation_dir: Path,
    skill: str,
    all_files: Mapping[str, bytes],
    tree: Mapping[str, bytes],
) -> None:
    """Copy the baseline text under `slim/`, replacing earlier copies of the skill."""
    slim = generation_dir / "slim"
    skill_files = dict(all_files)
    how_files = {
        path.removeprefix("how/"): data
        for path, data in tree.items()
        if path.startswith("how/")
    }
    _replace_dir(slim / skill, skill_files)
    _replace_dir(slim / "how" / skill, how_files)


def _replace_dir(target: Path, files: Mapping[str, bytes]) -> None:
    """Write `files` to a staging directory, then swap it in for `target`."""
    staging = target.with_name(f".{target.name}.staging")
    shutil.rmtree(staging, ignore_errors=True)
    for path, data in files.items():
        _write_bytes(staging / path, data)
    shutil.rmtree(target, ignore_errors=True)
    if files:
        staging.rename(target)


def _write_bytes(target: Path, data: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


def newest_entry(skill_entry: Mapping[str, object], gen: str | None) -> dict:
    """The baseline entry of `gen`, or the newest one."""
    entries = skill_entry.get("baselines")
    found = (
        [e for e in entries if isinstance(e, dict)] if isinstance(entries, list) else []
    )
    if gen is not None:
        found = [entry for entry in found if entry.get("gen") == gen]
    if not found:
        raise BaselineStoreError(f"no baseline entry{f' for gen {gen}' if gen else ''}")
    return found[-1]


def baseline_tree(generation_dir: Path, skill: str) -> dict[str, bytes]:
    """The baseline files of a skill in synced layout, read from `slim/`."""
    slim = generation_dir / "slim"
    tree: dict[str, bytes] = {}
    skill_root = slim / skill
    if skill_root.is_dir():
        for path in sorted(skill_root.rglob("*")):
            rel = path.relative_to(skill_root).as_posix()
            if path.is_file() and skill_props.is_hashed_path(rel):
                tree[rel] = path.read_bytes()
    for how_root in [slim / "how" / skill, *sorted(slim.glob(f"how/*/{skill}"))]:
        for path in sorted(how_root.glob("*.md")) if how_root.is_dir() else []:
            tree.setdefault(f"how/{path.name}", path.read_bytes())
    if not tree:
        raise BaselineStoreError(f"no slim copy of {skill} under {slim}")
    return tree


def verified_tree(
    entry: Mapping[str, object], tree: Mapping[str, bytes]
) -> dict[str, bytes]:
    """`tree` when its hash equals the entry's `tree_hash` (when recorded)."""
    expected = entry.get("tree_hash")
    if expected and skill_props.tree_hash(tree) != expected:
        raise BaselineStoreError(
            "slim copy does not match the recorded tree_hash of the baseline"
        )
    return dict(tree)


def restore_changes(
    current: Mapping[str, str], baseline: Mapping[str, str], place: Callable[[str], str]
) -> list[FileChange]:
    """Changes turning the current tree into the baseline one (pure).

    Keys are layout-relative paths; `place` maps one to the file to edit. Files
    absent from the baseline are deleted.
    """
    changes = []
    for rel in sorted(current.keys() | baseline.keys()):
        old, new = current.get(rel), baseline.get(rel)
        if old != new:
            changes.append(FileChange(place(rel), old, new))
    return changes


def texts(tree: Mapping[str, bytes]) -> dict[str, str]:
    return {path: data.decode("utf-8") for path, data in tree.items()}
