"""Separation of known-good and known-worse code by the top-line 0-100 score
(pure functions, no I/O, no model call).

A score table maps item key -> score (higher is better). Items have a role:
``good`` (agreed solutions and proxy modules), ``worse`` (degraded variants of an
agreed solution, with a degradation ``kind``) and ``contested`` (monolithic
drafts). The cut line is the score below which code is labelled "needs
refactor": the highest cut that keeps ``KEEP`` of the good items at or above it.
Leave-one-problem-out cross-validation selects among candidate score tables on
the other problems' items and tests on the held-out problem; proxies are good
items in every fold.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import discrimination as dc

KEEP = 0.9
EPS = 1e-9


@dataclass(frozen=True)
class Item:
    key: str
    role: str  # "good" | "worse" | "contested"
    problem: str | None = None  # None for proxy modules
    kind: str | None = None  # degradation type of a worse item


Scores = Mapping[str, float]


def summary(values: Sequence[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "min": None, "max": None}
    return {
        "n": len(values),
        "mean": statistics.fmean(values),
        "min": min(values),
        "max": max(values),
    }


def good_above_auc(good: Sequence[float], worse: Sequence[float]) -> float | None:
    """P(good score > worse score), ties counting half."""
    return dc.auc([-v for v in good], [-v for v in worse])


def cut_line(good: Sequence[float], keep: float = KEEP) -> float:
    """Highest cut with at least ``keep`` of the good scores at or above it."""
    if not good:
        raise ValueError("no good scores to set a cut line")
    ordered = sorted(good, reverse=True)
    return ordered[max(1, math.ceil(keep * len(ordered) - EPS)) - 1]


def flagged_share(values: Sequence[float], cut: float) -> float | None:
    """Share of scores below the cut (labelled needs-refactor)."""
    if not values:
        return None
    return sum(1 for v in values if v < cut - EPS) / len(values)


def paired_deltas(
    agreed: Scores, variants: Mapping[str, Scores]
) -> dict[str, dict[str, Any]]:
    """Per degradation kind: score(agreed) - score(variant) by problem."""
    out: dict[str, dict[str, Any]] = {}
    for kind, by_problem in variants.items():
        deltas = {p: agreed[p] - s for p, s in by_problem.items() if p in agreed}
        out[kind] = {"deltas": deltas, "monotonic": drop_share(deltas.values())}
    return out


def drop_share(deltas: Iterable[float]) -> float | None:
    """Share of paired deltas where the variant scores strictly lower."""
    values = list(deltas)
    if not values:
        return None
    return sum(1 for d in values if d > EPS) / len(values)


def overall_drop_share(paired: Mapping[str, Mapping[str, Any]]) -> float | None:
    return drop_share([d for p in paired.values() for d in p["deltas"].values()])


def keys_of(items: Sequence[Item], role: str, **where: Any) -> list[str]:
    return [
        i.key
        for i in items
        if i.role == role and all(getattr(i, k) == v for k, v in where.items())
    ]


def pick(scores: Scores, keys: Sequence[str]) -> list[float]:
    return [scores[k] for k in keys if k in scores]


def kind_counts(
    scores: Scores, worse: Sequence[str], kind_of: Mapping[str, str], cut: float
) -> dict[str, list[int]]:
    """Per degradation kind: [flagged, total] among the worse items."""
    counts: dict[str, list[int]] = {}
    for key in worse:
        entry = counts.setdefault(kind_of[key], [0, 0])
        entry[0] += scores[key] < cut - EPS
        entry[1] += 1
    return counts


def evaluate(
    scores: Scores,
    good: Sequence[str],
    worse: Sequence[str],
    contested: Sequence[str],
    kind_of: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """AUC, cut at ``KEEP`` of the good items, and flagged shares."""
    g, w, c = pick(scores, good), pick(scores, worse), pick(scores, contested)
    cut = cut_line(g)
    flagged = flagged_share(w, cut)
    return {
        "by_kind": kind_counts(scores, worse, kind_of, cut) if kind_of else {},
        "auc": good_above_auc(g, w),
        "pairs": len(g) * len(w),
        "cut": cut,
        "sens": flagged,
        "flagged": None if flagged is None else round(flagged * len(w)),
        "worse_n": len(w),
        "contested_sens": flagged_share(c, cut),
        "contested_n": len(c),
    }


def split_for_problem(
    items: Sequence[Item], problems: Sequence[str], held_out: str
) -> dict[str, dict[str, list[str]]]:
    """Train on the other problems' items plus all proxies; test on the held-out one."""
    train_problems = {p for p in problems if p != held_out}

    def part(allowed: set[str], with_proxies: bool) -> dict[str, list[str]]:
        def wanted(i: Item) -> bool:
            return i.problem in allowed or (with_proxies and i.problem is None)

        return {
            role: [i.key for i in items if i.role == role and wanted(i)]
            for role in ("good", "worse", "contested")
        }

    return {"train": part(train_problems, True), "test": part({held_out}, True)}


