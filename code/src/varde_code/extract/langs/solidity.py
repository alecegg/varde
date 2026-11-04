"""Solidity entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset(
    {
        "function_definition",
        "modifier_definition",
        "constructor_definition",
        "fallback_receive_definition",
        "yul_function_definition",
    }
)
TYPE_SCOPES = frozenset(
    {"contract_declaration", "library_declaration", "interface_declaration"}
)
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
    EntityKind.EXTENDS,
)
FLOW_NAME_ROLES: dict[str, str] = {}
_LITERALS = frozenset({"number_literal", "string_literal", "boolean_literal"})
_FLOW = frozenset(
    {
        "for_statement",
        "while_statement",
        "do_while_statement",
        "try_statement",
        "return_statement",
        "break_statement",
        "continue_statement",
    }
)


def _rule(kind: EntityKind, name: str, *, span: Node | None = None) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name, span_node=span)


def _name(node: Node) -> str:
    return _text(_field(node, "name"))


def _descendants(node: Node):
    pending = list(node.named_children)
    while pending:
        child = pending.pop()
        yield child
        pending.extend(child.named_children)


def _call_name(node: Node) -> str:
    function = _field(node, "function")
    if function is None:
        return ""
    descendants = list(_descendants(function))
    if any(child.type == "call_expression" for child in descendants):
        return ""
    creation = next(
        (child for child in descendants if child.type == "new_expression"), None
    )
    if creation is not None:
        return f"new {_text(_field(creation, 'name'))}".strip()
    members = [child for child in descendants if child.type == "member_expression"]
    if members:
        return _text(_field(members[-1], "property"))
    identifiers = [child for child in descendants if child.type == "identifier"]
    return _text(identifiers[-1]) if identifiers else _text(function)


def _ancestors(node: Node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_directive":
        return (_rule(EntityKind.IMPORT, unquote(_text(_field(node, "source")))),)
    if kind in {
        "function_definition",
        "modifier_definition",
        "event_definition",
        "error_declaration",
    }:
        return (_rule(EntityKind.FUNCTION, _name(node)),)
    if kind == "constructor_definition":
        return (_rule(EntityKind.FUNCTION, "constructor"),)
    if kind == "fallback_receive_definition":
        name = "receive" if _text(node).lstrip().startswith("receive") else "fallback"
        return (_rule(EntityKind.FUNCTION, name),)
    if kind == "yul_function_definition":
        return (_rule(EntityKind.FUNCTION, _name(node)),)
    if kind in {"contract_declaration", "library_declaration", "interface_declaration"}:
        entity = (
            EntityKind.INTERFACE
            if kind == "interface_declaration"
            else EntityKind.CLASS
        )
        rules = [_rule(entity, _name(node))]
        parents = [
            child
            for child in node.named_children
            if child.type == "inheritance_specifier"
        ]
        for index, parent in enumerate(parents):
            ancestor = _field(parent, "ancestor")
            rules.append(
                _rule(
                    EntityKind.EXTENDS if index == 0 else EntityKind.IMPLEMENTS,
                    _text(ancestor),
                    span=parent,
                )
            )
        return tuple(rules)
    if kind in {"state_variable_declaration", "variable_declaration"}:
        name = _name(node)
        return (_rule(EntityKind.VARIABLE, name),) if name else ()
    if kind == "parameter":
        name = _name(node)
        return (_rule(EntityKind.PARAMETER, name),) if name else ()
    if kind == "call_expression":
        name = _call_name(node)
        if not name:
            return ()
        return (
            (_rule(EntityKind.THROW, name),)
            if name in {"require", "assert"}
            else (_rule(EntityKind.CALL, name),)
        )
    if kind == "emit_statement":
        name_node = next(
            (child for child in node.named_children if child.type == "expression"), None
        )
        return (_rule(EntityKind.CALL, _text(name_node).split("(", 1)[0]),)
    if kind == "member_expression":
        prop = _field(node, "property")
        return (
            (_rule(EntityKind.MEMBER_ACCESS, _text(prop)),) if prop is not None else ()
        )
    if kind in _LITERALS and not any(
        parent.type in {"type_name", "primitive_type", "user_defined_type"}
        for parent in _ancestors(node)
    ):
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "revert_statement":
        value = next((child for child in node.named_children), None)
        name = (
            _text(value)
            if value is not None and value.type not in {"expression", "string_literal"}
            else "revert"
        )
        return (_rule(EntityKind.THROW, name),)
    if kind == "catch_clause":
        parameter = next(
            (child for child in node.named_children if child.type == "parameter"), None
        )
        return (
            _rule(EntityKind.CATCH, _name(parameter) if parameter is not None else ""),
        )
    if kind == "if_statement":
        has_else = any(_text(child) == "else" for child in node.children)
        rules = [_rule(EntityKind.CONTROL_FLOW, "if_statement")]
        if has_else:
            rules.append(_rule(EntityKind.CONTROL_FLOW, "else_branch"))
        return tuple(rules)
    if kind in _FLOW or kind == "ternary_expression":
        return (
            _rule(
                EntityKind.CONTROL_FLOW,
                "ternary_expression" if kind == "ternary_expression" else kind,
            ),
        )
    if kind == "binary_expression":
        source = _text(node)
        if "&&" in source:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_and"),)
        if "||" in source:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_or"),)
    if kind == "assembly_statement":
        return (_rule(EntityKind.CONTROL_FLOW, "inline_yul"),)
    if kind in {"yul_if_statement", "yul_for_statement", "yul_switch_statement"}:
        return (_rule(EntityKind.CONTROL_FLOW, "cognitive_decision"),)
    return None


def _function_name(node: Node) -> str | None:
    if node.type == "constructor_definition":
        return "constructor"
    if node.type == "fallback_receive_definition":
        return "receive" if _text(node).lstrip().startswith("receive") else "fallback"
    return _name(node) or None


def _type_name(node: Node) -> str | None:
    return _name(node) or None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=_function_name,
    type_name=_type_name,
)
