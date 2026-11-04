"""Sonar logical-operator sequence increments over the parse tree.

The shared engine derives logical sequences from extracted flow entities. For
these languages the extractor emits one entity per operator token of a whole
binary expression, all sharing the expression span, so the engine cannot see
operator runs. Sonar counts one increment per run of like operators, in
evaluation order (SonarSource Cognitive Complexity white paper, "Sequences of
logical operators" and rule S3776).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from tree_sitter import Node

from varde_code.model import Span
from varde_code.parse import parse_source_for_path

LOGICAL_LANGUAGES = frozenset({"typescript", "java", "go", "csharp", "cpp"})
_OPERATORS = frozenset({"&&", "||"})
_BINARY = "binary_expression"
_PARENTHESIZED = "parenthesized_expression"


def logical_sequence_totals(
    source: str, language: str, path: str | Path, spans: Iterable[Span]
) -> dict[tuple[int, int], int]:
    """Return Sonar sequence increments per callable span, keyed by byte range."""
    if language not in LOGICAL_LANGUAGES:
        return {}
    root = parse_source_for_path(language, path, source).root
    expressions = _maximal_expressions(root)
    return {
        (span.start_byte, span.end_byte): sum(
            increments
            for start, end, increments in expressions
            if span.start_byte <= start and end <= span.end_byte
        )
        for span in spans
    }


def _maximal_expressions(root: Node) -> list[tuple[int, int, int]]:
    """Collect each outermost logical expression with its increment count."""
    found = []
    pending = [root]
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if _is_logical(node) and not _has_logical_ancestor(node):
            operators = _operators(node)
            found.append((node.start_byte, node.end_byte, _increment_count(operators)))
    return found


def _has_logical_ancestor(node: Node) -> bool:
    ancestor = node.parent
    while ancestor is not None and ancestor.type == _PARENTHESIZED:
        ancestor = ancestor.parent
    return _is_logical(ancestor)


def _operators(node: Node) -> list[str]:
    """Flatten one logical expression into its in-order operator sequence."""
    operator = _operator(node)
    if operator is None:
        return []
    return [
        *_operand_operators(node.child_by_field_name("left")),
        operator,
        *_operand_operators(node.child_by_field_name("right")),
    ]


def _operand_operators(node: Node | None) -> list[str]:
    inner = _unparenthesized(node)
    if inner is None or not _is_logical(inner):
        return []
    return _operators(inner)


def _unparenthesized(node: Node | None) -> Node | None:
    while node is not None and node.type == _PARENTHESIZED and node.named_children:
        node = node.named_children[0]
    return node


def _is_logical(node: Node | None) -> bool:
    return node is not None and node.type == _BINARY and _operator(node) in _OPERATORS


def _operator(node: Node) -> str | None:
    token = node.child_by_field_name("operator")
    text = None if token is None else token.text
    if text is None:
        return None
    return text.decode("utf-8", errors="replace")


def _increment_count(operators: list[str]) -> int:
    return sum(
        1
        for index, operator in enumerate(operators)
        if index == 0 or operators[index - 1] != operator
    )
