"""C entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_definition"})
TYPE_SCOPES = frozenset({"struct_specifier", "union_specifier", "enum_specifier"})
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
    EntityKind.CALL,
    EntityKind.LITERAL,
    EntityKind.MEMBER_ACCESS,
    EntityKind.CONTROL_FLOW,
)
FLOW_NAME_ROLES: dict[str, str] = {}


def _children(node: Node) -> list[Node]:
    return list(node.named_children)


def _declarator_name(node: Node | None) -> str:
    if node is None:
        return ""
    if node.type in {"identifier", "field_identifier", "type_identifier"}:
        return _text(node)
    if node.type == "qualified_identifier":
        return _declarator_name(_field(node, "name"))
    if node.type == "operator_name":
        return _text(node)
    nested = _field(node, "declarator")
    if nested is None:
        nested = next(iter(node.named_children), None)
    return _declarator_name(nested)


def _function_name(node: Node) -> str | None:
    return _declarator_name(_field(node, "declarator")) or None


def _type_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _rule(kind: EntityKind, name: str, span_node: Node | None = None) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name, span_node=span_node)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "function_definition":
        name = _function_name(node)
        return (_rule(EntityKind.FUNCTION, name),) if name else ()
    if kind in {"struct_specifier", "union_specifier", "enum_specifier"}:
        name = _text(_field(node, "name"))
        return (_rule(EntityKind.CLASS, name),) if name else ()
    if kind == "type_definition":
        name = _declarator_name(_field(node, "declarator"))
        return (_rule(EntityKind.CLASS, name),) if name else ()
    if kind == "preproc_def":
        name = _text(_field(node, "name"))
        return (_rule(EntityKind.VARIABLE, name),) if name else ()
    if kind == "preproc_function_def":
        name = _text(_field(node, "name"))
        return (_rule(EntityKind.FUNCTION, name),) if name else ()
    if kind == "preproc_include":
        path = _text(_field(node, "path")).strip().strip('<>"')
        return (_rule(EntityKind.IMPORT, path),) if path else ()
    if kind == "declaration":
        rules = []
        for decl in node.children_by_field_name("declarator"):
            name = _declarator_name(decl)
            if not name:
                continue
            if _contains_function_declarator(decl):
                rules.append(_rule(EntityKind.FUNCTION, name))
            else:
                rules.append(_rule(EntityKind.VARIABLE, name))
        return tuple(rules)
    if kind == "parameter_declaration":
        name = _declarator_name(_field(node, "declarator"))
        return (_rule(EntityKind.PARAMETER, name),) if name else ()
    if kind == "call_expression":
        name = _text(_field(node, "function"))
        return (_rule(EntityKind.CALL, name),) if name else ()
    if kind == "field_expression":
        name = _text(_field(node, "field"))
        return (_rule(EntityKind.MEMBER_ACCESS, name),) if name else ()
    if kind in {"number_literal", "string_literal", "char_literal", "true", "false"}:
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "if_statement":
        consequence = _field(node, "consequence")
        rules = (
            [
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="if_statement",
                    span_start_node=node,
                    span_end_node=consequence,
                )
            ]
            if consequence
            else []
        )
        alternative = _field(node, "alternative")
        if alternative is not None:
            rules.append(_rule(EntityKind.CONTROL_FLOW, "legacy_nesting", alternative))
            if alternative.type != "if_statement":
                rules.append(_rule(EntityKind.CONTROL_FLOW, "else_branch", alternative))
        return tuple(rules)
    if kind == "binary_expression":
        source = _text(node)
        return (
            tuple(
                _rule(EntityKind.CONTROL_FLOW, name)
                for token, name in (("&&", "logical_and"), ("||", "logical_or"))
                if token in source
            )
            or None
        )
    controls = {
        "for_statement",
        "while_statement",
        "do_statement",
        "switch_statement",
        "case_statement",
        "return_statement",
        "break_statement",
        "continue_statement",
        "goto_statement",
        "conditional_expression",
    }
    if kind in controls:
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
    return None


def _contains_function_declarator(node: Node) -> bool:
    if node.type == "function_declarator":
        return True
    return any(_contains_function_declarator(child) for child in node.named_children)


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
