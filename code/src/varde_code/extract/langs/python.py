"""Python entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function_definition"})
TYPE_SCOPES = frozenset({"class_definition"})
REQUIRED_KINDS = (
    EntityKind.FUNCTION,
    EntityKind.CLASS,
    EntityKind.DECORATOR,
    EntityKind.VARIABLE,
    EntityKind.PARAMETER,
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
TYPE_CONTEXT_KINDS = frozenset(
    {
        "type_annotation",
        "return_type",
        "type_arguments",
        "type_parameters",
        "predefined_type",
        "literal_type",
        "union_type",
        "intersection_type",
        "array_type",
        "generic_type",
        "function_type",
        "tuple_type",
        "mapped_type",
        "nullable_type",
        "optional_type",
        "index_type_query",
        "type_parameter",
    }
)
# The Python grammar wraps direct `-> None` annotations in `type`, while the
# Rust extractor retains those literal nodes. Exclude only nested type forms.
LITERAL_TYPE_CONTEXT_KINDS = frozenset(
    {
        "generic_type",
        "union_type",
        "splat_type",
        "type_parameter",
        "type_argument_list",
    }
)


def _named(node: Node) -> list[Node]:
    return list(node.named_children)


def _target_names(node: Node) -> list[str]:
    if node.type == "identifier":
        return [] if _text(node) == "_" else [_text(node)]
    if node.type in {"pattern_list", "tuple_pattern", "list_pattern"}:
        return [name for child in _named(node) for name in _target_names(child)]
    return []


def _parameter_names(node: Node) -> list[str]:
    names: list[str] = []
    for child in _named(node):
        name = _field(child, "name")
        if child.type == "identifier":
            if _text(child) != "_":
                names.append(_text(child))
        elif name is not None:
            if _text(name) != "_":
                names.append(_text(name))
        elif child.type in {
            "typed_parameter",
            "list_splat_pattern",
            "dictionary_splat_pattern",
        }:
            target = next(
                (item for item in _named(child) if item.type == "identifier"), None
            )
            if target is not None and _text(target) != "_":
                names.append(_text(target))
    return names


def _contains_boolean_operator(node: Node) -> bool:
    pending = list(node.children)
    while pending:
        current = pending.pop()
        if current.type == "boolean_operator":
            return True
        pending.extend(current.children)
    return False


def _dotted_name(node: Node) -> str:
    if node.type == "relative_import":
        prefix = next(
            (child for child in _named(node) if child.type == "import_prefix"), None
        )
        module = next(
            (child for child in _named(node) if child.type == "dotted_name"), None
        )
        dot_count = _text(prefix).count(".") if prefix is not None else 0
        dots = "./" + "../" * max(0, dot_count - 1) if dot_count else ""
        return dots + (_dotted_name(module) if module is not None else "")
    if node.type == "aliased_import":
        target = _field(node, "name")
        return _dotted_name(target) if target is not None else ""
    return _text(node).replace(".", "/")


def _is_compensating_usage(node: Node) -> bool:
    body = _field(node, "body")
    if body is None:
        return False
    statements = _named(body)
    return (
        len(statements) == 2
        and any(statement.type == "function_definition" for statement in statements)
        and any(statement.type == "return_statement" for statement in statements)
    )


def _in_literal_type_context(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in LITERAL_TYPE_CONTEXT_KINDS:
            return True
        parent = parent.parent
    return False


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "decorator":
        expression = next(iter(_named(node)), None)
        if expression is None:
            return ()
        if expression.type == "call":
            expression = _field(expression, "function") or expression
        return (
            VisitRule(EntityKind.DECORATOR, name_field=None, literal=_text(expression)),
        )
    if kind == "function_definition":
        rules = [VisitRule(EntityKind.FUNCTION)]
        if _is_compensating_usage(node):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="compensating_usage",
                )
            )
        return tuple(rules)
    if kind == "class_definition":
        rules = [VisitRule(EntityKind.CLASS)]
        bases = _field(node, "superclasses")
        if bases is not None:
            rules.extend(
                VisitRule(
                    EntityKind.EXTENDS,
                    name_field=None,
                    literal=_text(base),
                    span_node=base,
                )
                for base in _named(bases)
                if base.type in {"identifier", "attribute"}
            )
        return tuple(rules)
    if kind == "assignment":
        left = _field(node, "left")
        names = _target_names(left) if left is not None else []
        return tuple(
            VisitRule(EntityKind.VARIABLE, name_field=None, literal=name)
            for name in names
        )
    if kind == "parameters":
        return tuple(
            VisitRule(EntityKind.PARAMETER, name_field=None, literal=name)
            for name in _parameter_names(node)
        )
    if kind == "call":
        callee = _field(node, "function")
        return (VisitRule(EntityKind.CALL, name_field=None, literal=_text(callee)),)
    if kind == "attribute":
        return (VisitRule(EntityKind.MEMBER_ACCESS, name_field="attribute"),)
    if kind in {"integer", "float", "string", "true", "false", "none"}:
        if _in_literal_type_context(node):
            return ()
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "except_clause":
        value = _field(node, "value")
        target = _field(value, "alias") if value is not None else None
        alias = next(iter(_named(target)), None) if target is not None else None
        return (VisitRule(EntityKind.CATCH, name_field=None, literal=_text(alias)),)
    if kind == "raise_statement":
        expression = next(iter(_named(node)), None)
        return (
            VisitRule(EntityKind.THROW, name_field=None, literal=_text(expression)),
        )
    if kind in {"import_statement", "import_from_statement"}:
        names = [_dotted_name(child) for child in node.children_by_field_name("name")]
        if kind == "import_from_statement":
            module = _field(node, "module_name")
            prefix = _dotted_name(module) if module is not None else ""
            if prefix and not prefix.endswith("/"):
                return (VisitRule(EntityKind.IMPORT, name_field=None, literal=prefix),)
            imported = next((name for name in names if name), "")
            names = [prefix + imported]
        return tuple(
            VisitRule(EntityKind.IMPORT, name_field=None, literal=name)
            for name in names
            if name
        )
    if kind == "if_statement":
        consequence = _field(node, "consequence")
        condition = _field(node, "condition")
        rules = [
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal="if_statement",
                span_node=consequence,
            )
        ]
        if condition is not None:
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="legacy_nesting",
                    span_node=condition,
                )
            )
        alternative = _field(node, "alternative")
        if alternative is not None:
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="legacy_nesting",
                    span_node=alternative,
                )
            )
        return tuple(rules)
    if kind in {
        "for_statement",
        "while_statement",
        "with_statement",
        "try_statement",
        "return_statement",
        "break_statement",
        "continue_statement",
        "conditional_expression",
    }:
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    if kind == "match_statement":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="match_expression"
            ),
        )
    if kind == "case_clause":
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="match_arm"),
        )
    if kind == "lambda" and node.is_named:
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind == "elif_clause":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="elseif_statement"
            ),
        )
    if (
        kind == "else_clause"
        and node.parent is not None
        and node.parent.type == "if_statement"
    ):
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="else_branch"),
        )
    if kind == "boolean_operator":
        operator = next(
            (child.type for child in node.children if child.type in {"and", "or"}), None
        )
        if operator:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal=f"logical_{operator}",
                ),
            )
    if kind == "not_operator" and _contains_boolean_operator(node):
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="negation_break"
            ),
        )
    if kind == "for_in_clause":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="comprehension_for"
            ),
        )
    if kind == "if_clause":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="comprehension_if"
            ),
        )
    return None


def _function_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _type_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


LANG = LanguageTables(
    visits={},
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    type_kinds=TYPE_CONTEXT_KINDS,
    function_name=_function_name,
    type_name=_type_name,
    visit_node=_visit,
)
