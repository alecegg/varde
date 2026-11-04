"""Java entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, strip_generic_args

BACKEND = "tree-sitter"
TYPE_SCOPES = frozenset(
    {"class_declaration", "interface_declaration", "record_declaration"}
)
FUNCTION_SCOPES = frozenset(
    {"method_declaration", "constructor_declaration", "compact_constructor_declaration"}
)
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
FLOW_NAME_ROLES: dict[str, str] = {}

_LITERALS = frozenset(
    {
        "decimal_integer_literal",
        "hex_integer_literal",
        "octal_integer_literal",
        "binary_integer_literal",
        "decimal_floating_point_literal",
        "hex_floating_point_literal",
        "string_literal",
        "character_literal",
        "true",
        "false",
        "null_literal",
    }
)
_ROUTE_METHODS = {
    "GetMapping": "GET",
    "PostMapping": "POST",
    "PutMapping": "PUT",
    "DeleteMapping": "DELETE",
    "PatchMapping": "PATCH",
}


def _named(node: Node, kind: str) -> Node | None:
    return next((child for child in node.named_children if child.type == kind), None)


def _function_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _type_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _is_top_level_type(node: Node) -> bool:
    parent = node.parent
    return parent is not None and parent.type == "program"


def _annotation_name(node: Node) -> str:
    return _text(_field(node, "name")) or _text(_named(node, "identifier"))


def _inheritance_rules(node: Node) -> tuple[VisitRule, ...]:
    rules: list[VisitRule] = []
    superclass = _field(node, "superclass")
    if superclass is not None and superclass.named_children:
        type_node = superclass.named_children[-1]
        rules.append(
            VisitRule(
                EntityKind.EXTENDS,
                name_field=None,
                literal=strip_generic_args(_text(type_node)),
                span_node=type_node,
            )
        )
    interfaces = _field(node, "interfaces")
    if interfaces is not None:
        for type_node in interfaces.named_children:
            if type_node.type == "type_list":
                rules.extend(
                    VisitRule(
                        EntityKind.IMPLEMENTS,
                        name_field=None,
                        literal=strip_generic_args(_text(child)),
                        span_node=child,
                    )
                    for child in type_node.named_children
                )
            else:
                rules.append(
                    VisitRule(
                        EntityKind.IMPLEMENTS,
                        name_field=None,
                        literal=strip_generic_args(_text(type_node)),
                        span_node=type_node,
                    )
                )
    return tuple(rules)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_declaration":
        path = _text(node).strip().removeprefix("import").removesuffix(";").strip()
        path = path.removeprefix("static ")
        path = path.removesuffix(".*").replace(".", "/")
        return (VisitRule(EntityKind.IMPORT, name_field=None, literal=path),)
    if kind in {
        "method_declaration",
        "constructor_declaration",
        "compact_constructor_declaration",
    }:
        return (VisitRule(EntityKind.FUNCTION),)
    if kind == "class_declaration":
        rules = [VisitRule(EntityKind.CLASS), *_inheritance_rules(node)]
        if _is_top_level_type(node) and "public" in _text(_named(node, "modifiers")):
            rules.append(VisitRule(EntityKind.EXPORT))
        return tuple(rules)
    if kind == "interface_declaration":
        rules = [VisitRule(EntityKind.INTERFACE), *_inheritance_rules(node)]
        if _is_top_level_type(node) and "public" in _text(_named(node, "modifiers")):
            rules.append(VisitRule(EntityKind.EXPORT))
        return tuple(rules)
    if kind == "record_declaration":
        return (VisitRule(EntityKind.CLASS), *_inheritance_rules(node))
    if kind in {
        "field_declaration",
        "local_variable_declaration",
        "constant_declaration",
    }:
        declarations = [
            child
            for child in node.named_children
            if child.type == "variable_declarator"
        ]
        return tuple(
            VisitRule(
                EntityKind.VARIABLE,
                name_field=None,
                literal=_text(_field(child, "name")),
            )
            for child in declarations
        )
    if kind == "formal_parameter":
        return (VisitRule(EntityKind.PARAMETER),)
    if kind == "lambda_expression":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind == "method_invocation":
        rules = [VisitRule(EntityKind.CALL)]
        method = _text(_field(node, "name"))
        receiver = _text(_field(node, "object"))
        if method == "setStatus" and receiver.rsplit(".", 1)[-1] in {"response", "res"}:
            rules.append(VisitRule(EntityKind.RESPONSE, name_field="name"))
        return tuple(rules)
    if kind == "object_creation_expression":
        return (VisitRule(EntityKind.CALL, name_field="type"),)
    if kind == "field_access":
        return (VisitRule(EntityKind.MEMBER_ACCESS, name_field="field"),)
    if kind in _LITERALS and not _inside_type(node):
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "catch_clause":
        parameter = _named(node, "catch_formal_parameter")
        name = _text(_field(parameter, "name")) if parameter is not None else ""
        return (VisitRule(EntityKind.CATCH, name_field=None, literal=name),)
    if kind == "throw_statement":
        value = next(
            (child for child in node.named_children if child.type != "throw"), None
        )
        return (VisitRule(EntityKind.THROW, name_field=None, literal=_text(value)),)
    if kind == "if_statement":
        label = "elseif_statement" if _is_else_if(node) else "if_statement"
        rules = [VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=label)]
        alternative = _field(node, "alternative")
        if alternative is not None and alternative.type != "if_statement":
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="else_branch"
                )
            )
        return tuple(rules)
    if kind == "binary_expression":
        text = _text(node)
        if "&&" in text:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="logical_and"
                ),
            )
        if "||" in text:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="logical_or"
                ),
            )
    if kind == "unary_expression" and _text(node).lstrip().startswith("!"):
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="negation_break"
            ),
        )
    if kind in {"switch_label", "guard"}:
        name = "case_statement" if kind == "switch_label" else "guard_statement"
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=name),)
    if kind in {
        "switch_statement",
        "switch_expression",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "return_statement",
        "try_statement",
        "try_with_resources_statement",
        "ternary_expression",
        "break_statement",
        "continue_statement",
    }:
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    if kind in {"annotation", "marker_annotation"}:
        name = _annotation_name(node)
        rules = [VisitRule(EntityKind.DECORATOR, name_field=None, literal=name)]
        if name in _ROUTE_METHODS and kind == "annotation":
            rules.append(VisitRule(EntityKind.ROUTE, name_field=None, literal=name))
        return tuple(rules)
    return None


def _inside_type(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in {
            "type_identifier",
            "integral_type",
            "floating_point_type",
            "boolean_type",
            "void_type",
        }:
            return True
        parent = parent.parent
    return False


def _is_else_if(node: Node) -> bool:
    parent = node.parent
    return (
        parent is not None
        and parent.type == "if_statement"
        and _field(parent, "alternative") == node
    )


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