def select_candidate(
    tables: Mapping[str, Scores], order: Sequence[str], part: Mapping[str, list[str]]
) -> str:
    """Best train AUC, then train sensitivity; first in ``order`` breaks ties."""

    def rank(name: str) -> tuple[float, float]:
        got = evaluate(tables[name], part["good"], part["worse"], [])
        return got["auc"] or 0.0, got["sens"] or 0.0

    best = order[0]
    for name in order[1:]:
        if rank(name) > rank(best):
            best = name
    return best


def kinds_of(items: Sequence[Item]) -> dict[str, str]:
    return {i.key: i.kind for i in items if i.kind}


def lopo_fixed(
    scores: Scores, items: Sequence[Item], problems: Sequence[str]
) -> list[dict[str, Any]]:
    """Per-fold test evaluation of one fixed score table (no selection)."""
    folds = []
    for held_out in problems:
        part = split_for_problem(items, problems, held_out)["test"]
        folds.append(
            {
                "held_out": held_out,
                **evaluate(
                    scores,
                    part["good"],
                    part["worse"],
                    part["contested"],
                    kinds_of(items),
                ),
            }
        )
    return folds


def lopo_selected(
    tables: Mapping[str, Scores],
    order: Sequence[str],
    items: Sequence[Item],
    problems: Sequence[str],
) -> list[dict[str, Any]]:
    """Per-fold test evaluation of the candidate chosen on the training items."""
    folds = []
    for held_out in problems:
        parts = split_for_problem(items, problems, held_out)
        chosen = select_candidate(tables, order, parts["train"])
        test = parts["test"]
        folds.append(
            {
                "held_out": held_out,
                "chosen": chosen,
                **evaluate(
                    tables[chosen],
                    test["good"],
                    test["worse"],
                    test["contested"],
                    kinds_of(items),
                ),
            }
        )
    return folds


def pooled(folds: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pair-weighted AUC and flagged share pooled over folds."""
    pairs = sum(f["pairs"] for f in folds if f["auc"] is not None)
    worse_n = sum(f["worse_n"] for f in folds)
    contested_n = sum(f["contested_n"] for f in folds)
    contested_hit = sum(
        f["contested_sens"] * f["contested_n"]
        for f in folds
        if f["contested_sens"] is not None
    )
    by_kind: dict[str, list[int]] = {}
    for fold in folds:
        for kind, (hit, total) in fold["by_kind"].items():
            entry = by_kind.setdefault(kind, [0, 0])
            entry[0] += hit
            entry[1] += total
    return {
        "by_kind": {k: hit / total for k, (hit, total) in sorted(by_kind.items())},
        "auc": sum(f["auc"] * f["pairs"] for f in folds if f["auc"] is not None)
        / max(pairs, 1),
        "sens": sum(f["flagged"] or 0 for f in folds) / max(worse_n, 1),
        "contested_sens": contested_hit / contested_n if contested_n else None,
        "mean_cut": statistics.fmean(f["cut"] for f in folds),
    }


def sensitivity_by_kind(
    scores: Scores, items: Sequence[Item], cut: float
) -> dict[str, float | None]:
    kinds = sorted({i.kind for i in items if i.role == "worse" and i.kind})
    return {
        kind: flagged_share(pick(scores, keys_of(items, "worse", kind=kind)), cut)
        for kind in kinds
    }


def cut_table(
    scores: Scores, items: Sequence[Item], cuts: Sequence[float]
) -> list[dict[str, Any]]:
    """Per candidate cut: good kept, worse flagged, contested flagged."""
    good = pick(scores, keys_of(items, "good"))
    worse = pick(scores, keys_of(items, "worse"))
    contested = pick(scores, keys_of(items, "contested"))
    return [
        {
            "cut": cut,
            "good_kept": 1 - (flagged_share(good, cut) or 0),
            "worse_flagged": flagged_share(worse, cut),
            "contested_flagged": flagged_share(contested, cut),
        }
        for cut in cuts
    ]
