"""Bench-only candidate scorers for the monolith blind spot (no shipped change).

Each candidate re-derives a file score from the shipped ``score_scope`` pieces:

* ``unstack`` applies the cognitive, long-side and small-side strengths once
  (they already sit inside the cost; the shipped scorer multiplies them again as
  the component weight);
* ``ungate`` counts structure costs at low structure confidence;
* ``p0`` replaces the Python parameter-comfort threshold;
* ``worst`` caps the score at the score of the worst single function, whose
  density uses at least ``WORST_FLOOR`` tokens, so it is not averaged away.
* ``dominance`` (round 2, exploratory, designed after seeing that monolith drafts
  hold 82-98% of file tokens in one function while proxies hold at most 47%)
  counts a function's own debt again by ``dominance * max(0, 2*share - 1)``,
  where share is its fraction of the file tokens.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import score_variants as sv
from varde_code.quality_score.calibration import Calibration
from varde_code.quality_score.scoring import score_scope
from varde_code.quality_score.scoring.scoring import STRUCTURE
from varde_code.quality_score.smap import score_density

MICRO = 1_000_000
WORST_FLOOR = 150
DOUBLED = ("cognitive", "long_side", "small_side")
STRENGTH_OF = {"cognitive": "w", "long_side": "wL", "small_side": "A"}


@dataclass(frozen=True)
class Spec:
    name: str
    unstack: bool = False
    ungate: bool = False
    p0: int | None = None
    worst: bool = False
    dominance: float = 0.0


# Pre-registered before any run: the placeholder and seven combinations.
CANDIDATES = (
    Spec("placeholder"),
    Spec("U unstack", unstack=True),
    Spec("G ungate", ungate=True),
    Spec("P p0=2", p0=2),
    Spec("W worst-fn", worst=True),
    Spec("U+W", unstack=True, worst=True),
    Spec("U+G+P", unstack=True, ungate=True, p0=2),
    Spec("U+G+P+W", unstack=True, ungate=True, p0=2, worst=True),
)
# Round 2: added after round 1 failed; exploratory, so its CV is optimistic.
ROUND2 = (
    Spec("D1 dominance x1", dominance=1.0),
    Spec("D2 dominance x2", dominance=2.0),
    Spec("U+D2", unstack=True, dominance=2.0),
    Spec("U+G+P+D2", unstack=True, ungate=True, p0=2, dominance=2.0),
)
# Round 3: the two combinations round 2 suggested (p0=2 carries good>worse,
# dominance carries the monolith); selection among all of them is cross-validated.
ROUND3 = (
    Spec("P+D2", p0=2, dominance=2.0),
    Spec("U+P+D2", unstack=True, p0=2, dominance=2.0),
)


def with_p0(base: Calibration, p0: int | None) -> Calibration:
    if p0 is None:
        return base
    language = base.languages["python"]
    tuned = replace(language, parameters={**language.parameters, "p0": p0 * MICRO})
    return replace(base, languages={**base.languages, "python": tuned})


def weighted_costs(
    costs: Mapping[str, int], strengths: Mapping[str, int], spec: Spec
) -> dict[str, int]:
    """Component costs after the strength weight, which ``unstack`` skips."""
    if spec.unstack:
        return dict(costs)
    return {
        name: value * strengths.get(STRENGTH_OF.get(name, name), MICRO) // MICRO
        if name in DOUBLED
        else value
        for name, value in costs.items()
    }


def gate_debt(costs: Mapping[str, int], low_confidence: bool) -> int:
    drop = STRUCTURE if low_confidence else set()
    return sum(v for k, v in costs.items() if k not in drop)


def density_score(debt: int, tokens: int) -> float:
    return score_density(debt * 1000 // max(1, tokens)) / MICRO


def function_debts(
    functions: Any, strengths: Mapping[str, int], spec: Spec, low_confidence: bool
) -> dict[str, int]:
    return {
        fn.id: gate_debt(weighted_costs(fn.costs, strengths, spec), low_confidence)
        for fn in functions
    }


def worst_function_score(
    debts: Mapping[str, int], tokens_of: Mapping[str, int]
) -> float:
    """Score of the single worst function at its own token count (floored)."""
    scores = [100.0]
    for fn_id, debt in debts.items():
        tokens = max(tokens_of.get(fn_id, 0), WORST_FLOOR)
        scores.append(density_score(debt, tokens))
    return min(scores)


def dominance_debt(
    debts: Mapping[str, int], tokens_of: Mapping[str, int], file_tokens: int, k: float
) -> int:
    """Extra debt: a function's debt again, scaled by how much of the file it is."""
    extra = 0.0
    for fn_id, debt in debts.items():
        share = tokens_of.get(fn_id, 0) / max(1, file_tokens)
        extra += k * max(0.0, 2 * share - 1) * debt
    return int(extra)


def candidate_score(record: Mapping[str, Any], base: Calibration, spec: Spec) -> float:
    gated = sv.gated_record(record, "ungated" if spec.ungate else "gated")
    scored = score_scope([gated], with_p0(base, spec.p0))
    file = scored.files[0]
    strengths = base.global_strengths
    low = bool(file.low_structure_confidence)
    components = dict(file.components)
    if spec.unstack:
        for name in DOUBLED:
            components[name] = sum(fn.costs.get(name, 0) for fn in file.functions)
    tokens_of = {str(f["id"]): f.get("tokens") or 0 for f in gated["functions"]}
    debts = function_debts(file.functions, strengths, spec, low)
    debt = gate_debt(components, low)
    debt += dominance_debt(debts, tokens_of, file.tokens, spec.dominance)
    score = density_score(debt, file.tokens)
    if not spec.worst:
        return score
    return min(score, worst_function_score(debts, tokens_of))
