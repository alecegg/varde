"""Rank-based baseline: express each solution as a percentile in a corpus
distribution and measure the buffer in percentile points (pure functions).

A raw statistic (a mean, a quantile) has between-problem spread of 20-90% with
four problems, so a relative 5-10% tolerance is out of reach. A rank in a large
reference distribution is bounded (0-100), insensitive to the integer
resolution of small metrics, and its tolerance is in points.

Two ways to score a set of rows (one solution, or several pooled):

* ``fn``: token-weighted mean of the mid-rank percentile of each function's value
  in the corpus's token-weighted per-function distribution;
* ``file:<stat>``: mid-rank percentile of the solution-level statistic
  (``mean`` = per function count, ``wmean`` = per token, ``density`` = per 1k
  tokens) among the same statistic of the corpus files. These are the
  problem-relative normalisations.

Errors reuse the earlier sources, now in points: leave-one-problem-out gap
(``lopo``), bootstrap half-width of the pooled score (``boot``, functions
resampled within each problem, fixed seed) and school-draft spread (``draft``).
Tier A is the worst of the three, tier B the worst of ``lopo`` and ``boot``;
a tier is 5 or 10 points, else ``none-yet``. No model call.
"""

from __future__ import annotations

import math
import statistics
from bisect import bisect_left, bisect_right
from collections.abc import Callable, Mapping, Sequence
from typing import Any, NamedTuple

import baseline_index_buffer as ib

POINT_STEPS = (5.0, 10.0)
Z90 = 1.645  # half-width multiplier of a two-sided 90% interval
MODES = ("fn", "file:mean", "file:wmean", "file:density")
MIN_FUNCTIONS = 5  # smallest corpus file used as one example

Rows = ib.Rows
Row = ib.Row
Scorer = Callable[[Rows], float | None]


class Cdf(NamedTuple):
    """Token-weighted distribution: weight strictly below / equal per value."""

    values: list[float]
    below: list[float]
    equal: list[float]
    total: float


def build_cdf(pairs: Sequence[tuple[float, float]]) -> Cdf:
    weights: dict[float, float] = {}
    for value, weight in pairs:
        weights[value] = weights.get(value, 0.0) + weight
    values = sorted(weights)
    below, running = [], 0.0
    for value in values:
        below.append(running)
        running += weights[value]
    return Cdf(values, below, [weights[v] for v in values], running)


def midrank(cdf: Cdf, value: float) -> float:
    """Mid-rank percentile (0-100): ties count half, so discrete values spread."""
    if cdf.total <= 0:
        raise ValueError("empty distribution")
    at = bisect_left(cdf.values, value)
    found = at < len(cdf.values) and cdf.values[at] == value
    under = cdf.below[at] if at < len(cdf.values) else cdf.total
    tied = cdf.equal[at] if found else 0.0
    return 100.0 * (under + tied / 2) / cdf.total


def rank_in_sorted(value: float, sample: Sequence[float]) -> float:
    """Mid-rank percentile (0-100) of ``value`` in a sorted unweighted sample."""
    low, high = bisect_left(sample, value), bisect_right(sample, value)
    return 100.0 * (low + (high - low) / 2) / len(sample)


# ---- scorers ----------------------------------------------------------------


def fn_scorer(metric: str, cdf: Cdf) -> Scorer:
    def score(rows: Rows) -> float | None:
        pairs = ib.weighted_pairs(rows, metric)
        total = sum(w for _, w in pairs)
        if total <= 0:
            return None
        return sum(midrank(cdf, v) * w for v, w in pairs) / total

    return score


def file_scorer(metric: str, stat: str, sample: Sequence[float]) -> Scorer:
    compute = ib.STATISTICS[stat]

    def score(rows: Rows) -> float | None:
        value = compute(rows, metric)
        return None if value is None else rank_in_sorted(value, sample)

    return score


def clamp_unit(q: float) -> float:
    return min(1.0, max(0.0, q))


def band_of_pairs(
    pairs: Sequence[tuple[float, float]], center: float, tol: float
) -> tuple[float | None, float | None]:
    """Raw values at the token-weighted quantiles ``center`` -/+ ``tol`` points."""
    low = ib.weighted_quantile(pairs, clamp_unit((center - tol) / 100))
    high = ib.weighted_quantile(pairs, clamp_unit((center + tol) / 100))
    return low, high


