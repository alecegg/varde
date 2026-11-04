from dataclasses import replace
from pathlib import Path

from varde_code.quality_score import score_scope
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.costs import dominance_scale
from varde_code.quality_score.fixedpoint import MICRO

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _function(name, tokens, cognitive=30):
    return {
        "id": f"a.py::{name}",
        "line": 1,
        "tokens": tokens,
        "cognitive": cognitive,
        "params": 1,
        "depth": 1,
        "fan_out": 1,
        "tree_size": 1,
        "name_issues": [],
        "exempt_role": None,
        "fragment_scope": None,
    }


def _record(functions, tokens):
    return {
        "contract": "facts-2",
        "path": "a.py",
        "language": "python",
        "module": ".",
        "tokens": tokens,
        "structure_confidence": "normal",
        "functions": functions,
    }


def _score(record, dominance=None):
    calibration = load_calibration(CALIBRATION)
    if dominance is not None:
        strengths = {**calibration.global_strengths, "dominance": dominance * MICRO}
        calibration = replace(calibration, global_strengths=strengths)
    scored = score_scope([record], calibration)
    return scored.files[0]


def test_dominance_scale_is_identity_up_to_half_the_file():
    assert dominance_scale(500, 1000, 2 * MICRO) == MICRO
    assert dominance_scale(100, 1000, 2 * MICRO) == MICRO
    assert dominance_scale(1000, 1000, 2 * MICRO) == 3 * MICRO
    assert dominance_scale(750, 1000, 2 * MICRO) == 2 * MICRO


def test_dominance_scale_ignores_zero_strength_and_empty_files():
    assert dominance_scale(900, 1000, 0) == MICRO
    assert dominance_scale(900, 0, 2 * MICRO) == MICRO


def test_default_calibration_has_no_dominance_effect():
    record = _record([_function("big", 400)], 450)
    assert _score(record).components == _score(record, dominance=0).components


def test_dominance_raises_the_cost_of_a_monolith_not_of_a_split_file():
    monolith = _record([_function("big", 400)], 450)
    split = _record([_function(f"f{i}", 80, cognitive=3) for i in range(5)], 450)
    plain, dominated = _score(monolith), _score(monolith, dominance=2)
    assert dominated.debt > 2 * plain.debt
    assert dominated.gate_score < plain.gate_score
    assert _score(split, dominance=2).components == _score(split).components
