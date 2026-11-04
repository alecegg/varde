"""Go entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_declaration", "method_declaration"})
TYPE_SCOPES: frozenset[str] = frozenset()
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
    EntityKind.THROW,
    EntityKind.CONTROL_FLOW,
    EntityKind.ROUTE,
    EntityKind.RESPONSE,
)
FLOW_NAME_ROLES: dict[str, str] = {}

_LITERALS = frozenset(
    {
        "int_literal",
        "float_literal",
        "imaginary_literal",
        "rune_literal",
        "interpreted_string_literal",
        "raw_string_literal",
        "true",
        "false",
        "nil",
    }
)
_FLOW = frozenset(
    {
        "for_statement",
        "expression_switch_statement",
        "type_switch_statement",
        "select_statement",
        "return_statement",
        "go_statement",
        "defer_statement",
        "goto_statement",
        "break_statement",
        "continue_statement",
        "expression_case",
        "type_case",
        "communication_case",
        "default_case",
    }
)


def _field_nodes(node: Node, name: str) -> list[Node]:
    return [
        child
        for index, child in enumerate(node.children)
        if node.field_name_for_child(index) == name
    ]


def _named(node: Node) -> list[Node]:
    return list(node.named_children)


def _identifiers(node: Node) -> list[str]:
    found: list[str] = []
    for child in _named(node):
        if child.type == "identifier":
            name = _text(child)
            if name != "_" and name not in found:
                found.append(name)
        else:
            found.extend(name for name in _identifiers(child) if name not in found)
    return found


def _is_package_level(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return False
    if parent.type == "source_file":
        return True
    declaration = (
        parent.parent
        if parent.type in {"var_declaration", "const_declaration"}
        else parent
    )
    return (
        declaration is not None
        and declaration.parent is not None
        and declaration.parent.type == "source_file"
    )


def _declaration_rules(node: Node, kind: EntityKind) -> tuple[VisitRule, ...]:
    names = [
        _text(child)
        for child in _field_nodes(node, "name")
        if child.type == "identifier" and _text(child) != "_"
    ]
    rules = tuple(VisitRule(kind, literal=name) for name in names)
    if _is_package_level(node):
        rules += tuple(
            VisitRule(EntityKind.EXPORT, literal=name)
            for name in names
            if name[:1].isupper()
        )
    return rules


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in {"function_declaration", "method_declaration"}:
        name = _field(node, "name")
        value = _text(name) if name is not None else ""
        rules = (VisitRule(EntityKind.FUNCTION, literal=value),)
        if _is_package_level(node) and value[:1].isupper():
            rules += (VisitRule(EntityKind.EXPORT, literal=value),)
        return rules
    if kind == "type_spec":
        name = _text(_field(node, "name"))
        ty = _field(node, "type")
        entity_kind = (
            EntityKind.INTERFACE
            if ty is not None and ty.type == "interface_type"
            else EntityKind.CLASS
        )
        rules = (VisitRule(entity_kind, literal=name),)
        if name[:1].isupper():
            rules += (VisitRule(EntityKind.EXPORT, literal=name),)
        return rules
    if kind == "type_alias":
        name = _text(_field(node, "name"))
        rules = (VisitRule(EntityKind.CLASS, literal=name),)
        if name[:1].isupper():
            rules += (VisitRule(EntityKind.EXPORT, literal=name),)
        return rules
    if kind == "field_declaration" and not _field_nodes(node, "name"):
        embedded = _field(node, "type")
        return (
            (VisitRule(EntityKind.EXTENDS, literal=_text(embedded)),)
            if embedded is not None
            else ()
        )
    if kind in {"var_spec", "const_spec"}:
        return _declaration_rules(node, EntityKind.VARIABLE)
    if kind == "short_var_declaration":
        left = _field(node, "left")
        return (
            tuple(
                VisitRule(EntityKind.VARIABLE, literal=name)
                for name in _identifiers(left)
            )
            if left
            else ()
        )
    if kind in {"parameter_declaration", "variadic_parameter_declaration"}:
        return tuple(
            VisitRule(EntityKind.PARAMETER, literal=_text(name))
            for name in _field_nodes(node, "name")
            if _text(name) != "_"
        )
    if kind == "import_spec":
        path = _field(node, "path")
        return (
            (
                VisitRule(
                    EntityKind.IMPORT, literal=unquote(_text(path), allow_backtick=True)
                ),
            )
            if path
            else ()
        )
    if kind == "call_expression":
        function = _field(node, "function")
        name = _text(function) if function else ""
        rules = (VisitRule(EntityKind.CALL, literal=name),)
        if name == "panic":
            args = _field(node, "arguments")
            first = _named(args)[0] if args is not None and _named(args) else None
            rules += (
                VisitRule(EntityKind.THROW, literal=_text(first) if first else ""),
            )
        return rules
    if kind == "selector_expression":
        field = _field(node, "field")
        return (
            VisitRule(EntityKind.MEMBER_ACCESS, literal=_text(field) if field else ""),
        )
    if kind in _LITERALS:
        return (VisitRule(EntityKind.LITERAL, literal=_text(node)),)
    if kind in _FLOW:
        value = (
            "goto_jump"
            if kind == "goto_statement"
            else "case_statement"
            if kind.endswith("_case")
            else kind
        )
        if kind in {"break_statement", "continue_statement"} and any(
            c.type == "label_name" for c in _named(node)
        ):
            value = "labeled_jump"
        return (VisitRule(EntityKind.CONTROL_FLOW, literal=value),)
    if kind == "if_statement":
        alternative = _field(node, "alternative")
        consequence = _field(node, "consequence")
        label = (
            "elseif_statement"
            if alternative is not None and alternative.type == "if_statement"
            else kind
        )
        rules = [
            VisitRule(
                EntityKind.CONTROL_FLOW,
                literal=label,
                span_node=consequence or node,
            ),
        ]
        if alternative is not None:
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    literal="legacy_nesting",
                    span_node=alternative,
                )
            )
            if alternative.type != "if_statement":
                rules.append(
                    VisitRule(
                        EntityKind.CONTROL_FLOW,
                        literal="else_branch",
                        span_node=alternative,
                    )
                )
        return tuple(rules)
    if kind == "binary_expression":
        text = _text(node)
        rules = []
        if "&&" in text:
            rules.append(VisitRule(EntityKind.CONTROL_FLOW, literal="logical_and"))
        if "||" in text:
            rules.append(VisitRule(EntityKind.CONTROL_FLOW, literal="logical_or"))
        return tuple(rules)
    if kind == "func_literal":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, literal=""),)
    return None


def _function_name(node: Node) -> str | None:
    name = _field(node, "name")
    return _text(name) if name is not None else None


LANG = LanguageTables(
    visits={},
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    visit_node=_visit,
    function_name=_function_name,
)
