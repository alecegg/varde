"""File-level features of raw per-function measurements (experiment, pure).

Every function here is deterministic and does no I/O and no model call. A file
is described by its ``raw_measure`` function rows (keys ``cognitive``, ``depth``,
``fan_out``, ``fan_in``, ``tree_size``, ``params``, ``tokens``, ``line_span``).
``region_fit_experiment.py`` loads the corpus and calls these functions.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import Any, NamedTuple

import baseline_region as br

TINY_TOKENS = 20  # a function this small is "tiny"
DELEGATE_MAX_TOKENS = (
    30  # proxy for "body is one call": small, one callee, no branching
)
CUT_PERCENTILES = (10, 90)  # good-file tail cuts
DRAW_SEEDS = 50
DRAW_KS = (1, 2, 3, 4, 5, 6)

FEATURES = (
    "n_functions",
    "file_tokens",
    "cog_sum",
    "cog_token_weighted",
    "cog_max",
    "cog_p90",
    "tokens_p50",
    "tokens_p90",
    "tiny_share",
    "call_depth",
    "edges_per_function",
    "fan_in_zero_share",
    "delegation_share",
)
# existing: from the raw_measure row facts; proxy: exact value needs a new measurement
SOURCE_OF = dict.fromkeys(FEATURES, "existing") | {"delegation_share": "proxy"}


class VariantRow(NamedTuple):
    """One degraded (or mined) file: ``base`` is its unchanged file's value, if any."""

    repo: str | None
    kind: str
    base: float | None
    value: float | None


def round6(value: float | None) -> float | None:
    return None if value is None else round(value, 6)


def ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def present(rows: Sequence[Mapping[str, Any]], key: str) -> list[Any]:
    return [r[key] for r in rows if r.get(key) is not None]


def percentile(values: Sequence[float], pct: int) -> float | None:
    """Nearest-rank percentile; None when empty."""
    return br.nearest_rank(values, pct)  # type: ignore[arg-type]


def median(values: Sequence[float]) -> float | None:
    known = sorted(values)
    if not known:
        return None
    mid = len(known) // 2
    return known[mid] if len(known) % 2 else (known[mid - 1] + known[mid]) / 2


def relative_iqr(values: Sequence[float]) -> float | None:
    """(q75 - q25) / median; None without values or with a non-positive median."""
    q1, q3, mid = (percentile(values, p) for p in (25, 75, 50))
    if mid is None or q1 is None or q3 is None or mid <= 0:
        return None
    return (q3 - q1) / mid


def share(hits: int, n: int) -> dict[str, Any]:
    return {"n": n, "value": round6(ratio(hits, n))}


# ---- Part A: features of one file ------------------------------------------


def token_weighted_cognitive(rows: Sequence[Mapping[str, Any]]) -> float | None:
    pairs = [
        (r["cognitive"], r["tokens"])
        for r in rows
        if r.get("cognitive") is not None and r.get("tokens")
    ]
    return ratio(sum(c * t for c, t in pairs), sum(t for _, t in pairs))


def is_delegation(row: Mapping[str, Any]) -> bool:
    """Proxy: one callee, no branching, small body (exact needs an AST check)."""
    return (
        row.get("fan_out") == 1
        and row.get("cognitive") == 0
        and (row.get("tokens") or 0) <= DELEGATE_MAX_TOKENS
    )


def file_features(rows: Sequence[Mapping[str, Any]]) -> dict[str, float | None]:
    """All features of one file; None where a value needs facts the rows lack."""
    n = len(rows)
    empty: dict[str, float | None] = dict.fromkeys(FEATURES)
    if n == 0:
        return empty | {"n_functions": 0}
    cognitive, tokens = present(rows, "cognitive"), present(rows, "tokens")
    depths, fan_in = present(rows, "depth"), present(rows, "fan_in")
    features: dict[str, float | None] = {
        "n_functions": n,
        "file_tokens": sum(tokens) if tokens else None,
        "cog_sum": sum(cognitive) if cognitive else None,
        "cog_token_weighted": token_weighted_cognitive(rows),
        "cog_max": max(cognitive, default=None),
        "cog_p90": percentile(cognitive, 90),
        "tokens_p50": percentile(tokens, 50),
        "tokens_p90": percentile(tokens, 90),
        "tiny_share": ratio(sum(t < TINY_TOKENS for t in tokens), len(tokens)),
        "call_depth": max(depths, default=None),
        "edges_per_function": ratio(sum(fan_in), len(fan_in)),
        "fan_in_zero_share": ratio(sum(v == 0 for v in fan_in), len(fan_in)),
        "delegation_share": ratio(sum(is_delegation(r) for r in rows), n),
    }
    return {name: round6(value) for name, value in features.items()}


# ---- Part B: style spread ---------------------------------------------------


