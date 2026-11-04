from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.extract import import_specs
from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.java import import_bindings


def test_package_wildcard_import_exposes_types_not_bare_methods():
    facts = {
        "src/main/java/p/Main.java": {
            "imports": [{"line": 1, "module": "q", "text": "import q.*;"}],
            "call_sites": [
                {"caller": "main", "name": "work", "arity": 0},
                {"caller": "main", "name": "B", "kind": "new", "arity": 0},
            ],
        },
        "src/main/java/q/B.java": {
            "types": [{"id": "type-b", "name": "B", "kind": "class"}],
            "functions": [
                {"id": "b-constructor", "name": "B", "owner": "B", "params": 0}
            ],
        },
        "src/main/java/q/W.java": {
            "functions": [{"id": "q-work", "name": "work", "owner": "W", "params": 0}]
        },
    }

    edges = edges_for_file(prepare(facts, facts), "src/main/java/p/Main.java")
    assert edges[0]["kind"] == "opaque"
    assert edges[1]["callee"] == "b-constructor"
    assert edges[1]["kind"] == "resolved"


def test_static_import_maps_to_the_declaring_type_file():
    facts = {
        "src/main/java/p/Main.java": {
            "imports": [
                {"line": 1, "module": "q/C/work", "text": "import static q.C.work;"}
            ],
            "call_sites": [{"caller": "main", "name": "work", "arity": 1}],
        },
        "src/main/java/q/C.java": {
            "functions": [
                {"id": "c-work-one", "name": "work", "params": 1},
                {"id": "c-work-two", "name": "work", "params": 2},
            ]
        },
        "src/main/java/q/D.java": {
            "functions": [{"id": "d-work", "name": "work", "params": 2}]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/main/java/p/Main.java")[0]
    assert edge["callee"] == "c-work-one"
    assert edge["kind"] == "resolved"
    assert edge["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.


def test_constructor_call_uses_matching_arity_in_an_imported_type_file():
    facts = {
        "src/main/java/p/Main.java": {
            "imports": [{"line": 1, "module": "q/A", "text": "import q.A;"}],
            "call_sites": [{"caller": "main", "name": "A", "arity": 1}],
        },
        "src/main/java/q/A.java": {
            "functions": [
                {"id": "a-one", "name": "A", "owner": "A", "params": 1},
                {"id": "a-two", "name": "A", "owner": "A", "params": 2},
            ]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/main/java/p/Main.java")[0]
    assert edge["callee"] == "a-one"
    assert edge["kind"] == "resolved"
    assert edge["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.


def test_class_import_binds_constructor_name_and_receiver():
    facts = {
        "src/main/java/p/Main.java": {
            "imports": [{"line": 1, "module": "q/B", "text": "import q.B;"}],
            "call_sites": [
                {"caller": "main", "name": "B", "arity": 0},
                {
                    "caller": "main",
                    "name": "work",
                    "receiver_text": "B",
                    "arity": 0,
                },
            ],
        },
        "src/main/java/q/B.java": {
            "types": [{"id": "type-b", "name": "B", "kind": "class"}],
            "functions": [
                {"id": "b-constructor", "name": "B", "owner": "B", "params": 0},
                {"id": "b-work", "name": "work", "owner": "B", "params": 0},
            ],
        },
    }

    edges = edges_for_file(prepare(facts, facts), "src/main/java/p/Main.java")
    assert [(edge["pass"], edge["callee"]) for edge in edges] == [
        ("imported", "b-constructor"),
        ("receiver", "b-work"),
    ]


def test_java_import_binding_shapes():
    paths = ("src/q/B.java", "src/q/C.java", "src/q/sub/D.java")
    context = {path: {} for path in paths}
    assert import_bindings(
        {"module": "q/B", "text": "import q.B;"}, "src/Main.java", paths, context
    ) == [{"path": "src/q/B.java", "names": ["B"], "binding": "B", "owner": "B"}]
    assert import_bindings(
        {"module": "q/C/f", "text": "import static q.C.f;"},
        "src/Main.java",
        paths,
        context,
    ) == [{"path": "src/q/C.java", "names": ["f"], "binding": None}]
    assert import_bindings(
        {"module": "q", "text": "import q.*;"}, "src/Main.java", paths, context
    ) == [
        {"path": "src/q/B.java", "names": [], "binding": "B", "owner": "B"},
        {"path": "src/q/C.java", "names": [], "binding": "C", "owner": "C"},
    ]


def test_java_static_wildcard_import_binds_every_name_in_the_declaring_type():
    paths = ("src/q/C.java", "src/q/D.java")
    assert import_bindings(
        {"module": "q/C", "text": "import static q.C.*;"},
        "src/Main.java",
        paths,
        {
            "src/q/C.java": {
                "functions": [
                    {"name": "factory", "static": True},
                    {"name": "instance", "static": False},
                ]
            }
        },
    ) == [{"path": "src/q/C.java", "names": ["factory"], "binding": None}]


def test_java_import_with_unrecognized_or_mismatched_text_binds_nothing():
    paths = ("src/q/B.java",)
    assert (
        import_bindings(
            {"module": "q/B", "text": "import q.B as Alias;"},
            "src/Main.java",
            paths,
            {},
        )
        == []
    )
    assert (
        import_bindings(
            {"module": "q/B", "text": "import q.C;"}, "src/Main.java", paths, {}
        )
        == []
    )


def test_extracted_new_expression_resolves_imported_constructor_by_arity():
    importer = "src/Main.java"
    target = "src/q/B.java"
    source = "import q.B; class Main { void run(){ new B(1); } }"
    facts = {
        importer: extract_facts(source, "java", importer),
        target: extract_facts(
            "package q; class B { B(){} B(int value){} }", "java", target
        ),
    }
    facts[importer]["imports"] = import_specs("Main.java", source, "java")

    sites = facts[importer]["call_sites"]
    assert [(site["name"], site["kind"], site["arity"]) for site in sites] == [
        ("B", "new", 1)
    ]
    edge = edges_for_file(prepare(facts, facts), importer)[0]
    assert edge["kind"] == "resolved"
    assert edge["callee"] == facts[target]["functions"][1]["id"]
