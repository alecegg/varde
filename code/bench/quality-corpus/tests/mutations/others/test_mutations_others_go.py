from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mutations.go import OPERATORS, mutate
from tools.behaviour_runner import run_version
from varde_code.parse import parse_source

GO_SAMPLE = """package corpus

func Add(left int, right int) int {
	total := left + right
	return total
}

func DoubleAdd(value int) int {
	return Add(value, value)
}
"""

GO_LOOP_SAMPLE = """package corpus

func Total(values []int) int {
	total := 0
	for _, value := range values {
		if value > 0 {
			total += value
		}
	}
	return total
}
"""


def _require_go_grammar() -> None:
    try:
        parsed = parse_source("go", GO_SAMPLE)
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"Go tree-sitter grammar unavailable: {exc}")
    if parsed.has_error():
        pytest.skip("Go tree-sitter grammar could not parse the fixture")


def _run_go(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    if not shutil.which("go"):
        pytest.skip("Go toolchain unavailable; behavior tests require go")
    solution = tmp_path / "solution.go"
    test = tmp_path / "behaviour_test.go"
    solution.write_text(source)
    test.write_text(
        'package corpus\n\nimport "testing"\n\nfunc TestBehaviour(t *testing.T) {\n'
        + assertions
        + "\n}\n"
    )
    return run_version(solution, test)


@pytest.mark.parametrize("operator", OPERATORS)
def test_go_operator_parses_and_records_direction(operator: str) -> None:
    _require_go_grammar()
    source = GO_LOOP_SAMPLE if operator == "loops-to-recursion" else GO_SAMPLE
    result = mutate(operator, source, pair_group_id="go-sample", seed=17)

    assert not parse_source("go", result.source).has_error()
    assert result.metadata.operator == operator
    assert result.metadata.expected_direction == OPERATORS[operator]
    assert result.metadata.pair_group_id == "go-sample"
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
            GO_SAMPLE,
            'if got := DoubleAdd(4); got != 8 { t.Fatalf("got %d", got) }',
        ),
        (
            "inline-all-locals",
            GO_SAMPLE,
            'if got := Add(4, 5); got != 9 { t.Fatalf("got %d", got) }',
        ),
        (
            "add-dead-branches",
            GO_SAMPLE,
            'if got := DoubleAdd(4); got != 8 { t.Fatalf("got %d", got) }',
        ),
        (
            "loops-to-recursion",
            GO_LOOP_SAMPLE,
            (
                "if got := Total([]int{1, -2, 3, 4}); got != 8 "
                '{ t.Fatalf("got %d", got) }\n'
                'if got := Total(nil); got != 0 { t.Fatalf("got %d", got) }'
            ),
        ),
    ],
)
def test_go_operator_output_runs_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_go_grammar()
    result = mutate(operator, source, pair_group_id="go-behaviour", seed=17)
    assert result.metadata.status == "mutated"
    status, detail = _run_go(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_go_loop_operator_reports_unsupported_loop_shape() -> None:
    _require_go_grammar()
    source = (
        "package corpus\nfunc Count(value int) int { total := 0; "
        "for value > 0 { total += value; value-- }; return total }\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="go-while")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


GO_MAP_SAMPLE = """package corpus

func Total(values map[int]int) int {
	total := 0
	for _, value := range values {
		total += value
	}
	return total
}
"""

GO_KEYED_SAMPLE = """package corpus

type Pair struct {
	n int
}

func Make(n int) Pair {
	return Pair{n: n}
}
"""

GO_TWO_LOCALS_SAMPLE = """package corpus

func Add(left int, right int) int {
	total := left + right
	return total
}

func Multiply(left int, right int) int {
	product := left * right
	return product
}
"""


def test_go_loop_operator_skips_map_range() -> None:
    _require_go_grammar()
    result = mutate("loops-to-recursion", GO_MAP_SAMPLE, pair_group_id="go-map")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_go_reorder_skips_keyed_literal_field_name(tmp_path: Path) -> None:
    _require_go_grammar()
    result = mutate(
        "reorder-and-rename", GO_KEYED_SAMPLE, pair_group_id="go-keyed", seed=17
    )

    assert result.metadata.status == "mutated"
    assert "Pair{n:" in result.source
    status, detail = _run_go(
        tmp_path,
        result.source,
        'if got := Make(3); got.n != 3 { t.Fatalf("got %d", got.n) }',
    )
    assert status == "passed", detail


def test_go_inline_locals_inlines_first_local_of_each_function(tmp_path: Path) -> None:
    _require_go_grammar()
    result = mutate(
        "inline-all-locals", GO_TWO_LOCALS_SAMPLE, pair_group_id="go-two", seed=17
    )

    assert result.metadata.status == "mutated"
    assert "return left + right" in result.source
    assert "return left * right" in result.source
    status, detail = _run_go(
        tmp_path,
        result.source,
        'if got := Add(4, 5); got != 9 { t.Fatalf("got %d", got) }\n'
        'if got := Multiply(4, 5); got != 20 { t.Fatalf("got %d", got) }',
    )
    assert status == "passed", detail


@pytest.mark.parametrize(
    "loop_body",
    [
        "\t\tvalue++\n\t\ttotal += value\n",
        "\t\tif &value != nil {\n\t\t\ttotal += value\n\t\t}\n",
    ],
)
def test_go_loop_operator_skips_mutated_loop_variable(loop_body: str) -> None:
    _require_go_grammar()
    source = (
        "package corpus\n\n"
        "func Total(values []int) int {\n"
        "\ttotal := 0\n"
        "\tfor _, value := range values {\n"
        f"{loop_body}"
        "\t}\n"
        "\treturn total\n"
        "}\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="go-mutated-item")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_go_loop_operator_skips_deferred_body() -> None:
    _require_go_grammar()
    source = (
        "package corpus\n\n"
        "func Total(values []int) int {\n"
        "\ttotal := 0\n"
        "\tfor _, value := range values {\n"
        "\t\tdefer func() {}()\n"
        "\t\ttotal += value\n"
        "\t}\n"
        "\treturn total\n"
        "}\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="go-defer")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason
