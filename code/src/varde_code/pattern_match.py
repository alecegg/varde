"""Pattern matching helpers backed by an independent ast-grep syntax tree."""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from ast_grep_py import SgRoot


class Language(NamedTuple):
    name: str


LANGUAGES = tuple(
    Language(name)
    for name in (
        "typescript",
        "tsx",
        "javascript",
        "c",
        "cpp",
        "go",
        "java",
        "csharp",
        "kotlin",
        "swift",
        "python",
        "ruby",
        "php",
        "scala",
        "dart",
        "lua",
        "elixir",
        "solidity",
        "haskell",
        "bash",
        "rust",
    )
)
LANGUAGE_ALIASES = {
    "ts": "typescript",
    "js": "javascript",
    "c++": "cpp",
    "cxx": "cpp",
    "golang": "go",
    "cs": "csharp",
    "kt": "kotlin",
    "py": "python",
    "rb": "ruby",
    "ex": "elixir",
    "sol": "solidity",
    "hs": "haskell",
    "sh": "bash",
    "shell": "bash",
}


def language_name(language: str) -> str:
    """Resolve a canonical language name or supported alias."""
    name = language.lower()
    name = LANGUAGE_ALIASES.get(name, name)
    if name not in _LANGUAGE_NAMES:
        raise ValueError(f"unsupported pattern language: {language}")
    return name


_LANGUAGE_NAMES = frozenset(lang.name for lang in LANGUAGES)


def wrap_pattern(language: str, pattern: str) -> str:
    """Place statement fragments into parseable syntax where required."""
    lang = language_name(language)
    wrappers = {
        "typescript": ("function __varde_wrapper__() { ", " }"),
        "tsx": ("function __varde_wrapper__() { ", " }"),
        "javascript": ("function __varde_wrapper__() { ", " }"),
        "go": ("func __varde_wrapper__() { ", " }"),
        "swift": ("func __varde_wrapper__() { ", " }"),
        "python": ("def __varde_wrapper__():\n    ", "\n"),
        "c": ("void __varde_wrapper__() { ", "; }"),
        "cpp": ("void __varde_wrapper__() { ", "; }"),
        "dart": ("void __varde_wrapper__() { ", "; }"),
        "java": ("class __VardeWrapper__ { void __varde_wrapper__() { ", "; } }"),
        "csharp": ("class __VardeWrapper__ { void __varde_wrapper__() { ", "; } }"),
        "kotlin": ("fun __varde_wrapper__() { ", " }"),
        "php": ("<?php function __varde_wrapper__() { ", "; }"),
        "scala": ("object __VardeWrapper__ { def __varde_wrapper__() = { ", " } }"),
        "solidity": (
            "contract __VardeWrapper__ { function __varde_wrapper__() public { ",
            "; } }",
        ),
        "ruby": ("def __varde_wrapper__\n", "\nend"),
        "lua": ("function __varde_wrapper__() ", " end"),
        "rust": ("fn __varde_wrapper__() { ", " }"),
    }
    prefix, suffix = wrappers.get(lang, ("", ""))
    return prefix + pattern + suffix


def find_patterns(source: str, pattern: str, language: str) -> list[dict[str, object]]:
    """Return ast-grep matches for a pattern in source using its own SgRoot."""
    source_root = SgRoot(source, language_name(language))
    nodes = source_root.root().find_all({"rule": {"pattern": pattern}})
    return [
        {"kind": node.kind(), "text": node.text(), "range": node.range()}
        for node in nodes
    ]


def find_patterns_unbounded(
    repo_root: str | Path, language: str, patterns: list[str] | tuple[str, ...]
) -> list[list[dict[str, object]]]:
    """Find each pattern in all readable files under a repository root."""
    lang = language_name(language)
    results: list[list[dict[str, object]]] = [[] for _ in patterns]
    for path in Path(repo_root).rglob("*"):
        if not path.is_file():
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = SgRoot(source, lang)
        except Exception:
            continue
        for index, pattern in enumerate(patterns):
            try:
                results[index].extend(
                    {
                        "file": str(path),
                        "kind": node.kind(),
                        "text": node.text(),
                        "range": node.range(),
                    }
                    for node in tree.root().find_all({"rule": {"pattern": pattern}})
                )
            except Exception:
                continue
    return results
