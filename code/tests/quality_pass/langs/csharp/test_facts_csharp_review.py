from varde_code.quality_pass.facts import extract_facts


def test_csharp_expression_members_operators_destructor_and_local_function():
    facts = extract_facts(
        "class C { public int P => x; public int this[int i] => i; "
        "public static C operator +(C a,C b) => a; "
        "public static implicit operator int(C x) => 1; ~C() { } "
        "void Outer() { int Local(int x) => x; } }",
        "csharp",
        "C.cs",
    )
    by_name = {item["name"]: item for item in facts["functions"]}

    assert set(by_name) == {
        "P.get",
        "this.get",
        "operator+",
        "implicit operator int",
        "C",
        "Outer",
        "Local",
    }
    assert by_name["P.get"]["tokens"] == 6
    assert by_name["P.get"]["exempt_role"] == "accessor"
    assert by_name["this.get"]["tokens"] == 10
    assert by_name["this.get"]["params"] == 1
    assert by_name["operator+"]["tokens"] == 15
    assert by_name["operator+"]["params"] == 2
    assert by_name["implicit operator int"]["tokens"] == 12
    assert by_name["implicit operator int"]["params"] == 1
    assert by_name["Local"]["tokens"] == 9
    assert by_name["Local"]["params"] == 1
    assert all(item["line"] == item["end_line"] == 1 for item in facts["functions"])
    assert facts["diagnostics"] == []
    assert facts["diagnostics"] == []


def test_csharp_partial_base_resolution_overloads_interfaces_and_visibility():
    source = """interface I { int G(); }
class Base { public virtual int F() { return 1; } }
partial class C : Base, I {
    private int Hidden() { return 0; }
    internal int Internal() { return 0; }
    private protected int PrivateProtected() { return 0; }
    public int F(int value) { return value; }
    public int G() { return 1; }
}
partial class C { public override int F() { return 2; } }
class MissingBaseChild : MissingBase { public override int F() { return 2; } }
"""
    facts = extract_facts(source, "csharp", "C.cs")
    items = [item for item in facts["functions"] if item["owner"] == "C"]
    by_name = {(item["name"], item["params"]): item for item in items}

    assert by_name[("Hidden", 0)]["file_private"] is True
    assert by_name[("Internal", 0)]["file_private"] is False
    assert by_name[("PrivateProtected", 0)]["file_private"] is True
    assert by_name[("F", 1)]["exempt_role"] is None
    assert by_name[("F", 0)]["exempt_role"] == "override"
    assert by_name[("F", 0)]["id"] == "C.cs::C.F#2"
    assert by_name[("G", 0)]["exempt_role"] == "override"
    assert not [item for item in facts["functions"] if item["owner"] == "I"]
    unresolved = next(
        item for item in facts["functions"] if item["owner"] == "MissingBaseChild"
    )
    assert unresolved["exempt_role"] is None


def test_csharp_complex_property_accessors_are_not_exempt():
    facts = extract_facts(
        "class C { int x; public int Z { "
        "get { if (x > 0) { return x; } return 0; } "
        "set { Validate(value); x = value; } } }",
        "csharp",
    )
    accessors = {item["name"]: item for item in facts["functions"]}

    assert accessors["Z.get"]["tokens"] == 17
    assert accessors["Z.get"]["exempt_role"] is None
    assert accessors["Z.set"]["tokens"] == 12
    assert accessors["Z.set"]["exempt_role"] is None


def test_csharp_expression_bodied_accessors_are_exempt_only_for_member_access():
    facts = extract_facts(
        "class C { int x; int X { get => x; set => x = value; } }", "csharp"
    )
    accessors = {item["name"]: item for item in facts["functions"]}

    assert accessors["X.get"]["tokens"] == 4
    assert accessors["X.get"]["exempt_role"] == "accessor"
    assert accessors["X.set"]["tokens"] == 6
    assert accessors["X.set"]["exempt_role"] == "accessor"


def test_csharp_handler_attributes_resolve_frameworks_and_generated_markers():
    source = """using Xunit;
using N = NUnit.Framework;
using System.CodeDom.Compiler;
class C {
    [Test] void Wrong() {}
    [N.Test] void NUnitTest() {}
    [Fact] void XunitTest() {}
    [GeneratedCode("tool", "1")] void Generated() {}
}
"""
    facts = extract_facts(source, "csharp", "C.cs")
    by_name = {item["name"]: item for item in facts["functions"]}

    assert by_name["Wrong"]["exempt_role"] is None
    assert by_name["NUnitTest"]["exempt_role"] == "handler"
    assert by_name["XunitTest"]["exempt_role"] == "handler"
    assert facts["markers"] == ["generated"]
    assert facts["diagnostics"] == []


def test_csharp_calls_keep_self_receivers_and_strip_generic_and_conditional_shapes():
    facts = extract_facts(
        "class C { void F() { this.A(); base.B(); A<int>(); x?.B(); } }",
        "csharp",
        "C.cs",
    )
    calls = [
        (item["name"], item["receiver"], item["arity"]) for item in facts["call_sites"]
    ]

    assert calls == [
        ("A", "self", 0),
        ("B", "self", 0),
        ("A", None, 0),
        ("B", None, 0),
    ]
    assert all(
        item["caller"] == facts["functions"][0]["id"] for item in facts["call_sites"]
    )


def test_csharp_generated_path_marker_is_recorded():
    facts = extract_facts("class C { }", "csharp", "C.g.cs")

    assert facts["markers"] == ["generated"]


def test_csharp_lambda_control_flow_rolls_into_enclosing_function_metrics():
    facts = extract_facts(
        "class C { int F(System.Collections.Generic.List<int> items) { return "
        "items.Select(x => { if (x > 0) return x; return 0; }).First(); } }",
        "csharp",
        "C.cs",
    )
    function = facts["functions"][0]

    assert function["name"] == "F"
    assert function["tokens"] == 44
    assert function["params"] == 1
    assert function["cognitive"] == 2
    assert (function["line"], function["end_line"]) == (1, 1)
    assert all(call["caller"] == function["id"] for call in facts["call_sites"])
