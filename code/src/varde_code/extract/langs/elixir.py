"""Elixir entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset()
TYPE_SCOPES = frozenset()
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.INTERFACE,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.CATCH,
    EntityKind.THROW,
    EntityKind.CONTROL_FLOW,
    EntityKind.ROUTE,
)
FLOW_NAME_ROLES = {
    "elixir_cond": "ignored",
    "elixir_comprehension": "legacy_nesting",
    "elixir_guard_statement": "legacy_nesting",
    "elixir_receive": "else",
    "elixir_unknown_multi_clause_grouping": "ignored",
}
_FUNCTION_DEFS = frozenset(
    {"def", "defp", "defmacro", "defmacrop", "defguard", "defguardp"}
)
_IMPORTS = frozenset({"import", "alias", "require", "use"})
_CONTROL = {
    "if": "if",
    "unless": "unless",
    "case": "case",
    "cond": "elixir_cond",
    "for": "elixir_comprehension",
    "with": "with",
    "receive": "elixir_receive",
    "try": "try",
}
_LITERALS = frozenset(
    {"integer", "float", "string", "atom", "boolean", "nil", "char", "charlist"}
)


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _args(node: Node) -> list[Node]:
    args = next((child for child in node.children if child.type == "arguments"), None)
    return list(args.named_children) if args else []


def _target(node: Node) -> Node | None:
    return node.child_by_field_name("target")


def _function_head(node: Node) -> tuple[str, Node | None] | None:
    args = _args(node)
    if not args:
        return None
    head = args[0]
    if head.type == "call":
        name = _text(_target(head))
        return (name, head) if name else None
    if head.type == "binary_operator":
        left = head.child_by_field_name("left")
        if left and left.type == "call":
            return _text(_target(left)), left
        if left and left.type == "identifier":
            return _text(left), None
    if head.type == "identifier":
        return _text(head), None
    return None


def _pattern_names(node: Node) -> list[str]:
    if node.type == "identifier":
        name = _text(node)
        return [name] if name != "_" and not name.startswith("_") else []
    if node.type in {"keyword", "string", "atom", "integer", "float"}:
        return []
    names = []
    for child in node.named_children:
        names.extend(_pattern_names(child))
    return names


def _dot_member(node: Node) -> str:
    right = node.child_by_field_name("right")
    if right:
        return _text(right)
    identifiers = [
        child for child in node.named_children if child.type in {"identifier", "alias"}
    ]
    return _text(identifiers[-1]) if identifiers else ""


def _ancestors(node: Node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _direct_stab_clause_count(node: Node) -> int:
    return sum(child.type == "stab_clause" for child in node.children)


def _has_sibling_function_clause(node: Node, name: str) -> bool:
    parent = node.parent
    if parent is None:
        return False
    clauses = 0
    for sibling in parent.children:
        if sibling.type != "call" or _text(_target(sibling)) not in _FUNCTION_DEFS:
            continue
        head = _function_head(sibling)
        if head and head[0] == name:
            clauses += 1
            if clauses > 1:
                return True
    return False


def _enclosing_function(node: Node) -> tuple[Node, str, Node | None] | None:
    for ancestor in _ancestors(node):
        if ancestor.type != "call" or _text(_target(ancestor)) not in _FUNCTION_DEFS:
            continue
        definition = _function_head(ancestor)
        if definition:
            return ancestor, definition[0], definition[1]
    return None


def _is_recursive_call(node: Node, callee: str) -> bool:
    enclosing = _enclosing_function(node)
    if enclosing is None or enclosing[1] != callee:
        return False
    head = enclosing[2]
    return not (
        head and head.start_byte <= node.start_byte and node.end_byte <= head.end_byte
    )


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "anonymous_function":
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind in _LITERALS:
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "unary_operator":
        op = node.child_by_field_name("operator")
        if op and _text(op) == "@":
            operand = next(
                (
                    child
                    for child in node.named_children
                    if child.type in {"call", "identifier"}
                ),
                None,
            )
            name = (
                _text(_target(operand))
                if operand and operand.type == "call"
                else _text(operand)
            )
            return (_rule(EntityKind.VARIABLE, f"@{name}"),) if name else None
        if op and _text(op) in {"not", "!"}:
            return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    if kind == "binary_operator":
        operator = _text(node.child_by_field_name("operator"))
        left = node.child_by_field_name("left")
        if operator == "=" and left:
            return (
                tuple(_rule(EntityKind.VARIABLE, name) for name in _pattern_names(left))
                or None
            )
        if operator in {"&&", "and"}:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_and"),)
        if operator in {"||", "or"}:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_or"),)
        if operator == "when":
            return (_rule(EntityKind.CONTROL_FLOW, "elixir_guard_statement"),)
    if kind == "call":
        target = _target(node)
        if target is None:
            return None
        callee = _text(target)
        if target.type == "dot":
            member = _dot_member(target)
            return (
                (
                    _rule(EntityKind.MEMBER_ACCESS, member),
                    _rule(EntityKind.CALL, member),
                )
                if member
                else None
            )
        if callee in _FUNCTION_DEFS:
            definition = _function_head(node)
            if not definition or not definition[0]:
                return None
            rules = [_rule(EntityKind.FUNCTION, definition[0])]
            if _has_sibling_function_clause(node, definition[0]):
                rules.append(
                    _rule(
                        EntityKind.CONTROL_FLOW, "elixir_unknown_multi_clause_grouping"
                    )
                )
            head = definition[1]
            if head:
                for arg in _args(head):
                    rules.extend(
                        _rule(EntityKind.PARAMETER, name)
                        for name in _pattern_names(arg)
                    )
            return tuple(rules)
        args = _args(node)
        if callee == "defmodule":
            return (_rule(EntityKind.CLASS, _text(args[0]) if args else ""),)
        if callee == "defprotocol":
            return (_rule(EntityKind.INTERFACE, _text(args[0]) if args else ""),)
        if callee == "defimpl":
            return (_rule(EntityKind.IMPLEMENTS, _text(args[0]) if args else ""),)
        if callee == "defstruct":
            return (_rule(EntityKind.CLASS, _text(args[0]) if args else "defstruct"),)
        if callee in _IMPORTS:
            return (_rule(EntityKind.IMPORT, _text(args[0])),) if args else None
        if callee in {"raise", "throw"}:
            return (_rule(EntityKind.THROW, _text(args[0]) if args else ""),)
        if callee in _CONTROL:
            return (_rule(EntityKind.CONTROL_FLOW, _CONTROL[callee]),)
        if callee in {"get", "post", "put", "patch", "delete", "options", "head"}:
            return (
                (_rule(EntityKind.ROUTE, callee),)
                if args and args[0].type == "string"
                else (_rule(EntityKind.CALL, callee),)
            )
        rules = [_rule(EntityKind.CALL, callee)]
        if _is_recursive_call(node, callee):
            rules.append(_rule(EntityKind.CONTROL_FLOW, "recursive_call"))
        return tuple(rules)
    if kind in {"rescue_block", "catch_block"}:
        return (
            (_rule(EntityKind.CATCH, kind),)
            if _direct_stab_clause_count(node) == 0
            else None
        )
    if kind == "else_block":
        rules = []
        keyword = next((child for child in node.children if child.type == "else"), None)
        control = next(
            (
                _text(_target(ancestor))
                for ancestor in _ancestors(node)
                if ancestor.type == "call"
            ),
            None,
        )
        first = next((child for child in node.named_children), None)
        is_else_if = (
            first is not None
            and first.type == "call"
            and _text(_target(first)) in {"if", "unless"}
        )
        if (
            keyword is not None
            and control in {"if", "unless", "with"}
            and not is_else_if
        ):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="else_branch",
                    span_node=keyword,
                )
            )
        if first is not None and first.type == "stab_clause":
            rules.append(_rule(EntityKind.CONTROL_FLOW, "case_item"))
        return tuple(rules) or None
    if kind == "stab_clause":
        for ancestor in _ancestors(node):
            if ancestor.type in {"rescue_block", "catch_block"}:
                return (_rule(EntityKind.CATCH, "catch_clause"),)
            if ancestor.type == "else_block":
                return (_rule(EntityKind.CONTROL_FLOW, "case_item"),)
            if ancestor.type == "anonymous_function":
                return (
                    (_rule(EntityKind.CONTROL_FLOW, "case_item"),)
                    if _direct_stab_clause_count(ancestor) > 1
                    else None
                )
            if ancestor.type == "call":
                callee = _text(_target(ancestor))
                if callee in {"case", "cond", "receive"}:
                    rules = [_rule(EntityKind.CONTROL_FLOW, "case_item")]
                    if callee in {"cond", "receive"}:
                        rules.append(
                            _rule(EntityKind.CONTROL_FLOW, "cognitive_decision")
                        )
                    return tuple(rules)
                return None
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
)
