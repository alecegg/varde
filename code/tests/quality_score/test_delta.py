import json

import pytest
from varde_code.quality_score.delta import judge
from varde_code.quality_score.reference import N_MIN

REFERENCE = [float(40 + i) for i in range(N_MIN)]  # 40..59, p10 = 41.0


def test_below_p10_with_reference_reports_all_fields():
    verdict = judge(30.0, 50.0, REFERENCE)
    assert verdict["needs_refactor"] is True
    assert verdict["below_reference_p10"] is True
    assert verdict["worse_than_before"] is True
    assert verdict["worse_than_percent"] == 100
    assert verdict["n_reference"] == N_MIN
    assert f"n={N_MIN}" in verdict["message"]


def test_at_or_above_p10_and_not_worse_than_before():
    verdict = judge(55.0, 50.0, REFERENCE)
    assert verdict["needs_refactor"] is False
    assert verdict["worse_than_before"] is False
    assert "no worse than before" in verdict["message"]


def test_small_reference_gives_no_reference_verdict_and_says_so():
    verdict = judge(30.0, 50.0, REFERENCE[: N_MIN - 1])
    assert "needs_refactor" not in verdict
    assert "worse_than_percent" not in verdict
    assert verdict["n_reference"] == N_MIN - 1
    assert "too small" in verdict["message"]
    assert f"n={N_MIN - 1}" in verdict["message"]
    assert f"need {N_MIN}" in verdict["message"]
    assert verdict["worse_than_before"] is True


def test_without_reference_or_before_only_the_given_part_appears():
    assert "n_reference" not in judge(30.0, 50.0, None)
    only_ref = judge(30.0, None, REFERENCE)
    assert "worse_than_before" not in only_ref


def test_judge_is_deterministic_and_never_claims_absolute_quality():
    first = json.dumps(judge(45.0, 44.0, REFERENCE), sort_keys=True)
    assert first == json.dumps(judge(45.0, 44.0, REFERENCE), sort_keys=True)
    for score in (10.0, 45.0, 99.0):
        message = judge(score, 50.0, REFERENCE)["message"]
        assert "good enough" not in message
        assert "high quality" not in message


@pytest.mark.parametrize("n", [0, 1])
def test_tiny_references_do_not_raise(n):
    assert "needs_refactor" not in judge(30.0, None, REFERENCE[:n])


def test_drop_within_tolerance_is_not_worse():
    from varde_code.quality_score.delta import WORSE_TOLERANCE

    assert judge(50.0 - WORSE_TOLERANCE, 50.0, None)["worse_than_before"] is False
    assert judge(49.4, 50.0, None)["worse_than_before"] is True
    assert "no worse than before" in judge(49.6, 50.0, None)["message"]


def test_low_confidence_band_is_named_in_the_message():
    low = judge(50.0, None, [float(40 + i) for i in range(30)])
    assert "low confidence" in low["message"]
    ok = judge(50.0, None, [float(40 + i) for i in range(60)])
    assert "low confidence" not in ok["message"]
