"""Syntax checks for mutation candidates using offline-safe parsers."""

from __future__ import annotations

import ast
import os
from pathlib import Path

from varde_code.parse import parse_source


def grammar_cache_dir() -> Path:
    """Return the external cache used for tree-sitter grammars."""
    cache_root = Path(
        os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde-bench")
    )
    return cache_root / "grammars"


def typescript_grammar_path() -> Path | None:
    """Find an already downloaded TypeScript grammar without triggering a fetch."""
    configured = os.environ.get("VARDE_TREE_SITTER_CACHE_DIR")
    root = Path(configured) if configured else grammar_cache_dir()
    return next(
        root.glob("tree-sitter-language-pack/*/libs/libtree_sitter_typescript.*"), None
    )


def typescript_grammar_available() -> bool:
    return typescript_grammar_path() is not None


def parse_typescript(source: str):
    """Parse TypeScript with the repository parser and configured external cache."""
    os.environ.setdefault("VARDE_TREE_SITTER_CACHE_DIR", str(grammar_cache_dir()))
    return parse_source("typescript", source)


def parses(language: str, source: str) -> bool:
    if language == "python":
        try:
            ast.parse(source)
        except SyntaxError:
            return False
        return True
    if language == "typescript":
        if not typescript_grammar_available():
            return False
        try:
            return not parse_typescript(source).has_error()
        except RuntimeError, OSError, ValueError:
            return False
    raise ValueError(f"unsupported mutation language: {language}")
