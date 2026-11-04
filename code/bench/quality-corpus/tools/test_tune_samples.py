from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import exact_scoring  # noqa: E402, RUF100
import tune_samples  # noqa: E402, RUF100
from exact_scoring import SampleFacts, worst_margin  # noqa: E402, RUF100
from tune_samples import (  # noqa: E402, RUF100
    check_failures,
    constraint_rows,
    loo_folds,
    main,
    split_by_scope,
    thin_suffix,
    variants_dir,
)


def _sample(sample_id: str, language: str = "python") -> SampleFacts:
    return SampleFacts(
        sample_id, language, {"id": "t"}, {"judge": {}, "gaming:tiny": {}}
    )


def _fake_debts(by_sample: dict[str, dict[str, int]]):
    """Replace scoring: debts per sample id, independent of the strengths."""

    def debts(sample: SampleFacts, calibration):
        return by_sample[sample.id]

    return debts


def test_constraint_rows_use_challenger_minus_target_and_skip_control() -> None:
    rows = constraint_rows(
        {"smoothed": 10, "judge": 15, "gaming:tiny": 7, "sizematched": 1}
    )
    assert rows == [  # noqa: S101 - pytest assertion.
        {"challenger": "gaming:tiny", "margin": -3, "passed": False},
        {"challenger": "judge", "margin": 5, "passed": True},
    ]


def test_two_in_scope_samples_of_one_language_are_both_fitted() -> None:
    scoped, info = split_by_scope([_sample("a"), _sample("b")], frozenset({"python"}))
    assert [item.id for item in scoped] == ["a", "b"]  # noqa: S101 - pytest assertion.
    assert info == []  # noqa: S101 - pytest assertion.


def test_variants_dir_prefers_the_sample_directory(tmp_path, monkeypatch) -> None:
    (tmp_path / "python" / "sx").mkdir(parents=True)
    monkeypatch.setattr(tune_samples, "SEEDED_PATH", tmp_path)
    assert variants_dir("python", "sx") == tmp_path / "python" / "sx"  # noqa: S101
    assert variants_dir("python", "sy") == tmp_path / "python"  # noqa: S101


def test_out_of_scope_samples_become_informational_never_fail() -> None:
    scoped, info = split_by_scope(
        [_sample("a"), _sample("g", "go")], frozenset({"python"})
    )
    assert [item.id for item in scoped] == ["a"]  # noqa: S101 - pytest assertion.
    assert [item.id for item in info] == ["g"]  # noqa: S101 - pytest assertion.


