"""Swift entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, strip_generic_args

BACKEND = "tree-sitter"
TYPE_SCOPES = frozenset({"class_declaration", "protocol_declaration"})
FUNCTION_SCOPES = frozenset(
    {
        "function_declaration",
        "init_declaration",
        "protocol_function_declaration",
        "computed_getter",
        "computed_setter",
    }
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
        "integer_literal",
        "real_literal",
        "line_string_literal",
        "multi_line_string_literal",
        "raw_string_literal",
        "boolean_literal",
        "nil",
        "nil_literal",
    }
)
_FLOW = frozenset(
    {
        "for_statement",
        "while_statement",
        "repeat_while_statement",
        "switch_statement",
        "guard_statement",
        "do_statement",
        "ternary_expression",
    }
)
_ROUTE_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})
_RESPONSE_METHODS = frozenset({"send", "json", "text"})


def _field_text(node: Node, field: str) -> str:
    return _text(_field(node, field))


def _named(node: Node, kind: str) -> Node | None:
    return next((child for child in node.named_children if child.type == kind), None)


def _is_public_top_level(node: Node) -> bool:
    parent = node.parent
    if parent is None or parent.type != "source_file":
        return False
    modifiers = _named(node, "modifiers")
    return modifiers is not None and any(
        child.type == "visibility_modifier" and _text(child) == "public"
        for child in modifiers.named_children
    )


def _function_name(node: Node) -> str | None:
    if node.type in {"computed_getter", "computed_setter"}:
        declaration = node.parent.parent if node.parent is not None else None
        owner = (
            _field_text(declaration, "name")
            if declaration is not None and declaration.type == "property_declaration"
            else "subscript"
        )
        return f"{owner}.{'get' if node.type == 'computed_getter' else 'set'}"
    return _field_text(node, "name") or None


def _type_name(node: Node) -> str | None:
    return _field_text(node, "name") or _text(_named(node, "type_identifier")) or None


def _member(node: Node) -> str:
    suffix = _field(node, "suffix")
    return _text(_named(suffix, "simple_identifier")) if suffix is not None else ""


def _base_identifier(node: Node) -> str:
    if node.type == "simple_identifier":
        return _text(node)
    target = _field(node, "target")
    return _base_identifier(target) if target is not None else ""


def _first_arg(node: Node) -> str:
    suffix = _named(node, "call_suffix")
    args = _named(suffix, "value_arguments") if suffix is not None else None
    arg = _named(args, "value_argument") if args is not None else None
    return _text(_field(arg, "value")) if arg is not None else ""


def _has_logical_sequence(node: Node) -> bool:
    if node.type in {"conjunction_expression", "disjunction_expression"}:
        return True
    return any(_has_logical_sequence(child) for child in node.named_children)


def _is_else_if(node: Node) -> bool:
    parent = node.parent
    return (
        parent is not None
        and parent.type == "if_statement"
        and any(child == node for child in parent.named_children)
        and any(child.type == "else" for child in parent.children)
    )


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_declaration":
        module = _text(node).split()
        return (
            VisitRule(
                EntityKind.IMPORT,
                literal=module[-1].replace(".", "/") if module else "",
            ),
        )
    if kind in FUNCTION_SCOPES:
        name = _function_name(node) or ""
        rules = [VisitRule(EntityKind.FUNCTION, name_field=None, literal=name)]
        if kind in {
            "function_declaration",
            "init_declaration",
            "protocol_function_declaration",
        } and _is_public_top_level(node):
            rules.append(VisitRule(EntityKind.EXPORT, name_field=None, literal=name))
        return tuple(rules)
    if kind == "class_declaration":
        name = _type_name(node) or ""
        rules = [VisitRule(EntityKind.CLASS, name_field=None, literal=name)]
        if _is_public_top_level(node):
            rules.append(VisitRule(EntityKind.EXPORT, name_field=None, literal=name))
        for spec in (
            child
            for child in node.named_children
            if child.type == "inheritance_specifier"
        ):
            ty = spec.named_children[0] if spec.named_children else None
            if ty is not None:
                rules.append(
                    VisitRule(
                        EntityKind.IMPLEMENTS,
                        name_field=None,
                        literal=strip_generic_args(_text(ty)),
                        span_node=spec,
                    )
                )
        return tuple(rules)
    if kind == "protocol_declaration":
        name = _type_name(node) or ""
        rules = [VisitRule(EntityKind.INTERFACE, name_field=None, literal=name)]
        if _is_public_top_level(node):
            rules.append(VisitRule(EntityKind.EXPORT, name_field=None, literal=name))
        for spec in (
            child
            for child in node.named_children
            if child.type == "inheritance_specifier"
        ):
            ty = spec.named_children[0] if spec.named_children else None
            if ty is not None:
                rules.append(
                    VisitRule(
                        EntityKind.EXTENDS,
                        name_field=None,
                        literal=strip_generic_args(_text(ty)),
                        span_node=spec,
                    )
                )
        return tuple(rules)
    if kind == "property_declaration":
        pattern = _field(node, "name")
        name = _text(_field(pattern, "bound_identifier")) if pattern is not None else ""
        name = name or _text(pattern)
        return (VisitRule(EntityKind.VARIABLE, name_field=None, literal=name),)
    if kind == "parameter":
        name = _field(node, "name") or _field(node, "external_name")
        return (VisitRule(EntityKind.PARAMETER, name_field=None, literal=_text(name)),)
    if kind == "lambda_literal":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind == "call_expression":
        callee = node.named_children[0] if node.named_children else None
        name = _text(callee)
        rules = [VisitRule(EntityKind.CALL, name_field=None, literal=name)]
        if any(
            child.type == "bang" for child in node.children
        ) and _has_logical_sequence(node):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="negation_break",
                )
            )
        if callee is not None and callee.type == "navigation_expression":
            base, method = _base_identifier(callee), _member(callee)
            arg = _first_arg(node)
            if (
                base in {"app", "router", "routes"}
                and method in _ROUTE_METHODS
                and arg.startswith('"')
            ):
                rules.append(VisitRule(EntityKind.ROUTE, name_field=None, literal=name))
            if base in {"res", "response"} and method in _RESPONSE_METHODS:
                rules.append(
                    VisitRule(EntityKind.RESPONSE, name_field=None, literal=name)
                )
        return tuple(rules)
    if kind == "navigation_expression":
        name = _member(node)
        return (
            (VisitRule(EntityKind.MEMBER_ACCESS, name_field=None, literal=name),)
            if name
            else ()
        )
    if kind in _LITERALS:
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "catch_block":
        error = _field(node, "error")
        name = _text(_field(error, "bound_identifier")) if error is not None else ""
        name = (
            name or _text(_named(error, "simple_identifier"))
            if error is not None
            else ""
        )
        return (VisitRule(EntityKind.CATCH, name_field=None, literal=name),)
    if kind == "control_transfer_statement":
        text = _text(node).lstrip()
        if text.startswith("throw"):
            child = next(
                (
                    child
                    for child in node.named_children
                    if child.type != "throw_keyword"
                ),
                None,
            )
            return (VisitRule(EntityKind.THROW, name_field=None, literal=_text(child)),)
        if text.startswith(("break", "continue")) and any(
            child.type == "simple_identifier" for child in node.children
        ):
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="labeled_jump",
                ),
            )
        label = next(
            (
                label
                for prefix, label in (
                    ("return", "return_statement"),
                    ("break", "break_statement"),
                    ("continue", "continue_statement"),
                    ("fallthrough", "fallthrough_statement"),
                )
                if text.startswith(prefix)
            ),
            "control_transfer_statement",
        )
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=label),)
    if kind == "if_statement":
        else_keyword = next(
            (child for child in node.children if child.type == "else"), None
        )
        if else_keyword is None:
            end = None
        else:
            end = next(
                (
                    child
                    for child in reversed(node.children)
                    if child.end_byte <= else_keyword.start_byte
                ),
                None,
            )
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal="elseif_statement" if _is_else_if(node) else "if_statement",
                span_end_node=end,
            ),
        )
    if kind == "switch_entry":
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="case_statement"
            ),
        )
    if kind in _FLOW:
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=kind),)
    if kind in {"conjunction_expression", "disjunction_expression"}:
        return (
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal="logical_and"
                if kind == "conjunction_expression"
                else "logical_or",
            ),
        )
    if kind == "else":
        parent = node.parent
        if parent is not None and parent.type == "if_statement":
            alternatives = [
                child
                for child in parent.named_children
                if child.start_byte > node.end_byte
            ]
            if alternatives and alternatives[0].type != "if_statement":
                return (
                    VisitRule(
                        EntityKind.CONTROL_FLOW,
                        name_field=None,
                        literal="else_branch",
                        span_node=parent,
                        span_start_node=node,
                        span_end_node=parent,
                    ),
                )
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_function_name,
    type_name=_type_name,
    visit_node=_visit,
)
