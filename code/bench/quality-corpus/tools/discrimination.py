"""Discrimination of a measurement between known-good and known-worse code
(pure functions, no I/O, no model call).

For one metric and one statistic form, every item (a module) has one value. The
baseline is the pooled value of the known-good set. The *band* is the widest
symmetric interval around the baseline that accepts at least ``ACCEPT`` of the
known-good items; known-worse items outside it are *caught*. Separation is the
AUC of the absolute deviation from the baseline (good vs worse, ties half).
Also reported: the one-sided (higher is worse) AUC and catch rate, and the
paired fraction of degradations that raise the value above their own source.
A metric whose best statistic has AUC under ``MIN_AUC`` or a catch rate under
``MIN_CAUGHT`` at 90% acceptance is non-discriminating.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

ACCEPT = 0.9
MIN_AUC = 0.65
MIN_CAUGHT = 0.25
EPS = 1e-9


def deviations(values: Sequence[float], baseline: float) -> list[float]:
    return [abs(v - baseline) for v in values]


def auc(good: Sequence[float], worse: Sequence[float]) -> float | None:
    """P(worse > good), ties counting half (pass deviations or signed values)."""
    if not good or not worse:
        return None
    wins = sum(
        1.0 if w > g + EPS else 0.5 if abs(w - g) <= EPS else 0.0
        for w in worse
        for g in good
    )
    return wins / (len(good) * len(worse))


def halfwidth(good_deviations: Sequence[float], accept: float = ACCEPT) -> float:
    """Smallest deviation that accepts at least ``accept`` of the good items."""
    ordered = sorted(good_deviations)
    return ordered[max(1, math.ceil(accept * len(ordered) - EPS)) - 1]


def caught(deviation_values: Sequence[float], half: float) -> float | None:
    if not deviation_values:
        return None
    return sum(1 for d in deviation_values if d > half + EPS) / len(deviation_values)


def paired_up(
    worse: Mapping[str, Mapping[str, float]], good: Mapping[str, float]
) -> dict[str, float | None]:
    """Per type: share of degraded modules whose value exceeds their source's."""
    out: dict[str, float | None] = {}
    for kind, items in worse.items():
        pairs = [(v, good.get(f"agreed:{p}")) for p, v in items.items()]
        known = [(v, g) for v, g in pairs if g is not None]
        out[kind] = (
            sum(1 for v, g in known if v > g + EPS) / len(known) if known else None
        )
    return out


def analyse(
    baseline: float,
    good: Mapping[str, float],
    worse: Mapping[str, Mapping[str, float]],
    contested: Mapping[str, float],
    agreed: Sequence[str],
) -> dict[str, Any]:
    """Band, separation and catch rates of one metric/statistic cell.

    ``worse`` maps degradation type -> item name -> value; ``agreed`` names the
    agreed solutions inside ``good`` (the strict, small-sample alternative).
    """
    good_dev = deviations(list(good.values()), baseline)
    half = halfwidth(good_dev)
    worse_all = [v for items in worse.values() for v in items.values()]
    worse_dev = deviations(worse_all, baseline)
    agreed_baseline = statistics.fmean(good[name] for name in agreed)
    agreed_half = max(deviations([good[n] for n in agreed], agreed_baseline))
    signed_good = [v - baseline for v in good.values()]
    upper_half = halfwidth(signed_good)
    signed_worse = [v - baseline for v in worse_all]
    return {
        "baseline": baseline,
        "half": half,
        "upper_auc": auc(signed_good, signed_worse),
        "upper_half": upper_half,
        "upper_caught": caught(signed_worse, upper_half),
        "paired_up": paired_up(worse, good),
        "accepted": sum(1 for d in good_dev if d <= half + EPS) / len(good_dev),
        "auc": auc(good_dev, worse_dev),
        "caught": caught(worse_dev, half),
        "by_type": {
            kind: caught(deviations(list(items.values()), baseline), half)
            for kind, items in worse.items()
        },
        "direction": statistics.median(v - baseline for v in worse_all)
        if worse_all
        else None,
        "contested_caught": caught(
            deviations(list(contested.values()), baseline), half
        ),
        "contested_direction": statistics.median(
            v - baseline for v in contested.values()
        )
        if contested
        else None,
        "agreed_only_half": agreed_half,
        "agreed_only_caught": caught(
            deviations(worse_all, agreed_baseline), agreed_half
        ),
    }


def pick_recommended(cells: Mapping[str, Mapping[str, Any]]) -> str | None:
    """Statistic with the best (caught, AUC); ties keep declaration order."""
    scored = [
        (c["caught"] or 0.0, c["auc"], -i, name)
        for i, (name, c) in enumerate(cells.items())
        if c["auc"] is not None
    ]
    return max(scored)[3] if scored else None


def verdict(best_auc: float | None, best_caught: float | None) -> str:
    if best_auc is None or best_caught is None:
        return "no-data"
    separates = best_auc >= MIN_AUC and best_caught >= MIN_CAUGHT
    return "discriminating" if separates else "non-discriminating"


def catch_matrix(
    cells: Mapping[str, Mapping[str, Mapping[str, Any]]],
    recommended: Mapping[str, str | None],
) -> dict[str, dict[str, float | None]]:
    """degradation type -> metric -> caught fraction at the recommended statistic."""
    matrix: dict[str, dict[str, float | None]] = {}
    for metric, by_stat in cells.items():
        stat = recommended.get(metric)
        if stat is None:
            continue
        for kind, fraction in by_stat[stat]["by_type"].items():
            matrix.setdefault(kind, {})[metric] = fraction
    return matrix