def band_of_sample(
    sample: Sequence[float], center: float, tol: float
) -> tuple[float | None, float | None]:
    low = ib.quantile(sample, clamp_unit((center - tol) / 100))
    high = ib.quantile(sample, clamp_unit((center + tol) / 100))
    return low, high


class Mode(NamedTuple):
    score: Scorer
    band: Callable[[float, float], tuple[float | None, float | None]]


def make_mode(
    mode: str, metric: str, corpus_files: Sequence[Rows], usable: Sequence[Rows]
) -> Mode:
    if mode == "fn":
        pairs = ib.weighted_pairs(ib.pooled_files(corpus_files), metric)
        return Mode(
            fn_scorer(metric, build_cdf(pairs)),
            lambda center, tol: band_of_pairs(pairs, center, tol),
        )
    stat = mode.split(":", 1)[1]
    sample = sorted(
        v for rows in usable if (v := ib.STATISTICS[stat](rows, metric)) is not None
    )
    return Mode(
        file_scorer(metric, stat, sample),
        lambda center, tol: band_of_sample(sample, center, tol),
    )


# ---- error sources in points ------------------------------------------------


def lopo_points(by_problem: Mapping[str, Rows], score: Scorer) -> dict[str, Any]:
    """Per-problem score and the gap between pooled-others and each problem."""
    if len(by_problem) < 2:
        raise ValueError("leave-one-problem-out needs at least two problems")
    own = {p: score(rows) for p, rows in by_problem.items()}
    gaps = []
    for problem in by_problem:
        others = score(ib.pooled({p: r for p, r in by_problem.items() if p != problem}))
        if own[problem] is not None and others is not None:
            gaps.append(abs(others - own[problem]))
    values = [v for v in own.values() if v is not None]
    return {
        "per_problem": own,
        "worst": max(gaps, default=None),
        "mean": sum(gaps) / len(gaps) if gaps else None,
        "sd": statistics.stdev(values) if len(values) > 1 else None,
    }


def bootstrap_points(
    by_problem: Mapping[str, Rows],
    draws: Sequence[Mapping[str, Sequence[int]]],
    score: Scorer,
) -> float | None:
    """Half-width (points) of the 90% percentile interval of the pooled score."""
    base = score(ib.pooled(by_problem))
    samples = [
        v
        for draw in draws
        if (v := score(ib.resampled_rows(by_problem, draw))) is not None
    ]
    low, high = (
        ib.quantile(samples, ib.INTERVAL[0]),
        ib.quantile(samples, ib.INTERVAL[1]),
    )
    if base is None or low is None or high is None:
        return None
    return max(high - base, base - low)


def draft_points(
    agreed: Mapping[str, Rows], drafts: ib.Drafts, score: Scorer
) -> dict[str, float | None]:
    """Worst draft-vs-agreed gap and worst school max-min spread within a run."""
    vs_agreed: list[float] = []
    spreads: list[float] = []
    for problem, by_draft in drafts.items():
        reference = score(agreed[problem]) if problem in agreed else None
        if reference is None:
            continue
        found = {k: v for k, rows in by_draft.items() if (v := score(rows)) is not None}
        vs_agreed += [abs(v - reference) for v in found.values()]
        for run in {run for run, _ in found}:
            same_run = [v for (r, _), v in found.items() if r == run]
            if len(same_run) > 1:
                spreads.append(max(same_run) - min(same_run))
    return {
        "vs_agreed": max(vs_agreed, default=None),
        "school_spread": max(spreads, default=None),
    }


def tier_points(err: float | None) -> float | str:
    """5 or 10 points by the error, else ``none-yet``."""
    if err is None:
        return ib.NONE_YET
    return next((step for step in POINT_STEPS if err <= step), ib.NONE_YET)


def problems_needed(sd: float | None, tol: float) -> int | None:
    """Examples to pool so the 90% half-width ``Z90 * sd / sqrt(k)`` reaches ``tol``."""
    if sd is None:
        return None
    return max(1, math.ceil((Z90 * sd / tol) ** 2))


# ---- one cell ---------------------------------------------------------------


def corpus_sd(score: Scorer, usable: Sequence[Rows]) -> float | None:
    scores = [v for rows in usable if (v := score(rows)) is not None]
    return statistics.pstdev(scores) if len(scores) > 1 else None


