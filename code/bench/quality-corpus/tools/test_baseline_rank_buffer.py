# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_index_buffer as ib
import baseline_rank_buffer as rb


def rows(values, metric="cognitive", tokens=100):
    return [{metric: v, "tokens": tokens} for v in values]


def test_midrank_counts_ties_half_and_handles_out_of_range():
    cdf = rb.build_cdf([(1, 1), (2, 1), (2, 1), (3, 1)])
    assert rb.midrank(cdf, 1) == pytest.approx(12.5)
    assert rb.midrank(cdf, 2) == pytest.approx(50.0)
    assert rb.midrank(cdf, 3) == pytest.approx(87.5)
    assert rb.midrank(cdf, 0) == 0.0
    assert rb.midrank(cdf, 2.5) == 75.0
    assert rb.midrank(cdf, 9) == 100.0
    with pytest.raises(ValueError):
        rb.midrank(rb.build_cdf([]), 1)


def test_midrank_is_token_weighted():
    cdf = rb.build_cdf([(1, 3), (5, 1)])
    assert rb.midrank(cdf, 1) == pytest.approx(37.5)
    assert rb.midrank(cdf, 5) == pytest.approx(87.5)


def test_rank_in_sorted_mid_rank():
    assert rb.rank_in_sorted(2, [1, 2, 2, 3]) == 50.0
    assert rb.rank_in_sorted(0, [1, 2]) == 0.0
    assert rb.rank_in_sorted(9, [1, 2]) == 100.0


def test_fn_scorer_is_token_weighted_mean_percentile():
    cdf = rb.build_cdf([(v, 1) for v in range(1, 11)])
    score = rb.fn_scorer("cognitive", cdf)
    assert score(rows([5])) == pytest.approx(45.0)
    mixed = [
        {"cognitive": 1, "tokens": 300},
        {"cognitive": 9, "tokens": 100},
    ]
    assert score(mixed) == pytest.approx((5 * 300 + 85 * 100) / 400)
    assert score([]) is None
    assert score([{"cognitive": 1, "tokens": 0}]) is None


def test_fn_score_is_invariant_to_splitting_a_function():
    cdf = rb.build_cdf([(v, 1) for v in range(1, 11)])
    score = rb.fn_scorer("cognitive", cdf)
    whole = [{"cognitive": 4, "tokens": 200}]
    split = [{"cognitive": 4, "tokens": 100}, {"cognitive": 4, "tokens": 100}]
    assert score(whole) == pytest.approx(score(split))


def test_file_scorer_ranks_the_statistic_among_files():
    sample = sorted([1.0, 2.0, 3.0, 4.0])
    score = rb.file_scorer("cognitive", "mean", sample)
    assert score(rows([2, 3])) == pytest.approx(rb.rank_in_sorted(2.5, sample))
    assert score([]) is None


def test_bands_map_points_back_to_raw_values_and_clamp():
    pairs = [(float(v), 1.0) for v in range(1, 101)]
    assert rb.band_of_pairs(pairs, 50, 10) == (40.0, 60.0)
    low, high = rb.band_of_pairs(pairs, 2, 10)
    assert low == 1.0 and high == 12.0
    sample = [float(v) for v in range(101)]
    assert rb.band_of_sample(sample, 50, 5) == pytest.approx((45.0, 55.0))


def test_tier_points_and_problems_needed():
    assert rb.tier_points(4.9) == 5.0
    assert rb.tier_points(5.1) == 10.0
    assert rb.tier_points(10.1) == ib.NONE_YET
    assert rb.tier_points(None) == ib.NONE_YET
    assert rb.problems_needed(None, 10) is None
    assert rb.problems_needed(10, 10) == 3  # (1.645)^2 = 2.7
    assert rb.problems_needed(1, 10) == 1


def test_lopo_points_reports_worst_gap_and_per_problem_scores():
    score = lambda rs: float(sum(r["cognitive"] for r in rs) / len(rs))  # noqa: E731
    agreed = {"a": rows([10]), "b": rows([20]), "c": rows([30])}
    out = rb.lopo_points(agreed, score)
    assert out["per_problem"] == {"a": 10.0, "b": 20.0, "c": 30.0}
    assert out["worst"] == pytest.approx(15.0)  # a vs mean(20, 30)
    assert out["mean"] == pytest.approx((15 + 0 + 15) / 3)
    assert out["sd"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        rb.lopo_points({"a": rows([1])}, score)


def test_draft_points_spread_within_a_run_and_gap_to_agreed():
    score = lambda rs: float(rs[0]["cognitive"])  # noqa: E731
    agreed = {"p": rows([50])}
    drafts = {
        "p": {
            ("r1", "x"): rows([40]),
            ("r1", "y"): rows([48]),
            ("r2", "x"): rows([70]),
        }
    }
    out = rb.draft_points(agreed, drafts, score)
    assert out["school_spread"] == 8.0
    assert out["vs_agreed"] == 20.0
    assert rb.draft_points(agreed, {"q": drafts["p"]}, score) == {
        "vs_agreed": None,
        "school_spread": None,
    }


def test_bootstrap_points_is_zero_for_constant_and_positive_for_varied():
    score = lambda rs: float(sum(r["cognitive"] for r in rs) / len(rs))  # noqa: E731
    draws = ib.resample_indices({"a": 6}, 200, 1)
    constant = {"a": rows([4] * 6)}
    assert rb.bootstrap_points(constant, draws, score) == 0.0
    varied = {"a": rows([0, 10, 0, 10, 0, 10])}
    assert rb.bootstrap_points(varied, draws, score) > 0


def corpus(count=20):
    return [rows([i % 7, (i + 3) % 7, 1, 2, 5, 6]) for i in range(count)]


def test_evaluate_is_deterministic_and_covers_metrics_and_modes():
    files = [
        [dict.fromkeys(ib.METRICS, v) | {"tokens": 50} for v in (i % 5, 1, 2, 3, 4, 5)]
        for i in range(12)
    ]
    agreed = {p: files[i] for i, p in enumerate("abc")}
    drafts = {"a": {("r", "x"): files[3], ("r", "y"): files[4]}}
    first = rb.evaluate(agreed, drafts, files, resamples=20)
    second = rb.evaluate(agreed, drafts, files, resamples=20)
    assert first == second
    assert set(first) == set(ib.METRICS)
    entry = first["cognitive"]
    assert set(entry["cells"]) == set(rb.MODES)
    cell = entry["cells"]["fn"]
    assert 0 <= cell["pooled"] <= 100
    assert cell["tier_a"] in (5.0, 10.0, ib.NONE_YET)
    assert cell["err_a"] >= cell["err_b"]
    assert set(cell["band"]) == {"5", "10"}


def test_raw_tiers_reads_best_stats():
    evaluation = {
        "m": {
            "best": "p50",
            "best_b": "mean",
            "cells": {"p50": {"tier": 0.1}, "mean": {"tier_b": "none-yet"}},
        }
    }
    assert rb.raw_tiers(evaluation) == {
        "m": {"stat_a": "p50", "tier_a": 0.1, "stat_b": "mean", "tier_b": "none-yet"}
    }


def test_pooled_scores_per_metric_and_mode():
    files = corpus()
    out = rb.pooled_scores({"a": files[0], "b": files[1]}, files)
    assert set(out["cognitive"]) == set(rb.MODES)
