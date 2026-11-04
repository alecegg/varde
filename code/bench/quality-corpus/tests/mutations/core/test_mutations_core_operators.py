from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from mutations.core import parses, stable_seed, typescript_grammar_available
from mutations.python import OPERATORS as PYTHON_OPERATORS
from mutations.python import mutate as mutate_python
from mutations.typescript import OPERATORS as TYPESCRIPT_OPERATORS
from mutations.typescript import mutate as mutate_typescript
from tools.behaviour_runner import available_commands, run_version

PYTHON_SAMPLE = """def add(left, right):
    total = left + right
    return total
"""
PYTHON_CLASS_SAMPLE = """def twice(value):
    return value * 2

def add_twice(value):
    return twice(value) + twice(value)
"""
PYTHON_LOOP_SAMPLE = """def total(xs):
    result = 0
    for item in xs:
        result += item
    return result
"""
TYPESCRIPT_SAMPLE = """export function add(left: number, right: number): number {
  const total = left + right;
  return total;
}
"""
TYPESCRIPT_LOOP_SAMPLE = """export function total(xs: number[]): number {
  let result = 0;
  for (const item of xs) {
    result += item;
  }
  return result;
}
"""


def _require_typescript_grammar() -> None:
    if not typescript_grammar_available():
        pytest.skip(
            "TypeScript tree-sitter grammar is not cached; "
            "tests never download grammars"
        )


