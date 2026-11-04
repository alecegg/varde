"""Macro regions, conventional names and closure roll-in for Rust facts."""

from varde_code.quality_pass.facts import extract_facts


def _overlaps(region: dict, function: dict) -> bool:
    return (
        function["line"] <= region["end_line"]
        and region["start_line"] <= function["end_line"]
    )


def test_code_expanding_macros_are_unmeasured_regions():
    record = extract_facts(
        'fn run() {\n    println!("hi");\n    generate_code!();\n}\n'
        "macro_rules! square { ($x:expr) => { $x * $x }; }\n"
        "fn plain() {}\n",
        "rust",
        "macros.rs",
    )

    assert record["unmeasured_regions"] == [
        {"kind": "macro", "start_line": 3, "end_line": 3},
        {"kind": "macro", "start_line": 5, "end_line": 5},
    ]
    by_name = {row["name"]: row for row in record["functions"]}
    assert any(
        _overlaps(region, by_name["run"]) for region in record["unmeasured_regions"]
    )
    assert not any(
        _overlaps(region, by_name["plain"]) for region in record["unmeasured_regions"]
    )


def test_standard_library_macros_stay_measured():
    record = extract_facts(
        'fn run() {\n    println!("hi");\n    assert!(true);\n'
        "    let values = vec![1, 2];\n}\n",
        "rust",
        "standard.rs",
    )

    assert record["unmeasured_regions"] == []


def test_scoped_user_macro_is_unmeasured():
    record = extract_facts(
        "fn run() {\n    my_crate::generate!(1);\n}\n", "rust", "scoped.rs"
    )

    assert record["unmeasured_regions"] == [
        {"kind": "macro", "start_line": 2, "end_line": 2}
    ]


def test_conventional_rust_names_skip_the_short_name_penalty():
    record = extract_facts(
        "fn fmt() {}\nfn eq() {}\nfn len() -> usize { 0 }\nfn zq() {}\n",
        "rust",
        "names.rs",
    )

    assert {row["name"]: row["name_issues"] for row in record["functions"]} == {
        "fmt": [],
        "eq": [],
        "len": [],
        "zq": ["single_char", "abbreviation"],
    }


def test_test_attribute_gets_the_test_role():
    record = extract_facts(
        "#[test]\nfn checks() {}\nfn plain() {}\n", "rust", "tests.rs"
    )

    assert {row["name"]: row["exempt_role"] for row in record["functions"]} == {
        "checks": "test",
        "plain": None,
    }


def test_mut_typed_self_parameter_is_not_counted():
    record = extract_facts(
        "struct Boxed;\nimpl Boxed { fn take(mut self: Box<Self>, value: i32) {} }\n",
        "rust",
        "self.rs",
    )

    assert [row["params"] for row in record["functions"]] == [1]


def test_closure_branch_rolls_into_the_enclosing_function():
    record = extract_facts(
        "fn run() { let f = |x: i32| { if x > 0 { 1 } else { 2 } }; f(1); }\n",
        "rust",
        "closures.rs",
    )

    assert [row["name"] for row in record["functions"]] == ["run"]
    assert record["functions"][0]["cognitive"] == 3
    assert [site["caller"] for site in record["call_sites"]] == ["closures.rs::run#1"]
