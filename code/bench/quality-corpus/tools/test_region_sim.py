# ruff: noqa: S101
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import baseline_region as br
import region_sim as rs

PLACEHOLDER = {**dict.fromkeys(br.FITTED.values(), 10), "Phi": 96, "p0": 2}
CORPUS = {m: [0] * 50 + [4 * i for i in range(1, 51)] for m in br.FITTED}


def synthetic_pool(name, value, files=12):
    """Every function of every file has ``value`` on every fitted measure."""
    rows = [[dict.fromkeys(br.FITTED, value)] * 3 for _ in range(files)]
    peaks = [rs.peak_vector(r) for r in rows]
    return rs.Pool(name, rows, peaks, peaks, {})


def fake_scorer(item, region):
    return 100 - 10 * rs.excess([item], region)


def data_for(pools):
    return rs.Data(pools, CORPUS, PLACEHOLDER, [], [], fake_scorer, 2, 3, {})


def test_draw_is_deterministic_sorted_and_in_range():
    first = rs.draw(20, 4, seed=7)
    assert first == rs.draw(20, 4, seed=7)
    assert first == sorted(set(first)) and len(first) == 4
    assert all(0 <= i < 20 for i in first)
    assert first != rs.draw(20, 4, seed=8)


def test_draw_rejects_pool_without_held_out_files():
    with pytest.raises(ValueError, match="too small"):
        rs.draw(5, 4, seed=0)


def test_k_range_is_one_to_six():
    assert rs.parse_ks("1,2,3,4,5,6") == [1, 2, 3, 4, 5, 6]
    for bad in ("0", "7", "", "1,9"):
        with pytest.raises(ValueError, match="k must be"):
            rs.parse_ks(bad)


def test_only_dev_paths_are_listed_and_read():
    paths = [f"pkg/module_{i}.py" for i in range(400)]
    listed = rs.dev_paths("repo/x", paths)
    assert listed
    assert {rs.split_of(f"repo/x:{p}") for p in listed} == {"dev"}
    assert {rs.split_of(f"repo/x:{p}") for p in paths} >= {
        "test-restricted",
        "regression",
    }
    seen = []

    def read(path):
        seen.append(path)

    assert rs.read_dev_files("repo/x", paths, read, per_repo=5) == []
    assert seen and set(seen) <= set(listed)


def test_relative_iqr_and_smallest_k():
    assert rs.relative_iqr([10] * 9) == 0
    assert rs.relative_iqr([0, 0, 0]) is None
    assert rs.relative_iqr(list(range(1, 101))) == pytest.approx(1.0, abs=0.05)
    assert rs.smallest_k({1: 0.3, 2: 0.12, 3: 0.1, 4: 0.05}) == 3
    assert rs.smallest_k({1: None, 2: 0.5}) is None


def test_synthetic_repos_with_known_example_values_recover_thresholds():
    low, high = synthetic_pool("low", 4), synthetic_pool("high", 40)
    for pool, value in ((low, 4), (high, 40)):
        runs = rs.run_pool(pool, PLACEHOLDER, CORPUS, [1, 3, 6], seeds=5)
        for k, by_seed in runs.items():
            expected = br.shifted(10, value, k)
            lo, hi = br.corpus_bounds(CORPUS["tokens"])
            expected = min(max(expected, lo), hi)
            assert {run.region[0] for run in by_seed} == {expected}
    stability = rs.stability_view(
        {
            "low": rs.run_pool(low, PLACEHOLDER, CORPUS, [3], 8),
            "high": rs.run_pool(high, PLACEHOLDER, CORPUS, [3], 8),
        },
        [3],
    )
    assert stability["median_spread"]["c0"][3]["value"] == 0
    assert stability["smallest_k_at_or_below_10pct"]["c0"] == 3


