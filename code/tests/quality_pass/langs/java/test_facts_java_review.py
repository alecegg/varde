from varde_code.quality_pass.facts import extract_facts


def test_java_compact_record_constructor_keeps_metrics_and_diagnostics():
    facts = extract_facts(
        "record P(int x) { P { if (x < 0) throw new IllegalArgumentException(); } }",
        "java",
        "P.java",
    )
    constructor = facts["functions"][0]

    assert constructor["name"] == "P"
    assert constructor["owner"] == "P"
    assert constructor["tokens"] == 15
    assert constructor["params"] == 1
    assert constructor["cognitive"] == 1
    assert constructor["exempt_role"] is None
    assert facts["diagnostics"] == []


def test_java_interface_visibility_setters_and_signature_checked_overrides():
    source = """interface I { default int G() { return 1; } }
class Base { int value() { return 1; } }
class Child extends Base implements I {
    int field;
    public void setField(int value) { this.field = value; }
    int value(int value) { return value; }
    public int G() { return 1; }
}
"""
    facts = extract_facts(source, "java", "I.java")
    items = {(item["owner"], item["name"]): item for item in facts["functions"]}

    assert items[("I", "G")]["file_private"] is False
    assert items[("Child", "G")]["file_private"] is False
    assert items[("Child", "G")]["exempt_role"] == "override"
    assert items[("Child", "setField")]["params"] == 1
    assert items[("Child", "setField")]["exempt_role"] == "accessor"
    assert items[("Child", "value")]["params"] == 1
    assert items[("Child", "value")]["exempt_role"] is None
    assert items[("Child", "value")]["line"] == 6
    assert items[("Child", "value")]["end_line"] == 6
    assert [item["id"] for item in facts["functions"] if item["name"] == "value"] == [
        "I.java::Base.value#1",
        "I.java::Child.value#1",
    ]


def test_java_wildcard_and_argument_annotations_register_handlers_and_generated():
    source = """import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import javax.annotation.processing.Generated;
class A {
    @Test(expected = Exception.class) void test() {}
    @ParameterizedTest void parameterized() {}
    @RepeatedTest(2) void repeated() {}
    @Generated("tool") int generated() { return 1; }
}
"""
    facts = extract_facts(source, "java", "A.java")
    by_name = {item["name"]: item for item in facts["functions"]}

    assert by_name["test"]["exempt_role"] == "handler"
    assert by_name["parameterized"]["exempt_role"] == "handler"
    assert by_name["repeated"]["exempt_role"] == "handler"
    assert by_name["generated"]["tokens"] == 14
    assert facts["markers"] == ["generated"]
    assert facts["diagnostics"] == []


def test_java_annotation_suffix_collision_does_not_register_handler():
    facts = extract_facts(
        "import org.junit.jupiter.api.*; class A { @Each void f() {} }", "java"
    )

    assert facts["functions"][0]["exempt_role"] is None


def test_java_lambda_control_flow_rolls_into_enclosing_function_metrics():
    facts = extract_facts(
        "class C { int f(java.util.List<Integer> xs) { return "
        "xs.stream().map(x -> { if (x > 0) return x; return 0; })"
        ".findFirst().orElse(0); } }",
        "java",
        "C.java",
    )
    function = facts["functions"][0]

    assert function["name"] == "f"
    assert function["tokens"] == 51
    assert function["params"] == 1
    assert function["cognitive"] == 2
    assert (function["line"], function["end_line"]) == (1, 1)
    assert all(call["caller"] == function["id"] for call in facts["call_sites"])
