from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mutations.cpp import OPERATORS, mutate
from mutations.cpp.operators import cpp_grammar_available
from tools.behaviour_runner import run_version
from varde_code.parse import parse_source

CPP_SAMPLE = """int add(int left, int right) {
    int total = left + right;
    return total;
}

int double_add(int value) {
    return add(value, value);
}
"""

CPP_LOOP_SAMPLE = """#include <vector>

int total_positive(const std::vector<int>& values) {
    int total = 0;
    for (int value : values) {
        if (value > 0) {
            total += value;
        }
    }
    return total;
}
"""


def _require_cpp_grammar() -> None:
    if not cpp_grammar_available():
        pytest.skip("C++ tree-sitter grammar is not cached; tests never download")
    try:
        parsed = parse_source("cpp", CPP_SAMPLE)
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"C++ tree-sitter grammar unavailable: {exc}")
    if parsed.has_error():
        pytest.skip("C++ tree-sitter grammar could not parse the fixture")


def _require_cpp_compiler() -> str:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("C++ syntax checks require g++ or clang++")
    return compiler


def _run_cpp(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    _require_cpp_compiler()
    solution = tmp_path / "solution.cpp"
    test = tmp_path / "behaviour_test.cpp"
    solution.write_text(source)
    test.write_text('#include "solution.cpp"\n\nint main() {\n' + assertions + "\n}\n")
    return run_version(solution, test)


@pytest.mark.parametrize("operator", OPERATORS)
def test_cpp_operator_parses_and_records_direction(
    operator: str, tmp_path: Path
) -> None:
    _require_cpp_grammar()
    compiler = _require_cpp_compiler()
    source = CPP_LOOP_SAMPLE if operator == "loops-to-recursion" else CPP_SAMPLE
    result = mutate(operator, source, pair_group_id="cpp-sample", seed=29)

    assert not parse_source("cpp", result.source).has_error()
    assert result.metadata.operator == operator
    assert result.metadata.expected_direction == OPERATORS[operator]
    assert result.metadata.pair_group_id == "cpp-sample"
    assert result.metadata.status == "mutated"
    syntax_source = tmp_path / f"candidate-{operator}.cpp"
    syntax_source.write_text(result.source)
    checked = subprocess.run(  # noqa: S603 - Runs the configured compiler on the test fixture.
        [compiler, "-fsyntax-only", "-std=c++17", str(syntax_source)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr


@pytest.mark.parametrize(
    "operator,source,assertions",
    [
        (
            "reorder-and-rename",
            CPP_SAMPLE,
            "if (double_add(4) != 8) return 1;",
        ),
        ("inline-all-locals", CPP_SAMPLE, "if (add(4, 5) != 9) return 1;"),
        (
            "add-dead-branches",
            CPP_SAMPLE,
            "if (double_add(4) != 8) return 1;",
        ),
        (
            "wrap-in-class",
            CPP_SAMPLE,
            "if (double_add(4) != 8) return 1;",
        ),
        (
            "loops-to-recursion",
            CPP_LOOP_SAMPLE,
            (
                "if (total_positive({1, -2, 3, 4}) != 8) return 1;\n"
                "if (total_positive({}) != 0) return 1;"
            ),
        ),
    ],
)
def test_cpp_operator_output_runs_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_cpp_grammar()
    result = mutate(operator, source, pair_group_id="cpp-behaviour", seed=29)
    assert result.metadata.status == "mutated"
    status, detail = _run_cpp(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_cpp_loop_operator_reports_unsupported_loop_shape() -> None:
    _require_cpp_grammar()
    source = (
        "int count(int value) { int total = 0; while (value > 0) { "
        "total += value; --value; } return total; }\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="cpp-while")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


CPP_FIELD_SAMPLE = """struct Point {
    int x;
};

int get_x(Point value) {
    return value.x;
}
"""

CPP_METHOD_SAMPLE = """#include <vector>

int measure(const std::vector<int>& values) {
    return static_cast<int>(values.size());
}
"""

CPP_REORDER_INCLUDE_SAMPLE = """#include <vector>

int first(int value) {
    return value + 1;
}

int second(int other) {
    return other * 2;
}
"""

CPP_WRAP_INCLUDE_SAMPLE = """#include <vector>

int add(int left, int right) {
    return left + right;
}
"""

CPP_TWO_LOCALS_SAMPLE = """int add(int left, int right) {
    int total = left + right;
    return total;
}

int multiply(int left, int right) {
    int product = left * right;
    return product;
}
"""


@pytest.mark.parametrize(
    "source,assertions",
    [
        (CPP_FIELD_SAMPLE, "if (get_x(Point{7}) != 7) return 1;"),
        (CPP_METHOD_SAMPLE, "if (measure({1, 2, 3}) != 3) return 1;"),
    ],
)
def test_cpp_reorder_renames_member_receiver_side(
    tmp_path: Path, source: str, assertions: str
) -> None:
    _require_cpp_grammar()
    result = mutate("reorder-and-rename", source, pair_group_id="cpp-member", seed=29)

    assert result.metadata.status == "mutated"
    status, detail = _run_cpp(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_cpp_reorder_allows_includes(tmp_path: Path) -> None:
    _require_cpp_grammar()
    result = mutate(
        "reorder-and-rename",
        CPP_REORDER_INCLUDE_SAMPLE,
        pair_group_id="cpp-inc",
        seed=29,
    )

    assert result.metadata.status == "mutated"
    status, detail = _run_cpp(
        tmp_path,
        result.source,
        "if (first(1) != 2) return 1;\nif (second(3) != 6) return 1;",
    )
    assert status == "passed", detail


def test_cpp_wrap_in_class_allows_includes(tmp_path: Path) -> None:
    _require_cpp_grammar()
    result = mutate(
        "wrap-in-class", CPP_WRAP_INCLUDE_SAMPLE, pair_group_id="cpp-inc", seed=29
    )

    assert result.metadata.status == "mutated"
    status, detail = _run_cpp(tmp_path, result.source, "if (add(1, 2) != 3) return 1;")
    assert status == "passed", detail


@pytest.mark.parametrize(
    "source",
    [
        "static int add(int value) { return value; }\n",
        "inline int add(int value) { return value; }\n",
        "constexpr int add(int value) { return value; }\n",
    ],
)
def test_cpp_wrap_in_class_skips_specified_functions(source: str) -> None:
    _require_cpp_grammar()
    result = mutate("wrap-in-class", source, pair_group_id="cpp-spec")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


@pytest.mark.parametrize(
    "source",
    [
        # Accumulator declared int but narrowed from another parameter.
        (
            "#include <vector>\n"
            "int total(const std::vector<int>& values, int offset) {\n"
            "    int total = 0;\n"
            "    for (int value : values) {\n"
            "        total += value + offset;\n"
            "    }\n"
            "    return total;\n"
            "}\n"
        ),
        # double accumulator would be narrowed to int by the helper.
        (
            "#include <vector>\n"
            "int total(const std::vector<int>& values) {\n"
            "    double total = 0;\n"
            "    for (int value : values) {\n"
            "        total += value;\n"
            "    }\n"
            "    return total;\n"
            "}\n"
        ),
        # The loop ranges over the second parameter, not the first.
        (
            "#include <vector>\n"
            "int total(const std::vector<int>& a, const std::vector<int>& values) {\n"
            "    int total = 0;\n"
            "    for (int value : values) {\n"
            "        total += value;\n"
            "    }\n"
            "    return total;\n"
            "}\n"
        ),
    ],
)
def test_cpp_loop_operator_skips_unsafe_shapes(source: str) -> None:
    _require_cpp_grammar()
    result = mutate("loops-to-recursion", source, pair_group_id="cpp-unsafe")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_cpp_inline_skips_narrowing_conversion() -> None:
    _require_cpp_grammar()
    source = (
        "int truncate(double value) { int narrowed = value * 0.5; return narrowed; }\n"
    )
    result = mutate("inline-all-locals", source, pair_group_id="cpp-narrow")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_cpp_inline_inlines_first_local_of_each_function(tmp_path: Path) -> None:
    _require_cpp_grammar()
    result = mutate(
        "inline-all-locals", CPP_TWO_LOCALS_SAMPLE, pair_group_id="cpp-two", seed=29
    )

    assert result.metadata.status == "mutated"
    assert "return left + right;" in result.source
    assert "return left * right;" in result.source
    status, detail = _run_cpp(
        tmp_path,
        result.source,
        "if (add(4, 5) != 9) return 1;\nif (multiply(4, 5) != 20) return 1;",
    )
    assert status == "passed", detail
