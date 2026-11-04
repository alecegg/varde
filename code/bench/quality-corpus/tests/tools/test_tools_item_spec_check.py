"""Behavior checks for the item specification command.

Every non-Python run points VARDE_TREE_SITTER_CACHE_DIR at an external,
prefetched grammar cache and never downloads a grammar. Tests that cannot load
a prefetched grammar skip with the parser's own grammar error.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from itertools import pairwise
from pathlib import Path

import item_spec_check
import item_spec_rules
import pytest
from item_spec_comments import comment_shape
from item_spec_extract import TOKEN, Function, extract
from item_spec_languages import EXTENSIONS, VERSIONS
from item_spec_metrics import depth, graph, reachable
from item_spec_quality import (
    entry_doc,
    entry_form,
    ids_opaque,
    patterned_ids,
    source_findings,
    unused_python_locals,
)
from item_spec_rules import ItemState, category_words, check_item
from item_spec_symbols import unused_symbols

GRAMMAR_ROOT = Path(
    os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
)
GRAMMAR_CACHE = GRAMMAR_ROOT / "grammars" / "item-spec-v1"
GRAMMAR_LIBS = GRAMMAR_CACHE / "tree-sitter-language-pack" / "v1.22.1" / "libs"
GRAMMAR_FILES = {
    "csharp": "c_sharp",
    "typescript": "typescript",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "cpp": "cpp",
}
TOOL = Path(__file__).resolve().parents[2] / "tools" / "item_spec_check.py"
SAMPLES = {
    "typescript": "function f(x: number) { return x; }",
    "java": "class A { int f(int x) { return x; } }",
    "csharp": "class A { int F(int x) { return x; } }",
    "go": "package main\nfunc f(x int) int { return x }",
    "rust": "fn f(x: i32) -> i32 { x }",
    "cpp": "int f(int x) { return x; }",
}


@pytest.fixture(autouse=True)
def _grammar_cache(monkeypatch):
    monkeypatch.setenv("VARDE_TREE_SITTER_CACHE_DIR", str(GRAMMAR_CACHE))


def tool_env() -> dict[str, str]:
    return {**os.environ, "VARDE_TREE_SITTER_CACHE_DIR": str(GRAMMAR_CACHE)}


def run_tool(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - Runs the item-spec CLI against a temporary fixture.
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
        env=tool_env(),
    )


def grammar_available(language: str) -> bool:
    return bool(list(GRAMMAR_LIBS.glob(f"libtree_sitter_{GRAMMAR_FILES[language]}.*")))


def require_grammar(language: str) -> None:
    if not grammar_available(language):
        pytest.skip(f"{language} grammar not prefetched in {GRAMMAR_CACHE}")
    try:
        extract(language, SAMPLES[language])
    except RuntimeError as error:
        pytest.skip(f"{language} grammar unavailable: {error}")


# --- small fixtures ---------------------------------------------------------


def write_item(root: Path, *, monolith_tokens: int = 220) -> Path:
    item = root / "invoice-aging"
    item.mkdir(parents=True)
    bodies = {
        "sensible": (
            "def solution(value):\n    return validate(value)\n\n"
            "def validate(value):\n    return value + 1\n"
        ),
        "monolith": "def solution(value):\n" + "    value += 1\n" * monolith_tokens,
        "tiny": "def solution(value):\n    return value\n",
        "padded": "def solution(value):\n    return value\n",
        "sizematched": "def solution(value):\n    return value\n",
        "namematched": "def solution(value):\n    return value\n",
    }
    for name, source in bodies.items():
        (item / f"{name}.py").write_text(source)
    (item / "pair.json").write_text('{"left":"sensible.py","right":"tiny.py"}\n')
    return item


LANGUAGE_ITEMS = {
    "python": (
        (
            'def solution(x):\n    """Entry docs."""\n    return x\n\n'
            "\ndef orphan():\n    return 0\n"
        ),
        "solution",
    ),
    "typescript": (
        (
            "/** Entry docs. */\nfunction solution(x: number) { return x; }\n"
            "function orphan() { return 0; }\n"
        ),
        "solution",
    ),
    "java": (
        (
            "class Sample { /** Entry docs. */ int solution(int x) { return x; } "
            "int orphan() { return 0; } }"
        ),
        "solution",
    ),
    "csharp": (
        (
            "class Sample { /// Entry docs.\nint Solution(int x) { return x; } "
            "int Orphan() { return 0; } }"
        ),
        "Solution",
    ),
    "go": (
        (
            "package main\n// Entry docs.\nfunc solution(x int) int { return x }\n"
            "func orphan() int { return 0 }\n"
        ),
        "solution",
    ),
    "rust": (
        "/// Entry docs.\nfn solution(x: i32) -> i32 { x }\nfn orphan() -> i32 { 0 }\n",
        "solution",
    ),
    "cpp": (
        (
            "/// Entry docs.\nint solution(int x) { return x; }\n"
            "int orphan() { return 0; }\n"
        ),
        "solution",
    ),
}


@pytest.mark.parametrize("language", ["python", *LANGUAGE_ITEMS.keys() - {"python"}])
def test_source_rules_find_unused_declaration_for_each_language(tmp_path, language):
    if language != "python":
        require_grammar(language)
    source, _ = LANGUAGE_ITEMS[language]
    sources = dict.fromkeys(VERSIONS, source)
    findings = source_findings(
        tmp_path,
        language,
        sources,
        {v: type("Entry", (), {"name": "solution"})() for v in VERSIONS},
    )
    assert any(
        f["kind"] == "unused_symbol" and f["function"] in {"orphan", "Orphan"}
        for f in findings
    )


@pytest.mark.parametrize("language", LANGUAGE_ITEMS)
def test_entry_doc_and_declaration_form_parity_for_each_language(language):
    if language != "python":
        require_grammar(language)
    source, entry = LANGUAGE_ITEMS[language]
    assert entry_doc(language, source, entry) == "Entry docs."
    assert entry_form(language, source, entry) in {"function declaration", "method"}


def test_entry_doc_parity_reports_one_corrupted_docstring(tmp_path):
    sources = dict.fromkeys(VERSIONS, LANGUAGE_ITEMS["python"][0])
    sources["tiny"] = sources["tiny"].replace(
        "Entry docs.", "Build a orderedTable tournament table"
    )
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    findings = source_findings(tmp_path, "python", sources, entries)
    assert any(f["kind"] == "entry_doc_text_parity" for f in findings)


def test_entry_doc_parity_reports_missing_documentation(tmp_path):
    sources = dict.fromkeys(VERSIONS, LANGUAGE_ITEMS["python"][0])
    sources["tiny"] = sources["tiny"].replace('    """Entry docs."""\n', "")
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    findings = source_findings(tmp_path, "python", sources, entries)
    assert any(f["kind"] == "entry_doc_text_parity" for f in findings)


@pytest.mark.parametrize("language", LANGUAGE_ITEMS)
def test_entry_doc_parity_reports_corruption_for_each_language(tmp_path, language):
    if language != "python":
        require_grammar(language)
    source, entry = LANGUAGE_ITEMS[language]
    sources = dict.fromkeys(VERSIONS, source)
    sources["tiny"] = source.replace(
        "Entry docs.", "Build a orderedTable tournament table"
    )
    entries = {version: type("Entry", (), {"name": entry})() for version in VERSIONS}
    findings = source_findings(tmp_path, language, sources, entries)
    assert any(f["kind"] == "entry_doc_text_parity" for f in findings)


@pytest.mark.parametrize(
    "language,entry,source",
    [
        (
            "go",
            "solution",
            (
                "package main\n// First line.\n// Second line.\n"
                "func solution() int { return 1 }\n"
            ),
        ),
        (
            "rust",
            "solution",
            "/// First line.\n/// Second line.\nfn solution() -> i32 { 1 }\n",
        ),
    ],
)
def test_entry_doc_joins_adjacent_line_comments(language, entry, source):
    require_grammar(language)
    assert entry_doc(language, source, entry) == "First line. Second line."


@pytest.mark.parametrize(
    "language,source",
    [
        (
            "go",
            "package main\n// Old docs.\nfunc previous() {}\n\nfunc solution() {}\n",
        ),
        ("rust", "/// Old docs.\nfn previous() {}\n\nfn solution() {}\n"),
    ],
)
def test_entry_doc_requires_attached_comment(language, source):
    require_grammar(language)
    assert entry_doc(language, source, "solution") == ""


def test_entry_doc_allows_attributes_between_comment_and_declaration():
    require_grammar("rust")
    source = "/// Entry docs.\n#[inline]\nfn solution() -> i32 { 1 }\n"
    assert entry_doc("rust", source, "solution") == "Entry docs."


def test_typescript_exported_const_doc_and_declaration_kinds():
    require_grammar("typescript")
    arrow = "/** Entry docs. */\nexport const solution = (x: number) => x;"
    function = "export const solution = function(x: number) { return x; };"
    assert entry_doc("typescript", arrow, "solution") == "Entry docs."
    assert entry_form("typescript", arrow, "solution") == "arrow-const"
    assert entry_form("typescript", function, "solution") == "function-expression-const"


@pytest.mark.parametrize(
    "language,source",
    [
        ("go", "package main\ntype Sample struct { field int }\n"),
        ("rust", "struct Sample { field: i32 }\n"),
    ],
)
def test_struct_fields_are_not_top_level_symbols(language, source):
    require_grammar(language)
    assert "field" not in unused_symbols(language, source, "solution")


def test_cpp_using_namespace_std_is_exempt():
    require_grammar("cpp")
    assert "std" not in unused_symbols(
        "cpp", "using namespace std;\nint solution() { return 0; }", "solution"
    )


@pytest.mark.parametrize(
    "declaration,name",
    [
        ("struct Record { int field; };", "Record"),
        ("typedef int Count;", "Count"),
        ("class Widget {};", "Widget"),
        ("using Count = int;", "Count"),
    ],
)
def test_cpp_top_level_declaration_kinds_are_checked(declaration, name):
    require_grammar("cpp")
    source = declaration + "\nint solution() { return 0; }"
    assert name in unused_symbols("cpp", source, "solution")


@pytest.mark.parametrize(
    "language,source",
    [
        (
            "typescript",
            (
                "function solution() {}\n"
                "function overloaded(x: number): number;\n"
                "function overloaded(x: string): string;\n"
                "function overloaded(x: any): any { return x; }\n"
            ),
        ),
        (
            "java",
            (
                "class A { void solution() {} int overloaded(int x) { return x; } "
                "String overloaded(String x) { return x; } }"
            ),
        ),
    ],
)
def test_overloaded_names_are_counted_as_one_symbol(language, source):
    require_grammar(language)
    assert "overloaded" in unused_symbols(language, source, "solution")
    if language == "typescript":
        source += "\nconst x = overloaded(1);"
    else:
        source = source.replace(
            "void solution() {}", "void solution() { overloaded(1); }"
        )
    assert "overloaded" not in unused_symbols(language, source, "solution")


@pytest.mark.parametrize("language", ["python", "typescript"])
def test_entry_declaration_form_mismatch_is_reported(language, tmp_path):
    if language == "python":
        function = 'def solution(x):\n    """Entry docs."""\n    return x\n'
        alternate = "solution = lambda x: x\n"
    else:
        function = (
            "/** Entry docs. */\nexport function solution(x: number) { return x; }\n"
        )
        alternate = "export const solution = (x: number) => x;\n"
    sources = dict.fromkeys(VERSIONS, function)
    sources["tiny"] = alternate
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    findings = source_findings(tmp_path, language, sources, entries)
    assert any(f["kind"] == "entry_declaration_form" for f in findings)


@pytest.mark.parametrize("language", LANGUAGE_ITEMS)
def test_entry_declaration_form_mismatch_for_each_language(language, tmp_path):
    if language != "python":
        require_grammar(language)
    _, entry = LANGUAGE_ITEMS[language]
    alternates = {
        "python": "solution = lambda x: x\n",
        "typescript": "export const solution = (x: number) => x;\n",
        "java": (
            "class Sample { static java.util.function.IntUnaryOperator "
            "solution = x -> x; }"
        ),
        "csharp": "class Sample { static System.Func<int, int> Solution = x => x; }",
        "go": "package main\nvar solution = func(x int) int { return x }\n",
        "rust": "static SOLUTION: fn(i32) -> i32 = |x| x;\n",
        "cpp": "auto solution = [](int x) { return x; };\n",
    }
    sources = dict.fromkeys(VERSIONS, LANGUAGE_ITEMS[language][0])
    sources["tiny"] = alternates[language]
    entries = {version: type("Entry", (), {"name": entry})() for version in VERSIONS}
    findings = source_findings(tmp_path, language, sources, entries)
    assert any(finding["kind"] == "entry_declaration_form" for finding in findings)


def test_pair_ids_reject_shared_long_prefix_and_arithmetic_progression():
    assert patterned_ids(["1234567890abcdef", "1234567890abcdee"])
    assert patterned_ids(["0000000000000001", "0000000000000003", "0000000000000005"])
    assert not patterned_ids(["item-1", "item-2"])
    assert not patterned_ids(["a1f04c8890360b77", "8db4f9c26310a5e2"])


def test_pair_id_opaque_rejects_non_hex_identifiers():
    assert not ids_opaque(["item-1", "item-2"])


def test_checker_reports_non_opaque_pair_ids(tmp_path):
    source, _ = LANGUAGE_ITEMS["python"]
    sources = dict.fromkeys(VERSIONS, source)
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    (tmp_path / "pair.json").write_text('{"left_id":"item-1", "right_id":"item-2"}')
    findings = source_findings(tmp_path, "python", sources, entries)
    assert any(f["kind"] == "pair_id_not_opaque" for f in findings)


def test_random_pair_ids_have_no_pattern_false_positives():
    import random

    rng = random.Random(815)  # noqa: S311 - Deterministic test data generation is not cryptographic.
    for _ in range(10_000):
        values = [f"{rng.getrandbits(128):032x}" for _ in range(6)]
        assert not patterned_ids(values)


def test_item_checker_reports_patterned_pair_ids(tmp_path):
    source = LANGUAGE_ITEMS["python"][0]
    sources = dict.fromkeys(VERSIONS, source)
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    (tmp_path / "pair.json").write_text(
        '{"left_id":"1234567890abcdef", "right_id":"1234567890abcdee"}'
    )
    findings = source_findings(tmp_path, "python", sources, entries)
    assert any(finding["kind"] == "pair_id_opaque" for finding in findings)


@pytest.mark.parametrize("language", LANGUAGE_ITEMS)
def test_line_width_rule_reports_long_lines_for_each_language(tmp_path, language):
    if language != "python":
        require_grammar(language)
    source, entry = LANGUAGE_ITEMS[language]
    comment = "#" if language == "python" else "//"
    sources = dict.fromkeys(VERSIONS, source + "\n" + comment + " x" * 60 + "\n")
    entries = {version: type("Entry", (), {"name": entry})() for version in VERSIONS}
    findings = source_findings(tmp_path, language, sources, entries)
    assert any(finding["kind"] == "line_too_long" for finding in findings)


def test_source_rules_report_long_lines_and_python_unused_locals(tmp_path):
    source = (
        'def solution(x):\n    """Entry docs."""\n    unused = 2\n'
        + "    return x  # "
        + "x" * 90
        + "\n"
    )
    assert unused_python_locals(source) == ["unused"]
    sources = dict.fromkeys(VERSIONS, source)
    entries = {
        version: type("Entry", (), {"name": "solution"})() for version in VERSIONS
    }
    findings = source_findings(tmp_path, "python", sources, entries)
    assert any(f["kind"] == "line_too_long" for f in findings)
    assert any(
        f["kind"] == "unused_local" and f["function"] == "unused" for f in findings
    )


def test_python_local_scope_reads_and_pyflakes_assignment_rules():
    source = """def solution():
    y = 1
    def nested():
        return y
    for loop_value in ():
        pass
    first, second = (1, 2)
    w = 0
    w += 1
    return nested()
