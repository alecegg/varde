"""Regression coverage for native crashes from tree-sitter Point access."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from item_spec_extract import extract

GRAMMAR_ROOT = Path(
    os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
)
GRAMMAR_CACHE = Path(
    os.environ.get(
        "VARDE_TREE_SITTER_CACHE_DIR",
        GRAMMAR_ROOT / "grammars" / "item-spec-v1",
    )
)
GRAMMAR_LIBS = GRAMMAR_CACHE / "tree-sitter-language-pack" / "v1.22.1" / "libs"
TOOLS = Path(__file__).resolve().parents[2] / "tools"
SAMPLE = "fn sample() -> i32 { 1 }"


def tool_env() -> dict[str, str]:
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(TOOLS), os.environ.get("PYTHONPATH", "")]),
        "VARDE_TREE_SITTER_CACHE_DIR": str(GRAMMAR_CACHE),
        "PYTHONMALLOC": "debug",
    }


def require_rust_grammar() -> None:
    if not list(GRAMMAR_LIBS.glob("libtree_sitter_rust.*")):
        pytest.skip(f"rust grammar not prefetched in {GRAMMAR_CACHE}")
    try:
        extract("rust", SAMPLE)
    except RuntimeError as error:
        pytest.skip(f"rust grammar unavailable: {error}")


def long_rust_source(function_count: int = 4, body_lines: int = 300) -> str:
    functions = []
    for index in range(function_count):
        body = "\n".join("    value += 1;" for _ in range(body_lines))
        functions.append(
            f"fn function_{index}() -> i32 {{\n    let mut value = 0;\n"
            f"{body}\n    value\n}}"
        )
    return "\n\n".join(functions) + "\n"


def test_tree_point_access_survives_large_function_rows() -> None:
    require_rust_grammar()
    source = long_rust_source()
    expected_lines = [304] * 4
    script = (
        "import json, sys; "
        "from item_spec_extract import extract; "
        "functions = extract('rust', sys.stdin.read()); "
        "print(json.dumps([function.lines for function in functions]))"
    )
    result = subprocess.run(  # noqa: S603 - Runs the item-spec extraction CLI against a fixture.
        [sys.executable, "-X", "faulthandler", "-c", script],
        input=source,
        capture_output=True,
        text=True,
        check=False,
        env=tool_env(),
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == expected_lines
