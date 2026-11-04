"""Relative refactor line and the separate monolith advisory.

The line ``X`` is the score below which ``share`` of the reference's own file
scores fall, so a finding reads "worse than N% of your reference". The monolith
advisory is a separate finding and never changes the score: tidy single-function
modules and school monoliths overlap on score, so only the structure tells them
apart. Pure functions; no I/O.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

MICRO = 1_000_000
DEFAULT_SHARE = 0.10
INDIRECTION_SHARE = Fraction(1, 2)  # tiny functions (<= t_frag) among all functions
LIMIT_KEYS = ("Phi", "c0", "t_frag")


def reference_line(
    reference_scores: Sequence[float], share: float = DEFAULT_SHARE
) -> float:
    """Nearest-rank score with at most ``share`` of the reference strictly below."""
    if not reference_scores:
        raise ValueError("no reference scores")
    ordered = sorted(reference_scores)
    rank = math.ceil(Fraction(str(share)) * len(ordered))
    return ordered[max(rank, 1) - 1]


def needs_refactor(score: float, line: float) -> bool:
    return score < line


def percentile_vs_reference(score: float, reference_scores: Sequence[float]) -> int:
    """Whole percent of the reference's file scores that are better than ``score``."""
    if not reference_scores:
        raise ValueError("no reference scores")
    better = sum(1 for value in reference_scores if value > score)
    return better * 100 // len(reference_scores)


def refactor_field(
    score: float, reference_scores: Sequence[float], share: float = DEFAULT_SHARE
) -> dict[str, Any]:
    """The user-view ``refactor`` field: verdict and where the code stands."""
    line = reference_line(reference_scores, share)
    worse_than = percentile_vs_reference(score, reference_scores)
    needed = needs_refactor(score, line)
    return {
        "needs_refactor": needed,
        "worse_than_percent": worse_than,
        "message": (
            f"worse than {worse_than}% of your reference: worth refactoring"
            if needed
            else f"worse than {worse_than}% of your reference: good enough"
        ),
    }


def limits_of(parameters: Mapping[str, int]) -> dict[str, int]:
    """Plain-unit ``Phi``, ``c0`` and ``t_frag`` from micro-unit calibration values."""
    return {key: parameters[key] // MICRO for key in LIMIT_KEYS}


def is_dominant(tokens: int, file_tokens: int) -> bool:
    return 2 * tokens > file_tokens


def indirection_is_high(functions: Sequence[Mapping[str, Any]], t_frag: int) -> bool:
    tiny = sum(1 for fn in functions if (fn.get("tokens") or 0) <= t_frag)
    return bool(functions) and Fraction(tiny, len(functions)) >= INDIRECTION_SHARE


def monolith_advisory(
    record: Mapping[str, Any], limits: Mapping[str, int]
) -> dict[str, Any] | None:
    """The ``monolith`` field for one file's facts, or None; never touches the score.

    Fires when one function holds more than half the file tokens and either
    exceeds ``Phi`` or ``c0`` or the file's indirection signal is high.
    """
    file_tokens = record.get("tokens") or 0
    functions = record.get("functions") or []
    indirect = indirection_is_high(functions, limits["t_frag"])
    for fn in functions:
        tokens = fn.get("tokens") or 0
        if not is_dominant(tokens, file_tokens):
            continue
        exceeds = tokens > limits["Phi"] or (fn.get("cognitive") or 0) > limits["c0"]
        if exceeds or indirect:
            return _advisory(record, fn, tokens, file_tokens)
    return None


def _advisory(
    record: Mapping[str, Any], fn: Mapping[str, Any], tokens: int, file_tokens: int
) -> dict[str, Any]:
    name = str(fn["name"])
    share = tokens * 100 // file_tokens
    return {
        "function": name,
        "file": str(record["path"]),
        "line": fn["line"],
        "share_percent": share,
        "action": (
            f"`{name}` holds {share}% of the file: split it at its responsibility "
            "boundaries into named parts"
        ),
    }
