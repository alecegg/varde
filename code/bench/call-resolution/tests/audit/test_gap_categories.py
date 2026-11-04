"""Behavior tests for gap-category classification and ranking."""

import pytest
from audit.gap_categories import (
    CATEGORIES,
    EXISTING,
    NEW,
    classify_miss,
    gain_by_category,
    is_missed,
    rank_categories,
    resolve_module,
    target_owner,
)


def _record(call_class="member", truth="a.py::f@1", status="opaque", edge=None):
    return {
        "call_class": call_class,
        "ground_truth": truth,
        "measured_status": status,
        "measured_edge": edge,
    }


@pytest.mark.parametrize(
    ("record", "missed"),
    [
        (_record(), True),
        (_record(status="resolved", edge="a.py::f@1"), False),
        (_record(status="resolved", edge="b.py::g@2"), True),
        (_record(truth="external"), False),
        (_record(truth="unknown"), False),
        (_record(call_class="dynamic"), False),
        (_record(call_class="higher_order"), False),
    ],
)
def test_is_missed(record, missed):
    assert is_missed(record) is missed


@pytest.mark.parametrize(
    ("evidence", "category"),
    [
        ({"status": "resolved"}, "wrong-target"),
        ({"status": "unresolved", "caller_present": False}, "module-level-call"),
        ({"status": "unresolved", "call_site_found": False}, "site-not-extracted"),
        ({"status": "ambiguous", "target_candidates": 3}, "overload"),
        ({"status": "ambiguous", "target_candidates": 1}, "owner"),
        (
            {"status": "opaque", "imported": True, "hook_missing": True},
            "unresolved-import",
        ),
        ({"status": "opaque", "target_anonymous": True}, "anonymous-target"),
        ({"status": "opaque", "target_nested": True}, "closure"),
        (
            {
                "status": "opaque",
                "receiver": "self",
                "target_owner": "Base",
                "caller_owner": "Child",
            },
            "inheritance",
        ),
        (
            {"status": "opaque", "receiver": "this", "same_file": False},
            "inheritance",
        ),
        (
            {"status": "opaque", "imported": True, "static_import": True},
            "static-import",
        ),
        ({"status": "opaque", "reexport": "star"}, "export-star"),
        ({"status": "opaque", "reexport": "all"}, "__all__"),
        ({"status": "opaque", "reexport": "named"}, "package"),
        (
            {"status": "external", "imported": True, "import_module_resolved": False},
            "unresolved-import",
        ),
        (
            {"status": "opaque", "language": "csharp", "same_file": False},
            "namespace",
        ),
        (
            {"status": "opaque", "arity": 1, "target_param_counts": [2, 3]},
            "arity",
        ),
        ({"status": "opaque", "receiver": "policy"}, "variable-receiver"),
        ({"status": "opaque", "dotted": True}, "variable-receiver"),
        (
            {"status": "opaque", "receiver": "Helper", "target_owner": "ns.Helper"},
            "owner",
        ),
        ({"status": "opaque", "same_file": True}, "other"),
    ],
)
def test_classify_miss(evidence, category):
    assert classify_miss(evidence) == category


def test_every_category_has_a_valid_tag():
    assert {tag for tag, _ in CATEGORIES.values()} <= {EXISTING, NEW}
    for name in ("inheritance", "static-import", "export-star"):
        assert CATEGORIES[name][0] == NEW


def test_every_classification_result_is_a_declared_category():
    results = {
        classify_miss(e)
        for e in (
            {"status": "resolved"},
            {"status": "opaque"},
            {"status": "opaque", "reexport": "star"},
        )
    }
    assert results <= set(CATEGORIES)


def test_target_owner():
    assert target_owner("a.py::Cls.method@10") == "Cls"
    assert target_owner("a.py::func@10") == ""
    assert target_owner("A.cs::N.T.M(System.Int32)") == "N.T"


def test_gain_by_category_uses_class_balanced_weights():
    all_records = [_record(call_class="same_file")] * 4 + [
        _record(call_class="member")
    ] * 2
    missed = [
        (all_records[0], "arity"),
        (all_records[4], "arity"),
        (all_records[5], "other"),
    ]
    gains = gain_by_category(all_records, missed)
    assert gains["arity"] == pytest.approx(1 / (4 * 2) + 1 / (2 * 2))
    assert gains["other"] == pytest.approx(1 / (2 * 2))


def test_rank_orders_by_gain_then_count():
    rows = rank_categories({"a": 5, "b": 2, "c": 2}, {"a": 0.1, "b": 0.3, "c": 0.3})
    assert [name for name, _, _ in rows] == ["b", "c", "a"]


def test_resolve_module_python_and_typescript():
    files = {"pkg/__init__.py", "pkg/mod.py", "src/a.ts", "src/b/index.ts", "src/c.js"}
    assert resolve_module("python", "pkg/x.py", ".mod", files) == "pkg/mod.py"
    assert resolve_module("python", "other/x.py", "pkg", files) == "pkg/__init__.py"
    assert resolve_module("python", "x.py", "missing", files) is None
    assert resolve_module("typescript", "src/z.ts", "./a", files) == "src/a.ts"
    assert resolve_module("typescript", "src/z.ts", "./b", files) == "src/b/index.ts"
    assert resolve_module("typescript", "src/z.ts", "./c.js", files) == "src/c.js"
    assert resolve_module("typescript", "src/z.ts", "lodash", files) is None
