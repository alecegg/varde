"""Test roles, conventional names and closure roll-in for Go facts."""

from varde_code.quality_pass.facts import extract_facts


def test_testing_functions_get_the_test_role():
    record = extract_facts(
        "package sample\n"
        'import "testing"\n'
        "func TestStore(t *testing.T) {}\n"
        "func BenchmarkStore(b *testing.B) {}\n"
        "func FuzzStore(f *testing.F) {}\n"
        "func TestHelper(value int) {}\n"
        "func Testing(t *testing.T) {}\n"
        "func testLower(t *testing.T) {}\n",
        "go",
        "store_test.go",
    )

    assert {row["name"]: row["exempt_role"] for row in record["functions"]} == {
        "TestStore": "test",
        "BenchmarkStore": "test",
        "FuzzStore": "test",
        "TestHelper": None,
        "Testing": None,
        "testLower": None,
    }


def test_conventional_go_names_skip_the_short_name_penalty():
    record = extract_facts(
        "package sample\nfunc ctx() {}\nfunc err() {}\nfunc r() {}\nfunc zq() {}\n",
        "go",
        "names.go",
    )

    assert {row["name"]: row["name_issues"] for row in record["functions"]} == {
        "ctx": [],
        "err": [],
        "r": [],
        "zq": ["single_char", "abbreviation"],
    }


def test_closure_branch_rolls_into_the_enclosing_function():
    record = extract_facts(
        "package sample\nfunc run() { f := func() { if true {} }; f() }\n",
        "go",
        "closures.go",
    )

    assert [row["name"] for row in record["functions"]] == ["run"]
    assert record["functions"][0]["cognitive"] == 2
    assert [site["caller"] for site in record["call_sites"]] == ["closures.go::run#1"]
