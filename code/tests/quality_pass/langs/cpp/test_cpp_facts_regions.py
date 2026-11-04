"""Unmeasured regions, overload pairs and idioms for C++ facts."""

from varde_code.quality_pass.facts import extract_facts


def _overlaps(region: dict, function: dict) -> bool:
    return (
        function["line"] <= region["end_line"]
        and region["start_line"] <= function["end_line"]
    )


def test_template_and_macro_definition_are_unmeasured_regions():
    record = extract_facts(
        "template<class T> T identity(T value) { return value; }\n"
        "#define APPLY(x) ((x) + 1)\n"
        "int plain(int x) { return x; }\n",
        "cpp",
        "shapes.cpp",
    )

    assert record["unmeasured_regions"] == [
        {"kind": "template", "start_line": 1, "end_line": 1},
        {"kind": "preprocessor", "start_line": 2, "end_line": 2},
    ]
    by_name = {row["name"]: row for row in record["functions"]}
    assert any(
        _overlaps(region, by_name["identity"])
        for region in record["unmeasured_regions"]
    )
    assert not any(
        _overlaps(region, by_name["plain"]) for region in record["unmeasured_regions"]
    )


def test_pragma_and_plain_functions_are_measured():
    record = extract_facts(
        "#pragma once\nint plain() { return 0; }\n", "cpp", "shapes.hpp"
    )

    assert record["unmeasured_regions"] == []


def test_conditional_compilation_block_is_unmeasured():
    record = extract_facts(
        (
            "#ifdef DEBUG\nint debug_only() { return 1; }\n#endif\n"
            "int plain() { return 0; }\n"
        ),
        "cpp",
        "shapes.cpp",
    )

    assert record["unmeasured_regions"] == [
        {"kind": "preprocessor", "start_line": 1, "end_line": 3}
    ]


def test_header_guard_is_not_unmeasured():
    record = extract_facts(
        "#ifndef SAMPLE_H\n#define SAMPLE_H\nint feature() { return 1; }\n#endif\n",
        "cpp",
        "sample.hpp",
    )

    assert record["unmeasured_regions"] == []
    assert [row["name"] for row in record["functions"]] == ["feature"]


def test_defined_form_header_guard_is_not_unmeasured():
    record = extract_facts(
        (
            "#if !defined(SAMPLE_H)\n#define SAMPLE_H\n"
            "int feature() { return 1; }\n#endif\n"
        ),
        "cpp",
        "sample.hpp",
    )

    assert record["unmeasured_regions"] == []


def test_template_inside_a_header_guard_stays_unmeasured():
    record = extract_facts(
        "#ifndef SAMPLE_H\n#define SAMPLE_H\n"
        "template<class T> T identity(T value) { return value; }\n#endif\n",
        "cpp",
        "sample.hpp",
    )

    assert record["unmeasured_regions"] == [
        {"kind": "template", "start_line": 3, "end_line": 3}
    ]


def test_header_guard_define_with_a_value_is_not_unmeasured():
    record = extract_facts(
        "#ifndef LIMIT_H\n#define LIMIT_H 4\n#endif\n", "cpp", "limit.hpp"
    )

    assert record["unmeasured_regions"] == []


def test_const_and_non_const_overloads_are_paired():
    record = extract_facts(
        "struct Box {\n"
        " int get() { return 1; }\n"
        " int get() const { return 1; }\n"
        " int size() { return 2; }\n"
        "};\n",
        "cpp",
        "box.cpp",
    )

    assert {row["id"]: row["overload_pair"] for row in record["functions"]} == {
        "box.cpp::Box.get#1": "box.cpp::Box.get#2",
        "box.cpp::Box.get#2": "box.cpp::Box.get#1",
        "box.cpp::Box.size#1": None,
    }


def test_same_arity_overloads_without_const_are_not_paired():
    record = extract_facts(
        "int compare(int a) { return a; }\nint compare(long a) { return 0; }\n",
        "cpp",
        "box.cpp",
    )

    assert [row["overload_pair"] for row in record["functions"]] == [None, None]


def test_lone_const_member_is_not_paired():
    record = extract_facts(
        "struct Box { int get() const { return 1; } };\n", "cpp", "box.cpp"
    )

    assert [row["overload_pair"] for row in record["functions"]] == [None]


def test_gtest_macro_case_gets_the_test_role():
    record = extract_facts(
        "TEST(Suite, Case) { EXPECT_TRUE(1 == 1); }\n", "cpp", "cases.cpp"
    )

    assert [row["exempt_role"] for row in record["functions"]] == ["test"]


def test_conventional_cpp_names_skip_the_short_name_penalty():
    record = extract_facts(
        (
            "int cmp(int a, int b) { return 0; }\n"
            "int ptr() { return 0; }\nint zq() { return 0; }\n"
        ),
        "cpp",
        "names.cpp",
    )

    assert {row["name"]: row["name_issues"] for row in record["functions"]} == {
        "cmp": [],
        "ptr": [],
        "zq": ["single_char", "abbreviation"],
    }


def test_inline_function_is_not_file_private():
    record = extract_facts(
        "static int local() { return 0; }\ninline int shared() { return 0; }\n",
        "cpp",
        "names.cpp",
    )

    assert {row["name"]: row["file_private"] for row in record["functions"]} == {
        "local": True,
        "shared": False,
    }


def test_lambda_branch_rolls_into_the_enclosing_function():
    record = extract_facts(
        "int run() { auto f = [](int x) { if (x > 0) { return 1; } return 2; }; "
        "return f(1); }\n",
        "cpp",
        "closures.cpp",
    )

    assert [row["name"] for row in record["functions"]] == ["run"]
    assert record["functions"][0]["cognitive"] == 1
    assert [site["caller"] for site in record["call_sites"]] == ["closures.cpp::run#1"]
