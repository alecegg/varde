"""Fixture calibration and the per-language gating-state stub for the gate suite.

``gate-test-cal`` is test data only. It marks python, typescript and csharp as
``panel-validated`` so the gate mechanism can be exercised before the real
calibration validates any language. It never ships and is never validation.

Calibration t2 adds ``Calibration.language_gating_available(language)`` on its
own branch. Until that branch merges, ``language_gating_state`` reads the same
per-language ``validation.state`` field the calibration records. ``KNOWN_STATES``
is the closed set; an unknown state or language raises instead of guessing.
"""

from __future__ import annotations

from pathlib import Path

from varde_code.quality_score.calibration import Calibration, load_calibration

CALIBRATION_PATH = Path(__file__).with_name("gate-test-cal.toml")
CALIBRATION_ID = "gate-test-cal"
GATED_LANGUAGES = ("python", "typescript", "csharp")
PANEL_VALIDATED = "panel-validated"
REPORT_ONLY = "report-only"
KNOWN_STATES = frozenset({PANEL_VALIDATED, REPORT_ONLY})


def load_gate_test_calibration() -> Calibration:
    return load_calibration(CALIBRATION_PATH)


def language_gating_state(calibration: Calibration, language: str) -> str:
    """Return the language's validation state; raise on an unknown language or state."""
    entry = calibration.languages.get(language)
    if entry is None:
        raise KeyError(f"calibration {calibration.id!r} has no language {language!r}")
    state = entry.validation.get("state", REPORT_ONLY)
    if state not in KNOWN_STATES:
        raise ValueError(f"unknown validation state {state!r} for {language!r}")
    return str(state)


def language_gating_available(calibration: Calibration, language: str) -> bool:
    """Stub of ``Calibration.language_gating_available`` (calibration t2)."""
    return language_gating_state(calibration, language) == PANEL_VALIDATED
