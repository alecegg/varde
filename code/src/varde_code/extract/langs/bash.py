"""Bash entity rules for the tree-sitter grammar."""

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_definition"})
TYPE_SCOPES: frozenset[str] = frozenset()
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.VARIABLE,
    EntityKind.EXPORT,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.CONTROL_FLOW,
)
FLOW_NAME_ROLES: dict[str, str] = {}


def _children(node: Node) -> list[Node]:
    return list(node.named_children)


def _name(node: Node, child_kind: str) -> str:
    child = next((item for item in _children(node) if item.type == child_kind), None)
    return _text(child) if child is not None else ""


def _is_export(node: Node) -> bool:
    return any(child.type == "export" for child in node.children)


def _has_logical_binary(node: Node) -> bool:
    if node.type == "binary_expression" and _boolean_operator(node) is not None:
        return True
    return any(_has_logical_binary(child) for child in node.named_children)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "function_definition":
        return (VisitRule(EntityKind.FUNCTION, name_field=None, name_kind="word"),)
    if kind == "variable_assignment":
        parent = node.parent
        if (
            parent is not None
            and parent.type == "declaration_command"
            and _is_export(parent)
        ):
            return ()
        return (
            VisitRule(EntityKind.VARIABLE, name_field=None, name_kind="variable_name"),
        )
    if kind == "declaration_command" and _is_export(node):
        name = _name(node, "variable_name")
        if not name:
            assignment = next(
                (
                    child
                    for child in _children(node)
                    if child.type == "variable_assignment"
                ),
                None,
            )
            name = _name(assignment, "variable_name") if assignment is not None else ""
        return (VisitRule(EntityKind.EXPORT, name_field=None, literal=name),)
    if kind == "command":
        callee = _name(node, "command_name")
        if callee in {"source", "."}:
            argument = next(
                (
                    child
                    for child in _children(node)
                    if child.type
                    in {"word", "number", "string", "raw_string", "concatenation"}
                ),
                None,
            )
            if argument is None:
                return ()
            return (
                VisitRule(
                    EntityKind.IMPORT, name_field=None, literal=unquote(_text(argument))
                ),
            )
        if callee in {"return", "break", "continue"}:
            return (
                VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=callee),
            )
        return (VisitRule(EntityKind.CALL, name_field=None, literal=callee),)
    if kind in {"string", "raw_string", "number"}:
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "case_statement":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="case_statement"
            ),
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="cognitive_decision"
            ),
        )
    if kind in {
        "if_statement",
        "elif_clause",
        "else_clause",
        "for_statement",
        "while_statement",
        "case_item",
        "last_case_item",
        "c_style_for_statement",
    }:
        name = {
            "last_case_item": "case_item",
            "c_style_for_statement": "for_statement",
        }.get(kind, kind)
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=name),)
    if kind == "ternary_expression":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="cognitive_decision"
            ),
        )
    if kind in {"unary_expression", "negated_command"}:
        if _text(node).lstrip().startswith("!") and _has_logical_binary(node):
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="negation_break"
                ),
            )
        return None
    if kind in {"binary_expression", "list"}:
        operator = _boolean_operator(node)
        if operator is not None:
            return (
                VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=operator),
            )
    return None


def _boolean_operator(node: Node) -> str | None:
    operator = node.child_by_field_name("operator")
    if operator is not None:
        value = _text(operator)
    else:
        value = next(
            (_text(child) for child in node.children if _text(child) in {"&&", "||"}),
            "",
        )
    return {"&&": "logical_and", "||": "logical_or"}.get(value)


def _function_name(node: Node) -> str | None:
    return _name(node, "word")


LANG = LanguageTables(
    visits={},
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=_function_name,
)
