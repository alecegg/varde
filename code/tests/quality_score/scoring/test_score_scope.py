from pathlib import Path

from varde_code.quality_score import explain, rescore_without, score_scope
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.scoring.scoring import _density_for_score
from varde_code.quality_score.smap import score_density

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _facts(path="src/a.py", *, language="python", tokens=1000, cognitive=10):
    return {
        "contract": "facts-2",
        "path": path,
        "language": language,
        "module": "src",
        "tokens": tokens,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": f"{path}::f",
                "line": 4,
                "tokens": 50,
                "cognitive": cognitive,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "exempt_role": None,
                "fragment_scope": None,
            }
        ],
    }


def test_scope_rolls_up_file_scores_and_component_ablation():
    calibration = load_calibration(CALIBRATION)
    scope = score_scope(
        [_facts("b.py", tokens=2000, cognitive=25), _facts("a.py")], calibration
    )
    assert scope.score is not None
    assert scope.tokens == 3000
    assert scope.score.denominator == 3000
    assert scope.score.numerator == sum(f.gate_score * f.tokens for f in scope.files)
    assert [f.path for f in scope.files] == ["a.py", "b.py"]
    rescored = rescore_without(scope, "cognitive")
    assert rescored.score is not None
    expected = sum(
        file.tokens * file.gate_score
        for file in rescored.files
        if not file.excluded and not file.not_applicable
    )
    assert rescored.score.numerator == expected
    assert explain(scope)["calibration"] == "placeholder; not validated"


def test_low_structure_confidence_is_reported_and_removed_from_gate_score():
    calibration = load_calibration(CALIBRATION)
    row = _facts(cognitive=20)
    row["structure_confidence"] = "low"
    row["functions"] = [
        {
            **row["functions"][0],
            "id": str(index),
            "tokens": 20,
            "depth": 10,
            "fan_out": 12,
            "tree_size": 20,
            "fragment_scope": "file",
        }
        for index in range(8)
    ]
    module_row = _facts("b.py")
    module_row["structure_confidence"] = "normal"
    module_row["functions"] = [
        {**row["functions"][0], "id": f"module-{index}", "fragment_scope": "module"}
        for index in range(8)
    ]
    files = score_scope([row, module_row], calibration).files
    file = next(item for item in files if item.path == "src/a.py")
    for component in ("depth", "fan_out", "tree_size", "fragmentation"):
        assert file.components[component] > 0
    assert (
        next(item for item in files if item.path == "b.py").components[
            "module_fragmentation"
        ]
        > 0
    )
    assert file.gate_score > file.score
    row["structure_confidence"] = "normal"
    normal = score_scope([row], calibration).files[0]
    assert normal.gate_score == normal.score


def test_excluded_and_unmeasured_languages_have_no_scope_weight():
    calibration = load_calibration(CALIBRATION)
    rows = [
        _facts(),
        {**_facts("vendor.py"), "excluded": "vendored"},
        _facts("x.kt", language="kotlin"),
    ]
    scope = score_scope(rows, calibration)
    assert scope.tokens == 1000
    assert scope.files[1].excluded == "vendored"
    assert scope.files[2].not_applicable


def test_output_is_repeatable_and_component_attribution_is_bounded():
    calibration = load_calibration(CALIBRATION)
    row = _facts(cognitive=30)
    first = explain(score_scope([row], calibration))
    second = explain(score_scope([row], calibration))
    assert first == second
    file = first["files"][0]
    assert file["points_lost"] >= 0
    assert file["components"]["cognitive"] > 0
    assert isinstance(file["functions"], list)


