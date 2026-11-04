"""Relative verdict for one score: against its earlier version and its reference.

Pure functions; no I/O. Wording is always relative ("worse than N% of your
reference", "no worse than before") and every percentage carries the reference
n. A reference smaller than ``reference.N_MIN`` gives no reference verdict.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .refactor_line import refactor_field, reference_line
from .reference import N_MIN, confidence

# A drop of at most this many points is noise, not "worse than before".
# Measured on the 65 dev-hash mined refactor pairs (notes/delta-eval.md in the
# plan 2026-10-31-vqs-delta-and-measures): good-file false positives fall from
# 14% (9/65) at 0.0 to 3% (2/65) at 0.5. Cost on dev-file degradations (circular
# against their own originals, n=79/97): guard_nesting 89% -> 37%, rename_vague
# 69% -> 46%, add_params 76% -> 64%; the lost flags were mostly sub-point moves.
WORSE_TOLERANCE = 0.5


def is_worse(score_now: float, score_before: float) -> bool:
    return score_before - score_now > WORSE_TOLERANCE


def _before_message(score_now: float, score_before: float) -> str:
    if is_worse(score_now, score_before):
        return f"worse than before ({score_before} -> {score_now})"
    return f"no worse than before ({score_before} -> {score_now})"


def _reference_message(field: dict[str, Any], line: float, n: int) -> str:
    low = " (low confidence)" if confidence(n) == "low" else ""
    where = f"worse than {field['worse_than_percent']}% of your reference (n={n}){low}"
    if field["needs_refactor"]:
        return f"{where}: below its 10th percentile ({line}), worth refactoring"
    return f"{where}: at or above its 10th percentile ({line})"


def judge(
    score_now: float,
    score_before: float | None,
    reference_scores: Sequence[float] | None,
) -> dict[str, Any]:
    """Verdict fields for ``score_now``; keys without a verdict are absent.

    ``reference_scores`` None means no reference was given.
    """
    verdict: dict[str, Any] = {}
    parts = []
    if score_before is not None:
        verdict["worse_than_before"] = is_worse(score_now, score_before)
        parts.append(_before_message(score_now, score_before))
    if reference_scores is None:
        verdict["message"] = "; ".join(parts)
        return verdict
    n = len(reference_scores)
    verdict["n_reference"] = n
    if n < N_MIN:
        parts.append(f"reference too small (n={n}, need {N_MIN}): no reference verdict")
    else:
        field = refactor_field(score_now, reference_scores)
        line = reference_line(reference_scores)
        verdict["needs_refactor"] = field["needs_refactor"]
        verdict["below_reference_p10"] = field["needs_refactor"]
        verdict["worse_than_percent"] = field["worse_than_percent"]
        parts.append(_reference_message(field, line, n))
    verdict["message"] = "; ".join(parts)
    return verdict
