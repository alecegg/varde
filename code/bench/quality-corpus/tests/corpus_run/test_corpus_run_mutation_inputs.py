"""Behaviour tests for the mutation inputs selected from mutation-base repos."""

from __future__ import annotations

import ast
import json
import os
import re
from pathlib import Path

import pytest
from corpus.manifest import load_manifest
from varde_code.parse import parse_source

QUALITY_CORPUS = Path(__file__).resolve().parents[2]
MANIFEST = QUALITY_CORPUS / "corpus" / "manifest.toml"
INPUTS = QUALITY_CORPUS / "corpus" / "verified" / "mutation-inputs"
SUMMARY = INPUTS / "summary.json"
SHA = re.compile(r"^[0-9a-f]{40}$")
MIN_LINES = 10
MAX_LINES = 60
PARSER_LANGUAGES = {
    "typescript": "typescript",
    "java": "java",
    "go": "go",
    "rust": "rust",
    "csharp": "csharp",
    "cpp": "cpp",
}
# The grammar pack names its libraries after the language, with c_sharp spelled
# with an underscore.
GRAMMAR_LIBRARIES = {"csharp": "c_sharp"}


def _summary() -> dict:
    return json.loads(SUMMARY.read_text(encoding="utf-8"))


def _manifest() -> dict:
    return load_manifest(MANIFEST)


def _input_files(language: str) -> list[Path]:
    return sorted(
        path
        for path in (INPUTS / language).iterdir()
        if path.is_file()
        and not path.name.endswith(".license.txt")
        and path.name != "provenance.json"
    )


def grammar_root() -> Path:
    """Resolve the tree-sitter grammar cache the repository parses with."""
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        return Path(configured)
    bench = os.environ.get("VARDE_BENCH_CACHE")
    if bench:
        return Path(bench) / "grammars"
    return Path.home() / ".cache" / "varde-bench" / "grammars"


def _grammar_available(language: str) -> bool:
    library = GRAMMAR_LIBRARIES.get(language, language)
    return bool(list(grammar_root().rglob(f"libtree_sitter_{library}.*")))


def test_provenance_matches_the_input_files_and_the_manifest() -> None:
    data = _manifest()
    by_name = {repo["name"]: repo for repo in data["repositories"]}
    summary = _summary()
    for language, stats in summary["languages"].items():
        provenance = json.loads(
            (INPUTS / language / "provenance.json").read_text(encoding="utf-8")
        )
        entries = provenance["inputs"]
        files = _input_files(language)
        assert stats["inputs"] == len(files) == len(entries), language
        assert {entry["file"] for entry in entries} == {path.name for path in files}
        assert stats["repositories"] == sorted({entry["repo"] for entry in entries}), (
            language
        )
        for entry in entries:
            repo = by_name[entry["repo"]]
            assert repo["roles"] == ["mutation-base"], entry["file"]
            assert entry["license"] == repo["spdx"], entry["file"]
            assert entry["pin_sha"] == repo["pin_sha"], entry["file"]
            assert SHA.fullmatch(entry["pin_sha"]), entry["file"]
            assert entry["path"] and entry["function"], entry["file"]
            assert MIN_LINES <= entry["lines"] <= MAX_LINES, entry["file"]
            assert (INPUTS / language / entry["file"]).is_file(), entry["file"]


def test_each_input_is_one_parseable_function_of_the_declared_line_count() -> None:
    for language in _summary()["languages"]:
        for path in _input_files(language):
            lines = path.read_text(encoding="utf-8").rstrip("\n").splitlines()
            assert MIN_LINES <= len(lines) <= MAX_LINES, path
            if language == "python":
                tree = ast.parse(path.read_text(encoding="utf-8"))
                assert tree.body, path
            else:
                parser_language = PARSER_LANGUAGES[language]
                if not _grammar_available(parser_language):
                    continue
                assert _parses(parser_language, path.read_text(encoding="utf-8")), path


def _parses(parser_language: str, source: str) -> bool:
    os.environ.setdefault("VARDE_TREE_SITTER_CACHE_DIR", str(grammar_root()))
    return not parse_source(parser_language, source).has_error()


@pytest.mark.parametrize("language", sorted(PARSER_LANGUAGES))
def test_non_python_inputs_parse_with_the_repo_grammar(language: str) -> None:
    if language not in _summary()["languages"]:
        pytest.skip(f"no {language} mutation inputs selected")
    if not _grammar_available(PARSER_LANGUAGES[language]):
        pytest.skip(
            f"no tree-sitter {PARSER_LANGUAGES[language]} grammar under "
            f"{grammar_root()}"
        )
    for path in _input_files(language):
        assert _parses(PARSER_LANGUAGES[language], path.read_text(encoding="utf-8"))


def test_license_headers_are_kept_in_sidecars() -> None:
    for language in _summary()["languages"]:
        provenance = json.loads(
            (INPUTS / language / "provenance.json").read_text(encoding="utf-8")
        )
        kept = [entry for entry in provenance["inputs"] if entry["license_header"]]
        assert len(kept) == _summary()["languages"][language]["license_headers"]
        for entry in kept:
            sidecar = INPUTS / language / entry["license_header"]
            assert sidecar.is_file(), entry["file"]
            assert re.search(
                r"copyright|licen[cs]e|spdx",
                sidecar.read_text(encoding="utf-8"),
                re.IGNORECASE,
            ), entry["file"]


def test_every_release_language_has_inputs_or_a_recorded_shortfall() -> None:
    summary = _summary()
    report = (QUALITY_CORPUS / "corpus" / "verified" / "REPORT.md").read_text(
        encoding="utf-8"
    )
    release_input_languages = {
        "python",
        "typescript",
        "java",
        "go",
        "rust",
        "csharp",
        "cpp",
    }
    assert set(summary["languages"]) == release_input_languages
    for language, stats in summary["languages"].items():
        assert stats["inputs"] >= 1, language
        assert stats["inputs"] == len(_input_files(language)), language
        assert f"| {language} |" in report, language
    assert summary["total"] == sum(
        stats["inputs"] for stats in summary["languages"].values()
    )
