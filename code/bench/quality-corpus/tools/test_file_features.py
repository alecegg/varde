# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import file_features as ff


def row(cognitive=0, tokens=50, depth=0, fan_out=0, fan_in=0):
    return {
        "cognitive": cognitive,
        "tokens": tokens,
        "depth": depth,
        "fan_out": fan_out,
        "fan_in": fan_in,
    }


ROWS = [
    row(cognitive=10, tokens=100, depth=2, fan_out=2, fan_in=0),
    row(cognitive=0, tokens=10, depth=1, fan_out=1, fan_in=1),
    row(cognitive=2, tokens=60, depth=0, fan_out=0, fan_in=1),
    row(cognitive=0, tokens=30, depth=0, fan_out=0, fan_in=0),
]


def test_features_of_known_file():
    f = ff.file_features(ROWS)
    assert f["n_functions"] == 4
    assert f["file_tokens"] == 200
    assert f["cog_sum"] == 12
    assert f["cog_max"] == 10
    assert f["cog_token_weighted"] == round((10 * 100 + 2 * 60) / 200, 6)
    assert f["tokens_p50"] == 30
    assert f["tiny_share"] == 0.25
    assert f["call_depth"] == 2
    assert f["edges_per_function"] == 0.5
    assert f["fan_in_zero_share"] == 0.5
    assert f["delegation_share"] == 0.25


def test_empty_file_has_no_features_except_count():
    f = ff.file_features([])
    assert f["n_functions"] == 0
    assert all(v is None for k, v in f.items() if k != "n_functions")
    assert set(f) == set(ff.FEATURES)


def test_delegation_proxy_requires_one_callee_no_branching_small_body():
    assert ff.is_delegation(row(fan_out=1, tokens=12))
    assert not ff.is_delegation(row(fan_out=2, tokens=12))
    assert not ff.is_delegation(row(fan_out=1, cognitive=1, tokens=12))
    assert not ff.is_delegation(row(fan_out=1, tokens=ff.DELEGATE_MAX_TOKENS + 1))


def test_tail_cuts_and_strict_hits():
    good = [float(i) for i in range(1, 11)]
    cuts = ff.tail_cuts(good)
    assert cuts == (1.0, 9.0)
    hits = ff.tail_hits([0.0, 1.0, 9.0, 10.0], cuts)
    assert hits["low"] == {"n": 4, "value": 0.25}
    assert hits["high"] == {"n": 4, "value": 0.25}


def test_spread_ratio_between_over_within():
    by_repo = {"a": [10.0, 11.0, 12.0], "b": [20.0, 21.0, 22.0]}
    result = ff.spread_ratio(by_repo)
    assert result["n"] == 2
    assert result["ratio"] > 1
    assert ff.repo_variance_share(by_repo)["value"] > 0.9


def test_spread_ratio_none_for_nonpositive_median():
    assert ff.spread_ratio({"a": [0.0, 0.0, 0.0]})["ratio"] is None


def test_sampled_ratio_is_deterministic_and_counts_repos():
    by_repo = {
        r: [float(i + off) for i in range(10)] for r, off in (("a", 0), ("b", 30))
    }
    first = ff.sampled_ratio(by_repo, 3, seeds=5)
    assert first == ff.sampled_ratio(by_repo, 3, seeds=5)
    assert first["n"] == 2


def test_feature_report_detects_a_shifted_variant():
    good = {
        "a": [float(i) for i in range(1, 21)],
        "b": [float(i) for i in range(1, 21)],
    }
    variants = [
        ff.VariantRow("a", "big", 5.0, 50.0),
        ff.VariantRow("a", "big", 5.0, 40.0),
    ]
    report = ff.feature_report(good, variants)
    kind = report["kinds"]["big"]
    assert kind["pooled_cut"]["high"] == {"n": 2, "value": 1.0}
    assert kind["paired_shift"]["up"] == {"n": 2, "value": 1.0}
    assert ff.best_tail(kind)[0] == "high"
    assert report["good_flagged"]["high"]["n"] == 40
