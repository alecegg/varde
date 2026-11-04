from varde_code.quality_resolve import coverage, edges_for_file, prepare


def edge(caller, line, callee, kind, pass_name):
    return {
        "caller": caller,
        "site_line": line,
        "callee": callee,
        "kind": kind,
        "pass": pass_name,
    }


def test_receiver_scope_is_import_bound_and_never_bare_local():
    facts = {
        "app.py": {
            "functions": [
                {"id": "app", "name": "app", "params": 0},
                {"id": "local", "name": "send", "params": 1},
            ],
            "imports": [{"module": "service", "line": 1}],
            "call_sites": [
                {
                    "caller": "app",
                    "name": "client.send",
                    "receiver": "client",
                    "arity": 1,
                    "line": 4,
                }
            ],
        },
        "service.py": {
            "functions": [{"id": "service-send", "name": "send", "params": 1}]
        },
    }
    assert edges_for_file(prepare(list(facts), facts), "app.py") == [
        edge("app", 4, None, "opaque", "local")
    ]


def test_receiver_resolves_import_binding_and_external_import_is_external():
    facts = {
        "app.py": {
            "functions": [{"id": "app", "name": "app", "params": 0}],
            "imports": [
                {"module": "service", "alias": "client", "line": 1},
                {"module": "os.path", "line": 2},
            ],
            "call_sites": [
                {
                    "caller": "app",
                    "name": "client.send",
                    "receiver": "client",
                    "arity": 1,
                    "line": 4,
                },
                {
                    "caller": "app",
                    "name": "os.path.join",
                    "receiver": "os",
                    "arity": 2,
                    "line": 5,
                },
            ],
        },
        "service.py": {
            "functions": [{"id": "service-send", "name": "send", "params": 1}]
        },
    }
    assert edges_for_file(prepare(list(facts), facts), "app.py") == [
        edge("app", 4, "service-send", "resolved", "receiver"),
        edge("app", 5, None, "external", "local"),
    ]


def test_imported_ambiguity_and_arity_filter():
    facts = {
        "main.py": {
            "imports": [
                {"module": "one", "name": "*", "line": 1},
                {"module": "two", "name": "*", "line": 2},
            ],
            "call_sites": [
                {"caller": "main", "name": "work", "arity": 1, "line": 3},
                {"caller": "main", "name": "fit", "arity": 2, "line": 4},
                {"caller": "main", "name": "fit", "arity": 4, "line": 5},
            ],
        },
        "one.py": {
            "functions": [
                {"id": "work-one", "name": "work", "params": 1},
                {"id": "fit-one", "name": "fit", "params": 1},
            ]
        },
        "two.py": {
            "functions": [
                {"id": "work-two", "name": "work", "params": 1},
                {"id": "fit-two", "name": "fit", "params": 2},
            ]
        },
    }
    assert edges_for_file(prepare(list(facts), facts), "main.py") == [
        edge("main", 3, None, "ambiguous", "imported"),
        edge("main", 4, "fit-two", "resolved", "imported"),
        edge("main", 5, None, "opaque", "local"),
    ]


def test_namespace_pass_languages_and_python_scope_limit():
    extension = {
        "csharp": "cs",
        "java": "java",
        "kotlin": "kt",
        "scala": "scala",
        "swift": "swift",
    }
    for suffix in extension.values():
        caller = f"pkg/Main.{suffix}"
        target = f"pkg/Other.{suffix}"
        facts = {
            caller: {
                "package": "sample",
                "call_sites": [
                    {"caller": "main", "name": "work", "arity": 0, "line": 7}
                ],
            },
            target: {
                "package": "sample",
                "functions": [{"id": "work", "name": "work", "params": 0}],
            },
            f"elsewhere/Other.{suffix}": {
                "package": "different",
                "functions": [{"id": "stray", "name": "stray", "params": 0}],
            },
        }
        assert edges_for_file(prepare(list(facts), facts), caller) == [
            edge("main", 7, "work", "resolved", "namespace")
        ]

    python_facts = {
        "app/main.py": {
            "call_sites": [{"caller": "main", "name": "stray", "arity": 0, "line": 1}]
        },
        "elsewhere.py": {"functions": [{"id": "stray", "name": "stray", "params": 0}]},
    }
    assert edges_for_file(prepare(list(python_facts), python_facts), "app/main.py") == [
        edge("main", 1, None, "opaque", "local")
    ]


