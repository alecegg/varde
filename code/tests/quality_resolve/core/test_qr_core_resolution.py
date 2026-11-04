from varde_code.quality_resolve import coverage, edges_for_file, prepare


def test_local_edges_keep_caller_and_report_ambiguity():
    facts = {
        "a.py": {
            "functions": [
                {"id": "a.py::caller#1", "name": "caller", "params": 0},
                {"id": "a.py::work#1", "name": "work", "params": 1},
                {"id": "a.py::work#2", "name": "work", "params": 1},
            ],
            "call_sites": [
                {"caller": "a.py::caller#1", "name": "work", "arity": 1, "line": 5},
                {"caller": "a.py::caller#1", "name": "missing", "arity": 0, "line": 6},
                {"caller": "a.py::caller#1", "name": "print", "arity": 1, "line": 7},
                {
                    "caller": "a.py::caller#1",
                    "name": "dynamic.send",
                    "receiver": "dynamic",
                    "arity": 1,
                    "line": 8,
                },
            ],
        }
    }
    edges = edges_for_file(prepare(list(facts), facts), "a.py")
    assert edges == [
        {
            "caller": "a.py::caller#1",
            "site_line": 5,
            "callee": None,
            "kind": "ambiguous",
            "pass": "local",
        },
        {
            "caller": "a.py::caller#1",
            "site_line": 6,
            "callee": None,
            "kind": "external",
            "pass": "local",
        },
        {
            "caller": "a.py::caller#1",
            "site_line": 7,
            "callee": None,
            "kind": "external",
            "pass": "local",
        },
        {
            "caller": "a.py::caller#1",
            "site_line": 8,
            "callee": None,
            "kind": "opaque",
            "pass": "local",
        },
    ]
    assert coverage(edges) == {
        "total": 4,
        "resolved": 0,
        "ambiguous": 1,
        "opaque": 1,
        "external": 2,
        "resolved_ratio": 0.0,
        "unresolved_ratio": 1.0,
    }


def test_imported_scope_is_limited_to_resolved_import_candidates():
    facts = {
        "src/main.py": {
            "functions": [{"id": "main", "name": "main", "params": 0}],
            "imports": [{"module": "lib", "name": "helper", "line": 1}],
            "call_sites": [{"caller": "main", "name": "helper", "arity": 0, "line": 3}],
        },
        "src/lib.py": {"functions": [{"id": "helper", "name": "helper", "params": 0}]},
        "src/other.py": {
            "functions": [{"id": "helper2", "name": "helper", "params": 0}]
        },
    }
    edges = edges_for_file(prepare(list(facts), facts), "src/main.py")
    assert edges[0]["callee"] == "helper"
    assert edges[0]["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.
    assert edges[0]["kind"] == "resolved"


def test_type_call_targets_initializer():
    facts = {
        "src/Main.cs": {
            "language": "csharp",
            "package": "widgets",
            "functions": [{"id": "make", "name": "make", "params": 0}],
            "types": [
                {
                    "id": "Widget",
                    "name": "Widget",
                    "kind": "class",
                    "path": "src/Widget.cs",
                }
            ],
            "call_sites": [{"caller": "make", "name": "Widget", "arity": 0, "line": 2}],
        },
        "src/Widget.cs": {
            "language": "csharp",
            "package": "widgets",
            "functions": [
                {
                    "id": "Widget::.ctor",
                    "name": "constructor",
                    "owner": "Widget",
                    "params": 0,
                }
            ],
        },
    }
    edge = edges_for_file(prepare(list(facts), facts), "src/Main.cs")[0]
    assert edge == {
        "caller": "make",
        "site_line": 2,
        "callee": "Widget::.ctor",
        "kind": "resolved",
        "pass": "type",
    }