"""
    assert unused_python_locals(source) == []


def test_python_nested_local_shadow_does_not_read_outer_assignment():
    source = """def solution():
    shadowed = 1
    def nested():
        shadowed = 2
        return shadowed
    return nested()
"""
    assert unused_python_locals(source) == ["shadowed"]


def test_python_self_recursion_does_not_make_top_level_symbol_used():
    assert "rec" in unused_symbols(
        "python",
        "def solution(): return 0\ndef rec(n): return rec(n - 1) if n else 0\n",
        "solution",
    )


# --- extractor --------------------------------------------------------------


def test_extract_python_metrics():
    functions = extract(
        "python",
        "def solution(x):\n    if x:\n        return helper(x)\n    return 0\n",
    )
    assert [(f.name, f.calls, f.complexity) for f in functions] == [
        ("solution", ["helper"], 1)
    ]


def test_python_attribute_calls_use_the_simple_name():
    functions = extract(
        "python",
        "class A:\n    def solution(self, x):\n        return self.helper(x)\n",
    )
    assert functions[0].calls == ["helper"]


def test_nested_function_is_counted_once_and_excluded_from_outer_calls():
    functions = extract(
        "python",
        "def solution():\n    def inner():\n        return hidden()\n    return 1\n",
    )
    assert [function.name for function in functions] == ["solution", "inner"]
    assert functions[0].calls == []


def test_function_value_inside_nested_python_function_is_excluded_from_outer():
    functions = extract(
        "python",
        (
            "def solution():\n    def inner(): return helper\n    return 1\n\n"
            "def helper(x): return x\n"
        ),
    )
    assert functions[0].calls == []


def test_python_function_value_resolution_handles_all_parameter_kinds():
    source = (
        "def solution(pos, /, helper=None, *args, kwonly=0, **kwargs):\n"
        "    return helper\n\n"
        "def helper(x): return x\n"
    )
    assert graph(extract("python", source))["solution"] == []


def test_python_member_calls_stay_in_calls_but_do_not_resolve_as_function_edges():
    source = (
        "def solution(pattern, text):\n"
        "    match = pattern.match(text)\n"
        "    return match.group(1)\n\n"
        "def match(value): return value\n"
        "def group(value): return value\n"
    )
    functions = extract("python", source)
    solution = next(function for function in functions if function.name == "solution")
    assert solution.calls == ["match", "group"]
    assert graph(functions)["solution"] == []


def test_python_lambda_and_comprehension_targets_shadow_function_values():
    source = (
        "solution = lambda helper: helper\n"
        "def other(items): return [helper for helper in items]\n"
        "def helper(x): return x\n"
    )
    calls = graph(extract("python", source))
    assert calls["solution"] == []
    assert calls["other"] == []


def test_nested_python_function_defaults_are_outer_scope_references():
    source = (
        "def solution():\n"
        "    def nested(value=helper, *, alternate=helper): return value\n"
        "    return nested()\n\n"
        "def helper(): return 1\n"
    )
    assert "helper" in graph(extract("python", source))["solution"]


def test_nested_branch_and_tokens_are_excluded_from_the_outer_function():
    functions = extract(
        "python",
        (
            "def solution():\n    def inner():\n        if x:\n"
            "            return hidden()\n    return 1\n"
        ),
    )
    assert functions[0].tokens == 7
    assert functions[0].complexity == 0
    assert functions[0].calls == []
    assert functions[1].complexity == 1


def test_named_python_lambda_is_extracted_as_its_variable():
    function = extract("python", "solution = lambda value: value + 1")[0]
    assert function.name == "solution"
    assert function.signature


def test_call_graph_keeps_distinct_same_file_callees_only():
    functions = extract(
        "python",
        "def solution(v):\n    return helper(v) + helper(v) + len(v)\n\n"
        "def helper(v):\n    return v\n",
    )
    assert graph(functions) == {"solution": ["helper"], "helper": []}


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "python",
            (
                "def solution(xs):\n    return map(helper, xs)\n\n"
                "def helper(x):\n    return x\n"
            ),
        ),
        (
            "typescript",
            (
                "function solution(xs: number[]) { return xs.map(helper); }\n"
                "function helper(x: number) { return x; }"
            ),
        ),
        (
            "go",
            (
                "package main\n"
                "func solution(xs []int) { _ = slices.SortFunc(xs, helper) }\n"
                "func helper(a, b int) int { return a - b }"
            ),
        ),
        (
            "rust",
            (
                "fn solution(xs: Vec<i32>) -> Vec<i32> { "
                "xs.into_iter().map(helper).collect() }\n"
                "fn helper(x: i32) -> i32 { x }"
            ),
        ),
    ],
)
def test_function_value_references_create_call_edges(language, source):
    if language != "python":
        require_grammar(language)
    functions = extract(language, source)
    assert graph(functions)["solution"] == ["helper"]


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "python",
            (
                "def solution(o):\n    helper = 1\n    return o.helper + helper\n\n"
                "def helper(x): return x\n"
            ),
        ),
        (
            "typescript",
            (
                "function solution(o: any) { const {helper} = o; const x = {helper: 1}; "
                "return o.helper + x.helper + helper; }\n"
                "function helper(x: number) { return x; }"
            ),
        ),
        (
            "go",
            (
                "package main\ntype T struct { helper int }\n"
                "func solution(o T) { helper := 1; _ = T{helper: 1}; _ = o.helper; _ = helper }\n"
                "func helper(x int) int { return x }"
            ),
        ),
        (
            "rust",
            (
                "struct T { helper: i32 }\n"
                "fn solution(o: T) { let helper = 1; let _x = T { helper: 1 }; "
                "let _y = o.helper; let _z = helper; }\n"
                "fn helper(x: i32) -> i32 { x }"
            ),
        ),
        (
            "java",
            (
                "class A { int helper(int x) { return x; } "
                "int solution(A o) { int helper = 1; Object x = o.helper; return helper; } }"
            ),
        ),
        (
            "cpp",
            (
                "struct P { int helper; }; int helper(int x) { return x; } "
                "int solution(P o) { int helper = 1; auto x = o.helper; return helper; }"
            ),
        ),
    ],
)
def test_local_fields_and_keys_do_not_create_function_value_edges(language, source):
    if language != "python":
        require_grammar(language)
    functions = extract(language, source)
    assert graph(functions)["solution"] == []


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "python",
            "def solution(xs): return map(helper, xs)\ndef helper(x): return x\n",
        ),
        (
            "typescript",
            (
                "function solution(xs: number[]) { return xs.map(helper); }\n"
                "function helper(x: number) { return x; }"
            ),
        ),
        (
            "go",
            (
                "package main\nfunc solution(xs []int) { consume(helper) }\n"
                "func consume(f func(int) int) {}\nfunc helper(x int) int { return x }"
            ),
        ),
        (
            "rust",
            (
                "fn solution(xs: Vec<i32>) -> Vec<i32> { "
                "xs.into_iter().map(helper).collect() }\nfn helper(x: i32) -> i32 { x }"
            ),
        ),
        (
            "java",
            (
                "import java.util.function.Function; class A { int helper(int x) { return x; } "
                "int solution() { Function<Integer, Integer> f = this::helper; "
                "return f.apply(1); } }"
            ),
        ),
        (
            "cpp",
            (
                "int helper(int x) { return x; } int apply(int (*f)(int)) { return f(1); } "
                "int solution() { return apply(helper); }"
            ),
        ),
    ],
)
def test_real_function_values_create_call_graph_edges(language, source):
    if language != "python":
        require_grammar(language)
    functions = extract(language, source)
    assert "helper" in graph(functions)["solution"]


@pytest.mark.parametrize(
    ("language", "source"),
    [
        ("python", "def helper(x): return helper(x)\n"),
        ("typescript", "function helper(x: number): number { return helper(x); }"),
        ("go", "package main\nfunc helper(x int) int { return helper(x) }"),
        ("rust", "fn helper(x: i32) -> i32 { helper(x) }"),
        ("java", "class A { int helper(int x) { return helper(x); } }"),
        ("cpp", "int helper(int x) { return helper(x); }"),
    ],
)
def test_recursive_function_still_has_self_edge(language, source):
    if language != "python":
        require_grammar(language)
    assert graph(extract(language, source))["helper"] == ["helper"]


@pytest.mark.parametrize(
    ("language", "source"),
    [
        (
            "python",
            (
                "def solution(helper):\n    return helper\n\n"
                "def helper(x):\n    return x\n"
            ),
        ),
        (
            "typescript",
            (
                "function solution(helper: (x: number) => number) { return helper(1); }\n"
                "function helper(x: number) { return x; }"
            ),
        ),
    ],
)
def test_shadowed_function_name_does_not_create_edge(language, source):
    if language != "python":
        require_grammar(language)
    assert graph(extract(language, source))["solution"] == []


def test_public_checker_applies_language_specific_row_caps(tmp_path):
    for language, extension, source, violates in (
        (
            "python",
            ".py",
            "def solution(x):\n    a = x\n    b = a\n    return b\n",
            True,
        ),
        (
            "go",
            ".go",
            (
                "package main\nfunc solution(x int) int {\n a := x\n b := a\n"
                " return b\n}\n"
            ),
            False,
        ),
    ):
        if language != "python":
            require_grammar(language)
        item = tmp_path / language
        item.mkdir()
        for version in VERSIONS:
            (item / f"{version}{extension}").write_text(source)
        findings, _ = check_item(item, language)
        has_row_violation = any(
            finding["kind"] == "tiny_function_lines" for finding in findings
        )
        assert has_row_violation is violates


@pytest.mark.parametrize(
    ("language", "used", "source"),
    [
        ("python", True, "import math\ndef solution(x): return math.floor(x)\n"),
        ("python", False, "import math\ndef solution(x): return x\n"),
        (
            "go",
            True,
            (
                'package main\nimport "strconv"\n'
                "func solution() string { return strconv.Itoa(1) }\n"
            ),
        ),
        (
            "go",
            False,
            'package main\nimport "strconv"\nfunc solution() int { return 1 }\n',
        ),
        (
            "typescript",
            True,
            (
                'import { floor } from "math"; '
                "function solution(x: number) { return floor(x); }"
            ),
        ),
        (
            "typescript",
            False,
            'import { floor } from "math"; function solution(x: number) { return x; }',
        ),
        (
            "java",
            True,
            "import java.util.List; class A { List solution() { return List.of(); } }",
        ),
        (
            "java",
            False,
            "import java.util.List; class A { int solution() { return 1; } }",
        ),
        (
            "csharp",
            True,
            (
                "using System; class A { int Solution() { "
                "System.Console.WriteLine(1); return 1; } }"
            ),
        ),
        ("csharp", False, "using System; class A { int Solution() { return 1; } }"),
    ],
)
def test_import_is_used_only_by_references_outside_its_declaration(
    tmp_path, language, used, source
):
    if language != "python":
        require_grammar(language)
    name = {
        "python": "math",
        "go": "strconv",
        "typescript": "floor",
        "java": "List",
        "csharp": "System",
    }[language]
    item = tmp_path / f"{language}-import"
    item.mkdir()
    for version in VERSIONS:
        (item / f"{version}{EXTENSIONS[language]}").write_text(source)
    findings, _ = check_item(item, language)
    flagged = any(
        finding["kind"] == "unused_symbol" and finding["function"] == name
        for finding in findings
    )
    assert flagged is (not used)


@pytest.mark.parametrize(
    ("language", "name", "source"),
    [
        ("python", "math", "import math\n# math\ndef solution(): return 'math'\n"),
        (
            "typescript",
            "floor",
            (
                'import { floor } from "math"; // floor\n'
                'function solution() { return "floor"; }'
            ),
        ),
        (
            "typescript",
            "m",
            'import * as m from "math"; function solution() { return 1; }',
        ),
        (
            "go",
            "strconv",
            (
                'package main\nimport "strconv"\n// strconv\n'
                'func solution() string { return "strconv" }\n'
            ),
        ),
        (
            "java",
            "List",
            "import java.util.List; /* List */ class A { int solution() { return 1; } }",
        ),
    ],
)
def test_comments_strings_and_unused_namespace_imports_do_not_count_as_import_use(
    tmp_path, language, name, source
):
    if language != "python":
        require_grammar(language)
    item = tmp_path / f"{language}-unused-import"
    item.mkdir()
    for version in VERSIONS:
        (item / f"{version}{EXTENSIONS[language]}").write_text(source)
    findings, _ = check_item(item, language)
    assert any(
        finding["kind"] == "unused_symbol" and finding["function"] == name
        for finding in findings
    )


def test_csharp_using_system_reference_is_not_flagged(tmp_path):
    require_grammar("csharp")
    source = (
        "using System; class A { int Solution() { System.Console.WriteLine(1); "
        "return 1; } }"
    )
    item = tmp_path / "csharp-using"
    item.mkdir()
    for version in VERSIONS:
        (item / f"{version}{EXTENSIONS['csharp']}").write_text(source)
    findings, _ = check_item(item, "csharp")
    assert not any(
        finding["kind"] == "unused_symbol" and finding["function"] == "System"
        for finding in findings
    )


def test_csharp_using_names_from_other_using_directives_is_unused(tmp_path):
    require_grammar("csharp")
    source = "using System; using System.Linq; class A { int Solution() { return 1; } }"
    item = tmp_path / "csharp-unused-system-import"
    item.mkdir()
    for version in VERSIONS:
        (item / f"{version}{EXTENSIONS['csharp']}").write_text(source)
    findings, _ = check_item(item, "csharp")
    assert any(
        finding["kind"] == "unused_symbol" and finding["function"] == "System"
        for finding in findings
    )


def test_csharp_solution_container_is_exempt_and_other_classes_are_not():
    require_grammar("csharp")
    container = (
        "public static class Solution { public static int solution(int x) => x + 1; }"
    )
    assert "Solution" not in unused_symbols("csharp", container, "solution")
    stray = (
        "class Orphan { }\n"
        "public static class Solution { public static int solution(int x) => x + 1; }"
    )
    assert unused_symbols("csharp", stray, "solution") == ["Orphan"]


def test_csharp_function_values_exclude_member_initializer_and_argument_labels():
    require_grammar("csharp")
    source = """
