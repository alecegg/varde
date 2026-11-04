"""``--vs``: which reference a file's score is judged against.

``repo`` judges against the repo's own file scores (a distribution, handled by
``delta.judge``). ``generic`` and ``mine`` give a line only: the shipped
calibration's ``X`` or the ``X`` of the user's saved examples. A line has no
score distribution, so those verdicts say above or below the line and never
"worse than N%". This module reads no accept/reject labels, only the overlay
the user saved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .calibration import Calibration
from .fixedpoint.arithmetic import MICRO
from .refactor_line import needs_refactor

VS_NAMES = ("repo", "generic", "mine")
BASIS_FILE = "file-only"
BASELINE_PAGE = "varde code quality baseline ui"


@dataclass(frozen=True)
class Reference:
    """One chosen reference; ``line`` is None when no verdict can be given."""

    name: str
    label: str
    n_or_k: int | None
    line: float | None
    calibration: Calibration
    reason: str = ""


def header(reference: Reference, basis: str = BASIS_FILE) -> str:
    return f"vs {reference.label}, basis {basis}"


def _placeholder(calibration: Calibration, language: str) -> bool:
    entry = calibration.languages.get(language)
    return entry is None or "placeholder" in str(entry.validation.get("provenance", ""))


def _line_of(calibration: Calibration, language: str) -> float:
    return calibration.languages[language].threshold_x / MICRO


def generic_reference(calibration: Calibration, language: str) -> Reference:
    label = f"generic corpus ({calibration.id}, n not recorded)"
    if _placeholder(calibration, language):
        return Reference(
            "generic",
            label,
            None,
            None,
            calibration,
            f"generic not calibrated for {language}: no verdict",
        )
    return Reference(
        "generic", label, None, _line_of(calibration, language), calibration
    )


def mine_reference(
    calibration: Calibration, sample_count: int, language: str
) -> Reference:
    label = f"your examples (k={sample_count})"
    if sample_count == 0:
        return Reference(
            "mine",
            label,
            0,
            None,
            calibration,
            f"no saved examples for {language} (k=0): no verdict; "
            f"save some with `{BASELINE_PAGE}`",
        )
    return Reference(
        "mine", label, sample_count, _line_of(calibration, language), calibration
    )


def resolve(vs_name: str, language: str, parent: Calibration) -> Reference:
    """The ``generic`` or ``mine`` reference; ``mine`` reads the user's overlay.

    ``repo`` has a score list instead of a line and is handled by the caller.
    """
    if vs_name == "generic":
        return generic_reference(parent, language)
    if vs_name != "mine":
        raise ValueError(f"unknown --vs {vs_name!r}; expected one of {VS_NAMES}")
    from .cli.baseline_service import DEFAULT_DATA, BaselineData, effective

    calibration, overlay = effective(BaselineData(DEFAULT_DATA), language)
    count = 0 if overlay is None else len(overlay.samples)
    return mine_reference(calibration, count, language)


def verdict(
    reference: Reference, score: float, basis: str = BASIS_FILE
) -> dict[str, Any]:
    """The line verdict for ``generic`` and ``mine``; no ``worse_than_percent``."""
    result: dict[str, Any] = {
        "vs": reference.name,
        "reference_name": reference.label,
        "basis": basis,
        "line": reference.line,
        "score": score,
    }
    key = "n" if reference.name == "repo" else "k"
    result[key] = reference.n_or_k
    if reference.line is None:
        result["message"] = f"{header(reference, basis)}: {reference.reason}"
        return result
    below = needs_refactor(score, reference.line)
    result["needs_refactor"] = below
    where = "below" if below else "at or above"
    advice = "worth refactoring" if below else "good enough"
    result["message"] = (
        f"{header(reference, basis)}: score {score} {where} its line {reference.line}, "
        f"{advice}"
    )
    return result


def repo_header(n: int, basis: str = BASIS_FILE) -> dict[str, Any]:
    """Header fields added to the ``repo`` verdict of ``delta.judge``."""
    label = f"repo (n={n})"
    return {"vs": "repo", "reference_name": label, "basis": basis, "n": n}


def with_header(label: str, message: str, basis: str = BASIS_FILE) -> str:
    return f"vs {label}, basis {basis}: {message}"
