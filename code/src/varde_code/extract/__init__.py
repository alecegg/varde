"""Shared source entity extraction framework."""

from __future__ import annotations

from varde_code.model import Entity, EntityKind, ExtractOutput, Symbol, SymbolKind

from .entity import extract_file, node_is_test
from .langs import language_tables, tables_for
from .minhash import body_minhash
from .preproc import scan as scan_preprocessor
from .recursion import resolve as resolve_recursion
from .symbol import extract_symbols

__all__ = [
    "Entity",
    "EntityKind",
    "ExtractOutput",
    "Symbol",
    "SymbolKind",
    "body_minhash",
    "extract_file",
    "extract_symbols",
    "language_tables",
    "node_is_test",
    "resolve_recursion",
    "scan_preprocessor",
    "tables_for",
]