class C {
    int Helper;
    void F(C o) { _ = o.Helper; }
    void G() { _ = new C { Helper = 1 }; }
    void L() { Apply(Helper: 1); Apply(Helper); }
    void Helper(int value) { }
    void Apply(object value) { }
}
"""
    functions = extract("csharp", source)
    edges = graph(functions)
    assert edges["F"] == []
    assert edges["G"] == []
    assert edges["L"] == ["Apply", "Helper"]


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        ("typescript", "f"),
        ("java", "f"),
        ("csharp", "F"),
        ("go", "f"),
        ("rust", "f"),
        ("cpp", "f"),
    ],
)
def test_tree_function_names_match_the_language(language, expected):
    require_grammar(language)
    assert [function.name for function in extract(language, SAMPLES[language])] == [
        expected
    ]


def test_typescript_arrow_and_method_names():
    require_grammar("typescript")
    source = (
        "const solution = (x: number) => x;"
        "class A { run() { return this.step(); } step() { return 1; } }"
    )
    functions = extract("typescript", source)
    assert [function.name for function in functions] == ["solution", "run", "step"]
    assert functions[1].calls == ["step"]


def test_typescript_arrow_argument_keeps_no_parameter_name():
    require_grammar("typescript")
    function = extract("typescript", "const total = xs => xs;")[0]
    assert function.name == "total"


def test_csharp_method_name_is_not_the_return_type():
    require_grammar("csharp")
    source = "class A { Order Solution(int x) { return x; } }"
    assert extract("csharp", source)[0].name == "Solution"


def test_csharp_and_java_class_methods_are_extracted():
    for language, source, names in (
        (
            "csharp",
            (
                "class A { int First(int x) { return Second(x); } "
                "int Second(int x) { return x; } }"
            ),
            ["First", "Second"],
        ),
        (
            "java",
            (
                "class A { int first(int x) { return second(x); } "
                "int second(int x) { return x; } }"
            ),
            ["first", "second"],
        ),
    ):
        require_grammar(language)
        assert [f.name for f in extract(language, source)] == names


def test_rust_impl_method_is_extracted():
    require_grammar("rust")
    source = "impl A { fn solution(x: i32) -> i32 { x } }"
    assert extract("rust", source)[0].name == "solution"


def test_cpp_names_come_from_the_declarator_chain():
    require_grammar("cpp")
    assert extract("cpp", "int* solution(int x) { return &x; }")[0].name == "solution"
    assert extract("cpp", "static int Foo::bar(int y) { return y; }")[0].name == "bar"
    assert extract("cpp", "auto lam = [](int v) { return v; };")[0].name == "lam"


def test_go_and_java_and_csharp_lambdas_are_extracted():
    samples = (
        (
            "go",
            "package main\nfunc m() { f := func(x int) int { return x }; _ = f }",
            "f",
        ),
        (
            "java",
            "class A { void m() { java.util.function.IntUnaryOperator f = v -> v; } }",
            "f",
        ),
        ("csharp", "class A { void M() { System.Func<int, int> f = v => v; } }", "f"),
        ("rust", "fn m() { let f = |x: i32| x + 1; }", "f"),
    )
    for language, source, expected in samples:
        require_grammar(language)
        assert expected in [f.name for f in extract(language, source)]


def test_tree_nested_function_is_excluded_from_outer_metrics():
    require_grammar("typescript")
    source = (
        "function solution(v: number) {\n"
        "  function inner() { return hidden(); }\n"
        "  return 1;\n"
        "}"
    )
    functions = extract("typescript", source)
    assert [f.name for f in functions] == ["solution", "inner"]
    assert functions[0].calls == []


@pytest.mark.parametrize(
    ("language", "source", "expected"),
    [
        ("python", "def solution(v):\n    if v: return a(v)\n", 1),
        ("python", "def solution(v):\n    if v:\n        if v: return a(v)\n", 3),
        (
            "python",
            (
                "def solution(v):\n    if v: return 1\n    elif v: return 2\n"
                "    else: return 3\n"
            ),
            3,
        ),
        ("python", "def solution(v):\n    if v and v and v: return 1\n", 2),
        ("python", "def solution(v):\n    if v and v or v: return 1\n", 3),
        ("python", "def solution(v):\n    for x in v:\n        if x: return x\n", 3),
        (
            "python",
            (
                "def solution(v):\n    match v:\n        case 1: return 1\n"
                "        case _: return 2\n"
            ),
            1,
        ),
        (
            "python",
            (
                "def solution(v):\n    match v:\n        case 1: return 1\n"
                "        case 2: return 2\n        case _: return 3\n"
            ),
            1,
        ),
        ("python", "def solution(v):\n    return solution(v)\n", 1),
        (
            "python",
            (
                "def solution(v):\n    try:\n        return a(v)\n"
                "    except ValueError:\n        return 1\n"
            ),
            1,
        ),
        ("python", "def solution(v):\n    return 1 if v else 2\n", 1),
        ("typescript", "function solution(v: number){ if(v){a();} }", 1),
        (
            "typescript",
            "function solution(v: number){ if(v){a();} else if(v){b();} else {c();} }",
            3,
        ),
        ("typescript", "function solution(v: number){ if(v && v && v){a();} }", 2),
        ("typescript", "function solution(v: number){ if(v && v || v){a();} }", 3),
        ("typescript", "function solution(v: number){ for(;;){ if(v){a();} } }", 3),
        (
            "typescript",
            "function solution(v: number){ switch(v){case 1: a(); break; default: b();} }",
            1,
        ),
        (
            "typescript",
            "function solution(v: number){ if(v){ switch(v){case 1: a(); break; default: b();} } }",
            3,
        ),
        ("typescript", "function solution(v: number){ return solution(v); }", 1),
        (
            "java",
            "class A { int solution(int v){ if(v>0){a();} else {b();} return v; } }",
            2,
        ),
        (
            "java",
            (
                "class A { int solution(int v){ switch(v){case 1: a(); break; "
                "case 2: b(); break; case 3: c(); break; default: d();} return v; } }"
            ),
            1,
        ),
        (
            "csharp",
            "class A { int solution(int v){ switch(v){case 1: a(); break; default: b();} return v; } }",
            1,
        ),
        (
            "go",
            (
                "package main\nfunc solution(v int) int { if v>0 {a()} else if v<0 {b()} "
                "else {c()}; return v }"
            ),
            3,
        ),
        ("rust", "fn solution(v: i32) -> i32 { match v { 1 => a(), _ => b() } }", 1),
        (
            "rust",
            "fn solution(v: i32) -> i32 { match v { 1 => a(), 2 => b(), _ => c() } }",
            1,
        ),
        (
            "cpp",
            "int solution(int v){ if(v>0){a();} else if(v<0){b();} else {c();} return v; }",
            3,
        ),
    ],
)
def test_cognitive_complexity(language, source, expected):
    if language != "python":
        require_grammar(language)
    assert extract(language, source)[0].complexity == expected


# --- anonymous functions, signatures, comments, category words -------------


def test_anonymous_python_lambda_stays_in_its_parent():
    functions = extract(
        "python",
        "def solution(xs):\n    return list(map(lambda x: helper(x), xs))\n",
    )
    assert [function.name for function in functions] == ["solution"]
    assert functions[0].calls == ["list", "map", "helper"]


def test_anonymous_lambda_tokens_stay_with_the_parent():
    plain = extract("python", "def solution(v):\n    return 1\n")[0].tokens
    with_lambda = extract("python", "def solution(v):\n    return (lambda x: x)(v)\n")[
        0
    ].tokens
    assert with_lambda > plain


def test_typescript_anonymous_arrow_keeps_calls_and_branches():
    require_grammar("typescript")
    source = (
        "function helper(x: number) { return x; }\n"
        "function solution(xs: number[]) { return xs.map(x => helper(x)); }"
    )
    functions = extract("typescript", source)
    solution = next(f for f in functions if f.name == "solution")
    assert solution.calls == ["map", "helper"]
    assert graph(functions)["solution"] == ["helper"]
    ternary = extract(
        "typescript", "function solution(xs: number) { return xs.map(x => x ? 1 : 2); }"
    )[0]
    assert ternary.complexity == 1


@pytest.mark.parametrize(
    ("language", "int_source", "str_source"),
    [
        (
            "typescript",
            "function solution(x: number): number { return x; }",
            "function solution(x: number): string { return ''; }",
        ),
        (
            "java",
            "class A { int solution(int x) { return x; } }",
            "class A { long solution(int x) { return x; } }",
        ),
        (
            "csharp",
            "class A { int Solution(int x) { return x; } }",
            'class A { string Solution(int x) { return ""; } }',
        ),
        (
            "go",
            "package main\nfunc solution(x int) int { return x }",
            'package main\nfunc solution(x int) string { return "" }',
        ),
        (
            "rust",
            "fn solution(x: i32) -> i32 { x }",
            "fn solution(x: i32) -> String { String::new() }",
        ),
        (
            "cpp",
            "int solution(int x) { return x; }",
            "long solution(int x) { return x; }",
        ),
    ],
)
def test_tree_signature_includes_return_types(language, int_source, str_source):
    require_grammar(language)
    assert (
        extract(language, int_source)[0].signature
        != extract(language, str_source)[0].signature
    )


def test_python_signature_includes_return_annotation():
    annotated = extract("python", "def solution(x) -> int:\n    return x\n")[0]
    other = extract("python", "def solution(x) -> str:\n    return x\n")[0]
    assert annotated.signature != other.signature
    assert "->" in annotated.signature or "returns" in annotated.signature


def test_python_signature_keeps_parameter_types():
    typed = extract("python", "def solution(x: int):\n    return x\n")[0]
    plain = extract("python", "def solution(x):\n    return x\n")[0]
    assert typed.signature != plain.signature


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("const stepCount = 1;", ["step"]),
        ("const getCore = 1;", ["core"]),
        ("const tinyThing = 1;", ["tiny"]),
        ("const steps = 1;", ["step"]),
        ("const leaf_nodes = 1;", ["leaf"]),
        ("const stageLimit = 1;", ["stage"]),
        ("const stepwise = 1;", []),
        ("const backstage = 1;", []),
        ("const score = 1;", []),
        ("// a step forward", ["step"]),
        ('const s = "hop";', ["hop"]),
    ],
)
def test_category_words_split_identifiers(text, expected):
    assert category_words(text) == expected


def test_comment_shape_uses_real_comments_not_literals():
    assert comment_shape("python", 'x = "# not a comment"\n') == (0, "short")
    assert comment_shape("python", "# real\nx = 1\n")[0] == 1
    assert comment_shape("python", 'def f():\n    """doc"""\n')[0] == 1


def test_tree_comment_shape_uses_comment_nodes():
    require_grammar("typescript")
    assert comment_shape("typescript", 'const s = "// not a comment";')[0] == 0
    assert comment_shape("typescript", "// real\nconst s = 1;")[0] == 1


# --- conforming items per language ------------------------------------------

TINY_TARGET = 90


@dataclass(frozen=True)
class Lang:
    name: str
    ext: str
    entry_param: str
    param: str
    preamble: str = ""
    class_name: str = ""

    def let(self, name: str, expr: str) -> str:
        if self.name == "python":
            return f"{name} = {expr}"
        if self.name == "go":
            return f"{name} := {expr}"
        if self.name == "rust":
            return f"let mut {name} = {expr};"
        if self.name == "typescript":
            return f"let {name} = {expr};"
        return f"int {name} = {expr};"

    def assign(self, name: str, expr: str) -> str:
        return (
            f"{name} = {expr}" if self.name in {"python", "go"} else f"{name} = {expr};"
        )

    def ret(self, expr: str) -> str:
        return f"return {expr}" if self.name in {"python", "go"} else f"return {expr};"

    def call(self, name: str, arg: str) -> str:
        return f"{name}({arg})"

    def header(self, name: str, param: str) -> str:
        if self.name == "python":
            return f"def {name}({param}):"
        if self.name == "go":
            return f"func {name}({param}) int {{"
        if self.name == "rust":
            return f"fn {name}({param}) -> i32 {{"
        if self.name == "typescript":
            return f"function {name}({param}): number {{"
        if self.name in {"java", "csharp"}:
            return f"static int {name}({param}) {{"
        return f"int {name}({param}) {{"

    def function(self, name: str, lines: list[str], param: str | None = None) -> str:
        param = self.param if param is None else param
        if self.name == "python":
            body = "".join(f"    {line}\n" for line in lines)
            return f"{self.header(name, param)}\n{body}"
        body = "".join(f"\t{line}\n" for line in lines)
        return f"{self.header(name, param)}\n{body}}}\n"

    def one_line(self, name: str, expr: str, param: str | None = None) -> str:
        param = self.param if param is None else param
        raw = {
            "python": f"def {name}({param}): return {expr}",
            "go": f"func {name}({param}) int {{ return {expr} }}",
            "rust": f"fn {name}({param}) -> i32 {{ {expr} }}",
            "typescript": f"function {name}({param}): number {{ return {expr}; }}",
            "java": f"static int {name}({param}) {{ return {expr}; }}",
            "csharp": f"static int {name}({param}) {{ return {expr}; }}",
            "cpp": f"int {name}({param}) {{ return {expr}; }}",
        }[self.name]
        if len(raw) + (16 if self.class_name else 0) > 100:
            parts = expr.split(" + ")
            if len(parts) < 2:
                parts = [expr, "0"]
            wrapped = f"{parts[0]} +\n        {' + '.join(parts[1:])}"
            if self.name == "python":
                return f"{self.header(name, param)}\n    return ({wrapped})"
            if self.name == "go":
                return f"{self.header(name, param)} return {wrapped} }}"
            if self.name == "rust":
                return f"{self.header(name, param)} {parts[0]} +\n        {' + '.join(parts[1:])} }}"
            if self.name == "typescript":
                return f"{self.header(name, param)} return {wrapped}; }}"
            return f"{self.header(name, param)} return {wrapped}; }}"
        return raw

    def branch(self, condition: str, then_line: str, else_line: str) -> list[str]:
        if self.name == "python":
            return [f"if {condition}:", f"    {then_line}", "else:", f"    {else_line}"]
        return [
            f"if ({condition}) {{",
            f"    {then_line}",
            "} else {",
            f"    {else_line}",
            "}",
        ]

    def wrap(self, functions: list[str]) -> str:
        body = "\n".join(functions)
        if self.class_name:
            indented = "".join(f"\t{line}\n" for line in body.splitlines())
            return f"class {self.class_name} {{\n{indented}}}\n"
        return f"{self.preamble}{body}\n"


LANGUAGES = {
    "python": Lang("python", ".py", "value", "v"),
    "typescript": Lang("typescript", ".ts", "value: number", "v: number"),
    "java": Lang("java", ".java", "int value", "int v", class_name="Item"),
    "csharp": Lang("csharp", ".cs", "int value", "int v", class_name="Item"),
    "go": Lang("go", ".go", "value int", "v int", preamble="package main\n"),
    "rust": Lang("rust", ".rs", "value: i32", "v: i32"),
    "cpp": Lang("cpp", ".cpp", "int value", "int v"),
}
TINY_EDGES = {
    "solution": ["helper_a", "helper_b", "helper_c", "helper_d"],
    "helper_a": ["helper_e"],
    "helper_b": ["helper_f"],
    "helper_c": ["helper_g"],
    "helper_d": ["helper_h"],
    "helper_e": ["helper_i"],
    "helper_f": ["helper_j"],
    "helper_g": ["helper_k"],
    "helper_h": [],
    "helper_i": [],
    "helper_j": [],
    "helper_k": [],
}
PADDED_EDGES = {
    "solution": ["derive_alpha", "derive_beta", "derive_gamma", "derive_delta"],
    "derive_alpha": ["scale_alpha"],
    "derive_beta": ["scale_beta"],
    "derive_gamma": ["scale_gamma"],
    "derive_delta": ["scale_delta"],
    "scale_alpha": ["offset_alpha"],
    "scale_beta": ["offset_beta"],
    "scale_gamma": ["offset_gamma"],
    "scale_delta": [],
    "offset_alpha": [],
    "offset_beta": [],
    "offset_gamma": [],
}
NAMED_EDGES = {
    "solution": ["validated_total", "discount_for", "subtotal_for", "balance_for"],
    "validated_total": ["row_total"],
    "discount_for": ["line_total"],
    "subtotal_for": ["net_total"],
    "balance_for": ["gross_total"],
    "row_total": ["amount_total"],
    "line_total": ["value_total"],
    "net_total": ["sum_total"],
    "gross_total": [],
    "amount_total": [],
    "value_total": [],
    "sum_total": [],
}


def tree_edges(size: int) -> dict[str, list[str]]:
    """A single tree of `size` functions: entry fanout 4, helper fanout <=2, depth 5."""
    names = ["solution"] + [f"helper_{index}" for index in range(1, size)]
    edges = {name: [] for name in names}
    pending = ["solution"]
    index = 1
    while pending and index < size:
        node = pending.pop(0)
        width = 4 if node == "solution" else 2
        children = names[index : index + width]
        edges[node] = children
        index += len(children)
        pending.extend(children)
    return edges


def renamed_edges(edges: dict[str, list[str]], prefix: str) -> dict[str, list[str]]:
    """Rename every helper with `prefix` while keeping the tree shape identical."""
    renamed = {
        name: "solution" if name == "solution" else f"{prefix}{name[7:]}"
        for name in edges
    }
    return {
        renamed[name]: [renamed[child] for child in children]
        for name, children in edges.items()
    }


def tokens_of(lang: Lang, name: str, lines: list[str]) -> int:
    return len(TOKEN.findall(lang.function(name, lines)))


def tree_source(lang: Lang, edges: dict[str, list[str]]) -> str:
    functions = []
    for name, targets in edges.items():
        param = lang.entry_param if name == "solution" else None
        if name == "solution":
            expr = entry_expression(lang, targets)
        elif targets:
            expr = " + ".join([*(lang.call(target, "v") for target in targets), "1"])
        else:
            expr = "v + 1"
        functions.append(lang.one_line(name, expr, param))
    return lang.wrap(functions)


def entry_expression(lang: Lang, targets: list[str]) -> str:
    """Nest the second callee inside the first to keep the entry within 30 tokens."""
    if len(targets) < 2:
        return " + ".join(lang.call(target, "value") for target in targets)
    head = f"{lang.call(targets[0], lang.call(targets[1], 'value'))}"
    return " + ".join([head, *(lang.call(t, "value") for t in targets[2:])])


def padded_source(lang: Lang, edges: dict[str, list[str]]) -> str:
    functions = []
    for name, targets in edges.items():
        if name == "solution":
            functions.append(
                lang.one_line(name, entry_expression(lang, targets), lang.entry_param)
            )
            continue
        lines = [
            lang.let("first", "v + 1"),
            lang.let("second", "first * 2"),
            lang.let("third", "second + 3"),
            lang.let("fourth", "third - first"),
        ]
        calls = " + ".join(lang.call(target, "fourth") for target in targets)
        tail = (
            f"{calls} + first - third + second"
            if targets
            else "fourth + first - third + second"
        )
        lines.append(lang.ret(tail))
        functions.append(lang.function(name, lines))
    return lang.wrap(functions)


def filled(lang: Lang, name: str, head: list[str], filler: str, tail: str) -> str:
    lines = list(head)
    while tokens_of(lang, name, [*lines, tail]) < TINY_TARGET:
        lines.append(filler)
    return lang.function(name, [*lines, tail])


def sensible_functions(lang: Lang) -> list[str]:
    entry = lang.function(
        "solution",
        [
            lang.let("first", lang.call("validate_one", "value")),
            lang.let("second", lang.call("normalize_one", "first")),
            lang.let("total", "first + second"),
            lang.assign("total", "total * 2"),
            lang.ret("total + first - second"),
        ],
        lang.entry_param,
    )
    helpers = [
        filled(
            lang,
            name,
            [lang.let("first", "v + 1"), lang.let("second", "first * 2")],
            lang.assign("second", "second + first + 1"),
            lang.ret("second + first"),
        )
        for name in ("validate_one", "normalize_one")
    ]
    return [entry, *helpers]


def monolith_function(lang: Lang) -> str:
    lines = [lang.let("total", "0"), lang.let("count", "0")]
    for _ in range(22):
        lines.extend(
            lang.branch(
                "value > count",
                lang.assign("total", "total + 1"),
                lang.assign("total", "total - 1"),
            )
        )
    lines.append(lang.ret("total"))
    return lang.function("solution", lines, lang.entry_param)


def sized_function(lang: Lang, target: int) -> str:
    lines = [lang.let("total", "value"), lang.let("count", "0")]
    filler = lang.assign("count", "count + 1")
    while (
        tokens_of(lang, "solution", [*lines, lang.ret("total")])
        + len(TOKEN.findall(filler))
        <= target
    ):
        lines.append(filler)
    expr = "total"
    while tokens_of(lang, "solution", [*lines, lang.ret(expr)]) < target:
        expr += " + 1"
    lines.append(lang.ret(expr))
    return lang.function("solution", lines, lang.entry_param)


def conforming_sources(
    lang: Lang,
    *,
    edges: dict[str, list[str]] = TINY_EDGES,
    padded_edges: dict[str, list[str]] = PADDED_EDGES,
    named_edges: dict[str, list[str]] = NAMED_EDGES,
) -> dict[str, str]:
    sensible = sensible_functions(lang)
    total = sum(len(TOKEN.findall(source)) for source in sensible)
    return {
        "sensible": lang.wrap(sensible),
        "monolith": lang.wrap([monolith_function(lang)]),
        "tiny": tree_source(lang, edges),
        "padded": padded_source(lang, padded_edges),
        "sizematched": lang.wrap([sized_function(lang, total)]),
        "namematched": tree_source(lang, named_edges),
    }


def write_language_item(root: Path, lang: Lang, sources: dict[str, str]) -> Path:
    item = root / "item"
    item.mkdir()
    for version, source in sources.items():
        (item / f"{version}{lang.ext}").write_text(source)
    return item


def fanout_edges(fanout: int) -> dict[str, list[str]]:
    """Entry with `fanout` distinct callees, the first three pure forwarders."""
    helpers = [f"helper_{index}" for index in range(fanout)]
    edges = {"solution": helpers}
    for index, name in enumerate(helpers):
        edges[name] = [f"leaf_{index}"] if index < 3 else []
    return edges


def sensible_source(lang: Lang, count: int) -> str:
    """`count` one-level functions, entry first, each within the sensible token cap."""
    names = [f"helper_{index}" for index in range(count - 1)]
    entry = lang.function(
        "solution",
        [lang.ret(" + ".join(lang.call(name, "value") for name in names) or "value")],
        lang.entry_param,
    )
    helpers = [
        filled(
            lang,
            name,
            [lang.let("first", "v + 1"), lang.let("second", "first * 2")],
            lang.assign("second", "second + first + 1"),
            lang.ret("second + first"),
        )
        for name in names
    ]
    return lang.wrap([entry, *helpers])


def tree_helper_at_tokens(
    root: Path, version: str, name: str, expression: str
) -> tuple[list[dict], int]:
    """Replace one tree helper body and return the findings plus its token count."""
    sources = conforming_sources(LANGUAGES["python"])
    sources[version] = sources[version].replace(
        f"def {name}(v): return v + 1",
        f"def {name}(v): return {expression}",
    )
    tokens = next(
        function.tokens
        for function in extract("python", sources[version])
        if function.name == name
    )
    return findings_at(root, sources), tokens


def padded_entry_at_tokens(root: Path, expression: str) -> tuple[list[dict], int]:
    """Replace the padded entry body and return the findings plus its token count."""
    sources = conforming_sources(LANGUAGES["python"])
    entry = (
        "def solution(value):\n    return (derive_alpha(derive_beta(value)) +\n"
        "        derive_gamma(value) + derive_delta(value))"
    )
    # Parentheses provide implicit continuation; trim one two-token filler so
    # the formatter wrapper does not move the 45/46 token boundary.
    adjusted = expression.rsplit(" + 1", 1)[0]
    wrapped = adjusted.replace(" + ", " +\n        ")
    replacement = f"def solution(value):\n    return ({wrapped})"
    sources["padded"] = sources["padded"].replace(entry, replacement)
    tokens = next(
        function.tokens
        for function in extract("python", sources["padded"])
        if function.name == "solution"
    )
    return findings_at(root, sources), tokens


@pytest.mark.parametrize("language", sorted(LANGUAGES))
def test_conforming_item_per_language_passes(tmp_path, language):
    if language != "python":
        require_grammar(language)
    lang = LANGUAGES[language]
    item = write_language_item(tmp_path, lang, conforming_sources(lang))
    findings, metrics = check_item(item, language)
    assert findings == [], findings
    assert len(metrics) == 6
    result = run_tool("--items", str(item), "--language", language, "--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert not any(line.startswith("{") for line in result.stdout.splitlines())


# --- rule coverage ----------------------------------------------------------


def assert_kind(findings: list[dict], kind: str) -> None:
    kinds = {finding["kind"] for finding in findings}
    assert kind in kinds, sorted(kinds)


def findings_at(root: Path, sources: dict[str, str]) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    lang = LANGUAGES["python"]
    found, _ = check_item(write_language_item(root, lang, sources), "python")
    return found


def findings_for(tmp_path, sources: dict[str, str]) -> list[dict]:
    return findings_at(tmp_path, sources)


def layered_item(
    root: Path,
    *,
    sensible_count=7,
    tiny_count=24,
    padded_count=14,
    profile=True,
    padded_edges=None,
) -> Path:
    edges = tree_edges(tiny_count)
    padded = padded_edges or renamed_edges(tree_edges(padded_count), "derive_")
    named = renamed_edges(edges, "named_")
    sources = conforming_sources(
        LANGUAGES["python"], edges=edges, padded_edges=padded, named_edges=named
    )
    sources["sensible"] = sensible_source(LANGUAGES["python"], sensible_count)
    item = write_language_item(root, LANGUAGES["python"], sources)
    if profile:
        (item / "spec-profile.toml").write_text('profile = "layered"\n')
    return item


def typescript_layered_item(root: Path, sensible: str) -> list[dict]:
    lang = LANGUAGES["typescript"]
    sources = conforming_sources(lang)
    sources["sensible"] = sensible
    item = write_language_item(root, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    return check_item(item, "typescript")[0]


@pytest.mark.parametrize(
    ("count", "fails"), [(6, True), (7, False), (20, False), (21, True)]
)
def test_layered_typescript_sensible_function_count_boundaries(tmp_path, count, fails):
    source = sensible_source(LANGUAGES["typescript"], count)
    findings = typescript_layered_item(tmp_path, source)
    assert any(f["kind"] == "sensible_function_count" for f in findings) is fails


@pytest.mark.parametrize(("fanout", "fails"), [(6, False), (7, True)])
def test_layered_typescript_sensible_entry_fanout_boundaries(tmp_path, fanout, fails):
    lang = LANGUAGES["typescript"]
    names = [f"helper_{index}" for index in range(fanout)]
    entry = lang.function(
        "solution",
        [lang.ret(" + ".join(f"{name}(value)" for name in names))],
        lang.entry_param,
    )
    helpers = [lang.one_line(name, "v + 1") for name in names]
    findings = typescript_layered_item(tmp_path, lang.wrap([entry, *helpers]))
    assert any(f["kind"] == "sensible_entry_fanout" for f in findings) is fails


@pytest.mark.parametrize(("depth", "fails"), [(4, False), (5, True)])
def test_layered_typescript_sensible_call_depth_boundaries(tmp_path, depth, fails):
    lang = LANGUAGES["typescript"]
    names = [f"helper_{index}" for index in range(depth - 1)]
    functions = [lang.one_line("solution", f"{names[0]}(value)", lang.entry_param)]
    functions.extend(
        lang.one_line(
            name,
            f"{names[index + 1]}(v)" if index + 1 < len(names) else "v + 1",
        )
        for index, name in enumerate(names)
    )
    findings = typescript_layered_item(tmp_path, lang.wrap(functions))
    assert any(f["kind"] == "sensible_call_depth" for f in findings) is fails


def item_findings(item: Path) -> list[dict]:
    return check_item(item, "python")[0]


def tree_entry_at_tokens(
    root: Path, version: str, token_count: int, *, profile: bool = True
) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    item = layered_item(root, profile=profile)
    source_path = item / f"{version}.py"
    source = source_path.read_text()
    expression = "value"
    while True:
        entry_source = (
            f'def solution(value):\n    """Shared entry."""\n    return {expression}'
        )
        entry = next(
            function
            for function in extract("python", entry_source)
            if function.name == "solution"
        )
        if entry.tokens == token_count:
            break
        expression += " + (not value)" if (token_count - entry.tokens) % 2 else " + 1"
        assert entry.tokens < token_count
    source = source.replace(
        next(line for line in source.splitlines() if line.startswith("def solution(")),
        entry_source,
    )
    source_path.write_text(source)
    return item_findings(item)


@pytest.mark.parametrize(
    ("version", "token_count", "fails"),
    [
        ("tiny", 90, False),
        ("tiny", 91, True),
        ("namematched", 90, False),
        ("namematched", 91, True),
    ],
)
def test_layered_tree_entry_token_cap_boundary(tmp_path, version, token_count, fails):
    findings = tree_entry_at_tokens(tmp_path, version, token_count)
    kind = (
        "padded_entry_tokens" if version == "padded" else f"{version}_function_tokens"
    )
    entry_findings = [
        finding
        for finding in findings
        if finding["kind"] == kind and finding.get("function") == "solution"
    ]
    assert bool(entry_findings) is fails
    if fails:
        assert entry_findings[0]["limit"] == "5-90"


def padded_helper_at_tokens(root: Path, target: int) -> list[dict]:
    lang = LANGUAGES["python"]
    sources = conforming_sources(lang)
    helper_name = "derive_alpha"
    base = f"def {helper_name}(v):\n    return (\n        derive_beta(v) + v\n    )\n"
    initial = next(
        function for function in extract("python", base) if function.name == helper_name
    ).tokens
    difference = target - initial
    assignments = difference % 2
    additions = (difference - assignments * 5) // 2
    helper_lines = [f"def {helper_name}(v):"]
    helper_lines.extend("    v = v + 1" for _ in range(assignments))
    helper_lines.extend(("    return (", "        derive_beta(v) + v"))
    helper_lines.extend("        + 1" for _ in range(additions))
    helper_lines.append("    )")
    replacement = "\n".join(helper_lines)
    start = sources["padded"].index(f"def {helper_name}(")
    end = sources["padded"].index("\ndef ", start + 1)
    sources["padded"] = (
        sources["padded"][:start] + replacement + sources["padded"][end:]
    )
    helper = next(
        function
        for function in extract("python", sources["padded"])
        if function.name == helper_name
    )
    assert helper.tokens == target
    item = write_language_item(root, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    return item_findings(item)


@pytest.mark.parametrize(("tokens", "fails"), [(130, False), (131, True)])
def test_layered_python_padded_helper_token_cap(tmp_path, tokens, fails):
    findings = padded_helper_at_tokens(tmp_path, tokens)
    flagged = [
        finding
        for finding in findings
        if finding["kind"] == "padded_function_tokens"
        and finding["function"] == "derive_alpha"
    ]
    assert bool(flagged) is fails
    if flagged:
        assert flagged[0]["limit"] == "30-130"


def test_layered_python_padded_entry_has_no_token_cap(tmp_path):
    findings = tree_entry_at_tokens(tmp_path, "padded", 131)
    assert not any(finding["kind"] == "padded_entry_tokens" for finding in findings)


@pytest.mark.parametrize("version", ["tiny", "namematched"])
def test_layered_tree_entry_46_token_profile_boundary(tmp_path, version):
    layered_findings = tree_entry_at_tokens(tmp_path / "layered", version, 46)
    unprofiled_findings = tree_entry_at_tokens(
        tmp_path / "unprofiled", version, 46, profile=False
    )
    kind = (
        "padded_entry_tokens" if version == "padded" else f"{version}_function_tokens"
    )
    assert not any(
        finding["kind"] == kind and finding.get("function") == "solution"
        for finding in layered_findings
    )
    unprofiled = [
        finding
        for finding in unprofiled_findings
        if finding["kind"] == kind and finding.get("function") == "solution"
    ]
    assert unprofiled and unprofiled[0]["limit"] == "5-45"


@pytest.mark.parametrize(
    ("size", "fails"), [(6, True), (7, False), (20, False), (21, True)]
)
def test_layered_sensible_function_count_boundaries(tmp_path, size, fails):
    findings = item_findings(layered_item(tmp_path, sensible_count=size))
    sensible = [f for f in findings if f["kind"].startswith("sensible_")]
    if fails:
        count = next(f for f in sensible if f["kind"] == "sensible_function_count")
        assert count["limit"] == "7-20"
    else:
        assert not any(f["kind"] == "sensible_function_count" for f in sensible)


@pytest.mark.parametrize("language", sorted(LANGUAGES))
@pytest.mark.parametrize("oversized", [False, True])
def test_layered_padded_helper_cap_is_language_independent(language, oversized):
    cap = 160 if language == "rust" else 130
    helper = Function("helper", cap + oversized, 4, [], 0, "()")
    entry = Function("solution", 200, 4, ["helper"], 0, "()", ["helper"])
    state = ItemState(
        language,
        {"padded": ""},
        {"padded": [entry, helper]},
        {"padded": {"solution": ["helper"], "helper": []}},
        {"padded": entry},
        "layered",
    )
    findings = []
    item_spec_rules._rule_padded(findings, state)
    violation = next(
        (f for f in findings if f["kind"] == "padded_function_tokens"), None
    )
    assert bool(violation) is oversized
    if violation:
        assert violation["limit"] == ("30-160" if language == "rust" else "30-130")
    entry_violation = next(
        (f for f in findings if f["kind"] == "padded_entry_tokens"), None
    )
    assert bool(entry_violation) is (language == "rust")
    if entry_violation:
        assert entry_violation["limit"] == "5-160"


@pytest.mark.parametrize("language", sorted(LANGUAGES))
@pytest.mark.parametrize(("rows", "fails"), [(10, False), (11, True)])
def test_layered_tree_row_limit_is_ten_for_every_language(language, rows, fails):
    function = Function("solution", 20, rows, [], 0, "()")
    state = ItemState(
        language, {}, {"tiny": [function]}, {"tiny": {}}, {"tiny": function}, "layered"
    )
    findings = []
    item_spec_rules._rule_tree(findings, state, "tiny")
    line_finding = next(
        (f for f in findings if f["kind"] == "tiny_function_lines"), None
    )
    assert bool(line_finding) is fails
    if line_finding:
        assert line_finding["limit"] == 10


@pytest.mark.parametrize("language", ["go", "java", "csharp", "cpp"])
@pytest.mark.parametrize(
    ("ratio", "kind"),
    [(0.8, None), (0.79, "monolith_file_tokens"), (1.61, "monolith_file_tokens_high")],
)
def test_layered_monolith_file_ratio_is_language_independent(
    language, ratio, kind, monkeypatch
):
    sensible = Function("part", 1000, 1, [], 0, "()")
    monolith = Function("solution", 1200, 15, [], 15, "()")
    state = ItemState(
        language,
        {"sensible": "sensible", "monolith": "monolith"},
        {"sensible": [sensible], "monolith": [monolith]},
        {},
        {},
        "layered",
    )
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: 100 if source == "sensible" else round(100 * ratio),
    )
    findings = []
    item_spec_rules._rule_monolith(findings, state)
    file_findings = {
        finding["kind"]
        for finding in findings
        if finding["kind"].startswith("monolith_file_tokens")
    }
    assert file_findings == ({kind} if kind else set())


@pytest.mark.parametrize("language", ["go", "java", "csharp", "cpp"])
@pytest.mark.parametrize(("size_tokens", "fails"), [(110, False), (111, True)])
def test_layered_sizematched_file_tolerance_is_language_independent(
    language, size_tokens, fails, monkeypatch
):
    state = ItemState(
        language,
        {"sensible": "sensible", "sizematched": "sizematched"},
        {
            "sensible": [Function("part", 100, 1, [], 0, "()")],
            "sizematched": [Function("solution", 100, 1, [], 0, "()")],
        },
        {},
        {},
        "layered",
    )
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: 100 if source == "sensible" else size_tokens,
    )
    findings = []
    item_spec_rules._rule_sizematched(findings, state)
    assert any(f["kind"] == "sizematched_file_tokens" for f in findings) is fails


@pytest.mark.parametrize(
    ("language", "size", "expected_limit", "fails"),
    [
        ("go", 20, "7-20", False),
        ("go", 21, "7-20", True),
        ("java", 20, "7-20", False),
        ("java", 21, "7-20", True),
        ("csharp", 20, "7-20", False),
        ("csharp", 21, "7-20", True),
        ("cpp", 20, "7-20", False),
        ("cpp", 21, "7-20", True),
        ("python", 20, "7-20", False),
        ("python", 21, "7-20", True),
        ("rust", 20, "7-20", False),
        ("rust", 21, "7-20", True),
        ("typescript", 20, "7-20", False),
        ("typescript", 21, "7-20", True),
    ],
)
def test_layered_sensible_function_count_is_language_independent(
    tmp_path, language, size, expected_limit, fails
):
    if language != "python":
        require_grammar(language)
    lang = LANGUAGES[language]
    sources = conforming_sources(lang)
    sources["sensible"] = sensible_source(lang, size)
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, language)[0]
    counts = [f for f in findings if f["kind"] == "sensible_function_count"]
    assert bool(counts) is fails
    if counts:
        assert counts[0]["limit"] == expected_limit


def test_go_entry_name_accepts_exported_solution():
    entry = Function("Solution", 20, 1, [], 0, "(value int) int")
    functions = {version: [entry] for version in VERSIONS}
    assert item_spec_rules._shared_entry(functions, "go") == "Solution"
    state = ItemState("go", {}, functions, {}, dict.fromkeys(VERSIONS, entry), None)
    findings = []
    item_spec_rules._rule_entry_names(findings, state)
    assert not findings


def test_layered_go_padded_has_130_token_helpers_and_no_entry_cap():
    edges = {
        "Solution": ["a", "b", "c", "d"],
        "a": ["e"],
        "b": ["f"],
        "c": ["g"],
        "d": ["h"],
        "e": ["i"],
        "f": ["j"],
        "g": ["k"],
        "h": ["l"],
        "l": ["m"],
    }
    for name in ("i", "j", "k", "m"):
        edges.setdefault(name, [])
    functions = [
        Function(name, 130, 4, children, 0, "(value int) int", children)
        for name, children in edges.items()
    ]
    state = ItemState(
        "go",
        {"padded": ""},
        {"padded": functions},
        {"padded": edges},
        {"padded": functions[0]},
        "layered",
    )
    findings = []
    item_spec_rules._rule_padded(findings, state)
    assert not any(
        finding["kind"] in {"padded_entry_tokens", "padded_function_tokens"}
        for finding in findings
    )


@pytest.mark.parametrize(("size", "fails"), [(159, False), (161, True)])
def test_layered_rust_sensible_token_boundary(tmp_path, size, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    sources = conforming_sources(lang)
    sources["sensible"] = sensible_source(lang, 7)
    name = "helper_0"
    expression = "v"
    target = size - 1
    while (
        extract("rust", lang.function(name, [lang.ret(expression)]))[0].tokens < target
    ):
        expression += " + 1"
    oversized = lang.function(name, [lang.ret(expression)])
    source = sources["sensible"]
    start = source.index("fn helper_0(")
    end = source.index("fn helper_1(", start)
    sources["sensible"] = source[:start] + oversized + source[end:]
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    tokens = [f for f in findings if f["kind"] == "sensible_function_tokens"]
    assert bool(tokens) is fails
    if tokens:
        assert tokens[0]["limit"] == "30-160"


@pytest.mark.parametrize(("size", "fails"), [(158, False), (161, True)])
@pytest.mark.parametrize("target", ["entry", "helper"])
def test_layered_rust_padded_token_boundary(tmp_path, target, size, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    sources = conforming_sources(lang)
    name = "solution" if target == "entry" else "derive_alpha"
    expression = "value" if target == "entry" else "v"
    parameter = lang.entry_param if target == "entry" else None
    while (
        extract("rust", lang.function(name, [lang.ret(expression)], parameter))[
            0
        ].tokens
        < size
    ):
        expression += " + 1"
    replacement = lang.function(name, [lang.ret(expression)], parameter)
    source = sources["padded"]
    start = source.index(f"fn {name}(")
    next_function = source.find("\nfn ", start + 1)
    end = len(source) if next_function < 0 else next_function + 1
    sources["padded"] = source[:start] + replacement + source[end:]
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    kind = "padded_entry_tokens" if target == "entry" else "padded_function_tokens"
    matched = [f for f in findings if f["kind"] == kind and f.get("function") == name]
    assert bool(matched) is fails
    if matched:
        limit = "5-160" if target == "entry" else "30-160"
        assert matched[0]["limit"] == limit


@pytest.mark.parametrize(("depth", "fails"), [(4, False), (5, True)])
def test_layered_rust_sensible_depth_boundary(tmp_path, depth, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    sources = conforming_sources(lang)
    edges = {"solution": ["helper_0"]}
    edges.update({f"helper_{index}": [] for index in range(6)})
    for index in range(depth - 2):
        edges[f"helper_{index}"] = [f"helper_{index + 1}"]
    functions = []
    for name, targets in edges.items():
        if name == "solution":
            expr = lang.call(targets[0], "value")
            functions.append(lang.function(name, [lang.ret(expr)], lang.entry_param))
        else:
            expr = lang.call(targets[0], "v") if targets else "v"
            functions.append(
                filled(lang, name, [], lang.assign("v", "v + 1"), lang.ret(expr))
            )
    sources["sensible"] = lang.wrap(functions)
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    assert any(f["kind"] == "sensible_call_depth" for f in findings) is fails


@pytest.mark.parametrize(("depth", "fails"), [(4, False), (5, True)])
def test_layered_sensible_call_depth_boundaries(tmp_path, depth, fails):
    item = layered_item(tmp_path)
    source = (item / "sensible.py").read_text()
    calls = [f"helper_{index + 1}" for index in range(depth - 2)]
    for index, child in enumerate(calls):
        marker = f"def helper_{index}(v):"
        start = source.index(marker)
        end = source.find("\ndef helper_", start + len(marker))
        if end < 0:
            end = len(source)
        chunk = source[start:end].replace(
            "return second + first", f"return {child}(second + first)"
        )
        source = source[:start] + chunk + source[end:]
    (item / "sensible.py").write_text(source)
    findings = item_findings(item)
    assert any(f["kind"] == "sensible_call_depth" for f in findings) is fails


@pytest.mark.parametrize(("fanout", "fails"), [(6, False), (7, True)])
def test_layered_sensible_entry_fanout_boundaries(tmp_path, fanout, fails):
    findings = item_findings(layered_item(tmp_path, sensible_count=fanout + 1))
    flagged = [f for f in findings if f["kind"] == "sensible_entry_fanout"]
    assert bool(flagged) is fails
    if flagged:
        assert flagged[0]["limit"] == "<=6"


@pytest.mark.parametrize(
    ("count", "fails"), [(1, True), (2, False), (6, False), (7, True)]
)
def test_default_sensible_function_count_boundaries(tmp_path, count, fails):
    item = layered_item(tmp_path, sensible_count=count, profile=False)
    findings = item_findings(item)
    count_findings = [f for f in findings if f["kind"] == "sensible_function_count"]
    assert bool(count_findings) is fails
    if count_findings:
        assert count_findings[0]["limit"] == "2-6"
    assert not any(f["kind"] == "sensible_entry_fanout" for f in findings)


@pytest.mark.parametrize(
    ("language", "size", "limit", "fails"),
    [
        ("cpp", 9, "2-9", False),
        ("cpp", 10, "2-9", True),
        ("python", 6, "2-6", False),
        ("python", 7, "2-6", True),
    ],
)
def test_unprofiled_sensible_function_count_language_boundaries(
    tmp_path, language, size, limit, fails
):
    if language != "python":
        require_grammar(language)
    lang = LANGUAGES[language]
    sources = conforming_sources(lang)
    sources["sensible"] = sensible_source(lang, size)
    item = write_language_item(tmp_path, lang, sources)
    findings = check_item(item, language)[0]
    counts = [f for f in findings if f["kind"] == "sensible_function_count"]
    assert bool(counts) is fails
    if counts:
        assert counts[0]["limit"] == limit


@pytest.mark.parametrize("version", ["tiny", "namematched"])
@pytest.mark.parametrize(
    ("size", "fails"), [(27, True), (28, False), (72, False), (73, True)]
)
def test_layered_tree_function_count_boundaries(tmp_path, version, size, fails):
    item = layered_item(tmp_path, tiny_count=size)
    if version == "namematched":
        source_path = item / "namematched.py"
        source_path.write_text(
            tree_source(LANGUAGES["python"], renamed_edges(tree_edges(size), "named_"))
        )
    findings = item_findings(item)
    assert any(f["kind"] == f"{version}_function_count" for f in findings) is fails


@pytest.mark.parametrize("version", ["tiny", "namematched"])
@pytest.mark.parametrize(("rows", "fails"), [(10, False), (11, True)])
def test_layered_tree_function_row_boundaries(tmp_path, version, rows, fails):
    item = layered_item(tmp_path)
    source_path = item / f"{version}.py"
    source = source_path.read_text()
    functions = extract("python", source)
    helper = functions[-1]
    body = ["    value = v + 1" for _ in range(rows - 1)]
    body[-1] = "    return v + 1"
    replacement = f"def {helper.name}(v):\n" + "\n".join(body)
    source_path.write_text(
        source.replace(f"def {helper.name}(v): return v + 1", replacement)
    )
    findings = item_findings(item)
    assert any(f["kind"] == f"{version}_function_lines" for f in findings) is fails


@pytest.mark.parametrize("version", ["tiny", "namematched"])
@pytest.mark.parametrize(("tokens", "fails"), [(90, False), (91, True)])
def test_layered_tree_helper_token_boundaries(tmp_path, version, tokens, fails):
    item = layered_item(tmp_path)
    source_path = item / f"{version}.py"
    source = source_path.read_text()
    helper = extract("python", source)[-1]
    expression = "v" + " + v" * ((tokens - 8) // 2)
    if tokens % 2:
        expression = "not v" + " + v" * ((tokens - 9) // 2)
    source_path.write_text(
        source.replace(
            f"def {helper.name}(v): return v + 1",
            f"def {helper.name}(v): return {expression}",
        )
    )
    helper = next(
        f for f in extract("python", source_path.read_text()) if f.name == helper.name
    )
    assert helper.tokens == tokens
    findings = item_findings(item)
    assert (
        any(
            f["kind"] == f"{version}_function_tokens" and f["function"] == helper.name
            for f in findings
        )
        is fails
    )


@pytest.mark.parametrize(
    ("size", "fails"), [(13, True), (14, False), (22, False), (23, True)]
)
def test_layered_padded_function_count_boundaries(tmp_path, size, fails):
    findings = item_findings(layered_item(tmp_path, padded_count=size))
    assert any(f["kind"] == "padded_function_count" for f in findings) is fails


@pytest.mark.parametrize(
    ("depth", "fails"), [(2, True), (3, False), (6, False), (7, True)]
)
def test_layered_padded_chain_depth_boundaries(tmp_path, depth, fails):
    names = ["solution", *(f"derive_{i}" for i in range(13))]
    edges = {name: [] for name in names}
    edges["solution"] = names[1:5]
    chain = names[4 : 3 + depth]
    for parent, child in pairwise(chain):
        edges[parent] = [child]
    if depth == 2:
        edges[names[4]] = []
    item = layered_item(tmp_path, padded_edges=edges)
    findings = item_findings(item)
    assert any(f["kind"] == "padded_chain_depth" for f in findings) is fails


def test_layered_padded_tree_is_independent_of_tiny(tmp_path):
    item = layered_item(tmp_path)
    assert not any(f["kind"] == "padded_shape" for f in item_findings(item))
    (item / "spec-profile.toml").unlink()
    assert any(f["kind"] == "padded_shape" for f in item_findings(item))


def test_layered_namematched_still_matches_tiny_tree(tmp_path):
    item = layered_item(tmp_path)
    findings = item_findings(item)
    assert not any(f["kind"] == "namematched_shape" for f in findings)


@pytest.mark.parametrize(
    ("depth", "fails"), [(2, True), (3, False), (8, False), (9, True)]
)
@pytest.mark.parametrize("version", ["tiny", "namematched"])
def test_layered_tiny_chain_depth_boundaries(tmp_path, version, depth, fails):
    item = layered_item(tmp_path)
    source_path = item / f"{version}.py"
    names = [f"helper_{index}" for index in range(1, 24)]
    edges = {name: [] for name in ["solution", *names]}
    edges["solution"] = ["helper_1", "helper_2", "helper_3", "helper_4"]
    chain = ["solution", *names[: depth - 1]]
    for parent, child in pairwise(chain[1:]):
        edges[parent] = [child]
    remaining = [name for name in names if name not in chain[1:]]
    branches = [*edges["solution"][1:], *chain[1:-1]]
    branches = list(dict.fromkeys(branches))
    if depth > 2:
        for index, name in enumerate(remaining):
            edges[branches[index % len(branches)]].append(name)
    source_path.write_text(tree_source(LANGUAGES["python"], edges))

    findings = item_findings(item)
    chain_finding = next(
        (
            finding
            for finding in findings
            if finding["kind"] == f"{version}_chain_depth"
        ),
        None,
    )
    assert (chain_finding is not None) is fails
    if chain_finding:
        assert chain_finding["limit"] == "3-8"


def test_tiny_chain_depth_limit_is_unchanged_without_layered_profile(tmp_path):
    item = layered_item(tmp_path, profile=False)
    names = [f"helper_{index}" for index in range(1, 24)]
    edges = {name: [] for name in ["solution", *names]}
    edges["solution"] = ["helper_1", "helper_2", "helper_3", "helper_4"]
    chain = ["solution", *names[:5]]
    for parent, child in pairwise(chain[1:]):
        edges[parent] = [child]
    remaining = [name for name in names if name not in chain[1:]]
    branches = [*edges["solution"][1:], *chain[1:-1]]
    branches = list(dict.fromkeys(branches))
    for index, name in enumerate(remaining):
        edges[branches[index % len(branches)]].append(name)
    (item / "tiny.py").write_text(tree_source(LANGUAGES["python"], edges))

    finding = next(
        finding
        for finding in item_findings(item)
        if finding["kind"] == "tiny_chain_depth"
    )
    assert finding["limit"] == "3-5"


def test_tiny_count_profile_is_opt_in(tmp_path):
    item = layered_item(tmp_path, tiny_count=12, profile=False)
    assert not any(f["kind"] == "tiny_function_count" for f in item_findings(item))
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    assert any(f["kind"] == "tiny_function_count" for f in item_findings(item))


TREE_SIZES = {"at-cap": 32, "over-cap": 33}
SENSIBLE_SIZES = {"at-cap": 6, "over-cap": 7}
FANOUT_SIZES = {"at-cap": 10, "over-cap": 11}


@pytest.mark.parametrize(("size", "fails"), [(72, False), (73, True)])
def test_layered_rust_tree_function_count_boundaries(tmp_path, size, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    edges = tree_edges(size)
    sources = conforming_sources(
        lang, edges=edges, named_edges=renamed_edges(edges, "amount_")
    )
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    counts = {
        finding["kind"]
        for finding in findings
        if finding["kind"] in {"tiny_function_count", "namematched_function_count"}
    }
    assert counts == (
        {"tiny_function_count", "namematched_function_count"} if fails else set()
    )


@pytest.mark.parametrize(
    ("version", "name"), [("tiny", "helper_a"), ("namematched", "validated_total")]
)
@pytest.mark.parametrize(("rows", "fails"), [(10, False), (11, True)])
def test_layered_rust_tree_row_boundaries(tmp_path, version, name, rows, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    sources = conforming_sources(lang)
    source = sources[version]
    start = source.index(f"fn {name}(")
    end = source.index("\nfn ", start + 1)
    statements = rows - 3
    body = "\n".join(
        f"    let n{index} = v + {index + 1};" for index in range(statements)
    )
    final = f"n{statements - 1}"
    replacement = f"fn {name}(v: i32) -> i32 {{\n{body}\n    {final}\n}}"
    sources[version] = source[:start] + replacement + source[end:]
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    row_findings = [f for f in findings if f["kind"] == f"{version}_function_lines"]
    assert bool(row_findings) is fails
    if row_findings:
        assert row_findings[0]["function"] == name
        assert row_findings[0]["limit"] == 10


@pytest.mark.parametrize("version", ["tiny", "namematched"])
@pytest.mark.parametrize(("target", "fails"), [(90, False), (91, True)])
def test_layered_rust_tree_token_boundaries(tmp_path, version, target, fails):
    require_grammar("rust")
    lang = LANGUAGES["rust"]
    sources = conforming_sources(lang)
    name = "helper_a" if version == "tiny" else "validated_total"
    function = None
    for parameter in ("v: i32", "mut v: i32"):
        expression = "v + 1"
        for _ in range(target):
            candidate = lang.one_line(name, expression, parameter)
            if extract("rust", candidate)[0].tokens == target:
                function = candidate
                break
            expression += " + 1"
        if function:
            break
    assert function is not None
    source = sources[version]
    start = source.index(f"fn {name}(")
    end = source.index("\nfn ", start + 1)
    sources[version] = source[:start] + function + source[end:]
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings = check_item(item, "rust")[0]
    token_findings = [
        finding
        for finding in findings
        if finding["kind"] == f"{version}_function_tokens"
        and finding["function"] == name
    ]
    assert bool(token_findings) is fails, findings
    if token_findings:
        assert token_findings[0]["limit"] == "5-90"


@pytest.mark.parametrize("language", ["python", "typescript"])
@pytest.mark.parametrize("case", sorted(TREE_SIZES))
def test_tree_function_count_boundary(tmp_path, language, case):
    if language != "python":
        require_grammar(language)
    size = TREE_SIZES[case]
    edges = tree_edges(size)
    assert len(edges) == size
    lang = LANGUAGES[language]
    sources = conforming_sources(
        lang,
        edges=edges,
        padded_edges=renamed_edges(edges, "derive_"),
        named_edges=renamed_edges(edges, "amount_"),
    )
    item = write_language_item(tmp_path, lang, sources)
    findings, _ = check_item(item, language)
    counts = {
        finding["kind"]
        for finding in findings
        if finding["kind"] in {"tiny_function_count", "namematched_function_count"}
    }
    if case == "at-cap":
        assert counts == set(), sorted(counts)
    else:
        assert counts == {"tiny_function_count", "namematched_function_count"}


@pytest.mark.parametrize("case", ["at-cap", "over-cap"])
def test_typescript_layered_tree_function_count_boundary(tmp_path, case):
    require_grammar("typescript")
    size = 72 if case == "at-cap" else 73
    edges = tree_edges(size)
    lang = LANGUAGES["typescript"]
    sources = conforming_sources(
        lang,
        edges=edges,
        padded_edges=renamed_edges(edges, "derive_"),
        named_edges=renamed_edges(edges, "amount_"),
    )
    item = write_language_item(tmp_path, lang, sources)
    (item / "spec-profile.toml").write_text('profile = "layered"\n')
    findings, _ = check_item(item, "typescript")
    counts = {
        finding["kind"]
        for finding in findings
        if finding["kind"] in {"tiny_function_count", "namematched_function_count"}
    }
    if case == "at-cap":
        assert counts == set(), sorted(counts)
    else:
        assert counts == {"tiny_function_count", "namematched_function_count"}


@pytest.mark.parametrize("case", sorted(SENSIBLE_SIZES))
def test_sensible_function_count_boundary(tmp_path, case):
    sources = conforming_sources(LANGUAGES["python"])
    sources["sensible"] = sensible_source(LANGUAGES["python"], SENSIBLE_SIZES[case])
    findings = findings_for(tmp_path, sources)
    kinds = {
        finding["kind"]
        for finding in findings
        if finding["kind"].startswith("sensible_")
    }
    if case == "at-cap":
        assert kinds == set(), findings
    else:
        assert kinds == {"sensible_function_count"}, findings
        assert (
            next(
                finding["limit"]
                for finding in findings
                if finding["kind"] == "sensible_function_count"
            )
            == "2-6"
        )


@pytest.mark.parametrize(
    ("version", "name"), [("tiny", "helper_k"), ("namematched", "sum_total")]
)
def test_tree_helper_token_cap_boundary(tmp_path, version, name):
    findings, tokens = tree_helper_at_tokens(
        tmp_path / "at-cap", version, name, "not v" + " + v" * 18
    )
    assert tokens == 45
    assert not [
        finding
        for finding in findings
        if finding["kind"] == f"{version}_function_tokens"
    ]

    findings, tokens = tree_helper_at_tokens(
        tmp_path / "over-cap", version, name, "v" + " + v" * 19
    )
    assert tokens == 46
    assert {
        finding["function"]
        for finding in findings
        if finding["kind"] == f"{version}_function_tokens"
    } == {name}


@pytest.mark.parametrize("case", sorted(FANOUT_SIZES))
def test_tiny_entry_fanout_boundary(tmp_path, case):
    edges = fanout_edges(FANOUT_SIZES[case])
    assert len(set(edges["solution"])) == FANOUT_SIZES[case]
    sources = conforming_sources(LANGUAGES["python"], edges=edges)
    findings = findings_for(tmp_path, sources)
    flagged = {
        finding["function"]
        for finding in findings
        if finding["kind"] == "tiny_entry_fanout"
    }
    assert flagged == (set() if case == "at-cap" else {"solution"})


def test_monolith_whole_file_ratio_is_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    clean = findings_at(tmp_path / "clean", sources)
    assert not any(finding["kind"] == "monolith_file_tokens" for finding in clean)

    sources["sensible"] += "REFERENCE_LIMIT = 1\n" * 40
    findings = findings_at(tmp_path / "ratio", sources)
    assert_kind(findings, "monolith_file_tokens")
    assert not any(finding["kind"] == "monolith_tokens" for finding in findings)


@pytest.mark.parametrize(
    ("profile", "ratio", "kind"),
    [
        ("layered", 0.8, None),
        ("layered", 0.79, "monolith_file_tokens"),
        ("default", 1.3, None),
        ("default", 1.29, "monolith_file_tokens"),
    ],
)
def test_monolith_file_token_floor_boundaries(
    tmp_path, monkeypatch, profile, ratio, kind
):
    root = tmp_path / profile
    root.mkdir()
    item = layered_item(root, profile=profile == "layered")
    paths = {name: item / f"{name}.py" for name in VERSIONS}
    state = item_spec_rules._load("python", paths)
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: (
            100 if source == state.sources["sensible"] else round(100 * ratio)
        ),
    )
    findings = []
    item_spec_rules._rule_monolith(findings, state)
    assert any(f["kind"] == "monolith_file_tokens" for f in findings) is (
        kind is not None
    )


@pytest.mark.parametrize(("ratio", "fails"), [(1.6, False), (1.61, True)])
def test_layered_monolith_file_token_ceiling(tmp_path, monkeypatch, ratio, fails):
    item = layered_item(tmp_path, profile=True)
    paths = {name: item / f"{name}.py" for name in VERSIONS}
    state = item_spec_rules._load("python", paths)
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: (
            100 if source == state.sources["sensible"] else round(100 * ratio)
        ),
    )
    findings = []
    item_spec_rules._rule_monolith(findings, state)
    assert any(f["kind"] == "monolith_file_tokens_high" for f in findings) is fails


@pytest.mark.parametrize(("tokens", "fails"), [(750, True), (751, False)])
def test_layered_rust_monolith_function_token_boundary(tokens, fails, monkeypatch):
    sensible = [item_spec_rules.Function("part", 1000, 1, [], 0, "")]
    monolith = [item_spec_rules.Function("solution", tokens, 1, [], 15, "")]
    state = item_spec_rules.ItemState(
        language="rust",
        sources={"sensible": "sensible", "monolith": "monolith"},
        functions={"sensible": sensible, "monolith": monolith},
        calls={},
        entries={},
        profile="layered",
    )
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: 100 if source == "sensible" else 80,
    )
    findings = []
    item_spec_rules._rule_monolith(findings, state)
    matched = [finding for finding in findings if finding["kind"] == "monolith_tokens"]
    assert bool(matched) is fails
    if matched:
        assert matched[0]["limit"] == ">200 and >750.0"


def test_sizematched_whole_file_tokens_are_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    clean = findings_at(tmp_path / "clean", sources)
    assert not any(finding["kind"] == "sizematched_file_tokens" for finding in clean)

    sources["sizematched"] += "REFERENCE_LIMIT = 1\n" * 40
    findings = findings_at(tmp_path / "bigger", sources)
    assert_kind(findings, "sizematched_file_tokens")
    assert not any(finding["kind"] == "sizematched_tokens" for finding in findings)


@pytest.mark.parametrize(
    ("profile", "size_tokens", "fails"),
    [
        (True, 90, False),
        (True, 110, False),
        (True, 89, True),
        (True, 111, True),
        (False, 97, False),
        (False, 103, False),
        (False, 96, True),
        (False, 104, True),
    ],
)
def test_sizematched_whole_file_tolerance(
    profile, size_tokens, fails, tmp_path, monkeypatch
):
    item = layered_item(tmp_path, profile=profile)
    paths = {version: item / f"{version}.py" for version in VERSIONS}
    state = item_spec_rules._load("python", paths)
    sensible_source = state.sources["sensible"]
    monkeypatch.setattr(
        item_spec_rules,
        "whole_file_tokens",
        lambda source: 100 if source == sensible_source else size_tokens,
    )
    state.functions["sensible"] = [replace(state.functions["sensible"][0], tokens=100)]
    state.functions["sizematched"] = [
        replace(state.functions["sizematched"][0], tokens=100)
    ]
    findings = []
    item_spec_rules._rule_sizematched(findings, state)
    finding = next(
        (f for f in findings if f["kind"] == "sizematched_file_tokens"), None
    )
    assert (finding is not None) is fails
    if finding:
        assert finding["limit"] == ("100 ±10%" if profile else "100 ±3%")


@pytest.mark.parametrize(
    ("profile", "size_tokens", "fails"),
    [
        (True, 90, False),
        (True, 110, False),
        (True, 89, True),
        (True, 111, True),
        (False, 97, False),
        (False, 103, False),
        (False, 96, True),
        (False, 104, True),
    ],
)
def test_sizematched_function_tolerance(
    profile, size_tokens, fails, tmp_path, monkeypatch
):
    item = layered_item(tmp_path, profile=profile)
    paths = {version: item / f"{version}.py" for version in VERSIONS}
    state = item_spec_rules._load("python", paths)
    monkeypatch.setattr(item_spec_rules, "whole_file_tokens", lambda _source: 100)
    state.functions["sensible"] = [replace(state.functions["sensible"][0], tokens=100)]
    state.functions["sizematched"] = [
        replace(state.functions["sizematched"][0], tokens=size_tokens)
    ]
    findings = []
    item_spec_rules._rule_sizematched(findings, state)
    finding = next((f for f in findings if f["kind"] == "sizematched_tokens"), None)
    assert (finding is not None) is fails
    if finding:
        assert finding["limit"] == ("100 ±10%" if profile else "100 ±3%")


def test_sensible_call_depth_is_reported(tmp_path):
    conforming = conforming_sources(LANGUAGES["python"])
    assert not any(
        f["kind"] == "sensible_call_depth"
        for f in findings_for(tmp_path / "depth-two", conforming)
    )
    sources = conforming_sources(LANGUAGES["python"])
    sources["sensible"] = (
        "def solution(value):\n"
        "    return validate_one(value) + normalize_one(value)\n\n"
        "def validate_one(v):\n"
        "    return normalize_one(v)\n\n"
        "def normalize_one(v):\n"
        "    return v + 1\n"
    )
    findings = findings_for(tmp_path / "depth-three", sources)
    assert_kind(findings, "sensible_call_depth")
    assert next(f for f in findings if f["kind"] == "sensible_call_depth")["limit"] == 2


def test_python_class_method_edges_drive_reachability_and_metrics():
    functions = extract(
        "python",
        "class Worker:\n"
        "    def __init__(self): self.run()\n"
        "    def run(self): self.check_items()\n"
        "    def check_items(self): return 1\n"
        "    def unused(self): return 2\n"
        "def solution(): return Worker()\n",
    )
    calls = graph(functions)
    assert "__init__" in calls["solution"]
    assert calls["__init__"] == ["run"]
    assert calls["run"] == ["check_items"]
    assert "unused" not in reachable(calls, "solution")
    assert depth(calls, "solution") == 4
    assert len(calls["__init__"]) == 1


def test_typescript_method_edges_drive_reachability():
    functions = extract(
        "typescript",
        "class Worker { run() { this.checkItems(); } "
        "checkItems() { return 1; } unused() { return 2; } }\n"
        "function solution() { new Worker().run(); }\n",
    )
    calls = graph(functions)
    assert calls["run"] == ["checkItems"]
    assert "checkItems" in reachable(calls, "solution")
    assert "unused" not in reachable(calls, "solution")


@pytest.mark.parametrize(
    "case",
    [
        (
            "rust",
            "rs",
            (
                "struct Worker; impl Worker { fn run(&self) { self.check(); Self::check(); "
                "Worker::check(); Worker::new(); } fn check(&self) {} fn new() {} "
                "fn unused(&self) {} } fn solution(w: Worker) { w.run(); }"
            ),
            "solution",
            "run",
            "check",
        ),
        (
            "go",
            "go",
            (
                "package p\ntype Worker struct{}\n"
                "func (w *Worker) run() { x.check(); check() }\n"
                "func (w *Worker) check() {}\nfunc (w *Worker) unused() {}\n"
                "func solution(w Worker) { w.run() }"
            ),
            "solution",
            "run",
            "check",
        ),
        (
            "java",
            "java",
            "class Worker { void run() { x.check(); check(); } void check() {} void unused() {} void solution() { x.run(); } }",
            "solution",
            "run",
            "check",
        ),
        (
            "csharp",
            "cs",
            "class Worker { void Run() { x.Check(); Check(); } void Check() {} void Unused() {} void Solution() { x.Run(); } }",
            "Solution",
            "Run",
            "Check",
        ),
        (
            "cpp",
            "cpp",
            "class Worker { void run() { x.check(); check(); } void check() {} void unused() {} void solution() { x.run(); } };",
            "solution",
            "run",
            "check",
        ),
    ],
)
def test_tree_language_method_edges_use_unique_same_file_methods(tmp_path, case):
    language, extension, source, entry, method, callee = case
    require_grammar(language)
    fixture = tmp_path / f"methods.{extension}"
    fixture.write_text(source)
    functions = extract(language, fixture.read_text())
    calls = graph(functions)
    assert callee in calls[method]
    assert method in reachable(calls, entry)
    assert callee in reachable(calls, entry)
    assert not any(name.lower() == "unused" for name in reachable(calls, entry))
    if language == "rust":
        assert "new" in calls[method]


def test_go_bare_call_to_shadowed_method_name_is_not_an_edge(tmp_path):
    require_grammar("go")
    fixture = tmp_path / "shadow.go"
    fixture.write_text(
        "package p\ntype Worker struct{}\n"
        "func (w *Worker) run() {}\n"
        "func solution() { run := 1; _ = run; run() }\n"
    )
    calls = graph(extract("go", fixture.read_text()))
    assert "run" not in calls["solution"]


def test_monolith_size_and_cognitive_are_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["monolith"] = "def solution(value):\n    total = value\n    return total\n"
    findings = findings_for(tmp_path, sources)
    assert_kind(findings, "monolith_tokens")
    assert_kind(findings, "monolith_cognitive")


def test_tiny_shallow_chain_is_reported(tmp_path):
    edges = {name: [] for name in TINY_EDGES}
    edges["solution"] = ["helper_a", "helper_b", "helper_c", "helper_d"]
    sources = conforming_sources(LANGUAGES["python"], edges=edges)
    assert_kind(findings_for(tmp_path, sources), "tiny_chain_depth")


def test_tiny_entry_fanout_counts_distinct_same_file_callees(tmp_path):
    edges = {name: [] for name in TINY_EDGES}
    edges["solution"] = ["helper_a"]
    sources = conforming_sources(LANGUAGES["python"], edges=edges)
    sources["tiny"] = sources["tiny"].replace(
        "def solution(value): return helper_a(value)",
        "def solution(value): return helper_a(value) + helper_a(value)",
    )
    assert_kind(findings_for(tmp_path, sources), "tiny_entry_fanout")


def test_tiny_dead_code_and_redefinitions_are_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] += "\ndef spare(v): return v + 1\n"
    sources["tiny"] += "\ndef helper_a(v): return v + 1\n"
    findings = findings_for(tmp_path, sources)
    assert_kind(findings, "tiny_dead_code")
    assert_kind(findings, "tiny_redefinitions")


def test_tiny_forwarders_are_reported(tmp_path):
    edges = {name: [] for name in TINY_EDGES}
    edges["solution"] = ["helper_a", "helper_b", "helper_c", "helper_d"]
    edges["helper_a"] = ["helper_e", "helper_f"]
    edges["helper_b"] = ["helper_g", "helper_h"]
    edges["helper_c"] = ["helper_i", "helper_j"]
    edges["helper_d"] = ["helper_k", "helper_e"]
    sources = conforming_sources(LANGUAGES["python"], edges=edges)
    assert_kind(findings_for(tmp_path, sources), "tiny_forwarders")


def test_padded_shape_and_names_are_reported(tmp_path):
    edges = {name: [] for name in TINY_EDGES}
    edges["solution"] = ["helper_a"]
    sources = conforming_sources(
        LANGUAGES["python"], padded_edges=edges, named_edges=edges
    )
    findings = findings_for(tmp_path, sources)
    assert_kind(findings, "padded_shape")
    assert_kind(findings, "padded_names")
    assert_kind(findings, "namematched_names")


def test_padded_identity_assignment_is_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["padded"] = sources["padded"].replace(
        "    second = first * 2\n", "    second = first\n"
    )
    assert_kind(findings_for(tmp_path, sources), "padded_identity_assignment")


def test_padded_token_range_applies_to_helpers(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["padded"] = sources["padded"].replace(
        "def derive_alpha(v):\n"
        "    first = v + 1\n"
        "    second = first * 2\n"
        "    third = second + 3\n"
        "    fourth = third - first\n"
        "    return scale_alpha(fourth) + first - third + second",
        "def derive_alpha(v): return scale_alpha(v)",
    )
    findings = findings_for(tmp_path, sources)
    flagged = {
        finding["function"]
        for finding in findings
        if finding["kind"] == "padded_function_tokens"
    }
    assert flagged == {"derive_alpha"}
    assert not any(finding["kind"] == "padded_entry_tokens" for finding in findings)


def test_padded_entry_token_cap_boundary(tmp_path):
    base = (
        "derive_alpha(derive_beta(value)) + derive_gamma(value) + derive_delta(value)"
    )
    findings, tokens = padded_entry_at_tokens(
        tmp_path / "at-cap", f"{base} + (not value)" + " + value + 1" * 4
    )
    assert tokens == 45
    assert not any(finding["kind"] == "padded_entry_tokens" for finding in findings)

    findings, tokens = padded_entry_at_tokens(
        tmp_path / "over-cap",
        f"{base} + (not value) + (not value)" + " + value + 1" * 3,
    )
    assert tokens == 46
    assert {
        finding["function"]
        for finding in findings
        if finding["kind"] == "padded_entry_tokens"
    } == {"solution"}


def test_anonymous_lambda_keeps_its_helper_reachable(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace(
        "def helper_a(v): return helper_e(v) + 1",
        "def helper_a(v): return (lambda x: helper_e(x))(v) + 1",
    )
    findings = findings_for(tmp_path, sources)
    assert not any(finding["kind"] == "tiny_dead_code" for finding in findings)
    helper_a = next(
        function
        for function in extract("python", sources["tiny"])
        if function.name == "helper_a"
    )
    assert "helper_e" in helper_a.calls


def test_entry_signature_parity_includes_return_annotation(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["padded"] = sources["padded"].replace(
        "def solution(value):", "def solution(value) -> str:"
    )
    assert_kind(findings_for(tmp_path, sources), "entry_signature_parity")


def test_comment_parity_ignores_hashes_inside_strings(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace(
        "def helper_k(v): return v + 1", "def helper_k(v): return v + 1  # real"
    )
    sources["namematched"] = sources["namematched"].replace(
        "def sum_total(v): return v + 1", 'def sum_total(v): return "# real"'
    )
    assert_kind(findings_for(tmp_path, sources), "comment_parity")


def test_split_category_word_is_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace("helper_a", "stepCount")
    findings = findings_for(tmp_path, sources)
    matches = [
        finding["value"] for finding in findings if finding["kind"] == "category_word"
    ]
    assert ["step"] in matches


def test_sizematched_tokens_are_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["sizematched"] = "def solution(value):\n    return value\n"
    assert_kind(findings_for(tmp_path, sources), "sizematched_tokens")


def test_recursion_cycle_is_reported(tmp_path):
    edges = {name: [] for name in TINY_EDGES}
    edges["solution"] = ["helper_a", "helper_b", "helper_c", "helper_d"]
    edges["helper_a"] = ["solution"]
    sources = conforming_sources(LANGUAGES["python"], edges=edges)
    assert_kind(findings_for(tmp_path, sources), "recursion")


def test_self_call_is_reported_as_recursion(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace(
        "def helper_a(v): return helper_e(v) + 1",
        "def helper_a(v): return helper_a(v) + 1",
    )
    findings = findings_for(tmp_path, sources)
    assert_kind(findings, "recursion")
    assert not any(
        finding["kind"].endswith("chain_depth") and finding["value"] == 99
        for finding in findings
    )


def test_comment_parity_is_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = "# a note\n" + sources["tiny"]
    assert_kind(findings_for(tmp_path, sources), "comment_parity")


def test_category_word_is_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace("helper_a", "hop_a")
    assert_kind(findings_for(tmp_path, sources), "category_word")


def test_entry_name_and_signature_parity_are_reported(tmp_path):
    sources = conforming_sources(LANGUAGES["python"])
    sources["tiny"] = sources["tiny"].replace(
        "def solution(value):", "def solve(value):"
    )
    sources["padded"] = sources["padded"].replace(
        "def solution(value):", "def solution(other):"
    )
    findings = findings_for(tmp_path, sources)
    assert_kind(findings, "entry_name")
    assert_kind(findings, "entry_signature_parity")


def test_each_missing_version_is_a_structured_violation(tmp_path):
    item = tmp_path / "item"
    item.mkdir(parents=True)
    violations, _ = check_item(item, "python")
    assert {finding["kind"] for finding in violations} == {"missing_version"}


# --- command line contract --------------------------------------------------


def test_cli_prints_metrics_and_json_lines(tmp_path):
    item = write_item(tmp_path)
    result = run_tool("--items", str(item), "--language", "python", "--check")
    assert result.returncode == 1
    assert "whole_file_tokens=" in result.stdout
    assert result.stdout.count("whole_file_tokens=") == 6
    assert all(f"{name}:" in result.stdout for name in VERSIONS)
    rows = [
        json.loads(line) for line in result.stdout.splitlines() if line.startswith("{")
    ]
    assert rows and all(
        "kind" in row and "version" in row and "limit" in row for row in rows
    )


def test_cli_print_only_mode_returns_zero_with_violations(tmp_path):
    item = write_item(tmp_path)
    result = run_tool("--items", str(item), "--language", "python")
    assert result.returncode == 0
    assert "whole_file_tokens=" in result.stdout
    assert not any(line.startswith("{") for line in result.stdout.splitlines())


def test_cli_empty_directory_is_usage_error(tmp_path):
    result = run_tool("--items", str(tmp_path))
    assert result.returncode == 2
    assert "no item directories" in result.stderr


def test_cli_missing_directory_is_usage_error(tmp_path):
    result = run_tool("--items", str(tmp_path / "absent"))
    assert result.returncode == 2
    assert "does not exist" in result.stderr


def test_cli_python_syntax_error_is_structured_status_two(tmp_path):
    item = write_item(tmp_path)
    (item / "sensible.py").write_text("def solution(:\n")
    result = run_tool("--items", str(item), "--language", "python", "--check")
    assert result.returncode == 2
    assert json.loads(result.stdout.splitlines()[0])["kind"] == "syntax_error"
    assert "Traceback" not in result.stderr


def test_cli_tree_syntax_error_is_structured_status_two(tmp_path):
    require_grammar("typescript")
    lang = LANGUAGES["typescript"]
    sources = conforming_sources(lang)
    sources["tiny"] = "function solution(: number { }"
    item = write_language_item(tmp_path, lang, sources)
    result = run_tool("--items", str(item), "--language", "typescript", "--check")
    assert result.returncode == 2
    assert json.loads(result.stdout.splitlines()[0])["kind"] == "syntax_error"


def test_cli_missing_grammar_is_structured_status_two(tmp_path, monkeypatch, capsys):
    lang = LANGUAGES["typescript"]
    item = write_language_item(tmp_path, lang, conforming_sources(lang))

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("Could not load the typescript grammar.")

    monkeypatch.setattr(item_spec_rules, "extract", unavailable)
    code = item_spec_check.main(
        ["--items", str(item), "--language", "typescript", "--check"]
    )
    assert code == 2
    out = capsys.readouterr().out
    assert json.loads(out.splitlines()[0])["kind"] == "grammar_error"


ITEMS = Path(__file__).resolve().parents[2] / "items"


def test_rich_items_keep_checking_clean_without_alts() -> None:
    for language, extension in (
        ("python", ".py"),
        ("typescript", ".ts"),
        ("rust", ".rs"),
    ):
        if language != "python":
            require_grammar(language)
        for sensible in sorted((ITEMS / language / "b").glob(f"*/sensible{extension}")):
            result = run_tool(
                "--items", str(sensible.parent), "--language", language, "--check"
            )
            assert result.returncode == 0, sensible.parent.name + result.stdout
