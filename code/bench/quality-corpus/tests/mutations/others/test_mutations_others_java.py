from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mutations.java import OPERATORS, mutate
from mutations.java.operators import java_grammar_available
from tools.behaviour_runner import run_version
from varde_code.parse import parse_source

JAVA_SAMPLE = """class Solution {
    static int add(int left, int right) {
        int total = left + right;
        return total;
    }

    static int doubleAdd(int value) {
        return add(value, value);
    }
}
"""

JAVA_LOOP_SAMPLE = """class Solution {
    static int total(int[] values) {
        int total = 0;
        for (int index = 0; index < values.length; index++) {
            if (values[index] > 0) {
                total += values[index];
            }
        }
        return total;
    }
}
"""


def _require_java_grammar() -> None:
    if not java_grammar_available():
        pytest.skip("Java tree-sitter grammar is not cached; tests never download")
    try:
        parsed = parse_source("java", JAVA_SAMPLE)
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"Java tree-sitter grammar unavailable: {exc}")
    if parsed.has_error():
        pytest.skip("Java tree-sitter grammar could not parse the fixture")


def _run_java(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    if not shutil.which("javac") or not shutil.which("java"):
        pytest.skip("Java compiler/runtime unavailable; behavior tests require both")
    solution = tmp_path / "solution.java"
    test = tmp_path / "behaviour_test.java"
    solution.write_text(source)
    test.write_text(
        "class behaviour_test {\n    public static void main(String[] args) {\n"
        + assertions
        + "\n    }\n}\n"
    )
    return run_version(solution, test)


@pytest.mark.parametrize("operator", OPERATORS)
def test_java_operator_parses_and_records_direction(operator: str) -> None:
    _require_java_grammar()
    source = JAVA_LOOP_SAMPLE if operator == "loops-to-recursion" else JAVA_SAMPLE
    result = mutate(operator, source, pair_group_id="java-sample", seed=29)

    assert not parse_source("java", result.source).has_error()
    assert result.metadata.operator == operator
    assert result.metadata.expected_direction == OPERATORS[operator]
    assert result.metadata.pair_group_id == "java-sample"
    if operator == "wrap-in-class":
        assert result.metadata.status == "skipped"
        assert "not applicable" in result.metadata.skip_reason
    else:
        assert result.metadata.status == "mutated"


@pytest.mark.parametrize(
    "operator,source,assertions",
    [
        (
            "reorder-and-rename",
            JAVA_SAMPLE,
            "if (Solution.doubleAdd(4) != 8) throw new AssertionError();",
        ),
        (
            "inline-all-locals",
            JAVA_SAMPLE,
            "if (Solution.add(4, 5) != 9) throw new AssertionError();",
        ),
        (
            "add-dead-branches",
            JAVA_SAMPLE,
            "if (Solution.doubleAdd(4) != 8) throw new AssertionError();",
        ),
        (
            "loops-to-recursion",
            JAVA_LOOP_SAMPLE,
            (
                "if (Solution.total(new int[] {1, -2, 3, 4}) != 8) "
                "throw new AssertionError();\n"
                "if (Solution.total(new int[0]) != 0) throw new AssertionError();"
            ),
        ),
    ],
)
def test_java_operator_output_runs_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_java_grammar()
    result = mutate(operator, source, pair_group_id="java-behaviour", seed=29)
    assert result.metadata.status == "mutated"
    status, detail = _run_java(tmp_path, result.source, assertions)
    assert status == "passed", detail


JAVA_TWO_ARRAYS_SAMPLE = """class Solution {
    static int sum(int[] first, int[] second) {
        int total = 0;
        for (int index = 0; index < second.length; index++) {
            total += first[index];
        }
        return total;
    }
}
"""


def test_java_loop_operator_requires_condition_array_parameter() -> None:
    _require_java_grammar()
    result = mutate(
        "loops-to-recursion", JAVA_TWO_ARRAYS_SAMPLE, pair_group_id="java-arrays"
    )

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_java_inline_skips_type_dropping() -> None:
    _require_java_grammar()
    source = (
        "class Solution {\n"
        "    static Object pick(double value) {\n"
        "        double scaled = value * 0.5;\n"
        "        return scaled;\n"
        "    }\n"
        "}\n"
    )
    result = mutate("inline-all-locals", source, pair_group_id="java-narrow")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason
