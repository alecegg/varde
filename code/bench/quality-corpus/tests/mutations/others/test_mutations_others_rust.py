from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from mutations.rust import OPERATORS, mutate
from mutations.rust.operators import rust_grammar_available
from tools.behaviour_runner import run_version
from varde_code.parse import parse_source

RUST_SAMPLE = """pub fn add(left: i32, right: i32) -> i32 {
    let total = left + right;
    total
}

pub fn double_add(value: i32) -> i32 {
    add(value, value)
}
"""

RUST_LOOP_SAMPLE = """pub fn total(values: &[i32]) -> i32 {
    let mut total = 0;
    for value in values {
        if *value > 0 {
            total += *value;
        }
    }
    total
}
"""


def _require_rust_grammar() -> None:
    if not rust_grammar_available():
        pytest.skip(
            "Rust tree-sitter grammar is not cached; tests never download grammars"
        )
    try:
        parsed = parse_source("rust", RUST_SAMPLE)
    except (RuntimeError, OSError, ValueError) as exc:
        pytest.skip(f"Rust tree-sitter grammar unavailable: {exc}")
    if parsed.has_error():
        pytest.skip("Rust tree-sitter grammar could not parse the fixture")


def _run_rust(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    if shutil.which("cargo") is None:
        pytest.skip("Rust toolchain unavailable; behavior tests require cargo")
    solution = tmp_path / "solution.rs"
    test = tmp_path / "behaviour_test.rs"
    solution.write_text(source)
    test.write_text("#[test]\nfn behaviour() {\n" + assertions + "\n}\n")
    return run_version(solution, test)


@pytest.mark.parametrize("operator", OPERATORS)
def test_rust_operator_parses_and_records_direction(operator: str) -> None:
    _require_rust_grammar()
    source = RUST_LOOP_SAMPLE if operator == "loops-to-recursion" else RUST_SAMPLE
    result = mutate(operator, source, pair_group_id="rust-sample", seed=23)

    assert not parse_source("rust", result.source).has_error()
    assert result.metadata.operator == operator
    assert result.metadata.expected_direction == OPERATORS[operator]
    assert result.metadata.pair_group_id == "rust-sample"
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
            RUST_SAMPLE,
            "assert_eq!(corpus::double_add(4), 8);",
        ),
        (
            "inline-all-locals",
            RUST_SAMPLE,
            "assert_eq!(corpus::add(4, 5), 9);",
        ),
        (
            "add-dead-branches",
            RUST_SAMPLE,
            "assert_eq!(corpus::double_add(4), 8);",
        ),
        (
            "loops-to-recursion",
            RUST_LOOP_SAMPLE,
            (
                "assert_eq!(corpus::total(&[1, -2, 3, 4]), 8);\n"
                "assert_eq!(corpus::total(&[]), 0);"
            ),
        ),
    ],
)
def test_rust_operator_output_runs_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_rust_grammar()
    result = mutate(operator, source, pair_group_id="rust-behaviour", seed=23)
    assert result.metadata.status == "mutated"
    status, detail = _run_rust(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_rust_loop_operator_reports_unsupported_loop_shape() -> None:
    _require_rust_grammar()
    source = (
        "pub fn count(mut value: i32) -> i32 { let mut total = 0; "
        "while value > 0 { total += value; value -= 1; } total }\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="rust-while")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


RUST_SHORTHAND_SAMPLE = """struct Pair {
    n: i32,
}

pub fn make(n: i32) -> Pair {
    Pair { n }
}
"""


def test_rust_reorder_skips_shorthand_field_initializer() -> None:
    _require_rust_grammar()
    result = mutate(
        "reorder-and-rename", RUST_SHORTHAND_SAMPLE, pair_group_id="rust-shorthand"
    )

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason


def test_rust_loop_operator_skips_iterator_in_body() -> None:
    _require_rust_grammar()
    source = (
        "pub fn total(values: &[i32]) -> i32 {\n"
        "    let mut total = 0;\n"
        "    for value in values {\n"
        "        total += *value + values.len() as i32;\n"
        "    }\n"
        "    total\n"
        "}\n"
    )
    result = mutate("loops-to-recursion", source, pair_group_id="rust-iterator")

    assert result.metadata.status == "skipped"
    assert result.metadata.skip_reason
