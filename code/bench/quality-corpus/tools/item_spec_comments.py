"""Count real comments and docstrings for item comment parity.

Python comments come from ``tokenize`` and docstrings from the AST; tree
languages use comment nodes from the parsed tree. Counting parsed comments
instead of matching ``#`` or ``//`` text keeps hashes inside string literals
out of the comparison.
"""

from __future__ import annotations

import ast
import io
import tokenize

from varde_code.parse import parse_source

COMMENT_NODES = frozenset({"comment", "line_comment", "block_comment"})
DOCSTRING_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def comment_shape(language: str, source: str) -> tuple[int, str]:
    """Return the comment and docstring count and length class of a source."""
    pieces = (
        _python_comments(source)
        if language == "python"
        else _tree_comments(language, source)
    )
    size = sum(len(piece) for piece in pieces)
    return len(pieces), _length_class(size)


def _python_comments(source: str) -> list[str]:
    tokens = tokenize.generate_tokens(io.StringIO(source).readline)
    comments = [token.string for token in tokens if token.type == tokenize.COMMENT]
    return comments + _python_docstrings(source)


def _python_docstrings(source: str) -> list[str]:
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, DOCSTRING_OWNERS):
            continue
        body = getattr(node, "body", None)
        if body and _is_docstring(body[0]):
            found.append(body[0].value.value)
    return found


def _is_docstring(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Constant)
        and isinstance(statement.value.value, str)
    )


def _tree_comments(language: str, source: str) -> list[str]:
    parsed = parse_source(language, source)
    data = parsed.source
    found: list[str] = []

    def walk(node) -> None:
        if node.type in COMMENT_NODES:
            found.append(data[node.start_byte : node.end_byte].decode())
            return
        for child in node.named_children:
            walk(child)

    walk(parsed.root)
    return found


def _length_class(size: int) -> str:
    if size < 80:
        return "short"
    return "medium" if size < 240 else "long"
