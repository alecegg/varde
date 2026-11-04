"""Scala entity extraction rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_definition", "function_declaration"})
TYPE_SCOPES = frozenset({"class_definition", "trait_definition", "object_definition"})
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

_LITERALS = frozenset(
    {
        "integer_literal",
        "floating_point_literal",
        "string",
        "boolean_literal",
        "null_literal",
        "character_literal",
    }
)
_TYPE_NODES = frozenset({"type_identifier", "generic_type"})
TYPE_CONTEXT_KINDS = _TYPE_NODES | frozenset({"type_arguments", "type_parameters"})
_CONTROL_FLOW = frozenset(
    {
        "while_expression",
        "for_expression",
        "match_expression",
        "try_expression",
        "return_expression",
    }
)


def _name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _variable_name(node: Node) -> str | None:
    pattern = _field(node, "pattern")
    value = _text(pattern)
    return (
        value
        if pattern is not None and pattern.type == "identifier" and value != "_"
        else None
    )


def _type_name(node: Node) -> str:
    type_node = _field(node, "type") if node.type == "generic_type" else None
    return (
        _text(type_node)
        if type_node is not None
        else _text(node).split("[", 1)[0].strip()
    )


def _supertypes(node: Node) -> tuple[VisitRule, ...]:
    clause = next(
        (child for child in node.named_children if child.type == "extends_clause"), None
    )
    if clause is None:
        return ()
    types = [child for child in clause.named_children if child.type in _TYPE_NODES]
    if not types:
        return ()
    rules = [
        VisitRule(
            EntityKind.EXTENDS,
            name_field=None,
            literal=_type_name(types[0]),
            span_node=types[0],
        )
    ]
    rules.extend(
        VisitRule(
            EntityKind.IMPLEMENTS,
            name_field=None,
            literal=_type_name(ancestor),
            span_node=ancestor,
        )
        for ancestor in types[1:]
    )
    return tuple(rules)


def _import_path(node: Node) -> str:
    path = _text(node).strip().removeprefix("import").strip()
    if "{" in path:
        path = path.split("{", 1)[0].rstrip(".").strip()
    return path.removesuffix("._").removesuffix(".*").replace(".", "/")


def _call_name(node: Node) -> str:
    function = _field(node, "function")
    if function is None:
        return ""
    if function.type == "field_expression":
        return _text(_field(function, "field"))
    return _text(function)


def _throw_name(node: Node) -> str:
    expression = next(iter(node.named_children), None)
    if expression is None:
        return ""
    if expression.type == "instance_expression":
        type_node = next(
            (child for child in expression.named_children if child.type in _TYPE_NODES),
            None,
        )
        if type_node is not None:
            return _type_name(type_node)
    return _text(expression)


def _catch_name(node: Node) -> str:
    block = next(
        (child for child in node.named_children if child.type == "case_block"), None
    )
    case = (
        next(
            (child for child in block.named_children if child.type == "case_clause"),
            None,
        )
        if block
        else None
    )
    pattern = _field(case, "pattern") if case else None
    return (
        _text(_field(pattern, "pattern"))
        if pattern is not None and pattern.type == "typed_pattern"
        else (
            _text(pattern)
            if pattern is not None and pattern.type == "identifier"
            else ""
        )
    )


def _inside_type(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in {
            "type_identifier",
            "generic_type",
            "type_arguments",
            "type_parameters",
        }:
            return True
        parent = parent.parent
    return False


def _else_if(node: Node) -> bool:
    parent = node.parent
    return (
        parent is not None
        and parent.type == "if_expression"
        and _field(parent, "alternative") == node
    )


def _bool_operator(node: Node) -> str | None:
    operators = {
        _text(child) for child in node.children if child.type == "operator_identifier"
    }
    if "&&" in operators:
        return "logical_and"
    if "||" in operators:
        return "logical_or"
    return None


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_declaration":
        return (
            VisitRule(EntityKind.IMPORT, name_field=None, literal=_import_path(node)),
        )
    if kind in FUNCTION_SCOPES:
        return (VisitRule(EntityKind.FUNCTION),)
    if kind == "lambda_expression":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind in TYPE_SCOPES:
        entity = (
            EntityKind.INTERFACE if kind == "trait_definition" else EntityKind.CLASS
        )
        return (VisitRule(entity), *_supertypes(node))
    if kind == "type_definition":
        return (VisitRule(EntityKind.INTERFACE),)
    if kind == "given_definition":
        return (VisitRule(EntityKind.VARIABLE),)
    if kind in {"val_definition", "var_definition"}:
        name = _variable_name(node)
        return (
            (VisitRule(EntityKind.VARIABLE, name_field=None, literal=name),)
            if name
            else None
        )
    if kind in {"parameter", "class_parameter"}:
        return (VisitRule(EntityKind.PARAMETER),)
    if kind == "call_expression":
        return (VisitRule(EntityKind.CALL, name_field=None, literal=_call_name(node)),)
    if kind == "field_expression":
        return (VisitRule(EntityKind.MEMBER_ACCESS, name_field="field"),)
    if kind in _LITERALS and not _inside_type(node):
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "throw_expression":
        return (
            VisitRule(EntityKind.THROW, name_field=None, literal=_throw_name(node)),
        )
    if kind == "catch_clause":
        return (
            VisitRule(EntityKind.CATCH, name_field=None, literal=_catch_name(node)),
        )
    if kind == "if_expression":
        label = "elseif_statement" if _else_if(node) else "if_expression"
        consequence = _field(node, "consequence")
        rules = (
            [
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal=label,
                    span_start_node=node,
                    span_end_node=consequence,
                )
            ]
            if consequence is not None
            else [VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=label)]
        )
        alternative = _field(node, "alternative")
        if alternative is not None and alternative.type != "if_expression":
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="else_branch",
                    span_node=alternative,
                )
            )
        return tuple(rules)
    if kind in _CONTROL_FLOW:
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    if kind == "case_clause" and not _inside_catch(node):
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="match_arm"),
        )
    if kind == "infix_expression":
        name = _bool_operator(node)
        return (
            (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=name),)
            if name
            else None
        )
    if (
        kind == "prefix_expression"
        and _text(node).lstrip().startswith("!")
        and any(
            child.type == "infix_expression" and _bool_operator(child)
            for child in _descendants(node)
        )
    ):
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="negation_break"
            ),
        )
    if kind == "annotation":
        name = _text(_field(node, "name"))
        if name:
            return (VisitRule(EntityKind.DECORATOR, name_field=None, literal=name),)
    return None


def _inside_catch(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "catch_clause":
            return True
        parent = parent.parent
    return False


def _descendants(node: Node):
    for child in node.named_children:
        yield child
        yield from _descendants(child)


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_name,
    type_name=_name,
    visit_node=_visit,
    type_kinds=TYPE_CONTEXT_KINDS,
)
