"""User-facing score view: 0-100 values only, built from a key whitelist."""

from __future__ import annotations

import math
from collections.abc import Mapping
from fractions import Fraction
from typing import Any

from .guidance import category_guidance

MICRO = 1_000_000
NO_CODE_NOTICE = "No scorable code found, so there is no score."
_ROUNDING_SLACK_TENTHS = 1


def user_view(  # noqa: PLR0913, PLR0917 - one optional finding per keyword
    scope_payload: dict[str, Any],
    breakdown: list[dict[str, Any]],
    tests_passed: bool | None = None,
    refactor: dict[str, Any] | None = None,
    monolith: dict[str, Any] | None = None,
    file_advisories: Mapping[str, dict[str, Any] | None] | None = None,
    fixes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the whitelisted 0-100 view of a scored scope.

    ``refactor`` and ``monolith`` are the optional findings of ``refactor_line``;
    ``file_advisories`` maps ``delegation`` and ``fragmentation`` to the optional
    findings of ``file_advisories``. Advisories sit beside the score and never
    change it. ``fixes`` is the ranked list of ``fix_explain.fixes``; an empty
    list is kept so a reader can tell "nothing to change" from "not asked".
    """
    view: dict[str, Any] = {
        "score": None,
        "calibration": str(scope_payload.get("calibration", "")),
        "categories": [],
        "tests_passed": tests_passed,
    }
    tokens = scope_payload.get("tokens", 0)
    score = scope_payload.get("score")
    if score is None or not tokens:
        view["notice"] = NO_CODE_NOTICE
        return view
    view["score"] = _tenths_to_float(_clamped_tenths(*_rational(score), "score"))
    view["categories"] = [
        {
            "name": str(entry["name"]),
            "points_lost": _tenths_to_float(
                _clamped_tenths(entry["points_lost"], 1, "points_lost")
            ),
            "hint": str(entry["hint"]),
            **category_guidance(str(entry["name"]), entry.get("fix_targets") or []),
        }
        for entry in breakdown
        if _positive_points(entry["points_lost"])
    ]
    if refactor is not None:
        view["refactor"] = dict(refactor)
    if fixes is not None:
        view["fixes"] = [dict(fix) for fix in fixes]
    if monolith is not None:
        view["monolith"] = dict(monolith)
    for key, advisory in (file_advisories or {}).items():
        if advisory is not None:
            view[key] = dict(advisory)
    return view


def with_debug(view: dict[str, Any], raw_payload: dict[str, Any]) -> dict[str, Any]:
    """Return the view plus the raw scorer fields under a ``debug`` key."""
    return {**view, "debug": raw_payload}


def _rational(score: Any) -> tuple[Any, Any]:
    if isinstance(score, dict):
        return score.get("numerator"), score.get("denominator")
    return score, MICRO


def _positive_points(micro_points: Any) -> bool:
    _require_number(micro_points, "points_lost")
    return micro_points > 0


def _require_number(value: Any, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a number")  # noqa: TRY004 - spec: bad inputs raise ValueError
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{label} must be finite")


def _clamped_tenths(micro_numerator: Any, denominator: Any, label: str) -> int:
    """Half-up tenths of a point from micro-points over a denominator."""
    _require_number(micro_numerator, label)
    _require_number(denominator, label)
    if denominator <= 0:
        raise ValueError(f"{label} denominator must be positive")
    points = Fraction(micro_numerator) / Fraction(denominator) / MICRO
    tenths = math.floor(points * 10 + Fraction(1, 2))
    if not -_ROUNDING_SLACK_TENTHS <= tenths <= 1000 + _ROUNDING_SLACK_TENTHS:
        raise ValueError(f"{label} is outside 0-100")
    return max(0, min(1000, tenths))


def _tenths_to_float(tenths: int) -> float:
    return tenths / 10
