from dataclasses import replace
from pathlib import Path
from typing import cast

from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.tuner import SampleVectors, recalibrate, tune

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _legacy_calibration():
    """Placeholder pinned to the pre-v7 strengths and limits."""
    calibration = load_calibration(CALIBRATION)
    strengths = {
        **calibration.global_strengths,
        "A": 2_000_000,
        "wL": 600_000,
        "w": 1_000_000,
    }
    limits = {name: dict(values) for name, values in calibration.limits.items()}
    limits["strength"] = dict.fromkeys(limits["strength"], (500000, 2000000))
    return replace(calibration, global_strengths=strengths, limits=limits)


def vectors(
    sample_id: str,
    *,
    original: int,
    target: int,
    judge: int | None = None,
    gaming: int | None = None,
    differences: tuple[str, ...] = (),
) -> SampleVectors:
    versions = {"original": {"cognitive": original}, "smoothed": {"cognitive": target}}
    if judge is not None:
        versions["judge-one"] = {"cognitive": judge}
    return SampleVectors(
        sample_id,
        versions,
        {"padded": {"cognitive": gaming}} if gaming is not None else None,
        {"original": differences} if differences else None,
    )


def test_tunes_feasible_fixture_with_strengths_inside_limits() -> None:
    calibration = _legacy_calibration()
    samples = [
        vectors("alpha", original=20, target=10, judge=14, gaming=30),
        vectors("beta", original=24, target=12, judge=18, gaming=32),
    ]

    result = tune(samples, calibration, held_out_id="beta", gaming_margin=1)

    assert result.validated
    assert all(item.passed for item in result.margins)
    bounds = calibration.limits["strength"]["cognitive"]
    start = calibration.global_strengths["w"]
    assert start * bounds[0] // 1_000_000 <= result.strengths["w"]
    assert result.strengths["w"] <= start * bounds[1] // 1_000_000


def test_input_order_does_not_change_tuned_result() -> None:
    calibration = _legacy_calibration()
    samples = [
        vectors("alpha", original=20, target=10, judge=18),
        vectors("beta", original=30, target=12, gaming=40),
    ]

    first = tune(samples, calibration, held_out_id="beta", gaming_margin=1)
    second = tune(
        list(reversed(samples)), calibration, held_out_id="beta", gaming_margin=1
    )

    assert first == second


def test_held_out_wrong_rank_is_not_validated() -> None:
    calibration = _legacy_calibration()
    samples = [
        vectors("alpha", original=20, target=10),
        vectors("beta", original=5, target=15, gaming=1),
    ]

    result = tune(samples, calibration, held_out_id="beta")

    assert not result.held_out_passed
    assert not result.validated
    assert result.reasons
    assert result.label == "not validated"
    assert result.profile is None


def test_user_infeasibility_names_blocking_components_and_has_no_profile() -> None:
    calibration = _legacy_calibration()
    sample = vectors("mine", original=0, target=50)

    result = recalibrate({"mine": {"cognitive": 50}}, calibration, samples=[sample])

    assert result.blocking_components == ("cognitive",)
    assert result.validated is False
    assert result.profile is None


def test_user_profile_marks_gaming_unchecked_without_variants() -> None:
    calibration = _legacy_calibration()
    sample = vectors("mine", original=20, target=10)

    result = recalibrate({"mine": {"cognitive": 10}}, calibration, samples=[sample])

    assert result.label == "user-edited, gaming-unchecked"
    assert result.profile is not None
    profile_languages = cast(
        "dict[str, dict[str, object]]", result.profile["languages"]
    )
    python_validation = cast(
        "dict[str, str]", profile_languages["python"]["validation"]
    )
    assert python_validation["state"] == result.label


def test_user_target_without_shipped_comparison_vectors_has_no_profile() -> None:
    calibration = _legacy_calibration()

    result = recalibrate({"mine": {"cognitive": 10}}, calibration)

    assert not result.validated
    assert result.profile is None
    assert "cognitive" in result.blocking_components


def test_ties_are_permitted_only_for_unmeasured_component_differences() -> None:
    calibration = _legacy_calibration()
    permitted = [
        vectors("alpha", original=10, target=10, differences=("formatting",)),
        vectors("beta", original=9, target=8),
    ]
    denied = [
        vectors("alpha", original=10, target=20, differences=("cognitive",)),
        vectors("beta", original=9, target=8),
    ]

    tied = tune(permitted, calibration, held_out_id="beta", tie_tolerance=0)
    constrained = tune(denied, calibration, held_out_id="beta", tie_tolerance=2)

    assert tied.margins[0].passed
    assert not constrained.margins[0].passed


def test_infeasible_equal_user_target_has_no_profile() -> None:
    calibration = _legacy_calibration()
    sample = vectors("mine", original=1, target=1)

    result = recalibrate({"mine": {"cognitive": 100}}, calibration, samples=[sample])

    assert not result.validated
    assert result.profile is None
    assert any("infeasible" in reason for reason in result.reasons)


def test_recalibrate_rejects_unknown_or_incomplete_targets() -> None:
    calibration = _legacy_calibration()
    sample = vectors("mine", original=20, target=10)

    try:
        recalibrate({"missing": {"cognitive": 10}}, calibration, samples=[sample])
    except ValueError as error:
        assert "unknown user target" in str(error)
    else:
        raise AssertionError("unknown target id was silently ignored")

    try:
        recalibrate({"mine": {"other": 10}}, calibration, samples=[sample])
    except ValueError as error:
        assert "components must be exactly" in str(error)
    else:
        raise AssertionError("incomplete component set was accepted")


