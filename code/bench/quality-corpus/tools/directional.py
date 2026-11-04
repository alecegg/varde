"""Directional, per-function exceedance statistics for discrimination (pure
functions, no I/O, no model call).

A user's code is checked per function against a threshold ("higher is worse").
A *signal* maps a module's functions to one number:

* ``share``: token share of the functions beyond a threshold ``T`` (above ``T``
  for the metrics, at or below ``T`` for the too-short and forwarder signals);
* ``max``: the largest metric value of any function (no threshold).

``T`` is swept over percentiles of the pooled known-good functions. The item cut
accepts at least ``ACCEPT`` of the known-good items (one-sided); known-worse
items above the cut are caught. The best ``T`` maximises that sensitivity.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import baseline_index_buffer as ib
import discrimination as dc

Rows = ib.Rows
Row = ib.Row
Predicate = Callable[[Row], bool]

SWEEP_ABOVE = tuple(q / 100 for q in range(50, 100, 5))
SWEEP_BELOW = tuple(q / 100 for q in range(5, 55, 5))
FORWARDER_FAN = 1  # a forwarder has at most this many callers and callees
CAUGHT_CELL = 0.5

# signal -> (direction, metric); the forwarder ("indirection") needs no metric.
SIGNALS: dict[str, tuple[str, str]] = {
    "cognitive": ("above", "cognitive"),
    "max_nesting": ("above", "max_nesting"),
    "fan_out": ("above", "fan_out"),
    "depth": ("above", "depth"),
    "tree_size": ("above", "tree_size"),
    "params": ("above", "params"),
    "name_issues": ("above", "name_issues"),
    "tokens_long": ("above", "tokens"),
    "tokens_short": ("below", "tokens"),
    "indirection": ("forwarder", "tokens"),
}
FORMS = ("share", "max")
MATCHED: dict[str, tuple[str, ...]] = {
    "inline_helpers": ("cognitive", "max_nesting", "fan_out", "tokens_long"),
    "guard_nesting": ("cognitive", "max_nesting", "fan_out", "tokens_long"),
    "compound": (
        "cognitive",
        "max_nesting",
        "fan_out",
        "tokens_long",
        "params",
        "name_issues",
    ),
    "rename_vague": ("name_issues",),
    "add_params": ("params",),
    "wrappers": ("indirection", "tokens_short"),
    "deep_chain": ("depth", "tree_size", "fan_out"),
}


def predicate(signal: str, threshold: float) -> Predicate:
    direction, metric = SIGNALS[signal]
    if direction == "above":
        return lambda r: r.get(metric) is not None and r[metric] > threshold
    if direction == "below":
        return lambda r: r.get(metric) is not None and r[metric] <= threshold

    def forwarder(r: Row) -> bool:
        return (
            (r.get("tokens") or 0) <= threshold
            and (r.get("cognitive") or 0) == 0
            and (r.get("fan_in") or 0) <= FORWARDER_FAN
            and (r.get("fan_out") or 0) <= FORWARDER_FAN
        )

    return forwarder


def token_share(rows: Rows, hit: Predicate) -> float | None:
    weighted = [r for r in rows if r.get("tokens")]
    total = sum(r["tokens"] for r in weighted)
    if total <= 0:
        return None
    return sum(r["tokens"] for r in weighted if hit(r)) / total


def max_value(rows: Rows, signal: str) -> float | None:
    values = ib.values_of(rows, SIGNALS[signal][1])
    return max(values) if values else None


def item_value(
    rows: Rows, signal: str, form: str, threshold: float | None
) -> float | None:
    if form == "max":
        return max_value(rows, signal)
    return token_share(rows, predicate(signal, threshold))


def percentile_of(pairs: Sequence[tuple[float, float]], value: float) -> float:
    """Token-weighted share of the pooled functions with metric <= value."""
    total = sum(w for _, w in pairs)
    return sum(w for v, w in pairs if v <= value) / total if total else 0.0


def thresholds(pool: Rows, signal: str) -> list[float]:
    """Distinct raw thresholds at the swept percentiles of the pooled good set."""
    direction, metric = SIGNALS[signal]
    steps = SWEEP_ABOVE if direction == "above" else SWEEP_BELOW
    pairs = ib.weighted_pairs(pool, metric)
    found = [ib.weighted_quantile(pairs, q) for q in steps]
    return sorted({t for t in found if t is not None})


def forms_of(signal: str) -> tuple[str, ...]:
    """The max form only makes sense for the higher-is-worse metrics."""
    return FORMS if SIGNALS[signal][0] == "above" else ("share",)


def candidates(pool: Rows, signal: str, form: str) -> list[float | None]:
    return [None] if form == "max" else list(thresholds(pool, signal))


def one_sided_cut(good_values: Sequence[float]) -> float:
    """Smallest cut that accepts at least ACCEPT of the good items."""
    return dc.halfwidth(list(good_values))


def values_for(
    items: Mapping[str, Rows], signal: str, form: str, threshold: float | None
) -> dict[str, float]:
    found = {k: item_value(r, signal, form, threshold) for k, r in items.items()}
    return {k: v for k, v in found.items() if v is not None}


def evaluate(
    good: Mapping[str, Rows],
    worse: Mapping[str, Mapping[str, Rows]],
    signal: str,
    form: str,
    threshold: float | None,
) -> dict[str, Any] | None:
    good_values = values_for(good, signal, form, threshold)
    if not good_values:
        return None
    cut = one_sided_cut(list(good_values.values()))
    by_type_values = {
        kind: values_for(items, signal, form, threshold)
        for kind, items in worse.items()
    }
    worse_all = [v for items in by_type_values.values() for v in items.values()]
    return {
        "signal": signal,
        "form": form,
        "threshold": threshold,
        "cut": cut,
        "accepted": sum(1 for v in good_values.values() if v <= cut + dc.EPS)
        / len(good_values),
        "auc": dc.auc(list(good_values.values()), worse_all),
        "sens": dc.caught(worse_all, cut),
        "by_type": {
            k: dc.caught(list(v.values()), cut) for k, v in by_type_values.items()
        },
    }


def rank_key(result: Mapping[str, Any]) -> tuple[float, float]:
    return (result["sens"] or 0.0, result["auc"] or 0.0)


def best_for(
    good: Mapping[str, Rows],
    worse: Mapping[str, Mapping[str, Rows]],
    signal: str,
    form: str,
) -> dict[str, Any] | None:
    """Threshold maximising sensitivity at 90% specificity (ties: AUC, then the
    lower swept percentile)."""
    pool = [r for rows in good.values() for r in rows]
    results = [
        evaluate(good, worse, signal, form, t) for t in candidates(pool, signal, form)
    ]
    results = [r for r in results if r is not None]
    if not results:
        return None
    best = results[0]
    for result in results[1:]:
        if rank_key(result) > rank_key(best):
            best = result
    return best


def fit_all(
    good: Mapping[str, Rows], worse: Mapping[str, Mapping[str, Rows]]
) -> dict[str, dict[str, dict[str, Any] | None]]:
    return {
        signal: {form: best_for(good, worse, signal, form) for form in forms_of(signal)}
        for signal in SIGNALS
    }


def best_form(by_form: Mapping[str, dict[str, Any] | None]) -> dict[str, Any] | None:
    found = [r for r in by_form.values() if r is not None]
    return max(found, key=rank_key) if found else None


def pool_percentile(
    good: Mapping[str, Rows], signal: str, threshold: float | None
) -> float | None:
    if threshold is None:
        return None
    pool = [r for rows in good.values() for r in rows]
    return percentile_of(ib.weighted_pairs(pool, SIGNALS[signal][1]), threshold)


def contested_view(
    good: Mapping[str, Rows], contested: Mapping[str, Rows], fit: Mapping[str, Any]
) -> dict[str, Any]:
    """Same statistic on contested drafts: flagged share and AUC against good."""
    signal, form, threshold = fit["signal"], fit["form"], fit["threshold"]
    values = values_for(contested, signal, form, threshold)
    good_values = list(values_for(good, signal, form, threshold).values())
    return {
        "flagged": dc.caught(list(values.values()), fit["cut"]),
        "auc": dc.auc(good_values, list(values.values())),
        "values": values,
    }


def is_caught(by_type: Mapping[str, float | None], kind: str) -> bool:
    fraction = by_type.get(kind)
    return fraction is not None and fraction >= CAUGHT_CELL


def matrix(
    best: Mapping[str, Mapping[str, Any] | None],
) -> dict[str, dict[str, float | None]]:
    """degradation type -> signal -> sensitivity at the signal's best form."""
    out: dict[str, dict[str, float | None]] = {}
    for signal, result in best.items():
        if result is None:
            continue
        for kind, fraction in result["by_type"].items():
            out.setdefault(kind, {})[signal] = fraction
    return out


