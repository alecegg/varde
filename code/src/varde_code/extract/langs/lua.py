"""Lua entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_declaration", "function_definition"})
TYPE_SCOPES: frozenset[str] = frozenset()
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.THROW,
    EntityKind.CONTROL_FLOW,
)
FLOW_NAME_ROLES: dict[str, str] = {}

_FLOW = frozenset(
    {
        "if_statement",
        "elseif_statement",
        "else_statement",
        "for_statement",
        "while_statement",
        "repeat_statement",
        "do_statement",
        "return_statement",
        "break_statement",
        "goto_statement",
        "label_statement",
    }
)
_LITERALS = frozenset({"string", "number", "true", "false", "nil"})


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _names(node: Node | None) -> list[str]:
    if node is None:
        return []
    return [
        _text(child)
        for child in node.named_children
        if child.type == "identifier" and _text(child) != "_"
    ]


def _first_arg(node: Node) -> Node | None:
    args = _field(node, "arguments")
    return (
        next((child for child in args.named_children), None)
        if args is not None
        else None
    )


def _descendants(node: Node):
    if node is None:
        return
    pending = list(node.named_children)
    while pending:
        child = pending.pop()
        yield child
        pending.extend(child.named_children)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "function_declaration":
        name_node = _field(node, "name")
        name = _text(name_node)
        rules = [_rule(EntityKind.FUNCTION, name)]
        body = _field(node, "body")
        if (
            name
            and body is not None
            and any(
                child.type == "function_call" and _text(_field(child, "name")) == name
                for child in _descendants(body)
            )
        ):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    literal="recursive_call",
                    span_node=name_node,
                )
            )
        return tuple(rules)
    if kind == "function_definition":
        parent = node.parent
        if parent is not None and parent.type == "field":
            return (_rule(EntityKind.FUNCTION, _text(_field(parent, "name"))),)
        if parent is not None and parent.type == "expression_list":
            assignment = parent.parent
            if assignment is not None and assignment.type == "assignment_statement":
                target = next(
                    (c for c in assignment.named_children if c.type == "variable_list"),
                    None,
                )
                return (
                    (_rule(EntityKind.FUNCTION, _text(target)),)
                    if target is not None
                    else (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
                )
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind == "assignment_statement":
        target = next(
            (child for child in node.named_children if child.type == "variable_list"),
            None,
        )
        return tuple(_rule(EntityKind.VARIABLE, name) for name in _names(target))
    if kind == "parameters":
        return tuple(_rule(EntityKind.PARAMETER, name) for name in _names(node))
    if kind == "function_call":
        name = _text(_field(node, "name"))
        if name == "require":
            arg = _first_arg(node)
            path = (
                unquote(_text(arg)).replace(".", "/")
                if arg is not None and arg.type == "string"
                else ""
            )
            return (_rule(EntityKind.IMPORT, path),) if path else ()
        if name in {"error", "assert"}:
            return (_rule(EntityKind.THROW, _text(_first_arg(node))),)
        callee = _field(node, "name")
        rules = [_rule(EntityKind.CALL, name)]
        if callee is not None and callee.type in {
            "dot_index_expression",
            "method_index_expression",
        }:
            rules.append(
                _rule(
                    EntityKind.MEMBER_ACCESS,
                    _text(_field(callee, "field") or _field(callee, "method")),
                )
            )
        return tuple(rules)
    if kind in {"dot_index_expression", "method_index_expression"}:
        if (
            node.parent is not None
            and node.parent.type == "function_call"
            and _field(node.parent, "name") == node
        ):
            return ()
        member = _field(node, "field") or _field(node, "method")
        return (
            (_rule(EntityKind.MEMBER_ACCESS, _text(member)),)
            if member is not None
            else ()
        )
    if kind in _LITERALS:
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind in _FLOW:
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
    if kind == "binary_expression":
        operator = next(
            (_text(child) for child in node.children if _text(child) in {"and", "or"}),
            None,
        )
        if operator:
            return (
                _rule(
                    EntityKind.CONTROL_FLOW,
                    "logical_and" if operator == "and" else "logical_or",
                ),
            )
    if (
        kind == "unary_expression"
        and _text(node).lstrip().startswith("not")
        and any(
            child.type == "binary_expression"
            and any(_text(part) in {"and", "or"} for part in child.children)
            for child in _descendants(node)
        )
    ):
        return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    return None


def _function_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=_function_name,
)
