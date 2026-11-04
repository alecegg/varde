import math

import pytest
from varde_dev.calibrate.rating import fit, win_probability


def test_three_item_cycle_free_ordering_and_invariance():
    items = [("g", name) for name in "abc"]
    matches = [("g", "a", "b", "x"), ("g", "a", "c", "x"), ("g", "b", "c", "x")]
    expected = fit(matches, items)
    assert expected["a"]["rating"] > expected["b"]["rating"] > expected["c"]["rating"]
    assert fit(list(reversed(matches)), items) == expected
    assert fit([("g", y, x, "y") for _, x, y, _ in matches], items) == expected
    assert win_probability(expected, "a", "c") > 0.5


def test_two_item_hand_computed_counts_probability_and_standard_error():
    items = [("g", "a"), ("g", "b")]
    matches = [("g", "a", "b", outcome) for outcome in ("x", "x", "x", "y")]
    result = fit(matches, items)
    assert result["a"]["wins"] == 3
    assert result["a"]["losses"] == 1
    assert result["a"]["ties"] == 0
    assert result["a"]["rating"] == -result["b"]["rating"]
    # The score equation for a is 3 - 4*sigmoid(2s) - s = 0: each
    # item's N(0,1) prior contributes -s. Its solution is s ~= .3418,
    # giving sigmoid(2s) ~= .6645.
    assert math.isclose(win_probability(result, "a", "b"), 0.66454702, abs_tol=0.000001)
    # H = [[1+4c, -4c], [-4c, 1+4c]], c=p*(1-p); its inverse
    # diagonal is (1+4c)/(1+8c), whose square root is .8244.
    assert math.isclose(result["a"]["standard_error"], 0.82440087, abs_tol=0.000001)


def test_ties_count_as_half_wins_and_pull_ratings_together():
    items = [("g", "a"), ("g", "b")]
    decisive = fit([("g", "a", "b", "x")], items)
    tied = fit([("g", "a", "b", "tie")], items)
    win_loss = fit([("g", "a", "b", "x"), ("g", "a", "b", "y")], items)
    assert tied["a"]["ties"] == tied["b"]["ties"] == 1
    assert tied["a"]["wins"] == tied["b"]["wins"] == 0
    assert tied["a"]["rating"] == tied["b"]["rating"] == 0
    assert (tied["a"]["rating"], tied["b"]["rating"]) == (
        win_loss["a"]["rating"],
        win_loss["b"]["rating"],
    )
    assert abs(decisive["a"]["rating"]) > 0


def test_prior_keeps_unbeaten_rating_finite_and_more_matches_shrink_error():
    items = [("g", "a"), ("g", "b")]
    one = fit([("g", "a", "b", "x")], items)
    many = fit([("g", "a", "b", "x")] * 20, items)
    assert math.isfinite(many["a"]["rating"])
    assert many["a"]["standard_error"] < one["a"]["standard_error"]


def test_single_item_and_no_match_groups_are_undetermined():
    result = fit([], [("a", "solo"), ("b", "left"), ("b", "right")])
    assert result["solo"]["rating"] == 0
    assert result["solo"]["standard_error"] == "undetermined"
    assert result["left"]["standard_error"] == "undetermined"


def test_cross_group_match_is_rejected():
    with pytest.raises(ValueError, match="different groups"):
        fit([("a", "one", "two", "x")], [("a", "one"), ("b", "two")])


def test_known_item_mixed_with_item_from_other_group_is_rejected():
    with pytest.raises(ValueError, match="different groups"):
        fit([("b", "one", "two", "x")], [("a", "one"), ("b", "two")])


def test_win_probability_accepts_float_ratings():
    assert win_probability({"a": 1.0, "b": 0.0}, "a", "b") == 0.73105858
