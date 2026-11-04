import pytest
from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_resolve import edges_for_file, prepare


@pytest.mark.parametrize(
    ("language", "path", "source", "call_name", "site_kind", "receiver"),
    [
        (
            "java",
            "A.java",
            "class B { B(int x) {} } class A { void f() { new B(1); } }",
            "B",
            "new",
            None,
        ),
        (
            "csharp",
            "A.cs",
            "class B { B(int x) {} } class A { void F() { new B(1); } }",
            "B",
            "new",
            None,
        ),
        (
            "typescript",
            "A.ts",
            "class B { constructor(x: number) {} } class A { f() { new B(1); } }",
            "B",
            "new",
            None,
        ),
        (
            "cpp",
            "A.cpp",
            "class B { public: B(int x) {} }; class A { void f() { new B(1); } };",
            "B",
            "new",
            None,
        ),
        (
            "python",
            "a.py",
            "class B:\n def __init__(self, x): pass\nB(1)\n",
            "B",
            None,
            None,
        ),
        (
            "rust",
            "a.rs",
            "struct Type; impl Type { fn new() {} } fn f() { Type::new(); }",
            "Type::new",
            None,
            "Type",
        ),
    ],
)
def test_extracted_types_resolve_through_core(
    language, path, source, call_name, site_kind, receiver
):
    facts = extract_facts(source, language, path)
    assert facts["types"]
    sites = [site for site in facts["call_sites"] if site.get("name") == call_name]
    if site_kind == "new":
        sites = [site for site in sites if site.get("kind") == "new"]
    if receiver:
        sites = [site for site in sites if site.get("receiver_text") == receiver]
    assert sites, language
    edges = edges_for_file(prepare([path], {path: facts}), path)
    edge = edges[facts["call_sites"].index(sites[0])]
    assert edge["kind"] == "resolved"


def test_constructor_overload_digest_tracks_only_dependent_importers():
    def facts(params):
        return {
            "src/main.py": {
                "imports": [{"module": "widget", "name": "B", "line": 1}],
                "functions": [{"id": "main", "name": "main", "params": 0}],
                "call_sites": [{"caller": "main", "name": "B", "arity": 1}],
            },
            "src/widget.py": {
                "types": [{"id": "type-B", "name": "B", "kind": "class"}],
                "functions": [
                    {
                        "id": f"init-{count}",
                        "name": "__init__",
                        "owner": "B",
                        "params": count,
                    }
                    for count in params
                ],
            },
            "src/other.py": {
                "functions": [{"id": "other", "name": "other", "params": 0}]
            },
        }

    first_facts = facts([0])
    changed_facts = facts([0, 1])
    first = prepare(first_facts, first_facts)
    second = prepare(changed_facts, changed_facts)
    assert first.input_digests["src/main.py"] != second.input_digests["src/main.py"]
    assert first.input_digests["src/widget.py"] != second.input_digests["src/widget.py"]
    assert first.input_digests["src/other.py"] == second.input_digests["src/other.py"]
    unrelated = facts([0])
    unrelated["src/other.py"]["functions"].append(
        {"id": "changed", "name": "changed", "params": 0}
    )
    third = prepare(unrelated, unrelated)
    assert first.input_digests["src/main.py"] == third.input_digests["src/main.py"]
    assert first.input_digests["src/widget.py"] == third.input_digests["src/widget.py"]
    assert first.input_digests["src/other.py"] != third.input_digests["src/other.py"]


def test_qualified_receiver_uses_owner_and_scope_and_unqualified_stays_ambiguous():
    facts = {
        "src/main.cpp": {
            "types": [
                {"id": "ns-Foo", "name": "Foo", "kind": "class", "qualifier": "ns"},
                {
                    "id": "other-Foo",
                    "name": "Foo",
                    "kind": "class",
                    "qualifier": "other",
                },
            ],
            "functions": [
                {
                    "id": "ns-g",
                    "name": "g",
                    "owner": "Foo",
                    "qualifier": "ns.Foo",
                    "params": 0,
                },
                {
                    "id": "other-g",
                    "name": "g",
                    "owner": "Foo",
                    "qualifier": "other.Foo",
                    "params": 0,
                },
            ],
            "call_sites": [
                {"name": "g", "receiver_text": "ns.Foo", "arity": 0},
                {"name": "g", "receiver_text": "Foo", "arity": 0},
            ],
        }
    }
    edges = edges_for_file(prepare(facts, facts), "src/main.cpp")
    assert [(edge["kind"], edge["callee"]) for edge in edges] == [
        ("resolved", "ns-g"),
        ("ambiguous", None),
    ]


