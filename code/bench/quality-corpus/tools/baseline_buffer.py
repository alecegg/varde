"""Buffer and leave-one-problem-out error of baseline metrics (pure functions).

Per metric m, language L, problem p:
``e_r = |m_r - m_agreed| / max(|m_agreed|, u_m)`` for each valid recreation r,
``e_recreate = max(e_1, e_2)`` (the mean is returned for the report only),
``e_loo = |b_(-p) - m_agreed,p| / max(|m_agreed,p|, u_m)`` with ``b_(-p)`` pooled
over the agreed code of the other problems. ``err = max over p of
max(e_recreate, e_loo)``; a problem with no valid recreation uses ``e_loo``
only. Buffer: 5% if ``err <= 0.05``, 10% if ``err <= 0.10``, else ``none-yet``
(more data or another statistic is needed, see ``baseline_index_buffer``;
never a final outcome).
No model call.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import baseline_measure as bm

BUFFER_STEPS = (0.05, 0.10)
NONE_YET = "none-yet"
RATE_METRICS = ("fragment_rate", "debt_density")
# One unit of each metric, fixed before any recreation is measured: 1 for the
# integer metrics, 1 per 1k tokens for rates and density.
UNIT = {
    "Plo": 1.0,
    "t_frag": 1.0,
    "Phi": 1.0,
    "c0": 1.0,
    "dp0": 1.0,
    "k0": 1.0,
    "t0": 1.0,
    "fragment_rate": 1.0,
    "debt_density": 1.0,
}

Scalars = Mapping[str, float | None]


def scalar_metrics(metrics: Mapping[str, Any]) -> dict[str, float | None]:
    """Flatten ``baseline_measure.metrics_of`` output to one float per metric."""
    flat: dict[str, float | None] = {}
    for name in UNIT:
        value = metrics[name]
        if name in RATE_METRICS:
            micro = value["per_1k_micro"]
            flat[name] = None if micro is None else micro / 1_000_000
        else:
            flat[name] = None if value is None else float(value)
    return flat


def relative_error(value: float, agreed: float, unit: float) -> float:
    """Error against the agreed value with the unit-floor denominator."""
    return abs(value - agreed) / max(abs(agreed), unit)


def recreation_errors(
    metric: str, agreed: float, recreations: Sequence[float | None]
) -> list[float]:
    """Errors of the valid recreations; ``None`` values are not measured."""
    unit = UNIT[metric]
    return [relative_error(r, agreed, unit) for r in recreations if r is not None]


def recreate_summary(errors: Sequence[float]) -> dict[str, Any]:
    """Worst-case error (used for the buffer) and mean (report only)."""
    if not errors:
        return {"e_recreate": None, "e_mean": None}
    return {"e_recreate": max(errors), "e_mean": sum(errors) / len(errors)}


def loo_baselines(
    measurements_by_problem: Mapping[str, Sequence[bm.Measurement]],
) -> dict[str, dict[str, float | None]]:
    """Per problem, scalar metrics pooled over the agreed code of the others."""
    pooled: dict[str, dict[str, float | None]] = {}
    for problem in measurements_by_problem:
        others = [
            m
            for other, measured in measurements_by_problem.items()
            if other != problem
            for m in measured
        ]
        if not others:
            raise ValueError("leave-one-problem-out needs at least two problems")
        pooled[problem] = scalar_metrics(bm.metrics_of(bm.pool_measurements(others)))
    return pooled


def pooled_baseline(
    measurements_by_problem: Mapping[str, Sequence[bm.Measurement]],
) -> dict[str, float | None]:
    """Baseline pooled over all problems."""
    every = [m for measured in measurements_by_problem.values() for m in measured]
    return scalar_metrics(bm.metrics_of(bm.pool_measurements(every)))


def problem_error(
    metric: str,
    agreed: float,
    loo_baseline: float,
    recreations: Sequence[float | None],
) -> dict[str, Any]:
    """Per-problem errors; with no valid recreation ``err`` falls back to e_loo."""
    e_loo = relative_error(loo_baseline, agreed, UNIT[metric])
    summary = recreate_summary(recreation_errors(metric, agreed, recreations))
    e_recreate = summary["e_recreate"]
    err = e_loo if e_recreate is None else max(e_recreate, e_loo)
    return {**summary, "e_loo": e_loo, "err": err}


def buffer_for(err: float) -> float | str:
    """0.05 if err <= 0.05, 0.10 if err <= 0.10, else ``none-yet``."""
    for step in BUFFER_STEPS:
        if err <= step:
            return step
    return NONE_YET


def metric_buffer(
    per_problem: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Max rule over problems and the buffer decision for one metric."""
    err = max(entry["err"] for entry in per_problem.values())
    return {"err": err, "buffer": buffer_for(err), "problems": dict(per_problem)}


def derive_buffers(
    agreed: Mapping[str, Sequence[bm.Measurement]],
    recreated: Mapping[str, Sequence[bm.Measurement]],
) -> dict[str, dict[str, Any]]:
    """Per metric: pooled baseline, per-problem errors, err and buffer.

    ``agreed`` and ``recreated`` map problem -> measurements of one language
    (agreed code, valid recreations). A metric with no agreed value for a
    problem (empty pool) is left out of that problem's errors.
    """
    loo = loo_baselines(agreed)
    baseline = pooled_baseline(agreed)
    agreed_scalars = {
        p: scalar_metrics(bm.metrics_of(bm.pool_measurements(ms)))
        for p, ms in agreed.items()
    }
    recreated_scalars = {
        p: [scalar_metrics(bm.metrics_of(m)) for m in ms] for p, ms in recreated.items()
    }
    result: dict[str, dict[str, Any]] = {}
    for metric in UNIT:
        per_problem: dict[str, Mapping[str, Any]] = {}
        for problem, values in agreed_scalars.items():
            agreed_value, loo_value = values[metric], loo[problem][metric]
            if agreed_value is None or loo_value is None:
                continue
            recs = [r[metric] for r in recreated_scalars.get(problem, [])]
            per_problem[problem] = problem_error(metric, agreed_value, loo_value, recs)
        if not per_problem or baseline[metric] is None:
            result[metric] = {
                "baseline": baseline[metric],
                "err": None,
                "buffer": NONE_YET,
                "problems": {},
            }
            continue
        result[metric] = {"baseline": baseline[metric], **metric_buffer(per_problem)}
    return result
