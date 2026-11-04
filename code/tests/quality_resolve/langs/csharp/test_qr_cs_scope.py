from varde_code.quality_pass.facts import extract_facts
from varde_code.quality_pass.pass_.extract import import_specs
from varde_code.quality_resolve import edges_for_file, prepare


def _facts(sources):
    facts = {
        path: extract_facts(source, "csharp", path) for path, source in sources.items()
    }
    for path, source in sources.items():
        facts[path]["imports"] = import_specs(path, source, "csharp")
    return facts


def _edges(sources, importer):
    facts = _facts(sources)
    return facts, edges_for_file(prepare(facts, facts), importer)


def test_type_in_same_directory_resolves_without_using():
    sources = {
        "src/A/Main.cs": "namespace N; class Main { void Run(){ new B(1); } }",
        "src/A/B.cs": "namespace N; class B { B(int v){} }",
    }
    facts, edges = _edges(sources, "src/A/Main.cs")
    assert edges[0]["kind"] == "resolved"
    assert edges[0]["callee"] == facts["src/A/B.cs"]["functions"][0]["id"]


def test_type_in_ancestor_directory_resolves_and_nearest_wins():
    sources = {
        "src/A/Main.cs": "namespace N.A; class Main { void Run(){ new B(); } }",
        "src/B.cs": "namespace N; class B { B(){} }",
        "src/A/Sub/B.cs": "namespace N.A.Sub; class B { B(){} }",
    }
    facts, edges = _edges(sources, "src/A/Main.cs")
    assert edges[0]["callee"] == facts["src/B.cs"]["functions"][0]["id"]

    sources["src/A/B.cs"] = "namespace N.A; class B { B(){} }"
    facts, edges = _edges(sources, "src/A/Main.cs")
    assert edges[0]["callee"] == facts["src/A/B.cs"]["functions"][0]["id"]


def test_same_directory_types_with_one_name_stay_ambiguous():
    sources = {
        "src/A/Main.cs": "class Main { void Run(){ new B(); } }",
        "src/A/B1.cs": "class B { B(){} }",
        "src/A/B2.cs": "class B { B(){} }",
    }
    _, edges = _edges(sources, "src/A/Main.cs")
    assert edges[0]["kind"] == "ambiguous"


def test_static_class_receiver_in_same_directory_resolves():
    sources = {
        "src/A/Main.cs": "class Main { void Run(){ Util.Work(1); } }",
        "src/A/Util.cs": "static class Util { public static void Work(int v){} }",
    }
    facts, edges = _edges(sources, "src/A/Main.cs")
    assert edges[0]["callee"] == facts["src/A/Util.cs"]["functions"][0]["id"]


def test_global_using_reaches_files_below_its_directory_only():
    sources = {
        "src/P/GlobalUsings.cs": "global using Q;",
        "src/P/Sub/Main.cs": "class Main { void Run(){ new B(); } }",
        "src/Q/B.cs": "namespace Q; class B { B(){} }",
        "other/Main.cs": "class Main { void Run(){ new B(); } }",
    }
    facts = _facts(sources)
    context = prepare(facts, facts)
    reached = edges_for_file(context, "src/P/Sub/Main.cs")[0]
    assert reached["callee"] == facts["src/Q/B.cs"]["functions"][0]["id"]
    assert edges_for_file(context, "other/Main.cs")[0]["kind"] != "resolved"


def test_constructor_with_omitted_optional_parameter_resolves():
    sources = {
        "src/Main.cs": "class Main { void Run(){ new B(1); } }",
        "src/B.cs": "class B { B(int a, int b = 0){} }",
    }
    facts, edges = _edges(sources, "src/Main.cs")
    assert edges[0]["callee"] == facts["src/B.cs"]["functions"][0]["id"]


def test_method_call_does_not_take_a_default_arity_match():
    sources = {
        "src/Main.cs": "class Main { void Run(){ Util.Work(1); } }",
        "src/Util.cs": (
            "static class Util { public static void Work(int a, int b = 0){} }"
        ),
    }
    _, edges = _edges(sources, "src/Main.cs")
    assert edges[0]["kind"] != "resolved"


def test_receiver_name_is_not_taken_from_an_outer_directory():
    sources = {
        "src/A/B/Main.cs": "class Main { void Run(){ SqlContext.Sql(); } }",
        "src/A/SqlContext.cs": "class SqlContext { public void Sql(){} }",
    }
    _, edges = _edges(sources, "src/A/B/Main.cs")
    assert edges[0]["kind"] != "resolved"
