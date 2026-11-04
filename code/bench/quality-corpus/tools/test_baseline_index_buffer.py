# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_buffer as ib


def rows(values, metric="cognitive", tokens=100):
    return [{metric: v, "tokens": tokens} for v in values]


def test_quantile_interpolates_and_handles_empty():
    assert ib.quantile([1, 2, 3, 4], 0.5) == 2.5
    assert ib.quantile([5], 0.9) == 5
    assert ib.quantile([], 0.5) is None


def test_statistics():
    r = rows([0, 2, 6, 10])
    assert ib.stat_mean(r, "cognitive") == 4.5
    assert ib.stat_share_above(r, "cognitive") == 0.0  # > 10 (calibration c0)
    assert ib.stat_share_above(rows([0, 11]), "cognitive") == 0.5
    assert ib.stat_density(r, "cognitive") == pytest.approx(1000 * 18 / 400)
    assert ib.stat_density(r, "tokens") == pytest.approx(
        10.0
    )  # functions per 1k tokens
    assert ib.stat_mean([], "cognitive") is None
    assert ib.stat_density([{"cognitive": 1, "tokens": 0}], "cognitive") is None


def test_thresholds_come_from_calibration_with_fallbacks():
    assert ib.COMFORT["cognitive"] == 10 and ib.COMFORT["tokens"] == 96
    assert ib.COMFORT["depth"] == 3 and ib.COMFORT["fan_out"] == 4
    assert ib.COMFORT["tree_size"] == 6
    assert ib.COMFORT["params"] == 4 and ib.COMFORT["name_issues"] == 0


def test_weighted_statistics_ignore_decomposition():
    one = [{"cognitive": 12, "tokens": 300}]
    split = [{"cognitive": 12, "tokens": 100}] * 3
    for stat in ("wmean", "wp50", "wp90", "wshare"):
        compute = ib.STATISTICS[stat]
        assert compute(one, "cognitive") == compute(split, "cognitive")
    mixed = [{"cognitive": 0, "tokens": 90}, {"cognitive": 20, "tokens": 10}]
    assert ib.stat_wmean(mixed, "cognitive") == pytest.approx(2.0)
    assert ib.stat_wquantile(0.5)(mixed, "cognitive") == 0
    assert ib.stat_wquantile(0.95)(mixed, "cognitive") == 20
    assert ib.stat_wshare(mixed, "cognitive") == pytest.approx(0.1)
    assert ib.stat_wmean([{"cognitive": 1, "tokens": 0}], "cognitive") is None


def test_none_values_are_skipped():
    r = [{"cognitive": None, "tokens": 10}, {"cognitive": 4, "tokens": 10}]
    assert ib.stat_mean(r, "cognitive") == 4


def test_tier_and_unit_floor():
    assert ib.tier_for(0.05) == 0.05
    assert ib.tier_for(0.0500001) == 0.10
    assert ib.tier_for(0.1000001) == ib.NONE_YET
    assert ib.tier_for(None) == ib.NONE_YET
    assert ib.relative_error(0.5, 0.0, 1.0) == pytest.approx(0.5)


def test_lopo_error_worst_and_mean():
    by_problem = {"a": rows([10] * 4), "b": rows([10] * 4), "c": rows([20] * 4)}
    # a: others {10,20 x4} mean 15 vs 10 -> 0.5; c: others mean 10 vs 20 -> 0.5
    assert ib.lopo_error(by_problem, "cognitive", "mean") == pytest.approx(0.5)
    assert ib.lopo_error(
        by_problem, "cognitive", "mean", reduce=ib._mean
    ) == pytest.approx(0.5)
    with pytest.raises(ValueError):
        ib.lopo_error({"a": rows([1])}, "cognitive", "mean")


def test_bootstrap_is_deterministic_and_zero_for_constant():
    agreed = {"a": rows([3] * 5), "b": rows([3] * 5)}
    draws = ib.resample_indices({p: len(r) for p, r in agreed.items()}, 50, seed=1)
    assert draws == ib.resample_indices({"a": 5, "b": 5}, 50, seed=1)
    assert ib.bootstrap_error(agreed, draws, "cognitive", "mean") == 0
    varied = {"a": rows([1, 9, 1, 9, 5]), "b": rows([2, 8, 2, 8, 5])}
    again = ib.resample_indices({"a": 5, "b": 5}, 50, seed=1)
    assert ib.bootstrap_error(varied, draws, "cognitive", "mean") == ib.bootstrap_error(
        varied, again, "cognitive", "mean"
    )
    assert ib.bootstrap_error(varied, draws, "cognitive", "mean") > 0


