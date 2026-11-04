"""Exact scoring of seeded samples at candidate strengths (read-only helpers)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any

from varde_code.quality_score.calibration import Calibration
from varde_code.quality_score.scoring import score_scope

TARGET = "smoothed"
CONTROL = "sizematched"


@dataclass
class SampleFacts:
    """Facts records of one sample: target, challengers (labelled), size control."""

    id: str
    language: str
    target: dict[str, Any]
    challengers: dict[str, dict[str, Any]]
    control: dict[str, Any] | None = None
    order: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.order = sorted(self.challengers)


def at_strengths(calibration: Calibration, strengths: Mapping[str, int]) -> Calibration:
    return replace(calibration, global_strengths=dict(strengths))


def debt(facts: dict[str, Any], calibration: Calibration) -> int:
    return score_scope([facts], calibration).debt


def sample_debts(sample: SampleFacts, calibration: Calibration) -> dict[str, int]:
    """Debt of every record of one sample, scored at this calibration."""
    debts = {TARGET: debt(sample.target, calibration)}
    debts.update(
        {name: debt(facts, calibration) for name, facts in sample.challengers.items()}
    )
    if sample.control is not None:
        debts[CONTROL] = debt(sample.control, calibration)
    return debts


def worst_margin(
    samples: list[SampleFacts], calibration: Calibration, floor: int
) -> int:
    """Smallest challenger-minus-target debt; stops at the first one below floor.

    The sample and challenger that stopped a point move to the front, so the
    next candidate meets the likeliest failure first. `samples` is reordered in
    place; the result does not depend on that order.
    """
    worst = None
    for sample in list(samples):
        target = debt(sample.target, calibration)
        for name in list(sample.order):
            margin = debt(sample.challengers[name], calibration) - target
            worst = margin if worst is None else min(worst, margin)
            if margin < floor:
                sample.order.remove(name)
                sample.order.insert(0, name)
                samples.remove(sample)
                samples.insert(0, sample)
                return worst
    return worst if worst is not None else floor
