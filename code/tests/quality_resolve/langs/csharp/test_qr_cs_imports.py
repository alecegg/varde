from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.extract import import_specs
from varde_code.quality_resolve import edges_for_file, prepare
from varde_code.quality_resolve.langs.csharp import import_bindings


def test_using_namespace_exposes_types_not_bare_methods():
    facts = {
        "src/Main.cs": {
            "imports": [{"line": 1, "module": "Q/Util", "text": "using Q.Util;"}],
            "call_sites": [
                {"caller": "main", "name": "run", "arity": 0},
                {"caller": "main", "name": "B", "kind": "new", "arity": 0},
            ],
        },
        "src/Q/Util/B.cs": {
            "types": [{"id": "type-b", "name": "B", "kind": "class"}],
            "functions": [{"id": "b-ctor", "name": "B", "owner": "B", "params": 0}],
        },
        "src/Q/Util/Runner.cs": {
            "functions": [
                {"id": "q-run", "name": "run", "owner": "Runner", "params": 0}
            ]
        },
    }

    edges = edges_for_file(prepare(facts, facts), "src/Main.cs")
    assert edges[0]["kind"] == "opaque"
    assert edges[1]["callee"] == "b-ctor"
    assert edges[1]["kind"] == "resolved"


def test_static_using_maps_partial_type_declarations_by_owner():
    facts = {
        "src/Main.cs": {
            "imports": [
                {
                    "line": 1,
                    "module": "Q/Util/Helper",
                    "text": "using static Q.Util.Helper;",
                }
            ],
            "call_sites": [{"caller": "main", "name": "run", "arity": 0}],
        },
        "src/Q/Util/Helper.Part1.cs": {
            "functions": [
                {
                    "id": "helper-run",
                    "name": "run",
                    "owner": "Helper",
                    "params": 0,
                    "static": True,
                }
            ]
        },
        "src/Q/Util/Helper.Part2.cs": {
            "functions": [
                {
                    "id": "helper-other",
                    "name": "other",
                    "owner": "Helper",
                    "params": 0,
                }
            ]
        },
        "src/Q/Util/Other.cs": {
            "functions": [
                {
                    "id": "other-run",
                    "name": "run",
                    "owner": "Other",
                    "params": 0,
                }
            ]
        },
    }

    edge = edges_for_file(prepare(facts, facts), "src/Main.cs")[0]
    assert edge["callee"] == "helper-run"
    assert edge["kind"] == "resolved"
    assert edge["pass"] == "imported"  # noqa: S105 - Resolver pass labels are fixture values, not credentials.


def test_using_bindings_cover_namespace_and_static_type_files():
    paths = (
        "src/Main.cs",
        "src/Q/Util/Runner.cs",
        "src/Q/Util/Helper.Part1.cs",
    )
    context = {
        "src/Q/Util/Helper.Part1.cs": {
            "functions": [{"owner": "Helper", "name": "run"}]
        }
    }
    assert import_bindings(
        {"module": "Q/Util", "text": "using Q.Util;"}, "src/Main.cs", paths, context
    ) == [
        {
            "path": "src/Q/Util/Helper.Part1.cs",
            "names": [],
            "binding": "Helper",
            "owner": "Helper",
        },
        {
            "path": "src/Q/Util/Runner.cs",
            "names": [],
            "binding": "Runner",
            "owner": "Runner",
        },
    ]
    assert (
        import_bindings(
            {"module": "Q/Util/Helper", "text": "using static Q.Util.Helper;"},
            "src/Main.cs",
            paths,
            {
                "src/Q/Util/Helper.Part1.cs": {
                    "functions": [
                        {"name": "run", "static": True},
                        {"name": "instance", "static": False},
                    ]
                }
            },
        )
        == []
    )


def test_using_namespace_matches_compressed_project_namespace_path():
    paths = (
        "src/Main.cs",
        "src/Umbraco.Core/Services/LoginService.cs",
        "src/Elsewhere/Services/Other.cs",
    )

    assert import_bindings(
        {
            "module": "Umbraco/Cms/Core/Services",
            "text": "using Umbraco.Cms.Core.Services;",
        },
        "src/Main.cs",
        paths,
        {},
    ) == [
        {
            "path": "src/Umbraco.Core/Services/LoginService.cs",
            "names": [],
            "binding": "LoginService",
            "owner": "LoginService",
        }
    ]


