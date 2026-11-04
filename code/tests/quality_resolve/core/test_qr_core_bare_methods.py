import pytest
from varde_code.quality_resolve import edges_for_file, prepare


@pytest.mark.parametrize("path", ["a.py", "a.ts", "a.rs", "a.go", "a.cpp"])
def test_bare_call_does_not_resolve_unrelated_method(path):
    facts = {
        path: {
            "functions": [
                {"id": "caller", "name": "run", "owner": "Caller"},
                {"id": "method", "name": "work", "owner": "Service", "params": 0},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["kind"] == "opaque"


@pytest.mark.parametrize("path", ["a.py", "a.ts", "a.rs", "a.go", "a.cpp"])
def test_bare_call_resolves_free_function(path):
    facts = {
        path: {
            "functions": [
                {"id": "caller", "name": "run", "owner": "Caller"},
                {"id": "helper", "name": "work", "params": 0},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["callee"] == "helper"


def test_cpp_bare_call_can_resolve_method_of_enclosing_class():
    facts = {
        "a.cpp": {
            "functions": [
                {"id": "caller", "name": "run", "owner": "Caller"},
                {"id": "method", "name": "work", "owner": "Caller", "params": 0},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), "a.cpp")[0]["callee"] == "method"


@pytest.mark.parametrize("path", ["a.py", "a.ts", "a.rs", "a.go"])
def test_bare_call_never_resolves_same_class_method(path):
    facts = {
        path: {
            "functions": [
                {"id": "caller", "name": "run", "owner": "Service"},
                {"id": "method", "name": "work", "owner": "Service", "params": 0},
            ],
            "call_sites": [{"caller": "caller", "name": "work", "arity": 0}],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["kind"] == "opaque"


def test_caller_owner_index_matches_naive_reference():
    from types import SimpleNamespace

    from varde_code.quality_resolve.core import _caller_owners, _functions_by_file

    fixtures = [
        (
            "A.java",
            {
                "functions": [
                    {"id": "a", "name": "run", "owner": "A", "qualifier": "A.Inner"}
                ]
            },
            [
                {"id": "outer", "name": "A", "qualifier": "A"},
                {"id": "inner", "name": "Inner", "qualifier": "A.Inner"},
            ],
        ),
        (
            "b.cs",
            {"functions": [{"id": "b", "name": "run", "owner": "B"}]},
            [],
        ),
    ]
    for path, facts, type_records in fixtures:
        grouped = _functions_by_file((path,), {path: facts})
        callers = {
            path: {
                record.get("id"): record
                for rows in grouped[path].values()
                for record in rows
            }
        }
        qualifiers = {
            path: {
                record["qualifier"]
                for record in type_records
                if isinstance(record.get("qualifier"), str)
            }
        }
        catalog = SimpleNamespace(
            callers_by_file=callers,
            type_qualifiers_by_file=qualifiers,
            functions=grouped,
            type_records={path: type_records},
        )
        site = {"caller": facts["functions"][0]["id"]}
        expected = set()
        for record in facts["functions"]:
            if record.get("id") != site["caller"]:
                continue
            if record.get("owner"):
                expected.add(record["owner"])
            qualifier = record.get("qualifier")
            if isinstance(qualifier, str):
                for type_record in type_records:
                    type_qualifier = type_record.get("qualifier")
                    if isinstance(type_qualifier, str) and (
                        qualifier == type_qualifier
                        or qualifier.startswith(type_qualifier + ".")
                    ):
                        expected.update(
                            __import__("re").split(r"[./:]", type_qualifier)
                        )
        assert _caller_owners(path, site, catalog) == expected


@pytest.mark.parametrize("path", ["a.ts", "a.java"])
def test_builtin_receiver_names_are_not_python_builtins(path):
    facts = {
        path: {
            "functions": [{"id": "caller", "name": "run"}],
            "call_sites": [
                {"caller": "caller", "name": "append", "receiver_text": "list"}
            ],
        }
    }
    assert edges_for_file(prepare(facts, facts), path)[0]["kind"] == "opaque"


def test_python_builtin_receiver_names_remain_external():
    facts = {
        "a.py": {
            "functions": [{"id": "caller", "name": "run"}],
            "call_sites": [
                {"caller": "caller", "name": "append", "receiver_text": "list"}
            ],
        }
    }
    assert edges_for_file(prepare(facts, facts), "a.py")[0]["kind"] == "external"
