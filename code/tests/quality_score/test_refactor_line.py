import pytest
from varde_code.quality_score.refactor_line import (
    limits_of,
    monolith_advisory,
    needs_refactor,
    percentile_vs_reference,
    refactor_field,
    reference_line,
)
from varde_code.quality_score.user_view import user_view

MICRO = 1_000_000
LIMITS = {"Phi": 96, "c0": 10, "t_frag": 60}
REFERENCE = [float(v) for v in range(70, 90)]  # 20 files


def _fn(name, line, tokens, cognitive=0):
    return {"name": name, "line": line, "tokens": tokens, "cognitive": cognitive}


def _record(*functions, tokens=None):
    total = tokens if tokens is not None else sum(f["tokens"] for f in functions)
    return {"path": "code.py", "tokens": total, "functions": list(functions)}


def test_line_has_at_most_share_of_reference_strictly_below():
    line = reference_line(REFERENCE)
    assert line == 71.0
    assert sum(1 for s in REFERENCE if s < line) <= len(REFERENCE) * 0.10


def test_line_is_order_independent_and_rejects_empty():
    assert reference_line(REFERENCE[::-1]) == reference_line(REFERENCE)
    with pytest.raises(ValueError):
        reference_line([])


def test_needs_refactor_is_strictly_below_the_line():
    line = reference_line(REFERENCE)
    assert needs_refactor(70.9, line)
    assert not needs_refactor(line, line)


def test_percentile_is_share_of_reference_that_is_better():
    assert percentile_vs_reference(69.0, REFERENCE) == 100
    assert percentile_vs_reference(79.5, REFERENCE) == 50
    assert percentile_vs_reference(95.0, REFERENCE) == 0


def test_refactor_field_message_names_the_percentile():
    low = refactor_field(60.0, REFERENCE)
    high = refactor_field(88.5, REFERENCE)
    assert low["needs_refactor"] is True
    assert low["message"].startswith("worse than 100% of your reference")
    assert high["needs_refactor"] is False


def test_limits_convert_micro_units():
    parameters = {"Phi": 96 * MICRO, "c0": 10 * MICRO, "t_frag": 60 * MICRO}
    assert limits_of(parameters) == LIMITS


def test_advisory_fires_for_a_dominant_function_past_phi():
    record = _record(_fn("run", 12, 400), _fn("helper", 3, 40))
    advisory = monolith_advisory(record, LIMITS)
    assert advisory is not None
    assert (advisory["function"], advisory["file"], advisory["line"]) == (
        "run",
        "code.py",
        12,
    )
    assert advisory["share_percent"] == 90
    assert "split" in advisory["action"]


def test_advisory_fires_on_cognitive_or_indirection_below_phi():
    cognitive = _record(_fn("run", 1, 90, cognitive=14), _fn("a", 9, 20))
    tiny = [_fn(f"t{i}", 20 + i, 10) for i in range(4)]
    indirection = _record(_fn("run", 1, 90), *tiny)
    assert monolith_advisory(cognitive, LIMITS) is not None
    assert monolith_advisory(indirection, LIMITS) is not None


def test_advisory_silent_when_not_dominant_or_small():
    balanced = _record(_fn("a", 1, 200), _fn("b", 30, 180), _fn("c", 60, 40))
    small = _record(_fn("run", 1, 80, cognitive=2))
    assert monolith_advisory(balanced, LIMITS) is None
    assert monolith_advisory(small, LIMITS) is None
    assert monolith_advisory(_record(), LIMITS) is None


def test_advisory_is_deterministic():
    record = _record(_fn("run", 12, 400), _fn("helper", 3, 40))
    assert monolith_advisory(record, LIMITS) == monolith_advisory(record, LIMITS)


def _payload():
    score = {"numerator": 80 * MICRO, "denominator": 1}
    return {"calibration": "c", "score": score, "tokens": 100}


def test_advisory_never_changes_the_score_and_fields_are_whitelisted():
    plain = user_view(_payload(), [])
    advisory = monolith_advisory(_record(_fn("run", 12, 400)), LIMITS)
    verdict = refactor_field(80.0, REFERENCE)
    full = user_view(_payload(), [], None, verdict, advisory)
    assert full["score"] == plain["score"] == 80.0
    assert set(full) - set(plain) == {"refactor", "monolith"}
    assert full["monolith"] == advisory
    assert full["refactor"] == verdict


def test_fields_absent_when_not_supplied():
    assert {"refactor", "monolith"}.isdisjoint(user_view(_payload(), []))
