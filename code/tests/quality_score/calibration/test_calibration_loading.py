"""Behavioral tests for calibration and profile inputs."""

from pathlib import Path

import pytest
from varde_code.quality_score.calibration import load_calibration, load_profile

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def test_placeholder_calibration_is_unvalidated_and_labelled() -> None:
    calibration = load_calibration(CALIBRATION)

    assert calibration.id == "cal-0-placeholder"
    assert calibration.validated is False
    assert calibration.gating_available is False
    assert calibration.output_label == "placeholder; not validated"
    assert calibration.languages["python"].threshold_x == 62_000_000


def test_profile_applies_decimal_strengths_and_thresholds(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.toml"
    profile_path.write_text(
        '[profile]\nid="personal-1"\nformula="vq1"\nbase_calibration="cal-0-placeholder"\n'
        '[languages.python.strength]\ncognitive="1.25"\nstructure="0.8"\n'
        '[languages.python.thresholds]\nX="65.5"\nY="38"\ncap="12.5"\n',
        encoding="utf-8",
    )

    first = load_profile(profile_path, load_calibration(CALIBRATION))
    second = load_profile(profile_path, load_calibration(CALIBRATION))

    effective = first.for_language("python")
    assert effective.global_strengths["w"] == 750_000
    assert effective.language.threshold_x == 65_500_000
    assert first.hash == second.hash
    assert first.effective_hash == second.effective_hash
    assert first.profile_sha256 == second.profile_sha256


def test_profile_outside_limits_has_diagnostic(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.toml"
    profile_path.write_text(
        '[profile]\nid="personal-1"\nformula="vq1"\nbase_calibration="cal-0-placeholder"\n'
        '[languages.python.strength]\ncognitive="2.1"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="outside limits.*cognitive"):
        load_profile(profile_path, load_calibration(CALIBRATION))


def test_formula_mismatch_is_rejected(tmp_path: Path) -> None:
    profile_path = tmp_path / "profile.toml"
    profile_path.write_text(
        '[profile]\nid="personal-1"\nformula="vq2"\nbase_calibration="cal-0-placeholder"\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="formula"):
        load_profile(profile_path, load_calibration(CALIBRATION))


def _calibration_with_state(tmp_path: Path, state: str) -> Path:
    text = CALIBRATION.read_text(encoding="utf-8")
    old = '[language.python.validation]\nstate = "report-only"'
    assert old in text
    path = tmp_path / "cal.toml"
    path.write_text(
        text.replace(old, f'[language.python.validation]\nstate = "{state}"'),
        encoding="utf-8",
    )
    return path


def test_state_defaults_to_report_only_and_placeholder_never_gates() -> None:
    calibration = load_calibration(CALIBRATION)

    assert calibration.languages["python"].state == "report-only"
    assert all(
        not calibration.language_gating_available(n) for n in calibration.languages
    )


@pytest.mark.parametrize("state", ["panel-validated", "baseline-validated"])
def test_validated_states_gate_only_their_language(tmp_path: Path, state: str) -> None:
    calibration = load_calibration(_calibration_with_state(tmp_path, state))

    assert calibration.languages["python"].state == state
    assert calibration.language_gating_available("python") is True
    assert calibration.gating_available is False


def test_unknown_state_raises_and_missing_language_is_false(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown language validation state"):
        load_calibration(_calibration_with_state(tmp_path, "bogus"))
    assert load_calibration(CALIBRATION).language_gating_available("nope") is False


def _with_states(tmp_path: Path, states: dict[str, str]) -> Path:
    text = CALIBRATION.read_text(encoding="utf-8")
    text = text.replace(
        '[language.python.validation]\nstate = "report-only"\n'
        'provenance = "synthetic placeholder; not validated"\n',
        "",
    )
    for language, state in states.items():
        text = text.replace(
            f"[language.{language}]\n",
            f'[language.{language}.validation]\nstate = "{state}"\n\n'
            f"[language.{language}]\n",
            1,
        )
    path = tmp_path / "cal.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_placeholder_reports_report_only_for_every_language() -> None:
    calibration = load_calibration(CALIBRATION)

    assert {item.state for item in calibration.languages.values()} == {"report-only"}
    assert not any(
        calibration.language_gating_available(name) for name in calibration.languages
    )
    assert calibration.language_gating_available("cobol") is False


def test_only_panel_validated_language_gates(tmp_path: Path) -> None:
    calibration = load_calibration(
        _with_states(tmp_path, {"python": "panel-validated", "csharp": "report-only"})
    )

    assert calibration.languages["python"].state == "panel-validated"
    assert calibration.language_gating_available("python") is True
    assert calibration.language_gating_available("csharp") is False
    assert calibration.language_gating_available("typescript") is False
    assert calibration.validated is False
    assert calibration.gating_available is False


def test_unknown_language_state_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="state 'validated'"):
        load_calibration(_with_states(tmp_path, {"python": "validated"}))
