"""JavaScript entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, unquote

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "generator_function",
        "method_definition",
        "generator_function_declaration",
    }
)
TYPE_SCOPES = frozenset({"class_declaration"})
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
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
FLOW_NAME_ROLES: dict[str, str] = {"legacy_nesting": "legacy_nesting"}
LITERALS = frozenset(
    {
        "number",
        "string",
        "true",
        "false",
        "null",
        "undefined",
        "template_string",
        "regex",
    }
)


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _ancestors(node: Node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _is_else_if(node: Node) -> bool:
    parent = node.parent
    return bool(
        parent
        and (
            parent.type == "if_statement"
            or (
                parent.type == "else_clause"
                and parent.parent
                and parent.parent.type == "if_statement"
            )
        )
    )


def _has_logical_binary(node: Node) -> bool:
    pending = list(node.named_children)
    while pending:
        child = pending.pop()
        if child.type == "binary_expression" and (
            "&&" in _text(child) or "||" in _text(child)
        ):
            return True
        pending.extend(child.named_children)
    return False


def _export_names(node: Node) -> list[str]:
    names = []
    for child in node.named_children:
        if child.type == "export_clause":
            names.extend(
                _text(spec.child_by_field_name("name"))
                for spec in child.named_children
                if spec.type == "export_specifier"
            )
        elif child.type in {
            "function_declaration",
            "generator_function_declaration",
            "class_declaration",
        }:
            names.append(_text(child.child_by_field_name("name")))
        elif child.type in {"lexical_declaration", "variable_declaration"}:
            for decl in child.named_children:
                if decl.type == "variable_declarator":
                    names.append(_text(decl.child_by_field_name("name")))
    return [name for name in names if name]


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in {
        "function_declaration",
        "generator_function_declaration",
        "method_definition",
    }:
        return (_rule(EntityKind.FUNCTION, _text(_field(node, "name"))),)
    if kind in {"function_expression", "generator_function", "arrow_function"}:
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind == "class_declaration":
        return (_rule(EntityKind.CLASS, _text(_field(node, "name"))),)
    if kind in {"lexical_declaration", "variable_declaration"}:
        return tuple(
            _rule(EntityKind.VARIABLE, _text(decl.child_by_field_name("name")))
            for decl in node.named_children
            if decl.type == "variable_declarator"
        )
    if kind == "formal_parameters":
        rules = []
        for child in node.named_children:
            name = (
                _text(child.child_by_field_name("left"))
                if child.type == "assignment_pattern"
                else _text(child.named_children[0])
                if child.type == "rest_pattern" and child.named_children
                else _text(child)
                if child.type == "identifier"
                else ""
            )
            if name:
                rules.append(_rule(EntityKind.PARAMETER, name))
        return tuple(rules)
    if kind == "import_statement":
        return (_rule(EntityKind.IMPORT, unquote(_text(_field(node, "source")), True)),)
    if kind == "export_statement":
        return tuple(_rule(EntityKind.EXPORT, name) for name in _export_names(node))
    if kind == "call_expression":
        callee = _text(_field(node, "function"))
        rules = [_rule(EntityKind.CALL, callee)]
        parts = callee.split(".")
        if (
            len(parts) == 2
            and parts[0] in {"app", "router"}
            and parts[1]
            in {
                "get",
                "post",
                "put",
                "patch",
                "delete",
                "options",
                "head",
                "all",
                "use",
            }
        ):
            rules.append(VisitRule(EntityKind.ROUTE, name_field=None, literal=callee))
        if (
            len(parts) == 2
            and parts[0] == "res"
            and parts[1] in {"send", "json", "end", "render", "redirect", "sendFile"}
        ):
            rules.append(_rule(EntityKind.RESPONSE, callee))
        return tuple(rules)
    if kind == "member_expression":
        return (_rule(EntityKind.MEMBER_ACCESS, _text(_field(node, "property"))),)
    if kind in LITERALS and not any(
        a.type in {"predefined_type", "type_annotation", "literal_type"}
        for a in _ancestors(node)
    ):
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "catch_clause":
        return (_rule(EntityKind.CATCH, _text(_field(node, "parameter"))),)
    if kind == "throw_statement":
        return (
            _rule(
                EntityKind.THROW,
                _text(node.named_children[0]) if node.named_children else "",
            ),
        )
    if kind == "if_statement":
        consequence = _field(node, "consequence")
        rules = [
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal="elseif_statement" if _is_else_if(node) else kind,
                span_end_node=consequence,
            )
        ]
        alternative = _field(node, "alternative")
        if (
            alternative is not None
            and not _is_else_if(node)
            and alternative.type == "else_clause"
        ):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="legacy_nesting",
                    span_node=alternative,
                )
            )
        return tuple(rules)
    if kind == "else_clause":
        alternative = next(iter(node.named_children), None)
        return (
            ()
            if alternative is None or alternative.type == "if_statement"
            else (
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="else_branch",
                    span_node=alternative,
                ),
            )
        )
    if kind == "binary_expression":
        text = _text(node)
        return (
            tuple(
                _rule(EntityKind.CONTROL_FLOW, name)
                for token, name in (("&&", "logical_and"), ("||", "logical_or"))
                if token in text
            )
            or None
        )
    if (
        kind == "unary_expression"
        and _text(node).lstrip().startswith("!")
        and _has_logical_binary(node)
    ):
        return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    if kind in {"switch_case", "switch_default"}:
        return (_rule(EntityKind.CONTROL_FLOW, "case_statement"),)
    if kind in {
        "for_statement",
        "for_in_statement",
        "for_of_statement",
        "while_statement",
        "switch_statement",
        "try_statement",
        "ternary_expression",
        "return_statement",
        "break_statement",
        "continue_statement",
    }:
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
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
