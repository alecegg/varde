# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import baseline_dominance as bd
import baseline_measure as bm
from varde_code.quality_score.calibration import load_calibration

BASE = load_calibration(bm.DEFAULT_CALIBRATION)
REGION = {"Phi": 96, "c0": 10}


def function(name, tokens, cognitive):
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


def record(functions, index=0):
    return {
        "contract": "facts-2",
        "path": f"m{index}.py",
        "language": "python",
        "module": ".",
        "tokens": sum(f["tokens"] for f in functions),
        "structure_confidence": "normal",
        "functions": functions,
    }


def spread(index):
    """Several small functions; none holds more than half the file."""
    return record([function(f"f{i}", 40, 8 + index % 3) for i in range(5)], index)


def single_tidy(index):
    """One comfortable function that holds the whole file."""
    return record([function("only", 60, 10)], index)


def monolith(index):
    return record([function("big", 400, 60), function("small", 20, 1)], index)


def test_dominant_large_reference_gives_zero():
    reference = [spread(0), spread(1), monolith(2)]
    assert bd.derive_dominance(reference, REGION, BASE) == 0


def test_reference_without_dominant_functions_gives_largest_grid_strength():
    reference = [spread(i) for i in range(5)]
    assert bd.derive_dominance(reference, REGION, BASE) == bd.GRID[-1]


def test_many_tidy_single_function_files_lower_the_strength():
    reference = [single_tidy(i) for i in range(5)] + [spread(i) for i in range(5, 10)]
    strength = bd.derive_dominance(reference, REGION, BASE)
    assert strength < bd.GRID[-1]


def test_result_is_on_the_grid_and_idempotent():
    reference = [single_tidy(0), single_tidy(1)] + [spread(i) for i in range(2, 10)]
    first = bd.derive_dominance(reference, REGION, BASE)
    assert first in bd.GRID
    assert first == bd.derive_dominance(reference, REGION, BASE)
    assert first == bd.derive_dominance(list(reversed(reference)), REGION, BASE)


def test_empty_reference_gives_zero():
    assert bd.derive_dominance([], REGION, BASE) == 0


def test_grid_is_fixed():
    assert bd.GRID[0] == 0
    assert bd.GRID[-1] == 2_000_000
    assert len(bd.GRID) == 9
    assert {b - a for a, b in zip(bd.GRID, bd.GRID[1:], strict=False)} == {250_000}


def test_dominant_large_needs_share_and_excess():
    assert bd.is_dominant_and_large(function("a", 400, 1), 600, REGION)
    assert not bd.is_dominant_and_large(function("a", 60, 10), 100, REGION)
    assert not bd.is_dominant_and_large(function("a", 200, 1), 600, REGION)


def test_within_budget_allows_ten_percent():
    scores = [90.0] * 9 + [10.0]
    assert bd.within_budget(scores, 50.0)
    assert not bd.within_budget([90.0] * 8 + [10.0, 10.0], 50.0)


def test_lower_percentile_is_nearest_rank():
    assert bd.lower_percentile_score([5, 1, 9, 3], 10) == 1
    assert bd.lower_percentile_score(list(range(1, 11)), 10) == 1
    assert bd.lower_percentile_score(list(range(1, 11)), 20) == 2


def test_cli_check_prints_strength(capsys):
    code = bd.main(["--check", "--language", "python", "--reference", "agreed"])
    assert code == 0
    assert capsys.readouterr().out.startswith("dominance: ")