def test_loo_fits_on_other_samples_only_and_scores_held_out(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fit(samples, calibration):
        seen.append([item.id for item in samples])
        return {"A": 1}

    monkeypatch.setattr(tune_samples, "at_strengths", lambda cal, strengths: cal)
    monkeypatch.setattr(
        tune_samples,
        "sample_debts",
        _fake_debts(
            {
                "a": {"smoothed": 2, "judge": 9, "gaming:tiny": 5},
                "b": {"smoothed": 2, "judge": 9, "gaming:tiny": 1},
            }
        ),
    )
    folds = loo_folds([_sample("a"), _sample("b")], None, fit)  # type: ignore[arg-type]

    assert seen == [["b"], ["a"]]  # noqa: S101 - pytest assertion.
    by_id = {fold["held_out"]: fold for fold in folds}
    assert by_id["b"]["target"] == 2  # noqa: S101 - pytest assertion.
    assert check_failures({"samples": [], "loo": folds}) == [  # noqa: S101 - pytest assertion.
        "loo b gaming:tiny margin -1"
    ]


def test_check_failures_names_in_sample_failure() -> None:
    report = {
        "samples": [
            {"id": "a", "constraints": [{"challenger": "judge", "margin": -4}]}
        ],
        "loo": [],
    }
    assert check_failures(report) == ["in-sample a judge margin -4"]  # noqa: S101 - pytest assertion.


def test_check_exits_1_on_failing_fold(monkeypatch, capsys) -> None:
    samples = [
        _sample("a", "python"),
        _sample("b", "typescript"),
        _sample("c", "csharp"),
    ]
    monkeypatch.setattr(tune_samples, "load_sample_facts", lambda: (samples, []))
    monkeypatch.setattr(
        tune_samples, "default_fit", lambda scoped, cal: dict(cal.global_strengths)
    )
    monkeypatch.setattr(
        tune_samples,
        "sample_debts",
        _fake_debts(
            {
                "a": {"smoothed": 2, "judge": 9, "gaming:tiny": 5},
                "b": {"smoothed": 2, "judge": 9, "gaming:tiny": 5},
                "c": {"smoothed": 2, "judge": 9, "gaming:tiny": 1, "sizematched": 3},
            }
        ),
    )
    monkeypatch.setattr(tune_samples, "at_strengths", lambda cal, strengths: cal)
    monkeypatch.setattr(sys, "argv", ["tune_samples.py", "--check"])
    assert main() == 1  # noqa: S101 - pytest assertion.
    assert "FAIL: " in capsys.readouterr().out  # noqa: S101 - pytest assertion.


def test_thin_suffix_flags_passing_margin_below_one_percent_of_target() -> None:
    assert thin_suffix(99, 10_000) == " thin"  # noqa: S101 - pytest assertion.
    assert thin_suffix(100, 10_000) == ""  # noqa: S101 - pytest assertion.
    assert thin_suffix(-1, 10_000) == ""  # noqa: S101 - pytest assertion.


def test_worst_margin_stops_at_floor_and_moves_failure_first(monkeypatch) -> None:
    samples = [_sample("a"), _sample("b")]
    samples[0].challengers = {"judge": {"d": 9}, "gaming:tiny": {"d": 5}}
    samples[1].challengers = {"judge": {"d": 9}, "gaming:tiny": {"d": 1}}
    samples[0].order = sorted(samples[0].challengers)
    samples[1].order = sorted(samples[1].challengers)
    monkeypatch.setattr(
        exact_scoring, "debt", lambda facts, calibration: facts.get("d", 2)
    )

    assert worst_margin(samples, None, -10) == -1  # type: ignore[arg-type]  # noqa: S101
    assert worst_margin(samples, None, 0) == -1  # type: ignore[arg-type]  # noqa: S101
    assert samples[0].id == "b"  # noqa: S101 - failing sample moved first.
    assert samples[0].order[0] == "gaming:tiny"  # noqa: S101


def _run_main(monkeypatch, capsys, argv: list[str]) -> tuple[int, str]:
    samples = [_sample("a", "python")]
    monkeypatch.setattr(tune_samples, "load_sample_facts", lambda: (samples, []))
    monkeypatch.setattr(tune_samples, "at_strengths", lambda cal, strengths: cal)
    monkeypatch.setattr(
        tune_samples,
        "sample_debts",
        _fake_debts({"a": {"smoothed": 2, "judge": 9, "gaming:tiny": 5}}),
    )
    monkeypatch.setattr(sys, "argv", ["tune_samples.py", *argv])
    code = main()
    return code, capsys.readouterr().out


def test_default_calibration_is_cal_1_and_is_named(monkeypatch, capsys) -> None:
    code, out = _run_main(monkeypatch, capsys, ["--check"])
    default = tune_samples.load_calibration(tune_samples.CALIBRATION_PATH)
    assert tune_samples.CALIBRATION_PATH.name == "cal-1.toml"  # noqa: S101 - pytest assertion.
    assert default.id == "cal-2"  # noqa: S101 - pytest assertion.
    assert code == 0  # noqa: S101 - pytest assertion.
    assert f"Calibration: {default.id} sha256 {default.source_sha256}" in out  # noqa: S101


def test_calibration_option_loads_the_given_file(monkeypatch, capsys, tmp_path) -> None:
    text = tune_samples.CALIBRATION_PATH.read_text(encoding="utf-8")
    other = tmp_path / "other.toml"
    other.write_text(text.replace('id = "cal-2"', 'id = "cal-test"'), encoding="utf-8")
    expected = tune_samples.load_calibration(other)
    assert expected.id == "cal-test"  # noqa: S101 - pytest assertion.
    code, out = _run_main(monkeypatch, capsys, ["--calibration", str(other)])
    assert code == 0  # noqa: S101 - pytest assertion.
    assert f"Calibration: cal-test sha256 {expected.source_sha256}" in out  # noqa: S101
