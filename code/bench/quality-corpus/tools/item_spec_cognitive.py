"""SonarSource-style cognitive complexity for Python and tree-sitter sources.

The score follows the published model: each branching construct costs one plus
its nesting level, a switch or match costs one plus its nesting level no matter
how many cases or arms it has, an ``else`` costs one, an ``else if`` costs one
without raising nesting, and every change of boolean operator in a logical
chain costs one. Recursion is added by the extractor, which knows the enclosing
function's name. Anonymous functions that are not extracted as their own
function stay inside their parent, so their branches count for the parent.
"""

from __future__ import annotations

import ast
from collections.abc import Callable

from item_spec_languages import COGNITIVE, FUNCTION_NODES


def python_cognitive(node: ast.AST, is_extracted: Callable[[ast.AST], bool]) -> int:
    score = _PythonScore(is_extracted)
    score.descend(node, 0)
    return score.total


class _PythonScore:
    def __init__(self, is_extracted: Callable[[ast.AST], bool]) -> None:
        self.is_extracted = is_extracted
        self.total = 0

    def descend(self, node: ast.AST, nesting: int) -> None:
        for child in ast.iter_child_nodes(node):
            self.visit(child, nesting)

    def visit(self, node: ast.AST, nesting: int, else_if: bool = False) -> None:
        if self.is_extracted(node):
            return
        if isinstance(node, ast.If):
            self._if(node, nesting, else_if)
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self.total += 1 + nesting
            self.descend(node, nesting + 1)
        elif isinstance(node, ast.BoolOp):
            self.total += 1
            self.descend(node, nesting)
        elif isinstance(node, (ast.ExceptHandler, ast.IfExp, ast.Match)):
            self.total += 1 + nesting
            self.descend(node, nesting + 1)
        else:
            self.descend(node, nesting)

    def _if(self, node: ast.If, nesting: int, else_if: bool) -> None:
        self.total += 1 if else_if else 1 + nesting
        inner = nesting + 1
        self.visit(node.test, inner)
        for statement in node.body:
            self.visit(statement, inner)
        if not node.orelse:
            return
        first = node.orelse[0]
        if isinstance(first, ast.If) and first.col_offset == node.col_offset:
            self.visit(first, nesting, else_if=True)
            return
        self.total += 1
        for statement in node.orelse:
            self.visit(statement, inner)


def tree_cognitive(root, language: str, is_extracted: Callable[[object], bool]) -> int:
    score = _TreeScore(language, root, is_extracted)
    score.visit(root, 0)
    return score.total


class _TreeScore:
    def __init__(
        self, language: str, root, is_extracted: Callable[[object], bool]
    ) -> None:
        self.spec = COGNITIVE[language]
        self.functions = FUNCTION_NODES[language]
        self.is_extracted = is_extracted
        self.root = root
        self.total = 0

    def visit(self, node, nesting: int, else_if: bool = False) -> None:
        if (
            node is not self.root
            and node.type in self.functions
            and self.is_extracted(node)
        ):
            return
        if node.type in self.spec.boolean:
            self.total += self._boolean(node)
            self.descend(node, nesting)
            return
        if node.type in self.spec.branches:
            self.total += 1 if else_if else 1 + nesting
            self._branch(node, nesting)
            return
        if node.type in self.spec.else_nodes:
            self._else(node, nesting)
            return
        self.descend(node, nesting)

    def descend(self, node, nesting: int) -> None:
        for child in node.named_children:
            self.visit(child, nesting)

    def _branch(self, node, nesting: int) -> None:
        alternative = self._alternative(node)
        for child in node.named_children:
            if _same_node(child, alternative):
                self._alternative_node(child, nesting)
            else:
                self.visit(child, nesting + 1)

    def _alternative(self, node):
        if self.spec.else_field:
            return node.child_by_field_name(self.spec.else_field)
        return next(
            (
                child
                for child in node.named_children
                if child.type in self.spec.else_nodes
            ),
            None,
        )

    def _alternative_node(self, child, nesting: int) -> None:
        if child.type in self.spec.branches:
            self.visit(child, nesting, else_if=True)
            return
        if child.type in self.spec.else_nodes:
            self._else(child, nesting)
            return
        self.total += 1
        self.descend(child, nesting + 1)

    def _else(self, node, nesting: int) -> None:
        inner = next(
            (
                child
                for child in node.named_children
                if child.type in self.spec.branches
            ),
            None,
        )
        if inner is None:
            self.total += 1
            self.descend(node, nesting + 1)
            return
        self.visit(inner, nesting, else_if=True)

    def _boolean(self, node) -> int:
        operator = node.child_by_field_name("operator")
        if operator is None or operator.type not in self.spec.operators:
            return 0
        parent = node.parent
        if parent is not None and parent.type in self.spec.boolean:
            parent_operator = parent.child_by_field_name("operator")
            if parent_operator is not None and parent_operator.type == operator.type:
                return 0
        return 1


def _same_node(left, right) -> bool:
    return (
        left is not None
        and right is not None
        and left.start_byte == right.start_byte
        and left.end_byte == right.end_byte
        and left.type == right.type
    )
