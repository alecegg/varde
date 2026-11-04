from varde_code.quality_pass.facts import extract_facts


def test_facts_record_declared_types():
    samples = {
        "python": "class A: pass",
        "java": "class A {} interface I {} enum E { X }",
        "csharp": "class A {} interface I {} enum E { X }",
        "typescript": "class A {} interface I {} type E = string",
        "javascript": "class A {}",
        "cpp": "class A {}; struct B {}; enum E { X };",
        "rust": "struct A; enum E { X } trait T {}",
    }
    for language, source in samples.items():
        types = extract_facts(source, language, "x")["types"]
        assert types, language
        assert all(
            {"id", "name", "kind", "line", "qualifier"} <= item.keys() for item in types
        )


def test_type_names_kinds_qualifiers_and_unique_ids():
    cases = (
        (
            "java",
            "package p.q; class A {} interface I {} enum E {}",
            {"A": ("class", "p.q"), "I": ("interface", "p.q"), "E": ("enum", "p.q")},
        ),
        (
            "go",
            "package main\ntype S struct{}\ntype I interface{}\ntype D = S",
            {
                "S": ("struct", "main"),
                "I": ("interface", "main"),
                "D": ("type", "main"),
            },
        ),
        (
            "rust",
            "mod a { struct S; trait T {} }",
            {"S": ("struct", "a"), "T": ("trait", "a")},
        ),
        (
            "typescript",
            "abstract class A {} interface I {} type E = string",
            {"A": ("class", ""), "I": ("interface", ""), "E": ("type", "")},
        ),
        ("java", "@interface Mark {}", {"Mark": ("interface", "")}),
    )
    for language, source, expected in cases:
        types = extract_facts(source, language, "x")["types"]
        actual = {item["name"]: (item["kind"], item["qualifier"]) for item in types}
        assert actual == expected, (language, actual)
        assert len({item["id"] for item in types}) == len(types)


def test_cpp_forward_declarations_are_omitted_and_scopes_are_qualified():
    facts = extract_facts(
        (
            "class Fwd; struct S; struct S* p; namespace a { "
            "struct Foo { int g(){} }; } namespace b { "
            "struct Foo { int g(){} }; }"
        ),
        "cpp",
        "x.cpp",
    )
    assert [(item["name"], item["qualifier"]) for item in facts["types"]] == [
        ("Foo", "a"),
        ("Foo", "b"),
    ]
    methods = {
        (item["owner"], item["qualifier"])
        for item in facts["functions"]
        if item["name"] == "g"
    }
    assert methods == {("Foo", "a.Foo"), ("Foo", "b.Foo")}


def test_cpp_new_expression_and_direct_initialization_are_creation_sites():
    facts = extract_facts(
        "class B { public: B(int){} }; void f() { B* b = new B(1); B c(2); }",
        "cpp",
        "x.cpp",
    )
    assert [
        (call["name"], call["arity"], call["kind"]) for call in facts["call_sites"]
    ] == [("B", 1, "new")]