def test_draft_error_vs_agreed_and_school_spread():
    agreed = {"a": rows([10, 10])}
    drafts = {
        "a": {
            ("r1", "x"): rows([10, 10]),
            ("r1", "y"): rows([12, 12]),
            ("r2", "x"): rows([10, 10]),
        }
    }
    result = ib.draft_error(agreed, drafts, "cognitive", "mean")
    assert result["vs_agreed"] == pytest.approx(0.2)
    assert result["school_spread"] == pytest.approx(0.2)  # only run r1 has two schools
    assert ib.draft_error(agreed, {"zz": drafts["a"]}, "cognitive", "mean") == {
        "vs_agreed": None,
        "school_spread": None,
    }


def stable_inputs():
    agreed = {p: rows([4, 4, 4, 4]) for p in "abc"}
    drafts = {p: {("r", s): rows([4, 4, 4, 4]) for s in "xy"} for p in "abc"}
    return agreed, drafts


def test_evaluate_stable_metric_reaches_five_percent_and_is_deterministic():
    agreed, drafts = stable_inputs()
    first = ib.evaluate(agreed, drafts, seed=3, resamples=20)
    assert first == ib.evaluate(agreed, drafts, seed=3, resamples=20)
    mean = first["cognitive"]["cells"]["mean"]
    assert mean["tier"] == 0.05 and not mean["degenerate"]
    assert first["cognitive"]["best"] == "mean"
    assert first["cognitive"]["remedy"] == {
        "kind": "statistic",
        "use": "mean",
        "tier": 0.05,
    }


def cells(**errors):
    return {
        stat: {
            "err": max(e),
            "degenerate": False,
            "tier": ib.tier_for(max(e)),
            "lopo": e[0],
            "bootstrap": e[1],
            "draft": e[2],
            "err_b": max(e[:2]),
            "tier_b": ib.tier_for(max(e[:2])),
        }
        for stat, e in errors.items()
    }


def test_best_statistic_prefers_non_degenerate():
    c = cells(mean=(0.3, 0.2, 0.1), p90=(0.2, 0.1, 0.1))
    c["p50"] = {**c["mean"], "err": 0.0, "degenerate": True}
    assert ib.best_statistic(c) == "p90"


def test_remedy_data_vs_spread():
    data_limited = cells(mean=(0.02, 0.20, 0.02))
    out = ib.remedy(data_limited, functions=30, problems=4)
    assert out["kind"] == "data" and out["factor"] == pytest.approx(4)
    assert (out["functions_needed"], out["problems_needed"]) == (120, 16)
    spread = ib.remedy(cells(mean=(0.4, 0.05, 0.3)), 30, 4)
    assert spread["kind"] == "statistic-or-normalization"
    assert spread["limited_by"] == ["lopo", "draft"]


def test_variant_b_excludes_school_spread():
    c = cells(mean=(0.4, 0.05, 0.3), p90=(0.02, 0.04, 0.9))
    assert ib.best_statistic(c) == "mean" and ib.best_statistic(c, "err_b") == "p90"
    assert ib.remedy(c, 30, 4, "B") == {"kind": "statistic", "use": "p90", "tier": 0.05}
    spread = ib.remedy(cells(mean=(0.4, 0.05, 0.3)), 30, 4, "B")
    assert spread["limited_by"] == ["lopo"]
    assert ib.reaching(c, 0.05) == ["p90"]


def test_corpus_position_and_units():
    agreed = {"a": rows([2] * 5)}
    corpus = [rows([v] * 5) for v in (1, 2, 3, 4)] + [rows([9])]  # last too short
    position = ib.corpus_position(agreed, corpus)["cognitive"]["mean"]
    assert position["files"] == 4
    assert position["percentile"] == pytest.approx(37.5)  # 1 below, 1 equal of 4
    assert position["units_for_10pct"] == ib.units_needed(
        position["file_dispersion_median"]
    )
    assert ib.units_needed(0.3) == 9 and ib.units_needed(0.05) == 1
    assert ib.percentile_rank(1, []) is None