def test_style_view_separates_between_repo_from_within_repo_spread():
    pools = [synthetic_pool(f"r{v}", v) for v in (2, 8, 20, 36)]
    runs = {p.name: rs.run_pool(p, PLACEHOLDER, CORPUS, [3], 6) for p in pools}
    stability = rs.stability_view(runs, [3])
    style = rs.style_view(runs, stability, [3])
    entry = style[3]["c0"]
    assert entry["within_repo_spread"]["value"] == 0
    assert entry["between_repo_spread"]["value"] > 0
    assert entry["between_over_within"]["value"] is None


def test_simulation_json_is_byte_identical_and_reports_n_everywhere():
    pools = [synthetic_pool("a", 6), synthetic_pool("b", 30)]
    first = rs.dumps(rs.simulate(data_for(pools), [1, 2, 3], seeds=4))
    second = rs.dumps(rs.simulate(data_for(pools), [1, 2, 3], seeds=4))
    assert first == second
    assert rs.missing_n(rs.simulate(data_for(pools), [1, 2], seeds=3)) == []
    assert rs.missing_n({"a": {"value": 1}}) == ["a/value"]


def test_held_out_never_includes_the_drawn_files():
    pool = synthetic_pool("a", 6, files=8)
    run = rs.Run(0, (0, 1, 2), rs.region_vector(PLACEHOLDER))
    tally = rs.tally_run(pool, [], run, [])
    assert tally["good_heldout"][1] == 5


def test_variants_count_only_when_their_source_file_is_held_out():
    pool = synthetic_pool("a", 6, files=8)._replace(
        variants={
            0: {"wrappers": ((99,) * 6, (99,) * 6)},
            5: {"wrappers": ((99,) * 6, (99,) * 6)},
        }
    )
    run = rs.Run(0, (0, 1, 2), rs.region_vector(PLACEHOLDER))
    assert rs.tally_run(pool, [], run, [])["flagged:wrappers"] == [1, 1]


def test_pair_outcome_counts_no_further_outside():
    region = (10,) * 6
    far, near, inside = [(30,) * 6], [(12,) * 6], [(5,) * 6]
    assert rs.pair_outcome({"before": far, "after": near}, region) == (True, True, True)
    assert rs.pair_outcome({"before": near, "after": far}, region) == (
        False,
        True,
        False,
    )
    assert rs.pair_outcome({"before": inside, "after": inside}, region) == (
        True,
        False,
        False,
    )


def test_default_regions_have_loose_corpus_default():
    regions = rs.default_regions(PLACEHOLDER, CORPUS)
    loose = regions["corpus-q95"]
    assert loose["c0"] == br.nearest_rank(CORPUS["cognitive"], 95)
    assert regions["placeholder"] == PLACEHOLDER


def test_scored_labels_only_for_seeds_below_the_limit_and_use_the_line():
    pool = synthetic_pool("a", 2, files=8)
    other = synthetic_pool("b", 50, files=8)
    region = rs.region_vector(PLACEHOLDER)
    scoring = rs.Scoring(fake_scorer, 99.0, seeds=2, cross_files=3)
    early = rs.tally_run(pool, [other], rs.Run(1, (0, 1), region), [], scoring)
    late = rs.tally_run(pool, [other], rs.Run(2, (0, 1), region), [], scoring)
    assert early["scored:good_heldout"] == [6, 6]
    assert early["scored:cross_style"] == [0, 3]
    assert early["cross_style"][1] == 8
    assert not any(label.startswith("scored:") for label in late)


def test_constants_sweep_restores_constants_and_larger_offset_moves_less():
    pools = [synthetic_pool("a", 4), synthetic_pool("b", 40)]
    before = br.WEIGHT_OFFSET, br.ANCHOR_PERCENTILE
    sweep = rs.constants_sweep(data_for(pools), PLACEHOLDER, [3], seeds=3)
    assert before == (br.WEIGHT_OFFSET, br.ANCHOR_PERCENTILE)
    near = sweep["offset1-q90"]["median_shift_from_default"][3]["value"]
    far = sweep["offset8-q90"]["median_shift_from_default"][3]["value"]
    assert far < near
    assert rs.missing_n(sweep) == []
