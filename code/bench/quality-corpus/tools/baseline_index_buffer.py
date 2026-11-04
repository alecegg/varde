"""Index-derived baseline statistics and achievable buffer tiers (pure functions).

Input is the raw per-function rows of ``raw_measure`` (one dict per function).
For each metric and candidate statistic the module computes four error sources
against the agreed solutions and takes their maximum:

* ``lopo``: leave-one-problem-out error, ``|stat(others) - stat(p)|`` over the
  floor-guarded ``max(|stat(p)|, unit)``, worst problem;
* ``bootstrap``: half-width of the 90% percentile interval of the pooled
  statistic, resampling functions within each problem (fixed seed);
* ``draft``: worst max-min spread of the statistic across the schools' first
  drafts of one run, over the floor-guarded agreed value (the worst error of
  any draft against the agreed value is reported as ``draft_vs_agreed`` only);
* tier A is 5% or 10% by the maximum of the three, tier B by the maximum of
  ``lopo`` and ``bootstrap`` only (school spread reported, not in the tier);
  otherwise ``none-yet`` together with the smallest remedy. There is no final
  "unbaselined" outcome.
  A statistic whose baseline is exactly 0 is ``degenerate`` (it cannot
  discriminate) and loses to any non-degenerate statistic as the best choice.

Decomposition-invariant statistics (``w*``) weight each function by its tokens,
as the scorer's value->token-weight pools do, and pool token counts over
solutions, so splitting one function into several leaves them unchanged to
first order. ``density`` is the solution total per 1k tokens, pooled.

No model call; every output is deterministic for a given seed.
"""

from __future__ import annotations

import math
import random
import tomllib
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

BUFFER_STEPS = (0.05, 0.10)
NONE_YET = "none-yet"
DEFAULT_SEED = 20261031
DEFAULT_RESAMPLES = 1000
INTERVAL = (0.05, 0.95)

METRICS = (
    "cognitive",
    "depth",
    "fan_out",
    "fan_in",
    "tree_size",
    "params",
    "tokens",
    "max_nesting",
    "name_issues",
)
CALIBRATION = (
    Path(__file__).resolve().parents[4]
    / "code/src/varde_code/quality_score/calibration/placeholder.toml"
)
# metric -> key of the scorer's python calibration section (the comfort threshold).
CALIBRATION_KEY = {
    "cognitive": "c0",
    "depth": "dp0",
    "fan_out": "k0",
    "tree_size": "t0",
    "tokens": "Phi",
}
# Metrics without a calibration key keep the earlier fixed choice.
FALLBACK_THRESHOLD = {"fan_in": 2, "params": 4, "max_nesting": 2, "name_issues": 0}


def load_thresholds(path: Path = CALIBRATION) -> dict[str, float]:
    """metric -> value above which a function counts as above comfort."""
    python = tomllib.loads(path.read_text())["language"]["python"]
    from_calibration = {m: float(python[k]) for m, k in CALIBRATION_KEY.items()}
    return {**FALLBACK_THRESHOLD, **from_calibration}


COMFORT = load_thresholds()
# One unit of each statistic family, the floor of the relative-error denominator:
# 1 for per-function values and per-1k-token density, 0.1 for a share.
UNIT = {
    "mean": 1.0,
    "p50": 1.0,
    "p75": 1.0,
    "p90": 1.0,
    "share_above": 0.1,
    "density": 1.0,
    "wmean": 1.0,
    "wp50": 1.0,
    "wp75": 1.0,
    "wp90": 1.0,
    "wshare": 0.1,
}

Row = Mapping[str, Any]
Rows = Sequence[Row]


# ---- statistics -------------------------------------------------------------


def values_of(rows: Rows, metric: str) -> list[float]:
    return [float(r[metric]) for r in rows if r.get(metric) is not None]


