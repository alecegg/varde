"""Pure independence rules for role queue claims."""

from __future__ import annotations

import posixpath
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from varde_data.records.queue import QueueItem


@dataclass(frozen=True)
class ItemFootprint:
    item_id: str
    owned_files: tuple[str, ...]
    depends_on_unmerged: tuple[str, ...]
    serialize_with: tuple[str, ...]
    worktree: str


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str


def independent(
    candidate: ItemFootprint, in_flight: Sequence[ItemFootprint]
) -> Verdict:
    """Explain whether candidate can run alongside every in-flight item."""
    for dependency in candidate.depends_on_unmerged:
        return Verdict(False, f"depends_on item {dependency} is unmerged")

    for item in in_flight:
        if (
            item.item_id in candidate.serialize_with
            or candidate.item_id in item.serialize_with
        ):
            return Verdict(False, f"serialize_with item {item.item_id} is in flight")
        if _normalize_path(candidate.worktree) == _normalize_path(item.worktree):
            return Verdict(False, f"worktree overlaps item {item.item_id}")
        for candidate_path in candidate.owned_files:
            for other_path in item.owned_files:
                if _paths_overlap(candidate_path, other_path):
                    return Verdict(
                        False,
                        f"owned_files overlap: {candidate_path} and {other_path}",
                    )

    return Verdict(True, "independent")


def ready(candidate: QueueItem, in_flight: Sequence[QueueItem]) -> bool:
    """Claim-compatible readiness predicate; detailed reasons use independent()."""
    return readiness(candidate, in_flight).ok


def readiness(
    candidate: QueueItem,
    in_flight: Sequence[QueueItem],
    *,
    unmerged_dependencies: Collection[str] | None = None,
) -> Verdict:
    """Return the claim readiness verdict, including known dependency states."""
    candidate_footprint = _footprint(candidate, in_flight)
    if unmerged_dependencies is not None:
        candidate_footprint = ItemFootprint(
            item_id=candidate_footprint.item_id,
            owned_files=candidate_footprint.owned_files,
            depends_on_unmerged=tuple(
                sorted(set(candidate.depends_on) & set(unmerged_dependencies))
            ),
            serialize_with=candidate_footprint.serialize_with,
            worktree=candidate_footprint.worktree,
        )
    active_footprints = tuple(_footprint(item, ()) for item in in_flight)
    return independent(candidate_footprint, active_footprints)


def _footprint(item: QueueItem, in_flight: Sequence[QueueItem]) -> ItemFootprint:
    extra = item.extra or {}
    worktree = extra.get("worktree")
    dependencies = set(item.depends_on)
    active_ids = {active.id for active in in_flight}
    return ItemFootprint(
        item_id=item.id,
        owned_files=_owned_files(item.owned_files, extra.get("owned_files")),
        depends_on_unmerged=tuple(sorted(dependencies & active_ids)),
        serialize_with=item.serialize_with,
        worktree=(
            str(worktree)
            if isinstance(worktree, str)
            else f"{item.plan_dir}/worktrees/{item.id}"
        ),
    )


def _owned_files(stored: str, extra_value: object) -> tuple[str, ...]:
    values: list[str] = []
    if stored.strip():
        values.extend(stored.splitlines())
    if isinstance(extra_value, str):
        values.extend(extra_value.splitlines())
    elif isinstance(extra_value, (tuple, list)):
        values.extend(value for value in extra_value if isinstance(value, str))
    return tuple(
        value for value in (_normalize_path(value) for value in values) if value
    )


def _normalize_path(value: str) -> str:
    cleaned = value.strip().strip("`").strip().replace("\\", "/")
    if not cleaned:
        return ""
    normalized = posixpath.normpath(cleaned)
    return normalized.casefold()


def _paths_overlap(left: str, right: str) -> bool:
    left = _normalize_path(left)
    right = _normalize_path(right)
    left_glob = _has_glob(left)
    right_glob = _has_glob(right)
    if left_glob and right_glob:
        # Proving two glob languages disjoint is difficult; fail closed.
        return True
    if (left_glob and fnmatchcase(right, left)) or (
        right_glob and fnmatchcase(left, right)
    ):
        return True
    left_path = PurePosixPath(left)
    right_path = PurePosixPath(right)
    return (
        left_path == right_path
        or left_path in right_path.parents
        or right_path in left_path.parents
    )


def _has_glob(path: str) -> bool:
    return any(character in path for character in "*?[")