def test_using_alias_binds_only_the_alias_receiver():
    paths = ("src/Main.cs", "src/Q/Util/Helper.cs")
    assert import_bindings(
        {"module": "Q/Util/Helper", "text": "using H = Q.Util.Helper;"},
        "src/Main.cs",
        paths,
        {},
    ) == [
        {
            "path": "src/Q/Util/Helper.cs",
            "names": [],
            "binding": "H",
            "aliases": {"H": "Helper"},
            "owner": "Helper",
        },
    ]


def test_using_static_requires_a_type_target_and_unknown_forms_bind_nothing():
    paths = ("src/Main.cs", "src/Q/Util/Helper.cs", "src/Q/Util/Runner.cs")
    assert (
        import_bindings(
            {"module": "Q/Util", "text": "using static Q.Util;"},
            "src/Main.cs",
            paths,
            {},
        )
        == []
    )
    assert (
        import_bindings(
            {"module": "Q/Util/Helper", "text": "using Q.Util.Helper as H;"},
            "src/Main.cs",
            paths,
            {},
        )
        == []
    )


def test_extracted_new_expression_resolves_imported_constructor_by_arity():
    importer = "src/Main.cs"
    target = "src/Q/B.cs"
    source = "using Q; class Main { void Run(){ new B(1); } }"
    facts = {
        importer: extract_facts(source, "csharp", importer),
        target: extract_facts(
            "namespace Q { class B { B(){} B(int value){} } }", "csharp", target
        ),
    }
    facts[importer]["imports"] = import_specs("Main.cs", source, "csharp")

    sites = facts[importer]["call_sites"]
    assert [(site["name"], site["kind"], site["arity"]) for site in sites] == [
        ("B", "new", 1)
    ]
    edge = edges_for_file(prepare(facts, facts), importer)[0]
    assert edge["kind"] == "resolved"
    assert edge["callee"] == facts[target]["functions"][1]["id"]


def test_type_alias_resolves_extracted_constructor_site():
    importer = "src/Main.cs"
    target = "src/Q/B.cs"
    source = "using Alias = Q.B; class Main { void Run(){ new Alias(); } }"
    facts = {
        importer: extract_facts(source, "csharp", importer),
        target: extract_facts("namespace Q { class B { B(){} } }", "csharp", target),
    }
    facts[importer]["imports"] = import_specs("Main.cs", source, "csharp")

    edge = edges_for_file(prepare(facts, facts), importer)[0]
    assert edge["kind"] == "resolved"
    assert edge["callee"] == facts[target]["functions"][0]["id"]


def test_using_type_alias_resolves_static_receiver_call():
    importer = "src/Main.cs"
    target = "src/Q/B.cs"
    source = "using Alias = Q.B; class Main { void Run(){ Alias.Work(); } }"
    facts = {
        importer: extract_facts(source, "csharp", importer),
        target: extract_facts(
            "namespace Q { class B { public static void Work(){} } }", "csharp", target
        ),
    }
    facts[importer]["imports"] = import_specs("Main.cs", source, "csharp")

    edge = edges_for_file(prepare(facts, facts), importer)[0]
    assert edge["kind"] == "resolved"
    assert edge["callee"] == facts[target]["functions"][0]["id"]


def test_namespace_using_does_not_match_deeper_directory_with_same_suffix():
    paths = (
        "src/Q/W.cs",
        "src/Z/Q/Wrong.cs",
    )
    bindings = import_bindings(
        {"module": "Q", "text": "using Q;"}, "src/Main.cs", paths, {}
    )
    assert [binding["path"] for binding in bindings] == ["src/Q/W.cs"]


def test_namespace_using_ignores_unrelated_type_with_same_directory_suffix():
    paths = ("src/Q/W.cs", "src/Z/Q/Wrong.cs")
    assert import_bindings(
        {"module": "Q", "text": "using Q;"}, "src/Main.cs", paths, {}
    ) == [{"path": "src/Q/W.cs", "names": [], "binding": "W", "owner": "W"}]
