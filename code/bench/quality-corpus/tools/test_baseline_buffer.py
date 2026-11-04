# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_buffer as bb
import baseline_measure as bm


def measurement(size_pool, tokens=1000, debt=100):
    empty = {}
    return {
        "calibration": "c",
        "language": "python",
        "files": 1,
        "tokens": tokens,
        "debt": debt,
        "pools": {
            "size": size_pool,
            "cognitive": {1: 10},
            "depth": {1: 10},
            "fan_out": {1: 10},
            "tree_size": {5: 10},
        },
        "fragment_sizes": empty,
        "fragment_tokens": tokens,
    }


def test_buffer_boundaries():
    assert bb.buffer_for(0.0) == 0.05
    assert bb.buffer_for(0.05) == 0.05
    assert bb.buffer_for(0.0500001) == 0.10
    assert bb.buffer_for(0.10) == 0.10
    assert bb.buffer_for(0.1000001) == bb.NONE_YET


def test_zero_agreed_uses_unit_floor():
    assert bb.relative_error(0.5, 0.0, 1.0) == pytest.approx(0.5)
    assert bb.recreation_errors("c0", 0.0, [2.0]) == [2.0]


def test_small_integer_metric_not_hidden():
    # c0 3 vs 4 is a 33% error, not hidden by the floor.
    (error,) = bb.recreation_errors("c0", 3.0, [4.0])
    assert error == pytest.approx(1 / 3)
    assert bb.buffer_for(error) == bb.NONE_YET


def test_max_of_two_recreations_beats_mean():
    errors = bb.recreation_errors("t0", 100.0, [100.0, 108.0])
    summary = bb.recreate_summary(errors)
    assert summary["e_recreate"] == pytest.approx(0.08)
    assert summary["e_mean"] == pytest.approx(0.04)
    assert bb.buffer_for(summary["e_mean"]) == 0.05
    assert bb.buffer_for(summary["e_recreate"]) == 0.10


def test_invalid_recreations_skipped():
    assert bb.recreation_errors("t0", 100.0, [None, 103.0]) == [pytest.approx(0.03)]
    assert bb.recreate_summary([]) == {"e_recreate": None, "e_mean": None}


def test_no_valid_recreation_falls_back_to_loo():
    entry = bb.problem_error("t0", 100.0, 107.0, [None, None])
    assert entry["e_recreate"] is None
    assert entry["err"] == pytest.approx(0.07)
    both = bb.problem_error("t0", 100.0, 101.0, [112.0])
    assert both["err"] == pytest.approx(0.12)


def test_max_rule_over_problems():
    per_problem = {
        "a": bb.problem_error("t0", 100.0, 101.0, [102.0]),
        "b": bb.problem_error("t0", 100.0, 109.0, [101.0]),
    }
    result = bb.metric_buffer(per_problem)
    assert result["err"] == pytest.approx(0.09)
    assert result["buffer"] == 0.10


def test_pooling_leave_one_out_and_all():
    agreed = {
        "a": [measurement({10: 100})],
        "b": [measurement({20: 100})],
        "c": [measurement({30: 100})],
    }
    loo = bb.loo_baselines(agreed)
    assert loo["a"]["Plo"] == 20.0  # pooled {20,30}: 25th percentile
    assert loo["c"]["Plo"] == 10.0
    assert bb.pooled_baseline(agreed)["t_frag"] == 20.0
    assert bb.pooled_baseline(agreed)["debt_density"] == pytest.approx(100.0)
    with pytest.raises(ValueError):
        bb.loo_baselines({"a": agreed["a"]})


def test_derive_buffers_end_to_end():
    agreed = {p: [measurement({10: 100})] for p in "abc"}
    recreated = {p: [measurement({10: 100}), measurement({10: 100})] for p in "abc"}
    result = bb.derive_buffers(agreed, recreated)
    assert result["Plo"]["buffer"] == 0.05
    assert result["Plo"]["baseline"] == 10.0
    off = dict(recreated, a=[measurement({13: 100})])
    assert bb.derive_buffers(agreed, off)["Plo"]["buffer"] == bb.NONE_YET


def test_scalar_metrics_flattens_ratios():
    flat = bb.scalar_metrics(bm.metrics_of(measurement({10: 100})))
    assert flat["debt_density"] == pytest.approx(100.0)
    assert flat["Plo"] == 10.0