def test_points_lost_reconcile_exactly_at_file_and_component_levels():
    calibration = load_calibration(CALIBRATION)
    scope = score_scope(
        [
            _facts("c.py", tokens=11, cognitive=30),
            _facts("a.py", tokens=7, cognitive=20),
            _facts("b.py", tokens=5, cognitive=25),
        ],
        calibration,
    )
    assert scope.score is not None
    expected = (100 * 1_000_000 * scope.tokens - scope.score.numerator) // scope.tokens
    assert sum(file.points_lost for file in scope.files) == expected
    for file in scope.files:
        assert file.component_points_lost is not None
        assert sum(file.component_points_lost.values()) == file.points_lost


def test_facts_produce_expected_density_score_and_worst_function_order():
    calibration = load_calibration(CALIBRATION)
    row = _facts(cognitive=30)
    row["functions"].append(
        {
            **row["functions"][0],
            "id": "z",
            "cognitive": 40,
            "depth": 15,
            "fan_out": 15,
            "tree_size": 30,
        }
    )
    file = score_scope([row], calibration).files[0]
    assert file.debt == sum(file.components.values())
    assert file.density == file.debt * 1000 // file.tokens
    assert file.score == file.gate_score
    assert [function.id for function in file.worst_functions] == [
        "z",
        row["functions"][0]["id"],
    ]


def test_mixed_language_scores_are_token_weighted_and_order_independent():
    calibration = load_calibration(CALIBRATION)
    rows = [
        _facts("a.py", tokens=1000),
        _facts("b.ts", language="typescript", tokens=2000, cognitive=20),
    ]
    forward = score_scope(rows, calibration)
    reverse = score_scope(list(reversed(rows)), calibration)
    assert forward.score is not None
    assert explain(forward) == explain(reverse)
    assert forward.score.numerator == sum(
        file.tokens * file.gate_score for file in forward.files
    )
    assert forward.languages["python"].denominator == 1000
    assert forward.languages["typescript"].denominator == 2000


def test_floor_exemption_obeys_overhead_threshold_across_file_shapes():
    calibration = load_calibration(CALIBRATION)
    shapes = [
        _facts("tiny.py", tokens=3),
        _facts("helpers.py", tokens=100, cognitive=0),
        _facts("large.py", tokens=5000, cognitive=0),
    ]
    for row in shapes:
        if row["path"] == "helpers.py":
            row["functions"] = [
                {**row["functions"][0], "id": str(index), "tokens": 4}
                for index in range(25)
            ]
        file = score_scope([row], calibration).files[0]
        floor = calibration.languages["python"].parameters["Y"]
        assert file.exempt_from_floor or file.score >= floor
        assert file.exempt_from_floor == (file.floor_exemption_reason is not None)
    floor = calibration.languages["python"].parameters["Y"]
    density = _density_for_score(floor)
    assert score_density(density) <= floor
    assert score_density(density - 1) > floor


def test_explain_contains_the_contract_score_records():
    calibration = load_calibration(CALIBRATION)
    explained = explain(score_scope([_facts()], calibration))
    file = explained["files"][0]
    assert {
        "path",
        "language",
        "tokens",
        "debt",
        "density",
        "score",
        "exempt_from_floor",
        "components",
        "worst_functions",
    } <= file.keys()
    assert isinstance(file["functions"], list)


def test_heuristic_components_respect_repository_caps():
    calibration = load_calibration(CALIBRATION)
    row = _facts()
    row["functions"][0]["name_issues"] = ["short", "vague", "generic"]
    row["functions"][0]["tokens"] = 1
    file = score_scope(
        [row], calibration, component_caps={"names": 10, "small_side": 1234}
    ).files[0]
    assert file.components["names"] <= 10
    assert file.components["small_side"] <= 1234


def test_component_caps_can_be_overridden_per_repository():
    calibration = load_calibration(CALIBRATION)
    row = _facts()
    row["functions"][0]["name_issues"] = ["short", "vague", "generic"]
    default = score_scope([row], calibration).files[0]
    capped = score_scope([row], calibration, component_caps={"names": 10}).files[0]
    assert default.components["names"] > capped.components["names"]
    assert capped.components["names"] == 10
