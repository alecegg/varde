from pathlib import Path

from varde_code.quality_score.breakdown import breakdown
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.scoring import score_scope

CALIBRATION = load_calibration(
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _function(name, line, **overrides):
    base = {
        "id": f"a.py::{name}#1",
        "line": line,
        "tokens": 50,
        "cognitive": 2,
        "params": 1,
        "depth": 1,
        "fan_out": 1,
        "tree_size": 1,
        "name_issues": [],
        "fragment_scope": None,
    }
    return {**base, **overrides}


def _record(*functions):
    return {
        "contract": "facts-2",
        "path": "a.py",
        "language": "python",
        "module": "src",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": list(functions),
    }


def _targets(record, name):
    rows = breakdown(score_scope([record], CALIBRATION), CALIBRATION, [record])
    return next(row for row in rows if row["name"] == name)["fix_targets"]


def test_cognitive_targets_are_beyond_comfort_ordered_by_share_top_three():
    record = _record(
        _function("fine", 1),
        _function("a", 10, cognitive=30),
        _function("b", 20, cognitive=20),
        _function("c", 30, cognitive=14),
        _function("d", 40, cognitive=12),
    )
    targets = _targets(record, "cognitive")
    assert [t["id"] for t in targets] == ["a.py::a#1", "a.py::b#1", "a.py::c#1"]
    assert [t["now"] for t in targets] == [30, 20, 14]
    assert {t["target"] for t in targets} == {10}
    assert targets[0]["share"] > targets[1]["share"] > targets[2]["share"]
    assert sum(t["share"] for t in targets) < 1_000_000


def test_long_side_uses_token_counts_from_records():
    record = _record(_function("big", 5, tokens=300), _function("ok", 50))
    targets = _targets(record, "long_side")
    assert [(t["id"], t["now"], t["target"]) for t in targets] == [
        ("a.py::big#1", 300, 96)
    ]


def test_within_limit_functions_are_listed_when_none_exceeds():
    record = _record(_function("x", 1, cognitive=5), _function("y", 9, cognitive=4))
    targets = _targets(record, "cognitive")
    assert [t["id"] for t in targets] == ["a.py::x#1", "a.py::y#1"]
    assert all(t["within_limit"] for t in targets)


def test_names_targets_list_issues_and_fragmentation_lists_tiny_helpers():
    tiny = [
        _function(f"h{i}", 10 + i, tokens=10 + i, fragment_scope="file")
        for i in range(5)
    ]
    record = _record(_function("v", 1, name_issues=["vague", "short"]), *tiny)
    names = _targets(record, "names")
    assert names[0]["issues"] == ["short", "vague"]
    assert names[0]["now"] == 2
    fragments = _targets(record, "fragmentation")
    assert [t["id"] for t in fragments] == [f"a.py::h{i}#1" for i in range(3)]
    assert {(t["now"], t["target"]) for t in fragments} == {(5, 3)}


def test_targets_are_deterministic_and_empty_without_loss():
    record = _record(_function("v", 1, cognitive=30))
    assert _targets(record, "cognitive") == _targets(record, "cognitive")
    assert _targets(record, "fan_out") == []