def test_type_candidates_separate_from_functions_and_constructor_cases():
    facts = {
        "Main.java": {
            "package": "sample",
            "functions": [{"id": "factory", "name": "Widget", "params": 0}],
            "call_sites": [
                {"caller": "factory", "name": "Widget", "arity": 2, "line": 1},
                {"caller": "factory", "name": "Plain", "arity": 0, "line": 2},
                {"caller": "factory", "name": "Multi", "arity": 0, "line": 3},
                {"caller": "factory", "name": "JavaCtor", "arity": 1, "line": 4},
            ],
        },
        "Widget.java": {
            "package": "sample",
            "types": [
                {
                    "id": "Widget-type",
                    "name": "Widget",
                    "kind": "class",
                    "path": "Widget.java",
                }
            ],
            "functions": [
                {
                    "id": "Widget-ctor",
                    "name": "constructor",
                    "owner": "Widget",
                    "params": 2,
                }
            ],
        },
        "Plain.java": {
            "package": "sample",
            "types": [{"id": "Plain-type", "name": "Plain", "kind": "class"}],
        },
        "Multi.java": {
            "package": "sample",
            "types": [{"id": "Multi-type", "name": "Multi", "kind": "class"}],
            "functions": [
                {"id": "Multi-one", "name": "init", "owner": "Multi", "params": 0},
                {"id": "Multi-two", "name": "<init>", "owner": "Multi", "params": 0},
            ],
        },
        "JavaCtor.java": {
            "package": "sample",
            "types": [{"id": "JavaCtor-type", "name": "JavaCtor", "kind": "class"}],
            "functions": [
                {
                    "id": "JavaCtor-init",
                    "name": "JavaCtor",
                    "owner": "JavaCtor",
                    "params": 1,
                }
            ],
        },
    }
    assert edges_for_file(prepare(list(facts), facts), "Main.java") == [
        edge("factory", 1, "Widget-ctor", "resolved", "type"),
        edge("factory", 2, "Plain-type", "resolved", "type"),
        edge("factory", 3, "Multi-two", "resolved", "type"),
        edge("factory", 4, "JavaCtor-init", "resolved", "type"),
    ]


def test_coverage_empty_ratio_data_and_deterministic_order():
    assert coverage([]) == {
        "total": 0,
        "resolved": 0,
        "ambiguous": 0,
        "opaque": 0,
        "external": 0,
        "resolved_ratio": 0.0,
        "unresolved_ratio": 0.0,
    }
    facts = {
        "a.py": {"call_sites": [{"caller": "a", "name": "missing", "line": 1}]},
        "b.py": {"call_sites": [{"caller": "b", "name": "unknown", "line": 2}]},
    }
    first = prepare(list(facts), facts)
    second = prepare(reversed(list(facts)), facts)
    assert (
        edges_for_file(first, "a.py")
        == edges_for_file(second, "a.py")
        == [edge("a", 1, None, "external", "local")]
    )
    assert edges_for_file(first, "missing.py") == []
    assert coverage(edges_for_file(first, "a.py")) == {
        "total": 1,
        "resolved": 0,
        "ambiguous": 0,
        "opaque": 0,
        "external": 1,
        "resolved_ratio": 0.0,
        "unresolved_ratio": 1.0,
    }
    assert edges_for_file(prepare(["orphan.py"], {}), "orphan.py") == []


def test_imports_do_not_follow_reexports_transitively():
    facts = {
        "main.py": {
            "imports": [{"module": "facade", "line": 1}],
            "call_sites": [
                {"caller": "main", "name": "leaf_work", "arity": 0, "line": 2}
            ],
        },
        "facade.py": {"imports": [{"module": "leaf", "line": 1}]},
        "leaf.py": {
            "functions": [{"id": "leaf-work", "name": "leaf_work", "params": 0}]
        },
    }
    assert edges_for_file(prepare(list(facts), facts), "main.py") == [
        edge("main", 2, None, "opaque", "local")
    ]
