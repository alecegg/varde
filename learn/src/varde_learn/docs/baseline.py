"""Baseline status logic: compare current skill files with the newest baseline.

Pure functions over plain data; file and git reads live in ``baseline_cmd``.
A current state maps a reference to its sha256: ``<skill>/<path>`` for a skill
file and ``how/<skill>/<step>`` for a how topic.
"""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

CommitTouches = Callable[[str, str], bool]
"""``(commit, ref) -> bool``: whether the commit changed the file behind ``ref``."""


def sha256_text(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def baseline_refs(skill: str, entry: Mapping[str, object]) -> dict[str, str]:
    """Reference to sha256 for one baselines entry of a skill."""
    refs: dict[str, str] = {}
    files = entry.get("files")
    for path, sha in (files if isinstance(files, dict) else {}).items():
        refs[path if path.startswith(f"{skill}/") else f"{skill}/{path}"] = sha
    how = entry.get("how")
    for step, info in (how if isinstance(how, dict) else {}).items():
        refs[f"how/{skill}/{step}"] = info["sha256"]
    return refs


def changed_refs(
    baseline: Mapping[str, str], current: Mapping[str, str]
) -> dict[str, str]:
    """Reference to ``changed``, ``added`` or ``removed`` against the baseline."""
    result = {}
    for ref in sorted(baseline.keys() | current.keys()):
        if ref not in current:
            result[ref] = "removed"
        elif ref not in baseline:
            result[ref] = "added"
        elif baseline[ref] != current[ref]:
            result[ref] = "changed"
    return result


def latest_fills(changelog: list[dict]) -> list[dict]:
    """Fill lines with the last line per `id` winning (a retire line replaces it)."""
    latest: dict[str, dict] = {}
    for line in changelog:
        if line.get("kind") == "fill":
            latest[str(line.get("id"))] = line
    return list(latest.values())


def active_fills(changelog: list[dict], skill: str, gen: str) -> list[dict]:
    return [
        line
        for line in latest_fills(changelog)
        if line.get("skill") == skill
        and line.get("gen") == gen
        and line.get("status") == "active"
    ]


def fill_names_ref(fill: Mapping[str, object], skill: str, ref: str) -> bool:
    """Whether a fill lists the file or step behind ``ref``."""
    if ref.startswith("how/"):
        return fill.get("step") == ref.removeprefix("how/")
    path = fill.get("path")
    if not isinstance(path, str) or not path:
        return False
    return ref == (path if path.startswith(f"{skill}/") else f"{skill}/{path}")


def explaining_fill(
    fills: list[dict], skill: str, ref: str, commit_touches: CommitTouches
) -> str | None:
    """Id of an active fill naming ``ref`` with a commit that touches it."""
    for fill in fills:
        commit = fill.get("commit")
        if not commit or not fill_names_ref(fill, skill, ref):
            continue
        if commit_touches(str(commit), ref):
            return str(fill["id"])
    return None


@dataclass
class SkillStatus:
    skill: str
    baseline: dict | None
    original: dict | None
    changes: list[dict] = field(default_factory=list)
    fills: list[dict] = field(default_factory=list)
    diff: dict | None = None
    tree_hash_match: bool | None = None  # None: no recorded tree_hash or not read

    @property
    def drift(self) -> bool | None:
        if self.baseline is None:
            return None
        return any(change["fill"] is None for change in self.changes)

    def to_json(self) -> dict:
        return {
            "skill": self.skill,
            "baseline": self.baseline,
            "original": self.original,
            "diff": self.diff,
            "gap_fills": self.fills,
            "changes": self.changes,
            "drift": self.drift,
            "tree_hash_match": self.tree_hash_match,
        }


def skill_status(
    skill: str,
    entry: Mapping[str, object],
    changelog: list[dict],
    current: Mapping[str, str],
    commit_touches: CommitTouches,
) -> SkillStatus:
    """Compare ``current`` (refs of this skill only) with the newest baseline."""
    raw_baselines = entry.get("baselines")
    baselines: list[dict] = raw_baselines if isinstance(raw_baselines, list) else []
    original = entry.get("original")
    original_info = (
        {"tag": original.get("tag"), "commit": original.get("commit")}
        if isinstance(original, dict)
        else None
    )
    if not baselines:
        return SkillStatus(skill, None, original_info)
    newest = baselines[-1]
    gen = newest["gen"]
    baseline_info = {
        "gen": gen,
        "tag": newest.get("tag"),
        "commit": newest.get("commit"),
    }
    fills = active_fills(changelog, skill, gen)
    changes = [
        {
            "ref": ref,
            "change": change,
            "fill": explaining_fill(fills, skill, ref, commit_touches),
        }
        for ref, change in changed_refs(baseline_refs(skill, newest), current).items()
    ]
    gap_fills = [
        {
            "fill": fill["id"],
            "step": fill.get("step") or "",
            "path": fill.get("path") or "",
            "tokens_added": fill.get("tokens_added", 0),
        }
        for fill in fills
    ]
    return SkillStatus(skill, baseline_info, original_info, changes, gap_fills)


def diff_size(old: str, new: str, tokens: Callable[[str], int]) -> dict[str, int]:
    """Lines added and removed, and the token difference, from ``old`` to ``new``."""
    added = removed = 0
    for line in difflib.unified_diff(
        old.splitlines(), new.splitlines(), lineterm="", n=0
    ):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return {
        "lines_added": added,
        "lines_removed": removed,
        "tokens": tokens(new) - tokens(old),
    }
