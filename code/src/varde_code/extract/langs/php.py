"""PHP extraction rules for tree-sitter."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
TYPE_SCOPES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "trait_declaration",
        "enum_declaration",
    }
)
FUNCTION_SCOPES = frozenset({"function_definition", "method_declaration"})
REQUIRED_KINDS = tuple(kind for kind in EntityKind if kind not in {EntityKind.EXPORT})
FLOW_NAME_ROLES = {
    "switch_statement": "decision_container",
    "match_expression": "decision_container",
    "short_ternary_expression": "legacy_only",
}

_REQUIRES = {
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
}
_LITERALS = {"integer", "float", "string", "encapsed_string", "boolean", "null"}
_CALLABLES = {"anonymous_function", "arrow_function"}
_CONTROL = {
    "switch_statement",
    "case_statement",
    "for_statement",
    "foreach_statement",
    "while_statement",
    "try_statement",
    "return_statement",
    "match_expression",
}


def _name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _children(node: Node, kind: str) -> list[Node]:
    return [child for child in node.named_children if child.type == kind]


def _normalize(value: str) -> str:
    return value.strip().lstrip("\\").replace("\\", "/")


def _literal_string(node: Node) -> str:
    if node.type not in {"string", "encapsed_string"}:
        return ""
    return "".join(
        _text(child) for child in node.named_children if child.type == "string_content"
    )


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in {"function_definition", "method_declaration"}:
        return (VisitRule(EntityKind.FUNCTION),)
    if kind in _CALLABLES:
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind in {"class_declaration", "trait_declaration", "enum_declaration"}:
        rules = [VisitRule(EntityKind.CLASS)]
        base = _children(node, "base_clause")
        if base:
            target = next(iter(base[0].named_children), None)
            if target:
                rules.append(
                    VisitRule(
                        EntityKind.EXTENDS,
                        name_field=None,
                        literal=_normalize(_text(target)),
                        span_node=target,
                    )
                )
        for clause in _children(node, "class_interface_clause"):
            rules.extend(
                VisitRule(
                    EntityKind.IMPLEMENTS,
                    name_field=None,
                    literal=_normalize(_text(item)),
                    span_node=item,
                )
                for item in clause.named_children
            )
        return tuple(rules)
    if kind == "interface_declaration":
        return (VisitRule(EntityKind.INTERFACE),)
    if kind == "namespace_use_declaration":
        return tuple(
            VisitRule(
                EntityKind.IMPORT, name_field=None, literal=_normalize(_text(item))
            )
            for clause in _children(node, "namespace_use_clause")
            for item in clause.named_children
            if item.type in {"name", "qualified_name"}
        )
    if kind in _REQUIRES:
        strings = [
            child
            for child in node.named_children
            if child.type in {"string", "encapsed_string"}
        ]
        return (
            VisitRule(
                EntityKind.IMPORT,
                name_field=None,
                literal=_literal_string(strings[0]) if strings else "",
            ),
        )
    if kind in {"assignment_expression", "augmented_assignment_expression"}:
        left = _field(node, "left")
        if left is not None and left.type == "variable_name":
            return (
                VisitRule(
                    EntityKind.VARIABLE,
                    name_field=None,
                    literal=_text(left).lstrip("$"),
                ),
            )
    if kind == "property_element":
        variable = next(
            (child for child in node.named_children if child.type == "variable_name"),
            None,
        )
        if variable:
            return (
                VisitRule(
                    EntityKind.VARIABLE,
                    name_field=None,
                    literal=_text(variable).lstrip("$"),
                ),
            )
    if kind in {
        "simple_parameter",
        "variadic_parameter",
        "property_promotion_parameter",
    }:
        variable = _field(node, "name")
        if variable:
            return (
                VisitRule(
                    EntityKind.PARAMETER,
                    name_field=None,
                    literal=_text(variable).lstrip("$"),
                ),
            )
    if kind == "function_call_expression":
        function = _field(node, "function")
        return (VisitRule(EntityKind.CALL, name_field=None, literal=_text(function)),)
    if kind in {"member_call_expression", "nullsafe_member_call_expression"}:
        method = _text(_field(node, "name"))
        return (
            VisitRule(EntityKind.MEMBER_ACCESS, name_field=None, literal=method),
            VisitRule(EntityKind.CALL, name_field=None, literal=method),
        )
    if kind == "scoped_call_expression":
        return (VisitRule(EntityKind.CALL, name_field="name"),)
    if kind in {"member_access_expression", "nullsafe_member_access_expression"}:
        return (VisitRule(EntityKind.MEMBER_ACCESS, name_field="name"),)
    if kind == "object_creation_expression":
        target = next(
            (
                child
                for child in node.named_children
                if child.type in {"name", "qualified_name"}
            ),
            None,
        )
        if target:
            return (VisitRule(EntityKind.CALL, name_field=None, literal=_text(target)),)
    if kind in _LITERALS:
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "catch_clause":
        caught = _field(node, "name")
        name = (
            _text(caught).lstrip("$")
            if caught
            else _normalize(_text(_field(node, "type")))
        )
        return (VisitRule(EntityKind.CATCH, name_field=None, literal=name),)
    if kind in {"throw_expression", "throw_statement"}:
        value = next(iter(node.named_children), None)
        return (VisitRule(EntityKind.THROW, name_field=None, literal=_text(value)),)
    if kind == "if_statement":
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="if_statement"),
        )
    if kind == "else_if_clause":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="elseif_statement"
            ),
        )
    if kind == "else_clause":
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="else_branch"),
        )
    if kind == "binary_expression":
        op = _text(_field(node, "operator"))
        if op in {"&&", "and"}:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="logical_and"
                ),
            )
        if op in {"||", "or"}:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="logical_or"
                ),
            )
    if kind == "goto_statement":
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="goto_jump"),
        )
    if kind in {"break_statement", "continue_statement"}:
        label = "labeled_jump" if len(_text(node).split()) > 1 else kind
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=label),)
    if kind in _CONTROL:
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    if kind in {"match_conditional_expression", "match_default_expression"}:
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="match_arm"),
        )
    if kind == "conditional_expression":
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    return None


LANG = LanguageTables(
    visits={},
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_name,
    type_name=_name,
    visit_node=_visit,
)
