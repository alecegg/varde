from pathlib import Path

import pytest
from ast_grep_py import SgRoot
from varde_code.pattern_match import (
    LANGUAGES,
    find_patterns,
    find_patterns_unbounded,
    language_name,
    wrap_pattern,
)


def test_find_patterns_matches_with_independent_ast_grep_root():
    matches = find_patterns("const answer = 42;", "const $NAME = $VALUE", "typescript")
    assert [match["text"] for match in matches] == ["const answer = 42;"]


def test_language_table_parses_with_ast_grep_py():
    failures = []
    for language in LANGUAGES:
        try:
            SgRoot("", language.name)
        except Exception as error:
            failures.append(f"{language.name}: {error}")
    assert not failures, failures


def test_csharp_and_solidity_statement_patterns_match_wrapped_source():
    assert find_patterns("class C { void M() { F(); } }", "F()", "csharp")
    assert "contract __VardeWrapper__" in wrap_pattern("solidity", "foo()")
    assert "class __VardeWrapper__" in wrap_pattern("csharp", "F()")


def test_find_patterns_unbounded_searches_files(tmp_path: Path):
    (tmp_path / "one.ts").write_text("foo(1);", encoding="utf-8")
    (tmp_path / "two.ts").write_text("foo(2);", encoding="utf-8")
    results = find_patterns_unbounded(tmp_path, "typescript", ["foo($A)"])
    assert len(results) == 1
    assert len(results[0]) == 2
    paths = [match["file"] for match in results[0]]
    assert all(isinstance(path, str) for path in paths)
    assert {Path(str(path)).name for path in paths} == {"one.ts", "two.ts"}


@pytest.mark.parametrize("alias,canonical", [("ts", "typescript"), ("cs", "csharp")])
def test_language_aliases(alias: str, canonical: str):
    assert language_name(alias) == canonical