def quantile(values: Sequence[float], q: float) -> float | None:
    """Linearly interpolated quantile (type 7); None when empty."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = math.floor(position)
    high = math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stat_mean(rows: Rows, metric: str) -> float | None:
    values = values_of(rows, metric)
    return sum(values) / len(values) if values else None


def stat_quantile(q: float) -> Callable[[Rows, str], float | None]:
    return lambda rows, metric: quantile(values_of(rows, metric), q)


def stat_share_above(rows: Rows, metric: str) -> float | None:
    values = values_of(rows, metric)
    if not values:
        return None
    return sum(1 for v in values if v > COMFORT[metric]) / len(values)


def stat_density(rows: Rows, metric: str) -> float | None:
    """Metric total per 1k tokens (functions per 1k tokens for ``tokens``)."""
    both = [r for r in rows if r.get(metric) is not None and r.get("tokens")]
    tokens = sum(r["tokens"] for r in both)
    if tokens <= 0:
        return None
    total = len(both) if metric == "tokens" else sum(r[metric] for r in both)
    return 1000.0 * total / tokens


def weighted_pairs(rows: Rows, metric: str) -> list[tuple[float, float]]:
    """(value, token weight) of the measured functions with tokens."""
    return [
        (float(r[metric]), float(r["tokens"]))
        for r in rows
        if r.get(metric) is not None and r.get("tokens")
    ]


def weighted_quantile(pairs: Sequence[tuple[float, float]], q: float) -> float | None:
    """Smallest value whose cumulative token weight reaches ``q`` (scorer rule)."""
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    running = 0.0
    for value, weight in sorted(pairs):
        running += weight
        if running >= q * total:
            return value
    return max(v for v, _ in pairs)


def stat_wquantile(q: float) -> Callable[[Rows, str], float | None]:
    return lambda rows, metric: weighted_quantile(weighted_pairs(rows, metric), q)


def stat_wmean(rows: Rows, metric: str) -> float | None:
    pairs = weighted_pairs(rows, metric)
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total > 0 else None


def stat_wshare(rows: Rows, metric: str) -> float | None:
    """Token share of the functions above the comfort threshold."""
    pairs = weighted_pairs(rows, metric)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    return sum(w for v, w in pairs if v > COMFORT[metric]) / total


STATISTICS: dict[str, Callable[[Rows, str], float | None]] = {
    "mean": stat_mean,
    "p50": stat_quantile(0.50),
    "p75": stat_quantile(0.75),
    "p90": stat_quantile(0.90),
    "share_above": stat_share_above,
    "density": stat_density,
    "wmean": stat_wmean,
    "wp50": stat_wquantile(0.50),
    "wp75": stat_wquantile(0.75),
    "wp90": stat_wquantile(0.90),
    "wshare": stat_wshare,
}


def relative_error(value: float, reference: float, unit: float) -> float:
    return abs(value - reference) / max(abs(reference), unit)


def tier_for(err: float | None) -> float | str:
    """0.05 or 0.10 by the error, else ``none-yet``."""
    if err is None:
        return NONE_YET
    for step in BUFFER_STEPS:
        if err <= step:
            return step
    return NONE_YET


# ---- error sources ----------------------------------------------------------


def pooled(by_problem: Mapping[str, Rows]) -> list[Row]:
    return [row for rows in by_problem.values() for row in rows]


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def lopo_error(
    by_problem: Mapping[str, Rows],
    metric: str,
    stat: str,
    reduce: Callable[[Sequence[float]], float] = max,
) -> float | None:
    """Relative error of the pooled-others statistic against each problem,
    reduced over problems (worst by default; the mean is a diagnostic)."""
    if len(by_problem) < 2:
        raise ValueError("leave-one-problem-out needs at least two problems")
    compute, unit = STATISTICS[stat], UNIT[stat]
    errors = []
    for problem, rows in by_problem.items():
        own = compute(rows, metric)
        others = compute(
            pooled({p: r for p, r in by_problem.items() if p != problem}), metric
        )
        if own is not None and others is not None:
            errors.append(relative_error(others, own, unit))
    return reduce(errors) if errors else None


def resample_indices(
    sizes: Mapping[str, int], resamples: int, seed: int
) -> list[dict[str, list[int]]]:
    """Per resample, per problem, function indices drawn with replacement."""
    rng = random.Random(seed)  # noqa: S311 - reproducible resampling, not security
    return [
        {p: [rng.randrange(n) for _ in range(n)] for p, n in sizes.items() if n}
        for _ in range(resamples)
    ]


def resampled_rows(
    by_problem: Mapping[str, Rows], draw: Mapping[str, Sequence[int]]
) -> list[Row]:
    return [by_problem[p][i] for p, indices in draw.items() for i in indices]


def bootstrap_error(
    by_problem: Mapping[str, Rows],
    draws: Sequence[Mapping[str, Sequence[int]]],
    metric: str,
    stat: str,
) -> float | None:
    """Relative half-width of the percentile interval of the pooled statistic."""
    compute, unit = STATISTICS[stat], UNIT[stat]
    baseline = compute(pooled(by_problem), metric)
    if baseline is None:
        return None
    samples = [
        v
        for draw in draws
        if (v := compute(resampled_rows(by_problem, draw), metric)) is not None
    ]
    low, high = quantile(samples, INTERVAL[0]), quantile(samples, INTERVAL[1])
    if low is None or high is None:
        return None
    return max(high - baseline, baseline - low) / max(abs(baseline), unit)


Drafts = Mapping[
    str, Mapping[tuple[str, str], Rows]
]  # problem -> (run, school) -> rows


def draft_error(
    agreed: Mapping[str, Rows], drafts: Drafts, metric: str, stat: str
) -> dict[str, float | None]:
    """Worst draft-vs-agreed error and worst school spread within one run."""
    compute, unit = STATISTICS[stat], UNIT[stat]
    vs_agreed: list[float] = []
    spreads: list[float] = []
    for problem, by_draft in drafts.items():
        reference = compute(agreed[problem], metric) if problem in agreed else None
        if reference is None:
            continue
        found = {k: compute(rows, metric) for k, rows in by_draft.items()}
        vs_agreed += [
            relative_error(v, reference, unit) for v in found.values() if v is not None
        ]
        for run in {run for run, _ in found}:
            same_run = [v for (r, _), v in found.items() if r == run and v is not None]
            if len(same_run) > 1:
                spreads.append(
                    (max(same_run) - min(same_run)) / max(abs(reference), unit)
                )
    return {
        "vs_agreed": max(vs_agreed) if vs_agreed else None,
        "school_spread": max(spreads) if spreads else None,
    }


def cell(
    agreed: Mapping[str, Rows],
    drafts: Drafts,
    draws: Sequence[Mapping[str, Sequence[int]]],
    metric: str,
    stat: str,
) -> dict[str, Any]:
    """All error sources, the worst of them and the tier for one statistic."""
    drafted = draft_error(agreed, drafts, metric, stat)
    parts = {
        "lopo": lopo_error(agreed, metric, stat),
        "bootstrap": bootstrap_error(agreed, draws, metric, stat),
        "draft": drafted["school_spread"],
    }
    known = [v for v in parts.values() if v is not None]
    err = max(known) if len(known) == len(parts) else None
    no_spread = [parts["lopo"], parts["bootstrap"]]
    err_b = max(no_spread) if None not in no_spread else None
    baseline = STATISTICS[stat](pooled(agreed), metric)
    return {
        "baseline": baseline,
        "degenerate": baseline == 0,
        **parts,
        "lopo_mean": lopo_error(agreed, metric, stat, reduce=_mean),
        "draft_vs_agreed": drafted["vs_agreed"],
        "err": err,
        "tier": tier_for(err),
        "err_b": err_b,
        "tier_b": tier_for(err_b),
        "part_tiers": {k: tier_for(v) for k, v in parts.items()},
    }


# ---- remedy -----------------------------------------------------------------


def best_statistic(
    cells: Mapping[str, Mapping[str, Any]], err_key: str = "err"
) -> str | None:
    """Lowest-error statistic, non-degenerate first (ties: declaration order)."""
    measured = [
        (c["degenerate"], c[err_key], i, s)
        for i, (s, c) in enumerate(cells.items())
        if c[err_key] is not None
    ]
    return min(measured)[3] if measured else None


def remedy(
    cells: Mapping[str, Mapping[str, Any]],
    functions: int,
    problems: int,
    variant: str = "A",
) -> dict[str, Any]:
    """Smallest remedy for a metric whose best statistic misses 10%.

    Bootstrap error falls with data (about 1/sqrt(n)), so a bootstrap-only miss
    needs ``(boot / 10%)^2`` times the functions and problems. A leave-one-problem-out
    miss is between-problem spread: more problems do not shrink it, so the
    statistic or its normalization must change. A draft-spread miss (variant A
    only) is school-to-school variation, which more data does not shrink either.
    """
    err_key = "err_b" if variant == "B" else "err"
    sources = ("lopo",) if variant == "B" else ("lopo", "draft")
    best = best_statistic(cells, err_key)
    if best is None:
        return {"kind": "no-data"}
    chosen, limit = cells[best], BUFFER_STEPS[-1]
    if chosen[err_key] <= limit:
        tier = chosen["tier_b" if variant == "B" else "tier"]
        return {"kind": "statistic", "use": best, "tier": tier}
    spread = [k for k in sources if chosen[k] > limit]
    if spread:
        return {"kind": "statistic-or-normalization", "use": best, "limited_by": spread}
    factor = (chosen["bootstrap"] / limit) ** 2
    return {
        "kind": "data",
        "use": best,
        "factor": factor,
        "functions_needed": math.ceil(functions * factor),
        "problems_needed": math.ceil(problems * factor),
    }


def reaching(cells: Mapping[str, Mapping[str, Any]], step: float) -> list[str]:
    """Non-degenerate statistics whose tier B is at most ``step``."""
    return [
        s
        for s, c in cells.items()
        if not c["degenerate"] and c["err_b"] is not None and c["err_b"] <= step
    ]


def evaluate(
    agreed: Mapping[str, Rows],
    drafts: Drafts,
    seed: int = DEFAULT_SEED,
    resamples: int = DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    """Per metric: every statistic's cell, the best statistic and its remedy."""
    draws = resample_indices({p: len(r) for p, r in agreed.items()}, resamples, seed)
    functions, problems = len(pooled(agreed)), len(agreed)
    result: dict[str, Any] = {}
    for metric in METRICS:
        cells = {s: cell(agreed, drafts, draws, metric, s) for s in STATISTICS}
        result[metric] = {
            "cells": cells,
            "best": best_statistic(cells),
            "remedy": remedy(cells, functions, problems),
            "best_b": best_statistic(cells, "err_b"),
            "remedy_b": remedy(cells, functions, problems, "B"),
            "reach_b": {str(step): reaching(cells, step) for step in BUFFER_STEPS},
        }
    return result


