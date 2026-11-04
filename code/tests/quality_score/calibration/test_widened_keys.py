"""Measure keys in cal-2: sn and sm off, sd on; absent keys load as off."""

from pathlib import Path

import pytest
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.scoring.scoring import score_scope

ROOT = Path(__file__).parents[4]
CAL1 = ROOT / "code/src/varde_code/quality_score/calibration/cal-1.toml"
AGREED = ROOT / "code/bench/quality-corpus/baseline/agreed"
SUFFIX = {".py": "python", ".ts": "typescript", ".cs": "csharp"}
STRENGTHS = ("sn", "sm", "sd")
THRESHOLDS = ("n0", "nm0", "dg0")
SHADOW_LINES = tuple(f"{key} = " for key in (*STRENGTHS, *THRESHOLDS))
# corpus q90 of max_nesting (measure_quantiles --check), exact good-file share cut
NESTING_Q90 = {"python": 1, "typescript": 1, "csharp": 0}


def without_shadow_keys(text: str) -> str:
    """The pre-t5 cal-1: no measure keys and no limits.measures table."""
    text = text.split("\n[limits.measures]")[0]
    lines = [line for line in text.splitlines() if not line.startswith(SHADOW_LINES)]
    return "\n".join(lines).rstrip("\n") + "\n"


def sample_records() -> list[dict]:
    paths = sorted(p for p in AGREED.rglob("*") if p.suffix in SUFFIX)
    paths += sorted((ROOT / "code/src/varde_code/quality_score").glob("*.py"))
    records = []
    for path in paths:
        relative = path.relative_to(ROOT).as_posix()
        records.append(extract_facts(path.read_bytes(), SUFFIX[path.suffix], relative))
    return records


def scores(records: list[dict], calibration_path: Path) -> list[tuple]:
    scored = score_scope(records, load_calibration(calibration_path))
    return [(f.path, f.score) for f in scored.files]


def test_cal2_carries_the_six_keys_with_only_delegation_on() -> None:
    calibration = load_calibration(CAL1)

    assert calibration.id == "cal-2"
    assert calibration.formula == "vq2"
    assert [calibration.global_strengths[key] for key in STRENGTHS] == [0, 0, 1_000_000]
    for name, language in calibration.languages.items():
        assert language.parameters["n0"] == NESTING_Q90.get(name, 1) * 1_000_000
        assert language.parameters["nm0"] == 0
        assert language.parameters["dg0"] == 333_333


def test_scores_are_bit_identical_with_and_without_the_keys(tmp_path: Path) -> None:
    old = tmp_path / "cal-1-before.toml"
    old.write_text(without_shadow_keys(CAL1.read_text("utf-8")), encoding="utf-8")
    records = sample_records()

    assert len(records) >= 12
    assert scores(records, CAL1) == scores(records, old)


def test_calibration_without_the_keys_loads_as_off(tmp_path: Path) -> None:
    old = tmp_path / "cal-1-before.toml"
    old.write_text(without_shadow_keys(CAL1.read_text("utf-8")), encoding="utf-8")

    calibration = load_calibration(old)

    assert not set(STRENGTHS) & calibration.global_strengths.keys()
    assert all("n0" not in lang.parameters for lang in calibration.languages.values())


def edited(tmp_path: Path, old: str, new: str) -> Path:
    text = CAL1.read_text("utf-8")
    assert old in text
    path = tmp_path / "edited.toml"
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("n0 = 1\n", "n0 = 51\n"),
        ("nm0 = 0\n", 'nm0 = "-1"\n'),
        ('dg0 = "0.333333"', 'dg0 = "1.5"'),
        ('sn = "0.0"', 'sn = "2.5"'),
        ('sd = "1.0"', 'sd = "-0.5"'),
    ],
)
def test_measure_keys_outside_limits_are_rejected(
    tmp_path: Path, old: str, new: str
) -> None:
    with pytest.raises(ValueError, match="outside limits"):
        load_calibration(edited(tmp_path, old, new))


def test_strength_without_its_threshold_is_rejected(tmp_path: Path) -> None:
    text = CAL1.read_text("utf-8").replace('sm = "0.0"', 'sm = "0.5"')
    path = tmp_path / "on.toml"
    path.write_text(
        "\n".join(line for line in text.splitlines() if not line.startswith("nm0 = ")),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="sm is on but nm0 is missing"):
        load_calibration(path)


def test_strength_on_with_thresholds_loads(tmp_path: Path) -> None:
    calibration = load_calibration(edited(tmp_path, 'sn = "0.0"', 'sn = "0.5"'))

    assert calibration.global_strengths["sn"] == 500_000


def test_measure_key_without_configured_limits_is_rejected(tmp_path: Path) -> None:
    text = CAL1.read_text("utf-8").split("\n[limits.measures]")[0] + "\n"
    path = tmp_path / "nolimits.toml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="no configured limits.measures"):
        load_calibration(path)
