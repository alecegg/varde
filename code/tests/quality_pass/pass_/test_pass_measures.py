"""Deterministic graph measures: bounded traversal and trivial-hop handling."""

from __future__ import annotations

from varde_code.quality_pass.pass_.measures import compute_measures, tree_size

FACTS = [
    {"id": "m.py::a#1", "module": "m", "exempt_role": None},
    {"id": "m.py::b#1", "module": "m", "exempt_role": "accessor"},
    {"id": "m.py::c#1", "module": "m", "exempt_role": None},
    {"id": "m.py::d#1", "module": "m", "exempt_role": None},
    {"id": "n.py::e#1", "module": "n", "exempt_role": None},
]
EDGES = [
    {"caller": "m.py::a#1", "callee": "m.py::b#1", "kind": "resolved"},
    {"caller": "m.py::b#1", "callee": "m.py::c#1", "kind": "resolved"},
    {"caller": "m.py::c#1", "callee": "m.py::d#1", "kind": "resolved"},
    {"caller": "m.py::a#1", "callee": "n.py::e#1", "kind": "resolved"},
]


def test_tree_size_counts_nontrivial_hops_and_skips_cross_module_edges():
    assert tree_size(EDGES, "m.py::a#1", 6, 1000, facts=FACTS) == 2
    assert tree_size(EDGES, "m.py::a#1", 1, 1000, facts=FACTS) == 1
    assert (
        tree_size(EDGES, "m.py::a#1", 6, 1000, facts=FACTS, trivial_ids={"m.py::c#1"})
        == 1
    )


def test_tree_size_stops_at_the_deterministic_expansion_cap():
    assert tree_size(EDGES, "m.py::a#1", 6, 0, facts=FACTS) == 0
    assert tree_size([], "m.py::a#1", 6, 1000, facts=FACTS) == 0


def test_compute_measures_can_be_limited_to_the_needed_modules():
    facts = {
        "a/x.py": {"language": "python", "functions": [], "unmeasured_regions": []},
        "b/y.py": {"language": "python", "functions": [], "unmeasured_regions": []},
    }
    edges = {"a/x.py": [], "b/y.py": []}
    modules = {"a/x.py": "a", "b/y.py": "b"}

    assert set(compute_measures(facts, edges, modules, only_modules={"b"})) == {
        "b/y.py"
    }
    assert set(compute_measures(facts, edges, modules)) == {"a/x.py", "b/y.py"}
