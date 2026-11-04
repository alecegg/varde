"""Tree-sitter parser abstraction and supported language registry."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Protocol

import tree_sitter_language_pack
from tree_sitter import Node, Tree
from tree_sitter import Parser as NativeParser
from tree_sitter_language_pack import (
    Error as LanguagePackError,
)
from tree_sitter_language_pack import (
    PackConfig,
    configure,
    get_language,
)

EXTENSION_LANGUAGES = {
    "ts": "typescript",
    "mts": "typescript",
    "cts": "typescript",
    "tsx": "tsx",
    "js": "javascript",
    "jsx": "javascript",
    "mjs": "javascript",
    "cjs": "javascript",
    "c": "c",
    "h": "c",
    "cpp": "cpp",
    "cc": "cpp",
    "cxx": "cpp",
    "c++": "cpp",
    "hpp": "cpp",
    "hh": "cpp",
    "hxx": "cpp",
    "h++": "cpp",
    "go": "go",
    "java": "java",
    "cs": "csharp",
    "kt": "kotlin",
    "kts": "kotlin",
    "swift": "swift",
    "py": "python",
    "rb": "ruby",
    "php": "php",
    "lua": "lua",
    "scala": "scala",
    "sc": "scala",
    "sbt": "scala",
    "dart": "dart",
    "ex": "elixir",
    "exs": "elixir",
    "sol": "solidity",
    "hs": "haskell",
    "sh": "bash",
    "bash": "bash",
    "zsh": "bash",
    "ksh": "bash",
    "bats": "bash",
    "rs": "rust",
}
ALIASES = {
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
SUPPORTED_LANGUAGES = tuple(dict.fromkeys(EXTENSION_LANGUAGES.values()))


class Parser(Protocol):
    def parse(self, language: str, source: str) -> ParsedFile: ...


@dataclass(frozen=True)
class ParsedFile:
    lang: str
    tree: Tree
    source: bytes
    masked_preprocessor: bool = False

    @property
    def root(self) -> Node:
        return self.tree.root_node

    def has_error(self) -> bool:
        return self.root.has_error


class TreeSitterParser:
    """Implementation using grammars cached by tree-sitter-language-pack."""

    def parse(self, language: str, source: str) -> ParsedFile:
        lang = language_from_name(language)
        if lang is None:
            raise ValueError(f"unsupported language: {language}")
        data = source.replace("\0", " ").encode("utf-8")
        _configure_language_cache()
        try:
            grammar = get_language(lang)
        except (LanguagePackError, OSError) as exc:
            raise RuntimeError(
                f"Could not load the {lang} grammar. Check that the tree-sitter-language-pack "
                "cache is writable and that the grammar was prefetched before running offline."
            ) from exc
        parser = NativeParser(grammar)
        return ParsedFile(lang, parser.parse(data), data)


def _configure_language_cache() -> None:
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    if configured:
        configure(PackConfig(cache_dir=configured))
    cache = (
        Path(configured) if configured else Path(tree_sitter_language_pack.cache_dir())
    )
    try:
        cache.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=cache, prefix=".varde-write-check-", delete=True
        ):
            pass
    except OSError as exc:
        raise RuntimeError(
            f"Tree-sitter grammar cache is not writable: {cache}. Set "
            "VARDE_TREE_SITTER_CACHE_DIR to a writable directory."
        ) from exc


def language_for_extension(extension: str) -> str | None:
    return EXTENSION_LANGUAGES.get(extension.removeprefix(".").lower())


def language_for_path(path: str | PurePath) -> str | None:
    return language_for_extension(Path(path).suffix)


def language_from_name(name: str) -> str | None:
    name = name.lower()
    if name in SUPPORTED_LANGUAGES:
        return name
    return ALIASES.get(name)


def language_name(language: str) -> str:
    resolved = language_from_name(language)
    if resolved is None:
        raise ValueError(f"unsupported language: {language}")
    return resolved


def parse_source(
    language: str, source: str, parser: Parser | None = None
) -> ParsedFile:
    return (parser or TreeSitterParser()).parse(language, source)


def parse_source_for_path(
    language: str, path: str | Path, source: str, parser: Parser | None = None
) -> ParsedFile:
    parse = parser or TreeSitterParser()
    parsed = parse.parse(language, source)
    if (
        language_from_name(language) == "c"
        and Path(path).suffix.lower() == ".h"
        and parsed.has_error()
    ):
        cpp = parse.parse("cpp", source)
        if not cpp.has_error():
            return cpp
        recovered_cpp = _preprocessor_recovery("cpp", source, cpp, parse)
        if not recovered_cpp.has_error():
            return recovered_cpp
    return _preprocessor_recovery(language, source, parsed, parse)


def _preprocessor_recovery(
    language: str, source: str, parsed: ParsedFile, parser: Parser
) -> ParsedFile:
    if (
        language_from_name(language) not in {"c", "cpp", "csharp"}
        or not parsed.has_error()
    ):
        return parsed
    lines = source.splitlines(keepends=True)
    if not any(_directive(line)[0] in {"if", "ifdef", "ifndef"} for line in lines):
        return parsed
    masked = _mask_lines(lines, alternatives=False)
    recovered = parser.parse(language, masked)
    if not recovered.has_error():
        return _mark_masked(recovered)
    if any(_directive(line)[0] in {"elif", "elseif", "else"} for line in lines):
        masked = _mask_lines(lines, alternatives=True)
        recovered = parser.parse(language, masked)
        if not recovered.has_error():
            return _mark_masked(recovered)
    return parsed


def _directive(line: str) -> tuple[str, bool]:
    stripped = line.lstrip()
    if not stripped.startswith("#"):
        return "", False
    parts = stripped[1:].strip().split(maxsplit=1)
    return (parts[0] if parts else ""), True


def _mask_lines(lines: list[str], alternatives: bool) -> str:
    branches: list[bool] = []
    masked: list[str] = []
    for line in lines:
        directive, is_directive = _directive(line)
        if is_directive:
            if directive in {"if", "ifdef", "ifndef"}:
                branches.append(False)
            elif directive in {"elif", "elseif", "else"} and branches:
                branches[-1] = True
            elif directive == "endif" and branches:
                branches.pop()
            masked.append(_spaces_preserving_newlines(line))
        elif alternatives and any(branches):
            masked.append(_spaces_preserving_newlines(line))
        else:
            masked.append(line)
    return "".join(masked)


def _spaces_preserving_newlines(text: str) -> str:
    return "".join(char if char in "\r\n" else " " for char in text)


def _mark_masked(parsed: ParsedFile) -> ParsedFile:
    return ParsedFile(parsed.lang, parsed.tree, parsed.source, masked_preprocessor=True)


def parse_file(path: str | Path, parser: Parser | None = None) -> ParsedFile | None:
    path = Path(path)
    language = language_for_path(path)
    if language is None:
        return None
    return parse_source_for_path(
        language, path, path.read_text(encoding="utf-8"), parser
    )
