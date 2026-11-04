# ruff: noqa: S101
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import baseline_q4q5 as q  # noqa: E402, RUF100

X = 76_000_000


def test_q4_boundary_95_percent_passes():
    pairs = [(100, 50)] * 19 + [(100, 100)]
    result = q.q4_result(pairs)
    assert result["n"] == 20
    assert result["rate"] == 0.95
    assert result["pass"] is True


def test_q4_below_boundary_fails():
    result = q.q4_result([(100, 50)] * 18 + [(100, 100)] * 2)
    assert result["rate"] == 0.9
    assert result["pass"] is False


def test_q4_skips_unscorable_original_and_counts_unscored_mutation_as_miss():
    result = q.q4_result([(None, 5), (100, None), (100, 50)])
    assert (result["n"], result["skipped"], result["hits"]) == (2, 1, 1)


def test_q5_boundary_90_percent_passes():
    excellent = [X + 1] * 5 + [X - 1]
    poor = [X - 5] * 4
    # one excellent below X is 1 of 10 out of band; it is also above every poor
    result = q.q5_result(excellent, poor, X)
    assert result["n"] == 10
    assert result["rate"] == 0.9
    assert result["inversions"] == 0
    assert result["pass"] is True


def test_q5_below_boundary_fails():
    result = q.q5_result([X + 1] * 4 + [X - 1] * 2, [X - 5] * 4, X)
    assert result["rate"] == 0.8
    assert result["pass"] is False


def test_q5_inversion_fails_even_at_full_band():
    result = q.q5_result([X + 1, X + 2], [X - 1], X)
    assert result["pass"] is True
    inverted = q.q5_result([X - 2, X + 2] * 5, [X - 1] * 10, X)
    assert inverted["inversions"] > 0
    assert inverted["pass"] is False


def test_q5_excellent_exactly_x_is_in_band_and_poor_exactly_x_is_not():
    result = q.q5_result([X], [X], X)
    assert result["hits"] == 1


def test_test_split_item_raises():
    with pytest.raises(ValueError, match="dev split only"):
        q.require_dev(
            [{"id": "a", "split": "dev"}, {"id": "b", "split": "test-restricted"}]
        )


def test_failures_name_language_and_rate():
    good = {"rate": 1.0, "hits": 1, "n": 1, "pass": True, "inversions": 0}
    bad = {"rate": 0.5, "hits": 1, "n": 2, "pass": False, "inversions": 0}
    lines = q.failures({"python": {"q4": bad, "q5": good}})
    assert lines == ["python Q4 rate 0.5 (1/2)"]
