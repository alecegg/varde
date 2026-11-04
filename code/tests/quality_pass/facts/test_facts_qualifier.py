from varde_code.quality_pass.facts import extract_facts


def test_function_records_have_qualifier():
    facts = extract_facts("class A { void f() {} }", "java")
    record = next(item for item in facts["functions"] if item["name"] == "f")
    assert record["qualifier"] == "A"


def test_cpp_out_of_line_definition_gets_written_scope_and_owner():
    facts = extract_facts(
        "namespace ns { class Foo { int g(); }; } int ns::Foo::g() { return 1; }",
        "cpp",
        "x.cpp",
    )
    record = next(item for item in facts["functions"] if item["name"] == "g")
    assert record["owner"] == "Foo"
    assert record["qualifier"] == "ns.Foo"
