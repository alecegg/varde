"""Dart entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset(
    {
        "function_declaration",
        "local_function_declaration",
        "method_signature",
        "constructor_signature",
        "function_signature",
        "getter_signature",
        "setter_signature",
    }
)
TYPE_SCOPES = frozenset({"class_definition", "mixin_declaration"})
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
    EntityKind.EXTENDS,
)
FLOW_NAME_ROLES: dict[str, str] = {}
_LITERALS = {
    "decimal_integer_literal",
    "hex_integer_literal",
    "decimal_floating_point_literal",
    "string_literal",
    "true",
    "false",
    "null_literal",
}


def _name(node: Node) -> str:
    return _text(_field(node, "name")) or next(
        (_text(c) for c in node.named_children if c.type == "identifier"), ""
    )


def _uri(node: Node) -> str:
    uri = next((c for c in node.named_children if c.type == "configurable_uri"), None)
    leaf = (
        next((c for c in uri.named_children if c.type == "uri"), None) if uri else None
    )
    return unquote(_text(leaf), False)


def _signature_body(node: Node) -> Node | None:
    parent = node.parent
    if parent and parent.type == "method_signature":
        return parent.next_named_sibling
    return node.next_named_sibling


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_specification":
        return (VisitRule(EntityKind.IMPORT, name_field=None, literal=_uri(node)),)
    if kind == "library_export":
        return (VisitRule(EntityKind.EXPORT, name_field=None, literal=_uri(node)),)
    if kind in {
        "function_declaration",
        "local_function_declaration",
        "getter_declaration",
        "setter_declaration",
        "method_declaration",
    }:
        sig = _field(node, "signature") or next(
            (c for c in node.named_children if c.type.endswith("signature")), None
        )
        return (
            VisitRule(
                EntityKind.FUNCTION,
                name_field=None,
                literal=_name(sig) if sig else _name(node),
            ),
        )
    if kind in {
        "function_signature",
        "constructor_signature",
        "factory_constructor_signature",
        "redirecting_factory_constructor_signature",
        "getter_signature",
        "setter_signature",
    }:
        parent = node.parent
        if parent and parent.type in {
            "function_declaration",
            "local_function_declaration",
            "getter_declaration",
            "setter_declaration",
            "method_declaration",
        }:
            return ()
        body = _signature_body(node)
        return (
            VisitRule(
                EntityKind.FUNCTION,
                name_field=None,
                literal=_name(node),
                span_start_node=node,
                span_end_node=body,
            ),
        )
    if kind == "function_expression":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind == "class_definition":
        rules = [VisitRule(EntityKind.CLASS, name_field=None, literal=_name(node))]
        superclass = _field(node, "superclass")
        if superclass:
            types = [
                c
                for c in superclass.named_children
                if c.type in {"type_identifier", "type"}
            ]
            if types:
                rules.append(
                    VisitRule(
                        EntityKind.EXTENDS,
                        name_field=None,
                        literal=_text(types[0]).split("<", 1)[0],
                        span_node=types[0],
                    )
                )
            mixins = next(
                (c for c in superclass.named_children if c.type == "mixins"), None
            )
            if mixins:
                rules.extend(
                    VisitRule(
                        EntityKind.IMPLEMENTS,
                        name_field=None,
                        literal=_text(c).split("<", 1)[0],
                        span_node=c,
                    )
                    for c in mixins.named_children
                )
        interfaces = _field(node, "interfaces")
        if interfaces:
            rules.extend(
                VisitRule(
                    EntityKind.IMPLEMENTS,
                    name_field=None,
                    literal=_text(c).split("<", 1)[0],
                    span_node=c,
                )
                for c in interfaces.named_children
                if c.type in {"type_identifier", "type"}
            )
        return tuple(rules)
    if kind == "mixin_declaration":
        return (VisitRule(EntityKind.INTERFACE, name_field=None, literal=_name(node)),)
    if kind in {
        "initialized_identifier",
        "static_final_declaration",
        "initialized_variable_definition",
    }:
        return (VisitRule(EntityKind.VARIABLE, name_field=None, literal=_name(node)),)
    if kind == "formal_parameter":
        name = _name(node)
        return (
            (VisitRule(EntityKind.PARAMETER, name_field=None, literal=name),)
            if name and name != "_"
            else ()
        )
    if kind == "annotation":
        return (VisitRule(EntityKind.DECORATOR, name_field=None, literal=_name(node)),)
    if kind == "call_expression":
        function = _field(node, "function")
        name = _text(function)
        return (
            VisitRule(
                EntityKind.CALL, name_field=None, literal=name.rsplit(".", 1)[-1]
            ),
        )
    if kind == "selector" and any(
        c.type == "argument_part" for c in node.named_children
    ):
        previous = node.prev_named_sibling
        if previous and previous.type == "selector":
            callee = next(
                (
                    c
                    for c in previous.named_children
                    if c.type == "unconditional_assignable_selector"
                ),
                None,
            )
            name = _text(next(iter(callee.named_children), None)) if callee else ""
        else:
            name = _text(previous)
        return (VisitRule(EntityKind.CALL, name_field=None, literal=name),)
    if kind in {"member_expression", "selector"}:
        if kind == "selector" and any(
            c.type == "argument_part" for c in node.named_children
        ):
            return None
        selector = next(
            (
                c
                for c in node.named_children
                if c.type == "unconditional_assignable_selector"
            ),
            node,
        )
        ids = [c for c in selector.named_children if c.type == "identifier"]
        if ids:
            return (
                VisitRule(
                    EntityKind.MEMBER_ACCESS, name_field=None, literal=_text(ids[-1])
                ),
            )
    if kind in _LITERALS:
        if node.parent and node.parent.type == kind:
            return ()
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "throw_expression":
        value = _field(node, "value")
        return (VisitRule(EntityKind.THROW, name_field=None, literal=_text(value)),)
    if kind == "rethrow_statement":
        return (VisitRule(EntityKind.THROW, name_field=None, literal="rethrow"),)
    if kind == "catch_clause":
        return (
            VisitRule(EntityKind.CATCH, name_field=None, literal="legacy_catch_clause"),
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="cognitive_decision"
            ),
        )
    if kind in {
        "if_statement",
        "for_statement",
        "while_statement",
        "switch_statement",
        "conditional_expression",
        "return_statement",
        "try_statement",
        "do_statement",
        "switch_statement_case",
        "switch_statement_default",
        "break_statement",
        "continue_statement",
        "logical_and_expression",
        "logical_or_expression",
    }:
        names = {
            "do_statement": "do_while_statement",
            "switch_statement_case": "case_statement",
            "switch_statement_default": "case_statement",
            "logical_and_expression": "logical_and",
            "logical_or_expression": "logical_or",
        }
        label = (
            "elseif_statement"
            if kind == "if_statement"
            and node.parent
            and node.parent.type == "if_statement"
            else names.get(kind, kind)
        )
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=label),)
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=lambda n: _name(
        next((c for c in n.named_children if c.type == "function_signature"), n)
    ),
    type_name=lambda n: _name(n),
)