def test_qualified_java_creation_uses_qualifier_package():
    facts = {
        "src/Main.java": {
            "package": "app",
            "call_sites": [
                {"kind": "new", "name": "B", "receiver_text": "q", "arity": 0}
            ],
        },
        "src/p/B.java": {
            "package": "p",
            "types": [{"id": "p-B", "name": "B", "kind": "class"}],
        },
        "src/q/B.java": {
            "package": "q",
            "types": [{"id": "q-B", "name": "B", "kind": "class"}],
        },
    }
    assert edges_for_file(prepare(facts, facts), "src/Main.java")[0]["callee"] == "q-B"


def test_unresolved_type_creation_keeps_external_classification():
    facts = {"main.ts": {"call_sites": [{"kind": "new", "name": "Date", "arity": 0}]}}
    assert edges_for_file(prepare(facts, facts), "main.ts")[0]["kind"] == "external"


def test_aliased_imported_type_creation_uses_import_name():
    facts = {
        "src/main.ts": {
            "imports": [{"module": "./lib", "name": "B", "alias": "C"}],
            "call_sites": [{"kind": "new", "name": "C", "arity": 0}],
        },
        "src/lib.ts": {"types": [{"id": "type-B", "name": "B", "kind": "class"}]},
    }
    edge = edges_for_file(prepare(facts, facts), "src/main.ts")[0]
    assert edge["callee"] == "type-B"


def test_initializer_names_are_language_specific_and_arity_mismatch_is_opaque():
    facts = {
        "main.ts": {
            "types": [{"id": "type-B", "name": "B", "kind": "class"}],
            "functions": [
                {"id": "ctor", "name": "constructor", "owner": "B", "params": 1},
                {"id": "method", "name": "init", "owner": "B", "params": 1},
            ],
            "call_sites": [{"kind": "new", "name": "B", "arity": 1}],
        },
        "bad.java": {
            "types": [{"id": "type-C", "name": "C", "kind": "class"}],
            "functions": [{"id": "ctor-C", "name": "C", "owner": "C", "params": 1}],
            "call_sites": [{"kind": "new", "name": "C", "arity": 0}],
        },
    }
    assert edges_for_file(prepare(facts, facts), "main.ts")[0]["callee"] == "ctor"
    java_edge = edges_for_file(prepare(facts, facts), "bad.java")[0]
    assert java_edge["kind"] == "opaque" and java_edge["callee"] is None


def test_qualified_receiver_digest_tracks_matching_remote_methods():
    facts = {
        "m.cpp": {"call_sites": [{"name": "g", "receiver_text": "ns.Foo", "arity": 0}]},
        "n.cpp": {
            "functions": [
                {
                    "id": "g1",
                    "name": "g",
                    "owner": "Foo",
                    "qualifier": "ns.Foo",
                    "params": 0,
                }
            ]
        },
        "other.cpp": {
            "functions": [
                {
                    "id": "g2",
                    "name": "g",
                    "owner": "Foo",
                    "qualifier": "other.Foo",
                    "params": 0,
                }
            ]
        },
    }
    changed = {
        **facts,
        "n.cpp": {
            "functions": [
                {
                    "id": "g2",
                    "name": "g",
                    "owner": "Foo",
                    "qualifier": "other.Foo",
                    "params": 0,
                }
            ]
        },
    }
    before, after = prepare(facts, facts), prepare(changed, changed)
    assert edges_for_file(before, "m.cpp")[0]["callee"] == "g1"
    assert edges_for_file(after, "m.cpp")[0]["kind"] == "opaque"
    assert before.input_digests["m.cpp"] != after.input_digests["m.cpp"]
