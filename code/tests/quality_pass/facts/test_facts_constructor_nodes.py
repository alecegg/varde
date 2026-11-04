from varde_code.quality_pass.facts import extract_facts


def test_java_constructor_has_hand_derived_tokens_parameters_and_role():
    facts = extract_facts(
        "class A { int x; public A(int x) { this.x = x; } "
        "public int getX() { return this.x; } } class Use { A value = new A(1); }",
        "java",
        "A.java",
    )
    by_name = {item["name"]: item for item in facts["functions"]}

    assert by_name["A"]["tokens"] == 14
    assert by_name["A"]["params"] == 1
    assert by_name["A"]["exempt_role"] == "constructor"
    assert by_name["A"]["file_private"] is False
    assert by_name["getX"]["tokens"] == 12
    assert by_name["getX"]["exempt_role"] == "accessor"
    assert facts["diagnostics"] == []


def test_csharp_constructor_and_property_accessors_are_measured_and_exempt():
    facts = extract_facts(
        "class A { private int x; public A(int x) { this.x = x; } "
        "public int X { get { return x; } set { x = value; } } "
        "public int Y { get; set; } } class Use { A value = new A(1); }",
        "csharp",
        "A.cs",
    )
    by_name = {item["name"]: item for item in facts["functions"]}

    assert set(by_name) == {"A", "X.get", "X.set"}
    assert by_name["A"]["tokens"] == 14
    assert by_name["A"]["params"] == 1
    assert by_name["A"]["exempt_role"] == "constructor"
    assert by_name["A"]["file_private"] is False
    assert by_name["X.get"]["tokens"] == 6
    assert by_name["X.get"]["exempt_role"] == "accessor"
    assert by_name["X.set"]["tokens"] == 7
    assert by_name["X.set"]["exempt_role"] == "accessor"
    assert facts["diagnostics"] == []