def uncaught(
    grid: Mapping[str, Mapping[str, float | None]],
) -> dict[str, dict[str, Any]]:
    """Per type: matched caught?, best matched, and best any-signal sensitivity."""
    out: dict[str, dict[str, Any]] = {}
    for kind, row in grid.items():
        matched = {s: row.get(s) for s in MATCHED.get(kind, ())}
        top_matched = max(
            matched.items(), key=lambda kv: kv[1] or 0.0, default=(None, None)
        )
        top_any = max(row.items(), key=lambda kv: kv[1] or 0.0, default=(None, None))
        out[kind] = {
            "matched_best": top_matched,
            "any_best": top_any,
            "caught": (top_matched[1] or 0.0) >= CAUGHT_CELL,
        }
    return out


# ---- proxy-set sensitivity --------------------------------------------------


def curated_good(good: Mapping[str, Rows]) -> dict[str, Rows]:
    """Agreed solutions plus proxies whose own cognitive and size exceedance is at
    or below the median of the whole good set. Chosen by the metrics themselves,
    so circular: an upper bound only."""
    stats = {
        k: (
            ib.stat_wshare(rows, "cognitive") or 0.0,
            ib.stat_wshare(rows, "tokens") or 0.0,
        )
        for k, rows in good.items()
    }
    medians = tuple(statistics.median(s[i] for s in stats.values()) for i in (0, 1))
    keep = {
        k
        for k, s in stats.items()
        if k.startswith("agreed:") or (s[0] <= medians[0] and s[1] <= medians[1])
    }
    return {k: v for k, v in good.items() if k in keep}


