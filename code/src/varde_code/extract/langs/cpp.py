"""C++ entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from . import c
from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = c.FUNCTION_SCOPES
TYPE_SCOPES = frozenset(
    {
        "class_specifier",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
        "namespace_definition",
    }
)
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.CATCH,
    EntityKind.THROW,
    EntityKind.CONTROL_FLOW,
)
FLOW_NAME_ROLES: dict[str, str] = {}


def _function_name(node: Node) -> str | None:
    declarator = _field(node, "declarator")
    while declarator is not None and declarator.type != "function_declarator":
        declarator = _field(declarator, "declarator")
    return c._declarator_name(_field(declarator, "declarator")) or None


def _function_declarator(node: Node | None) -> Node | None:
    if node is None:
        return None
    if node.type == "function_declarator":
        return node
    return next(
        (
            found
            for child in node.named_children
            if (found := _function_declarator(child)) is not None
        ),
        None,
    )


def _type_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in {"function_definition"}:
        name = _function_name(node)
        return (_rule(EntityKind.FUNCTION, name),) if name else ()
    if kind in {
        "class_specifier",
        "struct_specifier",
        "union_specifier",
        "enum_specifier",
    }:
        name = _text(_field(node, "name"))
        if not name:
            return ()
        rules = [_rule(EntityKind.CLASS, name)]
        clause = next(
            (
                child
                for child in node.named_children
                if child.type == "base_class_clause"
            ),
            None,
        )
        if clause is not None:
            rules.extend(
                _rule(
                    EntityKind.EXTENDS,
                    child.text.decode()
                    if isinstance(child.text, bytes)
                    else str(child.text),
                )
                for child in clause.named_children
                if child.type
                in {"type_identifier", "qualified_identifier", "template_type"}
            )
        return tuple(rules)
    if kind == "namespace_definition":
        return ()
    if kind == "type_definition":
        name = c._declarator_name(_field(node, "declarator"))
        return (_rule(EntityKind.CLASS, name),) if name else ()
    if kind == "preproc_include":
        rules = c._visit(node)
        return rules
    if kind == "using_declaration":
        value = (
            _text(node)
            .strip()
            .removeprefix("using")
            .removeprefix("namespace")
            .removesuffix(";")
            .strip()
        )
        return (_rule(EntityKind.IMPORT, value.replace("::", "/")),) if value else ()
    if kind in {"declaration", "field_declaration"}:
        rules = []
        for decl in node.children_by_field_name("declarator"):
            function = _function_declarator(decl)
            if function is not None:
                continue
            name = c._declarator_name(decl)
            if name:
                rules.append(_rule(EntityKind.VARIABLE, name))
        if kind == "field_declaration" and not rules:
            field = next(
                (
                    child
                    for child in node.named_children
                    if child.type == "field_identifier"
                ),
                None,
            )
            if field:
                rules.append(_rule(EntityKind.VARIABLE, _text(field)))
        return tuple(rules)
    if kind == "parameter_declaration":
        name = c._declarator_name(_field(node, "declarator"))
        return (_rule(EntityKind.PARAMETER, name),) if name else ()
    if kind == "call_expression":
        name = _text(_field(node, "function"))
        return (_rule(EntityKind.CALL, name),) if name else ()
    if kind == "new_expression":
        name = _text(_field(node, "type"))
        return (_rule(EntityKind.CALL, name),) if name else ()
    if kind == "field_expression":
        name = _text(_field(node, "field"))
        return (_rule(EntityKind.MEMBER_ACCESS, name),) if name else ()
    if kind in {"number_literal", "string_literal", "char_literal", "true", "false"}:
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "catch_clause":
        param_list = _field(node, "parameters")
        param = (
            next(
                (
                    item
                    for item in param_list.named_children
                    if item.type == "parameter_declaration"
                ),
                None,
            )
            if param_list
            else None
        )
        name = c._declarator_name(_field(param, "declarator")) if param else ""
        return (_rule(EntityKind.CATCH, name),)
    if kind in {"throw_statement", "throw_expression"}:
        value = next(
            (item for item in node.named_children if item.type not in {"throw"}), None
        )
        return (_rule(EntityKind.THROW, _text(value)),)
    c_rules = c._visit(node)
    if c_rules is not None and kind in {"if_statement", "binary_expression"}:
        return c_rules
    controls = {
        "for_statement",
        "for_range_loop",
        "while_statement",
        "do_statement",
        "switch_statement",
        "case_statement",
        "return_statement",
        "break_statement",
        "continue_statement",
        "goto_statement",
        "conditional_expression",
        "try_statement",
    }
    if kind in controls:
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
    return None


LANG = LanguageTables(
    visits={},
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_function_name,
    type_name=_type_name,
    visit_node=_visit,
)