def cell(
    agreed: Mapping[str, Rows],
    drafts: ib.Drafts,
    draws: Sequence[Mapping[str, Sequence[int]]],
    mode: Mode,
    usable: Sequence[Rows],
) -> dict[str, Any]:
    lopo = lopo_points(agreed, mode.score)
    drafted = draft_points(agreed, drafts, mode.score)
    parts = {
        "lopo": lopo["worst"],
        "boot": bootstrap_points(agreed, draws, mode.score),
        "draft": drafted["school_spread"],
    }
    known = [v for v in parts.values() if v is not None]
    err_a = max(known) if len(known) == len(parts) else None
    err_b = (
        max(parts["lopo"], parts["boot"])
        if None not in (parts["lopo"], parts["boot"])
        else None
    )
    pooled_score = mode.score(ib.pooled(agreed))
    sd_corpus = corpus_sd(mode.score, usable)
    return {
        "pooled": pooled_score,
        "per_problem": lopo["per_problem"],
        "problem_sd": lopo["sd"],
        "lopo_mean": lopo["mean"],
        **parts,
        "draft_vs_agreed": drafted["vs_agreed"],
        "err_a": err_a,
        "err_b": err_b,
        "tier_a": tier_points(err_a),
        "tier_b": tier_points(err_b),
        "band": {
            str(int(tol)): mode.band(pooled_score, tol)
            if pooled_score is not None
            else None
            for tol in POINT_STEPS
        },
        "corpus_sd": sd_corpus,
        "corpus_files": len(usable),
        "problems_needed": {
            str(int(tol)): {
                "observed_sd": problems_needed(lopo["sd"], tol),
                "corpus_sd": problems_needed(sd_corpus, tol),
            }
            for tol in POINT_STEPS
        },
    }


def best_mode(cells: Mapping[str, Mapping[str, Any]], err_key: str) -> str | None:
    """Lowest-error mode (ties: declaration order)."""
    measured = [
        (c[err_key], i, m)
        for i, (m, c) in enumerate(cells.items())
        if c[err_key] is not None
    ]
    return min(measured)[2] if measured else None


def usable_files(corpus_files: Sequence[Rows]) -> list[Rows]:
    return [rows for rows in corpus_files if len(rows) >= MIN_FUNCTIONS]


def pooled_scores(
    agreed: Mapping[str, Rows], corpus_files: Sequence[Rows]
) -> dict[str, dict[str, float | None]]:
    """metric -> mode -> pooled agreed score under a corpus (robustness check)."""
    usable = usable_files(corpus_files)
    every = ib.pooled(agreed)
    return {
        metric: {
            mode: make_mode(mode, metric, corpus_files, usable).score(every)
            for mode in MODES
        }
        for metric in ib.METRICS
    }


def evaluate(
    agreed: Mapping[str, Rows],
    drafts: ib.Drafts,
    corpus_files: Sequence[Rows],
    seed: int = ib.DEFAULT_SEED,
    resamples: int = ib.DEFAULT_RESAMPLES,
) -> dict[str, Any]:
    """Per metric: a cell for every mode, plus the best mode for tier A and B."""
    draws = ib.resample_indices({p: len(r) for p, r in agreed.items()}, resamples, seed)
    usable = usable_files(corpus_files)
    result: dict[str, Any] = {}
    for metric in ib.METRICS:
        cells = {
            mode: cell(
                agreed,
                drafts,
                draws,
                make_mode(mode, metric, corpus_files, usable),
                usable,
            )
            for mode in MODES
        }
        result[metric] = {
            "cells": cells,
            "best_a": best_mode(cells, "err_a"),
            "best_b": best_mode(cells, "err_b"),
        }
    return result


def raw_tiers(raw_evaluation: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Tier A/B of the earlier raw-value best statistics, per metric."""
    out: dict[str, dict[str, Any]] = {}
    for metric, entry in raw_evaluation.items():
        best, best_b = entry["best"], entry["best_b"]
        out[metric] = {
            "stat_a": best,
            "tier_a": entry["cells"][best]["tier"] if best else None,
            "stat_b": best_b,
            "tier_b": entry["cells"][best_b]["tier_b"] if best_b else None,
        }
    return out