def lopo(
    good: Mapping[str, Rows],
    worse: Mapping[str, Mapping[str, Rows]],
    problems: Sequence[str],
    keep_proxies: bool,
) -> dict[str, dict[str, Any]]:
    """Leave-one-problem-out: fit T and the cut without a problem's agreed
    solution and degradations, then test on them. Per signal and form: pooled
    held-out sensitivity, by type, and the held-out agreed items accepted."""
    tally: dict[str, dict[str, Any]] = {}
    for held in problems:
        train_good = {
            k: v
            for k, v in good.items()
            if k != f"agreed:{held}" and (keep_proxies or k.startswith("agreed:"))
        }
        train_worse = {
            kind: {p: r for p, r in items.items() if p != held}
            for kind, items in worse.items()
        }
        for signal, by_form in fit_all(train_good, train_worse).items():
            fit = best_form(by_form)
            if fit is None:
                continue
            cell = tally.setdefault(signal, {"hits": {}, "total": {}, "ok": 0, "n": 0})
            args = (fit["signal"], fit["form"], fit["threshold"])
            for kind, items in worse.items():
                if held in items:
                    value = item_value(items[held], *args)
                    cell["total"][kind] = cell["total"].get(kind, 0) + 1
                    cell["hits"][kind] = cell["hits"].get(kind, 0) + int(
                        value is not None and value > fit["cut"] + dc.EPS
                    )
            value = item_value(good[f"agreed:{held}"], *args)
            cell["n"] += 1
            cell["ok"] += int(value is not None and value <= fit["cut"] + dc.EPS)
    return {
        signal: {
            "by_type": {k: cell["hits"][k] / cell["total"][k] for k in cell["total"]},
            "sens": sum(cell["hits"].values()) / max(sum(cell["total"].values()), 1),
            "held_out_accepted": cell["ok"] / cell["n"],
        }
        for signal, cell in tally.items()
    }
