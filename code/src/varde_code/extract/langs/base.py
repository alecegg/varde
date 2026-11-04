"""Shared language table and tree-sitter node helpers for extraction."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import ModuleType

from tree_sitter import Node

from varde_code.model import EntityKind


def _text(node: Node | None) -> str:
    """Return a node's source text, or an empty string for a missing node."""
    if node is None:
        return ""
    value = node.text
    return (
        value.decode("utf-8", errors="replace")
        if isinstance(value, bytes)
        else str(value)
    )


def _field(node: Node | None, name: str | None) -> Node | None:
    """Return a named child field when both the node and field name exist."""
    return None if node is None or name is None else node.child_by_field_name(name)


@dataclass(frozen=True)
class VisitRule:
    """Describe an entity emitted for a matching syntax node."""

    kind: EntityKind
    name_field: str | None = "name"
    name_kind: str | None = None
    literal: str | None = None
    span_node: Node | None = None
    span_start_node: Node | None = None
    span_end_node: Node | None = None


@dataclass(frozen=True)
class LanguageTables:
    """Declarative per-language extraction tables and optional node hooks."""

    visits: Mapping[str, VisitRule] = field(default_factory=dict)
    function_scopes: frozenset[str] = frozenset()
    type_scopes: frozenset[str] = frozenset()
    required_kinds: tuple[EntityKind, ...] = tuple(EntityKind)
    flow_roles: Mapping[str, str] = field(default_factory=dict)
    type_kinds: frozenset[str] = frozenset()
    test_node: Callable[[Node], bool] | None = None
    function_name: Callable[[Node], str | None] | None = None
    type_name: Callable[[Node], str | None] | None = None
    visit_node: Callable[[Node], tuple[VisitRule, ...] | None] | None = None


def discover() -> dict[str, LanguageTables]:
    """Collect LANG tables from installed language modules."""
    from importlib import import_module

    from varde_code.parse import SUPPORTED_LANGUAGES

    tables: dict[str, LanguageTables] = {}
    for language in SUPPORTED_LANGUAGES:
        try:
            module_name = "ts" if language == "typescript" else language
            module: ModuleType = import_module(
                f"varde_code.extract.langs.{module_name}"
            )
        except ModuleNotFoundError as error:
            if error.name in {
                "varde_code.extract.langs",
                f"varde_code.extract.langs.{language}",
            }:
                continue
            raise
        table = getattr(module, "LANG", None)
        if isinstance(table, LanguageTables):
            tables[language] = table
    return tables


def strip_generic_args(name: str) -> str:
    """Remove a generic suffix from a type name."""
    return name.split("<", 1)[0].strip()


def unquote(text: str, allow_backtick: bool = False) -> str:
    """Strip one matching quote pair from literal text."""
    value = text.strip()
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in ("'\"" + ("`" if allow_backtick else ""))
    ):
        return value[1:-1]
    return value


@lru_cache(maxsize=1)
def _folded_flow_roles() -> dict[str, str]:
    """Fold registered flow-role names once; the first registration wins.

    A failing ``discover()`` raises, so ``lru_cache`` never stores a partial table.
    """
    roles: dict[str, str] = {}
    for table in discover().values():
        for registered, role in table.flow_roles.items():
            roles.setdefault(registered.lower(), role)
    return roles


def registered_flow_role(name: str) -> str | None:
    """Look up a normalized flow role across discovered language tables."""
    return _folded_flow_roles().get(name.lower())
