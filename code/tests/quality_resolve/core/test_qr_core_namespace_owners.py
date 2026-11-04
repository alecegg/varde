import pytest
from varde_code.quality_resolve import digest_for_file, edges_for_file, prepare


def test_namespace_unqualified_methods_require_an_enclosing_owner():
    facts = {
        "A.java": {
            "package": "sample",
            "functions": [{"id": "inside", "name": "inside", "owner": "A"}],
            "call_sites": [{"caller": "inside", "name": "work", "arity": 0}],
        },
        "B.java": {
            "package": "sample",
            "functions": [{"id": "b-work", "name": "work", "owner": "B"}],
        },
    }
    assert edges_for_file(prepare(facts, facts), "A.java")[0]["kind"] == "opaque"


def test_partial_type_method_and_enclosing_type_method_resolve():
    partial = {
        "A1.cs": {
            "namespace": "Sample",
            "functions": [{"id": "inside", "name": "inside", "owner": "A"}],
            "call_sites": [{"caller": "inside", "name": "work", "arity": 0}],
        },
        "A2.cs": {
            "namespace": "Sample",
            "functions": [{"id": "partial-work", "name": "work", "owner": "A"}],
        },
    }
    assert (
        edges_for_file(prepare(partial, partial), "A1.cs")[0]["callee"]
        == "partial-work"
    )

    nested = {
        "A.java": {
            "package": "sample",
            "types": [
                {"id": "a-type", "name": "A", "qualifier": "A"},
                {
                    "id": "inner-type",
                    "name": "Inner",
                    "qualifier": "A.Inner",
                },
            ],
            "functions": [
                {
                    "id": "inside",
                    "name": "inside",
                    "owner": "Inner",
                    "qualifier": "A.Inner",
                }
            ],
            "call_sites": [{"caller": "inside", "name": "work", "arity": 0}],
        },
        "Outer.java": {
            "package": "sample",
            "functions": [{"id": "outer-work", "name": "work", "owner": "A"}],
        },
    }
    assert (
        edges_for_file(prepare(nested, nested), "A.java")[0]["callee"] == "outer-work"
    )


def test_top_level_and_namespace_type_lookup_remain_available():
    facts = {
        "A.kt": {
            "package": "sample",
            "call_sites": [
                {"caller": "main", "name": "work", "arity": 0},
                {"caller": "main", "name": "B", "arity": 0, "kind": "new"},
                {"caller": "main", "name": "work", "arity": 0, "receiver_text": "B"},
            ],
        },
        "B.kt": {
            "package": "sample",
            "types": [{"id": "b-type", "name": "B", "kind": "class"}],
            "functions": [
                {"id": "top-work", "name": "work", "params": 0},
                {"id": "b-work", "name": "work", "owner": "B", "params": 0},
            ],
        },
    }
    edges = edges_for_file(prepare(facts, facts), "A.kt")
    assert edges[0]["callee"] == "top-work"
    assert edges[1]["kind"] == "resolved"
    assert edges[2]["callee"] == "b-work"


def test_namespace_method_digest_tracks_same_owner_changes_only_for_dependents():
    before = {
        "A.java": {
            "package": "sample",
            "functions": [{"id": "inside", "name": "inside", "owner": "A"}],
            "call_sites": [{"caller": "inside", "name": "work", "arity": 0}],
        },
        "A2.java": {
            "package": "sample",
            "functions": [{"id": "work", "name": "work", "owner": "A"}],
        },
        "C.java": {"package": "sample"},
    }
    after = {**before, "A2.java": {**before["A2.java"], "functions": []}}
    first, second = prepare(before, before), prepare(after, after)
    assert digest_for_file(first, "A.java") != digest_for_file(second, "A.java")
    assert digest_for_file(first, "C.java") == digest_for_file(second, "C.java")


@pytest.mark.parametrize(
    "path,owner,caller_owner",
    [
        ("A.cs", "B", "A"),
        ("A.java", "B", "A"),
        ("A.kt", "B", "A"),
        ("A.scala", "B", "A"),
        ("A.swift", "B", "A"),
    ],
)
def test_local_unqualified_call_rejects_unrelated_owner(path, owner, caller_owner):
    facts = {
        path: {
            "functions": [
                {"id": "caller", "name": "run", "owner": caller_owner},
                {"id": "other", "name": "work", "owner": owner},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["kind"] == "opaque"


@pytest.mark.parametrize(
    "path,owner",
    [("A.cs", "A"), ("A.java", "A"), ("A.kt", "A"), ("A.scala", "A"), ("A.swift", "A")],
)
def test_local_unqualified_call_accepts_same_owner(path, owner):
    facts = {
        path: {
            "functions": [
                {"id": "caller", "name": "run", "owner": owner},
                {"id": "method", "name": "work", "owner": owner},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["callee"] == "method"


def test_receiver_type_removal_changes_dependent_digest_and_resolution():
    before = {
        "A.java": {
            "package": "sample",
            "types": [{"id": "a-type", "name": "A", "kind": "class"}],
            "functions": [{"id": "call", "name": "call", "owner": "A"}],
            "call_sites": [
                {"caller": "call", "name": "work", "receiver_text": "B", "arity": 0}
            ],
        },
        "B.java": {
            "package": "sample",
            "types": [{"id": "b-type", "name": "B", "kind": "class"}],
            "functions": [{"id": "b-work", "name": "work", "owner": "B", "params": 0}],
        },
    }
    after = {
        **before,
        "B.java": {"package": "sample", "functions": before["B.java"]["functions"]},
    }
    first, second = prepare(before, before), prepare(after, after)
    assert edges_for_file(first, "A.java")[0]["callee"] == "b-work"
    assert edges_for_file(second, "A.java")[0]["kind"] == "opaque"
    assert digest_for_file(first, "A.java") != digest_for_file(second, "A.java")


@pytest.mark.parametrize("path", ["A.java", "A.cs"])
def test_outer_bare_call_does_not_resolve_nested_method(path):
    facts = {
        path: {
            "types": [
                {"id": "outer", "name": "A", "qualifier": "A"},
                {"id": "nested", "name": "N", "qualifier": "A.N"},
            ],
            "functions": [
                {"id": "outer-call", "name": "run", "owner": "A"},
                {"id": "nested-work", "name": "work", "owner": "N", "qualifier": "A.N"},
            ],
            "call_sites": [{"caller": "outer-call", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["kind"] == "opaque"


@pytest.mark.parametrize("path", ["A.java", "A.cs"])
def test_nested_bare_call_can_resolve_enclosing_method(path):
    facts = {
        path: {
            "types": [
                {"id": "outer", "name": "A", "qualifier": "A"},
                {"id": "nested", "name": "N", "qualifier": "A.N"},
            ],
            "functions": [
                {"id": "nested-call", "name": "run", "owner": "N", "qualifier": "A.N"},
                {"id": "outer-work", "name": "work", "owner": "A"},
            ],
            "call_sites": [{"caller": "nested-call", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["callee"] == "outer-work"
