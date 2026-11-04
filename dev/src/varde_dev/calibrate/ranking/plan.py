"""Dry-run adaptive pair planning from stored labels."""

from collections.abc import Mapping, Sequence
from typing import TypedDict

from varde_dev.calibrate.ranking.core import _matches
from varde_dev.calibrate.rating import fit, next_pairs


class PlanSettings(TypedDict, total=False):
    k: int
    repeats: int
    lens_count: int


def plan_next(
    labels: Sequence[Mapping[str, object]],
    units: Sequence[Mapping[str, object]],
    items: Sequence[Mapping[str, object]],
    rater_id: str,
    *,
    settings: PlanSettings | None = None,
) -> dict[str, object]:
    """Return the next pair round and projected calls without executing a client."""
    options = settings or {}
    k = options.get("k", 1)
    repeats = options.get("repeats", 2)
    lens_count = options.get("lens_count", 1)
    if k < 1 or repeats < 1 or lens_count < 1:
        raise ValueError("k, repeats, and lens_count must be positive")
    matches, _, _ = _matches(labels, units, items, rater_id)
    groups = {
        group: sorted(
            item
            for owner, item in (
                (str(row.get("pair_group_id", "")), str(row["id"])) for row in items
            )
            if owner == group
        )
        for group in sorted({str(row.get("pair_group_id", "")) for row in items})
    }
    estimates = fit(
        matches, [(str(row.get("pair_group_id", "")), str(row["id"])) for row in items]
    )
    selected = next_pairs(estimates, matches, groups, k)[:k]
    remaining = sum(
        len(members) * (len(members) - 1) // 2 for members in groups.values()
    ) - len({(g, min(x, y), max(x, y)) for g, x, y, _ in matches})
    return {
        "rater_id": rater_id,
        "pairs": selected,
        "k": k,
        "repeats": repeats,
        "lens_count": lens_count,
        "projected_remaining_calls": max(remaining, 0) * 2 * repeats * lens_count,
    }
