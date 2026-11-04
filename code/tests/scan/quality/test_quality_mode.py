"""Per-language activation: only panel- or baseline-validated languages gate."""

from __future__ import annotations

from varde_code.scan.quality_mode import (
    NOT_VALIDATED_LABEL,
    effective_mode,
    gate_fails,
    language_is_validated,
)

PLACEHOLDER = {
    "python": "report-only",
    "typescript": "report-only",
    "csharp": "report-only",
}
PYTHON_VALIDATED = {**PLACEHOLDER, "python": "panel-validated"}
LANGS = ("python", "typescript", "csharp")


def test_placeholder_calibration_caps_all_three_and_never_fails() -> None:
    for lang in LANGS:
        mode = effective_mode("error", lang, PLACEHOLDER.get)
        assert (mode.severity, mode.label, mode.gating) == (
            "info",
            NOT_VALIDATED_LABEL,
            False,
        )
    assert not gate_fails([("error", lang) for lang in LANGS], PLACEHOLDER.get)


def test_python_validated_gates_and_others_are_capped() -> None:
    py = effective_mode("error", "python", PYTHON_VALIDATED.get)
    assert (py.severity, py.label, py.gating) == ("error", None, True)
    for lang in ("typescript", "csharp"):
        mode = effective_mode("error", lang, PYTHON_VALIDATED.get)
        assert (mode.severity, mode.label, mode.gating) == (
            "info",
            NOT_VALIDATED_LABEL,
            False,
        )


def test_polyglot_repo_mixes_correctly() -> None:
    assert gate_fails(
        [("error", "typescript"), ("error", "python")], PYTHON_VALIDATED.get
    )
    assert not gate_fails(
        [("error", "typescript"), ("error", "csharp")], PYTHON_VALIDATED.get
    )
    assert not gate_fails([("warning", "python")], PYTHON_VALIDATED.get)


def test_unknown_or_missing_language_is_not_validated() -> None:
    assert not language_is_validated(PYTHON_VALIDATED.get, "go")
    assert not language_is_validated(PYTHON_VALIDATED.get, None)


def test_baseline_validated_gates_like_panel_validated() -> None:
    states = {**PLACEHOLDER, "python": "baseline-validated"}
    mode = effective_mode("error", "python", states.get)
    assert (mode.severity, mode.label, mode.gating) == ("error", None, True)
    assert not language_is_validated(states.get, "typescript")
