"""Pure rules for the measures evaluation (no I/O, no scoring).

A strength (sn nesting, sm vague names, sd delegation) is turned on in the
calibration only if it passes the budget below on the dev split. Everything
here is a plain function over numbers so the decision is directly testable.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from typing import Any

from varde_code.quality_score.calibration import Calibration

MICRO = 1_000_000
STRENGTHS = ("sn", "sm", "sd")
GRID = (0.5, 1.0, 2.0)
TARGET = {"sn": "guard_nesting", "sm": "rename_vague", "sd": "wrappers"}
PAIR_FP_BUDGET = 0.10  # worse-than-before (tolerance) on refactor-after files
BELOW_P10_BAR = 0.12  # same bar as delta_eval_run.GOOD_FP_BAR (10% in expectation)
FILE_LOSS_BUDGET = 0.10  # dev files losing more than the tolerance against off
AFTER_HIGHER_SLACK = 0.05  # dev pairs where after scores above before
MIN_TARGET_GAIN = 0.05  # target below-p10 rate must rise by 5 points
SCORE_TOLERANCE = 0.5  # delta.WORSE_TOLERANCE
Q_SLACK = 1e-9


class SplitError(ValueError):
    """The test split was asked for."""


def require_dev_split(split: str) -> None:
    if split != "dev":
        raise SplitError(f"only the dev split is readable, not {split!r}")


def config_names() -> list[tuple[str, dict[str, float]]]:
    """(name, strengths) for baseline, each strength alone at each grid value, all."""
    configs: list[tuple[str, dict[str, float]]] = [
        ("off", dict.fromkeys(STRENGTHS, 0.0))
    ]
    for key in STRENGTHS:
        configs += [(f"{key}={v}", {key: v}) for v in GRID]
    configs += [(f"all={v}", dict.fromkeys(STRENGTHS, v)) for v in GRID]
    return configs


def with_strengths(
    calibration: Calibration, values: Mapping[str, float]
) -> Calibration:
    strengths = dict(calibration.global_strengths)
    for key, value in values.items():
        strengths[key] = round(value * MICRO)
    return dataclasses.replace(calibration, global_strengths=strengths)


def rate_of(cell: Mapping[str, Any]) -> float | None:
    return cell["rate"]


def targets_of(values: Mapping[str, float]) -> list[str]:
    return [TARGET[k] for k in STRENGTHS if values.get(k, 0) > 0]


def q_hurt(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> list[str]:
    """Languages whose Q4 or Q5 pass rate fell against the baseline."""
    hurt = []
    for language, base in baseline.items():
        for part in ("q4", "q5"):
            was, now = rate_of(base[part]), rate_of(candidate[language][part])
            if was is not None and (now is None or now < was - Q_SLACK):
                hurt.append(f"{language} {part} {was:.3f}->{now}")
        more = candidate[language]["q5"]["inversions"] - base["q5"]["inversions"]
        if more > 0:
            hurt.append(f"{language} q5 inversions +{more}")
    return hurt


def agreed_hurt(
    baseline: Mapping[str, float], candidate: Mapping[str, float]
) -> list[str]:
    """Agreed samples that lose more than the verdict tolerance."""
    return [
        f"{key} {baseline[key]:.1f}->{candidate[key]:.1f}"
        for key in sorted(baseline)
        if baseline[key] - candidate[key] > SCORE_TOLERANCE
    ]


def file_loss(
    baseline: Mapping[str, float], candidate: Mapping[str, float]
) -> dict[str, Any]:
    """Share of files scoring over the tolerance below their strengths-off score."""
    keys = sorted(baseline.keys() & candidate.keys())
    hits = sum(1 for k in keys if baseline[k] - candidate[k] > SCORE_TOLERANCE)
    return {"hits": hits, "n": len(keys), "rate": hits / len(keys) if keys else None}


def target_gain(
    kind: str, baseline: Mapping[str, Any], candidate: Mapping[str, Any]
) -> float | None:
    """Rise of the non-circular (leave-one-out below-p10) rate of ``kind``."""
    was = baseline["kinds"].get(kind, {}).get("below", {}).get("rate")
    now = candidate["kinds"].get(kind, {}).get("below", {}).get("rate")
    return None if was is None or now is None else now - was


def problems(
    name: str,
    values: Mapping[str, float],
    baseline: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> list[str]:
    """Reasons a configuration must stay off; empty means it may ship on.

    Budget: good-file false positives (pair worse-than-before at the tolerance
    <= 10%, leave-one-out below-p10 <= 0.12), every turned-on strength lifts its
    target degradation by at least 5 points, and Q4/Q5, agreed samples and the
    monolith and school-draft below-p10 shares do not get worse.
    """
    found = []
    pair_fp = rate_of(candidate["pair_fp"])
    if pair_fp is None or pair_fp > PAIR_FP_BUDGET:
        found.append(f"pair false positive {pair_fp} over {PAIR_FP_BUDGET}")
    below_fp = rate_of(candidate["good_product"])
    if below_fp is None or below_fp > BELOW_P10_BAR:
        found.append(f"good-file below-p10 {below_fp} over {BELOW_P10_BAR}")
    for kind in targets_of(values):
        gain = target_gain(kind, baseline, candidate)
        if gain is None or gain < MIN_TARGET_GAIN:
            found.append(f"{kind} gain {gain} under {MIN_TARGET_GAIN}")
    found += [f"Q hurt: {h}" for h in q_hurt(baseline["q"], candidate["q"])]
    found += [
        f"agreed: {h}" for h in agreed_hurt(baseline["agreed"], candidate["agreed"])
    ]
    was, now = rate_of(baseline["drafts_below"]), rate_of(candidate["drafts_below"])
    if was is not None and (now is None or now < was - Q_SLACK):
        found.append(f"drafts_below {was:.3f}->{now}")
    loss = rate_of(candidate["file_loss"])
    if loss is None or loss > FILE_LOSS_BUDGET:
        found.append(f"good files losing points {loss} over {FILE_LOSS_BUDGET}")
    higher = candidate["pairs_dev"]["after_higher"]["rate"]
    was_higher = baseline["pairs_dev"]["after_higher"]["rate"]
    if higher is None or higher < was_higher - AFTER_HIGHER_SLACK:
        found.append(f"pairs after>before {was_higher:.3f}->{higher}")
    return [f"{name}: {p}" for p in found]


def decisions(
    results: Sequence[tuple[str, Mapping[str, float], Mapping[str, Any]]],
) -> dict[str, list[str]]:
    """Configuration name -> its problems; the first entry must be the baseline."""
    baseline = results[0][2]
    return {
        name: problems(name, values, baseline, result)
        for name, values, result in results[1:]
    }