def _run_python(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    solution = tmp_path / "solution.py"
    test = tmp_path / "behaviour_test.py"
    solution.write_text(source)
    test.write_text("import solution\n" + assertions)
    return run_version(solution, test)


def _run_typescript(tmp_path: Path, source: str, assertions: str) -> tuple[str, str]:
    _require_typescript_grammar()
    if available_commands(".ts") is None:
        pytest.skip(
            "TypeScript runtime is unavailable; behavior tests require Node or tsc"
        )
    solution = tmp_path / "solution.ts"
    test = tmp_path / "behaviour_test.ts"
    solution.write_text(source)
    test.write_text('import * as solution from "./solution.ts";\n' + assertions)
    return run_version(solution, test)


@pytest.mark.parametrize("operator", PYTHON_OPERATORS)
def test_python_operator_mutates_or_reports_a_reasoned_skip(operator: str) -> None:
    source = PYTHON_LOOP_SAMPLE if operator == "loops-to-recursion" else PYTHON_SAMPLE
    result = mutate_python(operator, source, pair_group_id="sample-42", seed=7)

    assert parses("python", result.source)
    assert result.metadata.expected_direction == PYTHON_OPERATORS[operator]
    assert result.metadata.pair_group_id == "sample-42"
    assert result.to_dict()["metadata"]["pair_group_id"] == "sample-42"
    if operator in {
        "reorder-and-rename",
        "inline-all-locals",
        "add-dead-branches",
        "wrap-in-class",
        "loops-to-recursion",
    }:
        assert result.metadata.status == "mutated"
        assert result.source != source


@pytest.mark.parametrize("operator", TYPESCRIPT_OPERATORS)
def test_typescript_operator_mutates_nested_braces_and_records_pair(
    operator: str,
) -> None:
    _require_typescript_grammar()
    source = (
        TYPESCRIPT_LOOP_SAMPLE
        if operator == "loops-to-recursion"
        else TYPESCRIPT_SAMPLE
    )
    if operator == "add-dead-branches":
        source = (
            "export function add(a: number, b: number): number { "
            "if (a) { return b; } return a; }"
        )
    result = mutate_typescript(operator, source, pair_group_id="ts-42", seed=7)

    assert parses("typescript", result.source)
    assert result.metadata.expected_direction == TYPESCRIPT_OPERATORS[operator]
    assert result.metadata.pair_group_id == "ts-42"
    assert result.metadata.status == "mutated"
    assert result.source != source


@pytest.mark.parametrize(
    "operator,source,assertions",
    [
        ("reorder-and-rename", PYTHON_SAMPLE, "assert solution.add(2, 3) == 5\n"),
        ("inline-all-locals", PYTHON_SAMPLE, "assert solution.add(2, 3) == 5\n"),
        ("add-dead-branches", PYTHON_SAMPLE, "assert solution.add(2, 3) == 5\n"),
        (
            "wrap-in-class",
            PYTHON_CLASS_SAMPLE,
            "assert solution.twice(4) == 8\nassert solution.add_twice(3) == 12\n",
        ),
        (
            "loops-to-recursion",
            PYTHON_LOOP_SAMPLE,
            (
                "assert solution.total([1, 2, 3, 4]) == 10\n"
                "assert solution.total([]) == 0\n"
            ),
        ),
    ],
)
def test_python_outputs_run_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    result = mutate_python(operator, source, pair_group_id="python-behaviour", seed=19)

    assert result.metadata.status == "mutated"
    status, detail = _run_python(tmp_path, result.source, assertions)
    assert status == "passed", detail


@pytest.mark.parametrize(
    "operator,source,assertions",
    [
        (
            "reorder-and-rename",
            TYPESCRIPT_SAMPLE,
            "if (solution.add(2, 3) !== 5) throw Error();\n",
        ),
        (
            "inline-all-locals",
            TYPESCRIPT_SAMPLE,
            "if (solution.add(2, 3) !== 5) throw Error();\n",
        ),
        (
            "add-dead-branches",
            (
                "export function add(a: number, b: number): number { "
                "if (a) { return b; } return a; }"
            ),
            "if (solution.add(2, 3) !== 3) throw Error();\n",
        ),
        (
            "wrap-in-class",
            TYPESCRIPT_SAMPLE,
            "if (solution.add(2, 3) !== 5) throw Error();\n",
        ),
        (
            "loops-to-recursion",
            TYPESCRIPT_LOOP_SAMPLE,
            (
                "if (solution.total([1, 2, 3, 4]) !== 10 "
                "|| solution.total([]) !== 0) throw Error();\n"
            ),
        ),
    ],
)
def test_typescript_outputs_run_through_behaviour_runner(
    tmp_path: Path, operator: str, source: str, assertions: str
) -> None:
    _require_typescript_grammar()
    result = mutate_typescript(operator, source, pair_group_id="ts-behaviour", seed=19)

    assert result.metadata.status == "mutated"
    status, detail = _run_typescript(tmp_path, result.source, assertions)
    assert status == "passed", detail


def test_python_inline_skips_augmented_assignment_loop() -> None:
    result = mutate_python("inline-all-locals", PYTHON_LOOP_SAMPLE, "inline-loop")

    assert result.metadata.status == "skipped"
    assert "single-use straight-line" in result.metadata.skip_reason


def test_python_inline_skips_side_effect_and_deleted_local_cases() -> None:
    side_effect = "def value():\n    total = record_call()\n    return total\n"
    deleted = (
        "def value():\n    total = 1\n    del total\n    total = 2\n    return total\n"
    )

    side_effect_result = mutate_python("inline-all-locals", side_effect, "side-effect")
    deleted_result = mutate_python("inline-all-locals", deleted, "delete")

    assert side_effect_result.metadata.status == "skipped"
    assert deleted_result.metadata.status == "skipped"


def test_unsupported_while_loop_is_recorded_as_skipped() -> None:
    source = (
        "def count(n):\n    total = 0\n    while n:\n"
        "        total += n\n        n -= 1\n    return total\n"
    )
    result = mutate_python("loops-to-recursion", source, "while-sample")

    assert result.metadata.status == "skipped"
    assert "while" in result.metadata.skip_reason


def test_reorder_rename_skips_closures_and_keyword_calls(tmp_path: Path) -> None:
    closure = (
        "def outer(value):\n    def inner():\n"
        "        return value\n    return inner()\n"
    )
    independent_nested = (
        "def outer(value):\n    def inner(item):\n"
        "        return item + 1\n    return inner(value)\n"
    )
    keyword = (
        "def add(left, right):\n    return left + right\n"
        "answer = add(left=2, right=3)\n"
    )

    closure_result = mutate_python("reorder-and-rename", closure, "closure")
    nested_result = mutate_python("reorder-and-rename", independent_nested, "nested")
    keyword_result = mutate_python("reorder-and-rename", keyword, "keyword")

    assert closure_result.metadata.status == "skipped"
    assert "closure" in closure_result.metadata.skip_reason
    assert nested_result.metadata.status == "mutated"
    assert (
        _run_python(tmp_path, nested_result.source, "assert solution.outer(4) == 5\n")[
            0
        ]
        == "passed"
    )
    assert keyword_result.metadata.status == "skipped"
    assert "keyword" in keyword_result.metadata.skip_reason


def test_reorder_rename_skips_global_bindings() -> None:
    source = (
        "counter = 0\ndef increment(value):\n    global counter\n"
        "    counter += value\n    return counter\n"
    )
    result = mutate_python("reorder-and-rename", source, "global")

    assert result.metadata.status == "skipped"
    assert "global/nonlocal" in result.metadata.skip_reason


def test_mutation_seed_is_deterministic_and_changes_selected_dead_branch_count() -> (
    None
):
    first = mutate_python("add-dead-branches", PYTHON_SAMPLE, "seed", seed=1)
    repeated = mutate_python("add-dead-branches", PYTHON_SAMPLE, "seed", seed=1)
    another = mutate_python("add-dead-branches", PYTHON_SAMPLE, "seed", seed=5)

    assert first.source == repeated.source
    assert first.metadata.seed == stable_seed("add-dead-branches", PYTHON_SAMPLE, 1)
    assert first.source != another.source
    unseeded = mutate_python("add-dead-branches", PYTHON_SAMPLE, "seed")
    assert unseeded.metadata.seed == stable_seed("add-dead-branches", PYTHON_SAMPLE)


def test_python_multi_function_rename_avoids_existing_names_and_runs(
    tmp_path: Path,
) -> None:
    source = (
        "def first(p0):\n    v0 = p0 + 1\n    return v0\n\n"
        "def second(value):\n    return first(value) * 2\n"
    )
    result = mutate_python("reorder-and-rename", source, "multi-function", seed=4)

    assert result.metadata.status == "mutated"
    status, detail = _run_python(
        tmp_path, result.source, "assert solution.second(3) == 8\n"
    )
    assert status == "passed", detail


def test_python_top_level_code_prevents_reordering_but_remains_behavioral(
    tmp_path: Path,
) -> None:
    source = (
        "def first(value):\n    return value + 1\n\n"
        "saved = first\n\ndef second(value):\n    return value * 2\n"
    )
    result = mutate_python("reorder-and-rename", source, "top-level", seed=4)

    assert result.metadata.status == "mutated"
    status, detail = _run_python(
        tmp_path,
        result.source,
        "assert solution.saved(2) == 3\nassert solution.second(3) == 6\n",
    )
    assert status == "passed", detail


def test_python_wrapped_class_keeps_exported_names_and_internal_calls(
    tmp_path: Path,
) -> None:
    result = mutate_python("wrap-in-class", PYTHON_CLASS_SAMPLE, "class-calls")

    status, detail = _run_python(
        tmp_path, result.source, "assert solution.add_twice(3) == 12\n"
    )
    assert status == "passed", detail


def test_typescript_multi_function_wrap_rewrites_static_calls(tmp_path: Path) -> None:
    _require_typescript_grammar()
    source = (
        "export function twice(value: number): number { return value * 2; }\n"
        "export function addTwice(value: number): number { "
        "return twice(value) + twice(value); }"
    )
    result = mutate_typescript("wrap-in-class", source, "ts-class-calls")

    assert result.metadata.status == "mutated"
    status, detail = _run_typescript(
        tmp_path, result.source, "if (solution.addTwice(3) !== 12) throw Error();\n"
    )
    assert status == "passed", detail


def test_typescript_multi_function_rename_runs_without_name_collisions(
    tmp_path: Path,
) -> None:
    _require_typescript_grammar()
    source = (
        "// café\n"
        "export function first(p0: number): number { "
        "const v0 = p0 + 1; return v0; }\n"
        "export function second(value: number): number { "
        "return first(value) * 2; }"
    )
    result = mutate_typescript("reorder-and-rename", source, "ts-multi", seed=3)

    status, detail = _run_typescript(
        tmp_path, result.source, "if (solution.second(3) !== 8) throw Error();\n"
    )
    assert result.metadata.status == "mutated"
    assert status == "passed", detail


def test_typescript_nested_closure_is_recorded_as_skipped() -> None:
    _require_typescript_grammar()
    source = (
        "export function outer(value: number): number { "
        "function inner() { return value; } return inner(); }"
    )
    result = mutate_typescript("reorder-and-rename", source, "ts-closure")

    assert result.metadata.status == "skipped"
    assert "closures" in result.metadata.skip_reason


def test_typescript_while_loop_is_recorded_as_skipped() -> None:
    _require_typescript_grammar()
    source = (
        "export function count(n: number): number { let total = 0; "
        "while (n > 0) { total += n; n--; } return total; }"
    )
    result = mutate_typescript("loops-to-recursion", source, "ts-while")

    assert result.metadata.status == "skipped"
    assert "while" in result.metadata.skip_reason


def test_cli_writes_pairable_mutations_and_metadata(tmp_path: Path) -> None:
    source_dir = tmp_path / "clean"
    output_dir = tmp_path / "mutants"
    source_dir.mkdir()
    (source_dir / "example.py").write_text(PYTHON_SAMPLE)

    cli_path = Path(__file__).resolve().parents[3] / "mutations" / "core" / "cli.py"
    process = subprocess.run(  # noqa: S603 - Runs the operator CLI against a temporary fixture.
        [
            sys.executable,
            str(cli_path),
            "--input-dir",
            str(source_dir),
            "--out",
            str(output_dir),
            "--language",
            "python",
            "--operator",
            "add-dead-branches",
            "--seed",
            "11",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert process.returncode == 0, process.stderr
    metadata_files = list(output_dir.rglob("*.json"))
    source_files = list(output_dir.rglob("*.mutant.py"))
    assert len(metadata_files) == 1
    assert len(source_files) == 1
    metadata = json.loads(metadata_files[0].read_text())
    assert metadata["metadata"]["pair_group_id"]
    assert metadata["base_path"] == "example.py"
    assert metadata["metadata"]["status"] == "mutated"


def test_cli_uses_distinct_exit_codes_for_invalid_args_and_bad_source(
    tmp_path: Path,
) -> None:
    cli_path = Path(__file__).resolve().parents[3] / "mutations" / "core" / "cli.py"
    invalid_args = subprocess.run(  # noqa: S603 - Verifies CLI rejection of invalid fixture arguments.
        [sys.executable, str(cli_path)],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    source_dir = tmp_path / "bad"
    source_dir.mkdir()
    (source_dir / "broken.py").write_text("def broken(:\n    pass\n")
    failed_input = subprocess.run(  # noqa: S603 - Verifies CLI handling of invalid fixture input.
        [
            sys.executable,
            str(cli_path),
            "--input-dir",
            str(source_dir),
            "--out",
            str(tmp_path / "failed-out"),
            "--language",
            "python",
            "--operator",
            "add-dead-branches",
        ],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert invalid_args.returncode == 2
    assert failed_input.returncode == 1


def test_typescript_syntax_check_does_not_claim_balanced_invalid_source_parses() -> (
    None
):
    _require_typescript_grammar()

    assert parses("typescript", "function broken( {") is False


def test_typescript_syntax_check_skips_without_cached_grammar(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("VARDE_TREE_SITTER_CACHE_DIR", str(tmp_path))

    assert parses("typescript", "function add(a: number) { return a; }") is False
    skipped = mutate_typescript("add-dead-branches", TYPESCRIPT_SAMPLE, "no-grammar")
    assert skipped.metadata.status == "skipped"
    assert "not cached" in skipped.metadata.skip_reason
