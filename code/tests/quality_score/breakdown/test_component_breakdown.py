from copy import deepcopy
from pathlib import Path

from varde_code.quality_score.breakdown import COMPONENTS, HINTS, breakdown
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.fixedpoint import MICRO
from varde_code.quality_score.scoring import score_scope

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _facts(path="src/a.py", *, tokens=1000, functions=None):
    return {
        "contract": "facts-2",
        "path": path,
        "language": "python",
        "module": "src",
        "tokens": tokens,
        "structure_confidence": "normal",
        "functions": functions
        or [
            {
                "id": f"{path}::f",
                "line": 4,
                "tokens": 50,
                "cognitive": 10,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "fragment_scope": None,
            }
        ],
    }


def _entries(rows):
    calibration = load_calibration(CALIBRATION)
    scope = score_scope(rows, calibration)
    return scope, {item["name"]: item for item in breakdown(scope, calibration)}


def test_shares_sum_to_one_with_fixed_point_rounding_and_hints_are_present():
    _, items = _entries(
        [
            _facts(
                functions=[
                    {**_facts()["functions"][0], "id": "a", "cognitive": 31},
                    {**_facts()["functions"][0], "id": "b", "cognitive": 22},
                ]
            )
        ]
    )
    assert sum(item["share"] for item in items.values()) == MICRO
    assert all(HINTS[name] and items[name]["hint"] for name in COMPONENTS)


def test_zero_debt_component_has_no_recovery_or_offenders():
    _, items = _entries([_facts()])
    assert items["names"]["debt"] == 0
    assert items["names"]["points_recoverable"] == 0
    assert items["names"]["worst_offenders"] == []


def test_recoverable_points_match_removing_offender_cost_in_facts():
    row = _facts()
    row["functions"][0]["name_issues"] = ["vague", "generic"]
    calibration = load_calibration(CALIBRATION)
    scope = score_scope([row], calibration)
    component = next(
        item for item in breakdown(scope, calibration) if item["name"] == "names"
    )
    edited = deepcopy(row)
    edited["functions"][0]["name_issues"] = []
    edited_score = score_scope([edited], calibration).score
    assert edited_score is not None
    assert scope.score is not None
    expected = edited_score.numerator * MICRO // edited_score.denominator
    actual = scope.score.numerator * MICRO // scope.score.denominator
    assert component["points_recoverable"] == expected - actual


def test_offenders_are_ordered_by_component_debt_then_id():
    base = _facts()["functions"][0]
    row = _facts(
        functions=[
            {**base, "id": "z", "name_issues": ["vague"]},
            {**base, "id": "b", "name_issues": ["vague", "generic"]},
            {**base, "id": "a", "name_issues": ["vague", "generic"]},
        ]
    )
    _, items = _entries([row])
    offenders = items["names"]["worst_offenders"]
    assert [item["id"] for item in offenders] == ["a", "b", "z"]


def test_output_is_deterministic_and_offender_lists_are_capped_at_five():
    base = _facts()["functions"][0]
    row = _facts(
        functions=[
            {**base, "id": str(index), "name_issues": ["vague", "generic"]}
            for index in range(8)
        ]
    )
    calibration = load_calibration(CALIBRATION)
    first = breakdown(score_scope([row], calibration), calibration)
    second = breakdown(score_scope([row], calibration), calibration)
    assert first == second
    assert (
        len(next(item for item in first if item["name"] == "names")["worst_offenders"])
        == 5
    )