def repo_variance_share(by_repo: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Share of the total variance that lies between repos (eta squared)."""
    groups = [list(v) for v in by_repo.values() if v]
    values = [x for g in groups for x in g]
    if len(groups) < 2 or len(values) < 3:
        return {"n": len(values), "value": None}
    grand = sum(values) / len(values)
    total = sum((x - grand) ** 2 for x in values)
    between = sum(len(g) * (sum(g) / len(g) - grand) ** 2 for g in groups)
    return {"n": len(values), "value": round6(ratio(between, total))}


def spread_ratio(by_repo: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Between-repo spread of repo medians over the median within-repo spread."""
    groups = [list(v) for v in by_repo.values() if v]
    between = relative_iqr([m for m in (median(g) for g in groups) if m is not None])
    within = median([w for w in (relative_iqr(g) for g in groups) if w is not None])
    return {
        "n": len(groups),
        "between": round6(between),
        "within": round6(within),
        "ratio": round6(None if between is None or not within else between / within),
    }


def draw(size: int, k: int, seed: int) -> list[int]:
    rng = random.Random(f"file-features:{seed}:{k}")  # noqa: S311 (seeded)
    return sorted(rng.sample(range(size), k))


def sampled_ratio(
    by_repo: Mapping[str, Sequence[float]], k: int, seeds: int = DRAW_SEEDS
) -> dict[str, Any]:
    """Spread ratio of the median of k drawn files per resample (as region_sim)."""
    stats = {}
    for repo, values in sorted(by_repo.items()):
        if len(values) < k + 2:
            continue
        stats[repo] = [
            m
            for seed in range(seeds)
            if (m := median([values[i] for i in draw(len(values), k, seed)]))
            is not None
        ]
    return spread_ratio(stats)


# ---- Part B: detection of degradations --------------------------------------


def tail_cuts(good: Sequence[float]) -> tuple[float, float] | None:
    low, high = (percentile(good, p) for p in CUT_PERCENTILES)
    return None if low is None or high is None else (low, high)


def tail_hits(values: Sequence[float], cuts: tuple[float, float]) -> dict[str, Any]:
    """Share strictly below the low cut and strictly above the high cut."""
    n = len(values)
    return {
        "low": share(sum(v < cuts[0] for v in values), n),
        "high": share(sum(v > cuts[1] for v in values), n),
    }


def paired_shift(variants: Sequence[VariantRow]) -> dict[str, Any]:
    pairs = [
        (v.base, v.value)
        for v in variants
        if v.base is not None and v.value is not None
    ]
    return {
        "up": share(sum(value > base for base, value in pairs), len(pairs)),
        "down": share(sum(value < base for base, value in pairs), len(pairs)),
    }


def kind_report(
    variants: Sequence[VariantRow],
    pooled: tuple[float, float] | None,
    per_repo: Mapping[str, tuple[float, float]],
) -> dict[str, Any]:
    known = [v for v in variants if v.value is not None]
    values = [v.value for v in known]
    by_repo = [(per_repo[v.repo], v.value) for v in known if v.repo in per_repo]
    repo_low = share(sum(val < cut[0] for cut, val in by_repo), len(by_repo))
    repo_high = share(sum(val > cut[1] for cut, val in by_repo), len(by_repo))
    return {
        "pooled_cut": tail_hits(values, pooled) if pooled and values else None,
        "repo_cut": {"low": repo_low, "high": repo_high},
        "paired_shift": paired_shift(known),
    }


def feature_report(
    good_by_repo: Mapping[str, Sequence[float]],
    variants: Sequence[VariantRow],
) -> dict[str, Any]:
    """Style spread and per-kind detection for one feature."""
    good = [v for values in good_by_repo.values() for v in values]
    pooled = tail_cuts(good)
    per_repo = {r: c for r, v in good_by_repo.items() if (c := tail_cuts(v))}
    kinds = sorted({v.kind for v in variants})
    return {
        "spread": spread_ratio(good_by_repo),
        "repo_variance_share": repo_variance_share(good_by_repo),
        "sampled_ratio": {k: sampled_ratio(good_by_repo, k) for k in DRAW_KS},
        "cuts": None if pooled is None else {"low": pooled[0], "high": pooled[1]},
        "good_flagged": tail_hits(good, pooled) if pooled and good else None,
        "kinds": {
            kind: kind_report([v for v in variants if v.kind == kind], pooled, per_repo)
            for kind in kinds
        },
    }


def best_tail(report: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    """The tail ("low" or "high") with the higher pooled detection rate."""
    cell = report.get("pooled_cut")
    if not cell:
        return None
    ranked = sorted(
        cell.items(),
        key=lambda item: -(item[1]["value"] if item[1]["value"] is not None else -1),
    )
    return ranked[0]