def test_development_judge_and_gaming_constraints_bind_strength_fit() -> None:
    calibration = _legacy_calibration()
    samples = [
        SampleVectors(
            "a",
            {
                "smoothed": {"cognitive": 40, "small_side": 0},
                "original": {"cognitive": 40, "small_side": 0},
                "judge-one": {"cognitive": 20, "small_side": 4},
            },
            {"padded": {"cognitive": 0, "small_side": 20}},
        ),
        SampleVectors(
            "b",
            {
                "smoothed": {"cognitive": 0, "small_side": 20},
                "original": {"cognitive": 0, "small_side": 20},
            },
            {"padded": {"cognitive": 0, "small_side": 22}},
        ),
    ]
    result = tune(samples, calibration, held_out_id="b", gaming_margin=50)

    assert result.strengths["w"] < calibration.global_strengths["w"]
    assert result.strengths["A"] > calibration.global_strengths["A"]
    judge = next(m for m in result.margins if m.challenger == "judge-one")
    gaming = next(
        m
        for m in result.margins
        if m.challenger == "gaming:padded" and m.sample_id == "a"
    )
    assert judge.passed and judge.margin >= 0
    assert gaming.passed and gaming.margin >= 0
    bounds = calibration.limits["strength"]
    assert (
        result.strengths["w"]
        <= calibration.global_strengths["w"] * bounds["cognitive"][1] // 1_000_000
    )
    assert (
        result.strengths["A"]
        <= calibration.global_strengths["A"] * bounds["small_side"][1] // 1_000_000
    )


def test_identical_judge_vector_is_a_non_strict_pass() -> None:
    calibration = _legacy_calibration()
    sample = SampleVectors(
        "a",
        {
            "smoothed": {"cognitive": 10},
            "original": {"cognitive": 10},
            "judge-one": {"cognitive": 10},
        },
    )
    other = vectors("b", original=20, target=10, gaming=30)

    result = tune([sample, other], calibration, held_out_id="b", gaming_margin=1)

    judge_margin = next(m for m in result.margins if m.challenger == "judge-one")
    assert judge_margin.passed
    assert judge_margin.margin == 0


def test_candidate_grid_stays_inside_calibration_limits_across_rounds() -> None:
    calibration = _legacy_calibration()
    limits = {name: dict(values) for name, values in calibration.limits.items()}
    limits["strength"]["small_side"] = (2_000_000, 2_000_000)
    limits["strength"]["cognitive"] = (500_000, 1_250_000)
    bounded = replace(calibration, limits=limits)
    constrained = SampleVectors(
        "alpha",
        {
            "smoothed": {"cognitive": 0, "small_side": 100},
            "original": {"cognitive": 100, "small_side": 0},
        },
        {"attack": {"cognitive": 200, "small_side": 0}},
    )
    held = vectors("beta", original=0, target=1, gaming=10)

    result = tune([constrained, held], bounded, held_out_id="beta", gaming_margin=1)

    assert result.strengths["w"] == 1_250_000
    assert result.strengths["w"] <= 1_250_000


def test_judge_constraint_alone_forces_a_strength_move() -> None:
    calibration = _legacy_calibration()
    start = calibration.global_strengths
    sample = SampleVectors(
        "a",
        {
            "smoothed": {"cognitive": 10, "small_side": 0},
            "original": {"cognitive": 20, "small_side": 0},
            "judge-one": {"cognitive": 5, "small_side": 2},
        },
    )
    other = vectors("b", original=20, target=10, gaming=30)

    result = tune([sample, other], calibration, held_out_id="b", gaming_margin=1)

    judge = next(m for m in result.margins if m.challenger == "judge-one")
    original = next(
        m for m in result.margins if m.sample_id == "a" and m.challenger == "original"
    )
    assert original.passed
    assert judge.passed
    assert result.strengths["A"] > start["A"] or result.strengths["w"] < start["w"]


def test_gaming_constraint_alone_forces_a_strength_move() -> None:
    calibration = _legacy_calibration()
    start = calibration.global_strengths
    sample = SampleVectors(
        "a",
        {
            "smoothed": {"cognitive": 10, "small_side": 0},
            "original": {"cognitive": 20, "small_side": 0},
        },
        {"padded": {"cognitive": 5, "small_side": 2}},
    )
    other = vectors("b", original=20, target=10, gaming=30)

    result = tune([sample, other], calibration, held_out_id="b", gaming_margin=1)

    gaming = next(m for m in result.margins if m.challenger == "gaming:padded")
    original = next(
        m for m in result.margins if m.sample_id == "a" and m.challenger == "original"
    )
    assert original.passed
    assert gaming.sample_id == "a" and gaming.passed
    assert result.strengths["A"] > start["A"] or result.strengths["w"] < start["w"]


def test_infeasible_gaming_only_user_target_has_no_profile() -> None:
    calibration = _legacy_calibration()
    sample = vectors("mine", original=20, target=10, gaming=10)

    result = recalibrate(
        {"mine": {"cognitive": 10}}, calibration, samples=[sample], gaming_margin=1
    )

    assert result.blocking_components == ()
    assert not result.validated
    assert result.profile is None
    assert any("infeasible" in reason for reason in result.reasons)
