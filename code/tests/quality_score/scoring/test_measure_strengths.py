"""Shadow measure strengths: off is identical, on adds a monotone cost and guidance."""

from dataclasses import replace
from pathlib import Path

import pytest
from varde_code.quality_score import score_scope
from varde_code.quality_score.breakdown import breakdown
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.fixedpoint import MICRO
from varde_code.quality_score.scoring import explain
from varde_code.quality_score.user_view import user_view

CAL1 = Path(__file__).parents[3] / "src/varde_code/quality_score/calibration/cal-1.toml"
CALIBRATION = load_calibration(CAL1)


def _function(name, line, **extra):
    return {
        "id": f"a.py::{name}",
        "name": name,
        "line": line,
        "tokens": 60,
        "cognitive": 2,
        "params": 1,
        "depth": 1,
        "fan_out": 1,
        "tree_size": 1,
        "name_issues": [],
        "exempt_role": None,
        "fragment_scope": None,
        **extra,
    }


def _record(functions):
    return {
        "contract": "facts-2",
        "path": "a.py",
        "language": "python",
        "module": ".",
        "tokens": 60 * len(functions) + 40,
        "structure_confidence": "normal",
        "functions": functions,
    }


def _with(**strengths):
    return replace(
        CALIBRATION,
        global_strengths={
            **CALIBRATION.global_strengths,
            **{k: int(v * MICRO) for k, v in strengths.items()},
        },
    )


def _debt(record, calibration, component):
    scored = score_scope([record], calibration)
    return scored.files[0].components.get(component, 0)


def _score(record, calibration):
    scored = score_scope([record], calibration)
    assert scored.score is not None
    return scored.score.numerator * MICRO // scored.score.denominator


def test_cal2_ships_delegation_on_and_nesting_and_vague_names_off():
    """Chosen in notes/measures-eval.md: only sd passed the false-positive budget."""
    strengths = CALIBRATION.global_strengths
    assert [strengths[k] for k in ("sn", "sm", "sd")] == [0, 0, MICRO]


def test_strengths_off_ignore_the_measures_bit_identically():
    plain = _record([_function("f", 1), _function("g", 20)])
    marked = _record(
        [
            _function("f", 1, max_nesting=9, vague_names=5, delegates=True),
            _function("g", 20, max_nesting=7, vague_names=3, delegates=True),
        ]
    )
    off = _with(sn=0.0, sm=0.0, sd=0.0)
    assert score_scope([plain], off) == score_scope([marked], off)
    components = score_scope([marked], off).files[0].components
    assert not {"nesting", "vague_names", "delegation"} & set(components)


@pytest.mark.parametrize(
    ("strength", "component", "measure"),
    [("sn", "nesting", "max_nesting"), ("sm", "vague_names", "vague_names")],
)
def test_function_measure_cost_is_monotone_in_the_excess(strength, component, measure):
    calibration = _with(**{strength: 1.0})
    debts = [
        _debt(_record([_function("f", 1, **{measure: value})]), calibration, component)
        for value in range(7)
    ]
    assert debts[0] == 0
    assert debts[1:] == sorted(set(debts[1:]))
    assert debts[-1] > 0


def test_function_measure_cost_scales_with_the_strength():
    record = _record([_function("f", 1, max_nesting=5)])
    low = _debt(record, _with(sn=0.5), "nesting")
    high = _debt(record, _with(sn=1.0), "nesting")
    assert 0 < low < high
    assert _score(record, _with(sn=1.0)) < _score(record, CALIBRATION)


def test_delegation_cost_needs_share_above_the_threshold_and_grows_with_it():
    calibration = _with(sd=1.0)

    def share(wrappers):
        functions = [_function(f"w{i}", i + 1, delegates=True) for i in range(wrappers)]
        functions += [
            _function(f"r{i}", 50 + i, delegates=False) for i in range(8 - wrappers)
        ]
        return _debt(_record(functions), calibration, "delegation")

    debts = [share(n) for n in range(9)]
    assert debts[0] == debts[2] == 0  # 2/8 is below 1/3
    assert debts[3:] == sorted(set(debts[3:]))


def test_delegation_ignores_rows_without_an_exact_flag():
    record = _record([_function(f"w{i}", i + 1) for i in range(4)])
    assert _debt(record, _with(sd=1.0), "delegation") == 0


def _largest_category(record, calibration):
    scored = score_scope([record], calibration)
    view = user_view(
        {**explain(scored), "calibration": "x"},
        breakdown(scored, calibration, [record]),
    )
    return view["categories"]


def test_guidance_names_nesting_vague_names_and_delegation_with_file_and_line():
    calibration = _with(sn=2.0, sm=2.0, sd=2.0)
    nested = _record([_function("deep", 7, max_nesting=8)])
    vague = _record([_function("names", 9, vague_names=6)])
    wrappers = _record(
        [_function(f"w{i}", 3 + i, delegates=True) for i in range(4)]
        + [_function("real", 30, delegates=False)]
    )
    for record, name, line in (
        (nested, "nesting", 7),
        (vague, "vague_names", 9),
        (wrappers, "delegation", 3),
    ):
        categories = _largest_category(record, calibration)
        top = max(categories, key=lambda c: c["points_lost"])
        assert top["name"] == name
        worst = top["worst"][0]
        assert (worst["file"], worst["line"]) == ("a.py", line)
        assert top["goal"] and worst["action"]


def test_zero_delegation_cost_adds_no_component_key():
    record = _record([_function("r", 1, delegates=False)])
    assert "delegation" not in score_scope([record], _with(sd=1.0)).files[0].components