# ---- corpus comparison ------------------------------------------------------


def percentile_rank(value: float, sample: Sequence[float]) -> float | None:
    """Mid-rank percentile (0-100) of ``value`` in ``sample``."""
    if not sample:
        return None
    below = sum(1 for s in sample if s < value)
    equal = sum(1 for s in sample if s == value)
    return 100.0 * (below + equal / 2) / len(sample)


def units_needed(dispersion: float | None) -> int | None:
    """Problems to pool so ``dispersion / sqrt(k)`` reaches 10% (independent units)."""
    if dispersion is None:
        return None
    return max(1, math.ceil((dispersion / BUFFER_STEPS[-1]) ** 2))


def pooled_files(files: Sequence[Rows]) -> list[Row]:
    return [row for rows in files for row in rows]


def corpus_position(
    agreed: Mapping[str, Rows],
    corpus_files: Sequence[Rows],
    min_functions: int = 5,
) -> dict[str, dict[str, Any]]:
    """Percentile of each agreed statistic among per-file corpus statistics."""
    usable = [rows for rows in corpus_files if len(rows) >= min_functions]
    every = pooled(agreed)
    position: dict[str, dict[str, Any]] = {}
    for metric in METRICS:
        position[metric] = {}
        for stat, compute in STATISTICS.items():
            ours = compute(every, metric)
            sample = [v for rows in usable if (v := compute(rows, metric)) is not None]
            ref = compute(pooled_files(usable), metric)
            spread = [
                relative_error(v, ref, UNIT[stat]) for v in sample if ref is not None
            ]
            position[metric][stat] = {
                "agreed": ours,
                "file_dispersion_median": (dispersion := quantile(spread, 0.5)),
                "units_for_10pct": units_needed(dispersion),
                "percentile": None if ours is None else percentile_rank(ours, sample),
                "corpus_median": quantile(sample, 0.5),
                "files": len(sample),
            }
    return position
