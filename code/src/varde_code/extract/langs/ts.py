"""TypeScript entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from . import javascript as js
from .base import LanguageTables, VisitRule

BACKEND = "tree-sitter"
FUNCTION_SCOPES = js.FUNCTION_SCOPES | frozenset({"method_signature"})
TYPE_SCOPES = frozenset({"class_declaration", "interface_declaration"})
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.INTERFACE,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
    EntityKind.EXPORT,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.CATCH,
    EntityKind.THROW,
    EntityKind.CONTROL_FLOW,
    EntityKind.ROUTE,
    EntityKind.RESPONSE,
)
FLOW_NAME_ROLES = js.FLOW_NAME_ROLES
TYPE_CONTEXT_KINDS = frozenset(
    {
        "predefined_type",
        "type_annotation",
        "literal_type",
        "type_identifier",
        "generic_type",
        "type_arguments",
        "type_parameters",
        "object_type",
        "union_type",
        "intersection_type",
        "function_type",
        "array_type",
    }
)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "interface_declaration":
        return (
            js._rule(EntityKind.INTERFACE, js._text(node.child_by_field_name("name"))),
        )
    if kind in {"required_parameter", "optional_parameter"}:
        pattern = node.child_by_field_name("pattern")
        if not pattern:
            return ()
        if pattern.type in {
            "object_pattern",
            "array_pattern",
            "object_binding_pattern",
            "array_binding_pattern",
        }:
            return (js._rule(EntityKind.PARAMETER, js._text(pattern)),)
        names = (
            [js._text(pattern)]
            if pattern.type in {"identifier", "type_identifier"}
            else [
                js._text(child)
                for child in pattern.named_children
                if child.type in {"shorthand_property_identifier_pattern", "identifier"}
            ]
        )
        return tuple(js._rule(EntityKind.PARAMETER, name) for name in names if name)
    if kind == "method_signature":
        return (
            js._rule(EntityKind.FUNCTION, js._text(node.child_by_field_name("name"))),
        )
    if kind in {"public_field_definition", "property_signature"}:
        name = node.child_by_field_name("name") or next(
            (
                child
                for child in node.named_children
                if child.type == "property_identifier"
            ),
            None,
        )
        return (js._rule(EntityKind.VARIABLE, js._text(name)),)
    if kind in {"type_alias_declaration", "enum_declaration"}:
        return (js._rule(EntityKind.CLASS, js._text(node.child_by_field_name("name"))),)
    if kind in {
        "number",
        "string",
        "true",
        "false",
        "null",
        "undefined",
        "template_string",
        "regex",
    } and any(parent.type in TYPE_CONTEXT_KINDS for parent in js._ancestors(node)):
        return ()
    return js._visit(node)


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=js._function_name,
    type_name=js._function_name,
    type_kinds=TYPE_CONTEXT_KINDS,
)
