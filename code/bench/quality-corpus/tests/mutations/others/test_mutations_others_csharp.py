from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from mutations.csharp import OPERATORS, mutate
from mutations.csharp.operators import csharp_grammar_available
from tools.behaviour_runner import run_version
from varde_code.parse import parse_source

CSHARP_SAMPLE = """class Solution {
    public static int Add(int left, int right) {
        int total = left + right;
        return total;
    }

    public static int DoubleAdd(int value) {
        return Add(value, value);
    }
}
"""

CSHARP_LOOP_SAMPLE = """class Solution {
    public static int Total(int[] values) {
        int total = 0;
        for (int index = 0; index < values.Length; index++) {
            if (values[index] > 0) {
                total += values[index];
            }
        }
        return total;
    }
}
"""


def _require_csharp_grammar() -> None:
    if not csharp_grammar_available():
        pytest.skip("C# tree-sitter grammar is not cached; tests never download")
    try:
        parsed = parse_source("csharp", CSHARP_SAMPLE)
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"C# tree-sitter grammar unavailable: {exc}")
    if parsed.has_error():
        pytest.skip("C# tree-sitter grammar could not parse the fixture")


def _run_csharp(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK unavailable; behavior tests require dotnet")
    sdks = subprocess.run(  # noqa: S603 - Probes the configured .NET SDK for the test fixture.
        [dotnet, "--list-sdks"], check=False, capture_output=True, text=True
    )
    if sdks.returncode or not sdks.stdout.strip():
        pytest.skip(".NET SDK unavailable; behavior tests require an installed SDK")
    solution = tmp_path / "solution.cs"
    test = tmp_path / "behaviour_test.cs"
    solution.write_text(source)
    test.write_text(
        "class behaviour_test {\n    static void Main(string[] args) {\n"
        + assertions
        + "\n    }\n}\n"
    )
    return run_version(solution, test)


@pytest.mark.parametrize("operator", OPERATORS)
def test_csharp_operator_parses_and_records_direction(operator: str) -> None:
    _require_csharp_grammar()
    source = CSHARP_LOOP_SAMPLE if operator == "loops-to-recursion" else CSHARP_SAMPLE
    result = mutate(operator, source, pair_group_id="csharp-sample", seed=31)

    assert not parse_source("csharp", result.source).has_error()
    assert result.metadata.operator == operator
    assert result.metadata.expected_direction == OPERATORS[operator]
    assert result.metadata.pair_group_id == "csharp-sample"
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
            CSHARP_SAMPLE,
            "if (Solution.DoubleAdd(4) != 8) throw new System.Exception();",
        ),
        (
            "inline-all-locals",
            CSHARP_SAMPLE,
            "if (Solution.Add(4, 5) != 9) throw new System.Exception();",
        ),
        (
            "add-dead-branches",
            CSHARP_SAMPLE,
            "if (Solution.DoubleAdd(4) != 8) throw new System.Exception();",
        ),
        (
            "loops-to-recursion",
            CSHARP_LOOP_SAMPLE,
            (
                "if (Solution.Total(new int[] {1, -2, 3, 4}) != 8) "
                "throw new System.Exception();\n"
                "if (Solution.Total(new int[0]) != 0) throw new System.Exception();"
            ),
        ),
    ],
)
def test_csharp_operator_output_runs_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_csharp_grammar()
    result = mutate(operator, source, pair_group_id="csharp-behaviour", seed=31)
    assert result.metadata.status == "mutated"
    status, detail = _run_csharp(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_csharp_inline_skips_type_dropping() -> None:
    _require_csharp_grammar()
    source = (
        "class Solution {\n"
        "    public static object Pick(double value) {\n"
        "        double scaled = value * 0.5;\n"
        "        return scaled;\n"
        "    }\n"
        "}\n"
    )
    result = mutate("inline-all-locals", source, pair_group_id="csharp-narrow")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def _require_dotnet() -> None:
    dotnet = shutil.which("dotnet")
    if dotnet is None:
        pytest.skip(".NET SDK unavailable; compiling tests require dotnet")
    sdks = subprocess.run(  # noqa: S603 - Probes the configured .NET SDK for the test fixture.
        [dotnet, "--list-sdks"], check=False, capture_output=True, text=True
    )
    if sdks.returncode or not sdks.stdout.strip():
        pytest.skip(".NET SDK unavailable; compiling tests require an installed SDK")


def test_csharp_inline_skips_uncompilable_input() -> None:
    _require_csharp_grammar()
    _require_dotnet()
    source = (
        "class Solution {\n"
        "    public static float Half() {\n"
        "        float value = 5.5;\n"
        "        return value;\n"
        "    }\n"
        "}\n"
    )
    result = mutate("inline-all-locals", source, pair_group_id="csharp-uncompilable")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason == "input does not compile"
