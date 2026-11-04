"""Ruby entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"method", "singleton_method"})
TYPE_SCOPES = frozenset({"class", "module", "singleton_class"})
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
    EntityKind.ROUTE,
    EntityKind.RESPONSE,
)
FLOW_NAME_ROLES = {
    "negation_break": "ignored",
    "rescue_begin": "legacy_only",
    "yield": "legacy_only",
}
_TARGETS = {
    "identifier",
    "instance_variable",
    "class_variable",
    "global_variable",
    "constant",
}
_REQUIRE_CALLS = {"require", "require_relative", "load", "autoload"}
_ATTR_CALLS = {"attr", "attr_accessor", "attr_reader", "attr_writer"}
_RESPONSES = {
    "json",
    "erb",
    "haml",
    "slim",
    "erubis",
    "redirect",
    "halt",
    "send_file",
    "body",
}
_HTTP_VERBS = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "options",
    "head",
    "link",
    "unlink",
}
_MIXINS = {"include", "prepend", "extend"}


def _rule(kind: EntityKind, name: str, span_node: Node | None = None) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name, span_node=span_node)


def _named(node: Node) -> list[Node]:
    return list(node.named_children)


def _target_names(node: Node | None) -> list[str]:
    if node is None:
        return []
    if node.type in _TARGETS:
        value = _text(node)
        return [] if value == "_" else [value]
    if node.type in {"left_assignment_list", "destructured_left_assignment"}:
        return [name for child in node.children for name in _target_names(child)]
    return []


def _parameter_names(node: Node) -> list[str]:
    result = []
    for child in node.children:
        if child.type == "identifier":
            name = _text(child)
        elif child.type in {"optional_parameter", "keyword_parameter"}:
            name = _text(_field(child, "name"))
        elif child.type in {
            "splat_parameter",
            "hash_splat_parameter",
            "block_parameter",
            "forward_parameter",
        }:
            name = _text(_field(child, "name")) or next(
                (_text(item) for item in child.children if item.type == "identifier"),
                "",
            )
        else:
            continue
        if name and name != "_":
            result.append(name)
    return result


def _string_content(node: Node | None) -> str | None:
    if node is None or node.type != "string":
        return None
    return "".join(
        _text(child) for child in node.children if child.type == "string_content"
    )


def _first_argument(node: Node) -> Node | None:
    args = next(
        (child for child in node.children if child.type == "argument_list"), None
    )
    return (
        next(
            (child for child in args.children if child.type not in {"(", ",", ")"}),
            None,
        )
        if args
        else None
    )


def _call_name(node: Node) -> str:
    method = _field(node, "method")
    if method is not None:
        return _text(method)
    return next(
        (
            _text(child)
            for child in node.children
            if child.type in {"identifier", "constant"}
        ),
        "",
    )


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in FUNCTION_SCOPES:
        rules = [_rule(EntityKind.FUNCTION, _text(_field(node, "name")))]
        rescue = _first_implicit_rescue(node)
        descendants = list(_descendants(node))
        if rescue is not None or any(item.type == "yield" for item in descendants):
            rules.append(_rule(EntityKind.CONTROL_FLOW, "legacy_nesting"))
        if rescue is not None:
            rules.append(_rule(EntityKind.CATCH, "legacy_catch_clause", rescue))
        return tuple(rules)
    if kind in {"block", "do_block"}:
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind == "class":
        name = _text(_field(node, "name"))
        if not name:
            return ()
        rules = [_rule(EntityKind.CLASS, name)]
        superclass = _field(node, "superclass")
        base = (
            next(
                (
                    child
                    for child in _named(superclass)
                    if child.type in {"constant", "scope_resolution"}
                ),
                None,
            )
            if superclass
            else None
        )
        if base is not None:
            rules.append(_rule(EntityKind.EXTENDS, _text(base), base))
        return tuple(rules)
    if kind == "module":
        name = _text(_field(node, "name"))
        return (_rule(EntityKind.INTERFACE, name),) if name else ()
    if kind in {"assignment", "operator_assignment"}:
        return tuple(
            _rule(EntityKind.VARIABLE, name)
            for name in _target_names(_field(node, "left"))
        )
    if kind in {"method_parameters", "block_parameters", "lambda_parameters"}:
        return tuple(
            _rule(EntityKind.PARAMETER, name) for name in _parameter_names(node)
        )
    if kind == "call":
        return _visit_call(node)
    if kind in {"integer", "float", "string", "true", "false", "nil"}:
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "rescue" and node.named_children:
        variable = next(
            (child for child in node.children if child.type == "exception_variable"),
            None,
        )
        identifier = (
            next(
                (child for child in variable.children if child.type == "identifier"),
                None,
            )
            if variable
            else None
        )
        exceptions = next(
            (child for child in node.children if child.type == "exceptions"), None
        )
        return (_rule(EntityKind.CATCH, _text(identifier) or _text(exceptions)),)
    if kind == "binary":
        operator = _text(_field(node, "operator"))
        if operator in {"&&", "and"}:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_and"),)
        if operator in {"||", "or"}:
            return (_rule(EntityKind.CONTROL_FLOW, "logical_or"),)
        return ()
    if kind == "unary" and _text(_field(node, "operator")) in {"!", "not"}:
        return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    flow_kinds = {
        "if",
        "unless",
        "while",
        "until",
        "for",
        "case",
        "return",
        "break",
        "next",
        "redo",
        "retry",
        "yield",
        "if_modifier",
        "unless_modifier",
        "while_modifier",
        "until_modifier",
        "rescue_modifier",
        "conditional",
    }
    is_bare_transfer = (
        kind in {"return", "next"}
        and node.parent is not None
        and node.parent.type != kind
    )
    if kind in flow_kinds and (node.named_children or is_bare_transfer):
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
    if kind == "elsif" and node.named_children:
        condition = _field(node, "condition")
        return (_rule(EntityKind.CONTROL_FLOW, "elseif_statement", condition or node),)
    if (
        kind == "else"
        and node.parent is not None
        and node.parent.type in {"if", "elsif", "unless"}
    ):
        return (_rule(EntityKind.CONTROL_FLOW, "else_branch"),)
    if kind == "when" and node.named_children:
        return (_rule(EntityKind.CONTROL_FLOW, "case_statement"),)
    if kind == "begin" and node.named_children:
        has_rescue = any(
            item.type == "rescue" and item.named_children for item in _descendants(node)
        )
        rules = [
            _rule(EntityKind.CONTROL_FLOW, "rescue_begin" if has_rescue else "begin")
        ]
        rescues = [
            item
            for item in _descendants(node)
            if item.type == "rescue" and item.named_children
        ]
        if len(rescues) > 1:
            rules.append(_rule(EntityKind.CATCH, "legacy_catch_clause", rescues[0]))
        return tuple(rules)
    return None


def _descendants(node: Node):
    for child in node.children:
        yield child
        yield from _descendants(child)


def _ancestors(node: Node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _first_implicit_rescue(method: Node) -> Node | None:
    for rescue in _descendants(method):
        if rescue.type != "rescue" or not rescue.named_children:
            continue
        explicit = any(
            ancestor.type == "rescue_modifier"
            or ancestor.type == "begin"
            and _text(ancestor).lstrip().startswith("begin")
            for ancestor in _ancestors(rescue)
        )
        if not explicit:
            return rescue
    return None


def _visit_call(node: Node) -> tuple[VisitRule, ...]:
    name = _call_name(node)
    if name in _REQUIRE_CALLS:
        value = _string_content(_first_argument(node))
        return (_rule(EntityKind.IMPORT, value),) if value is not None else ()
    if name in _ATTR_CALLS:
        args = next(
            (child for child in node.children if child.type == "argument_list"), None
        )
        return tuple(
            _rule(EntityKind.VARIABLE, _text(child).lstrip(":"))
            for child in (args.children if args else ())
            if child.type in {"simple_symbol", "hash_key_symbol"}
        )
    if name in {"raise", "fail"}:
        return (_rule(EntityKind.THROW, _text(_first_argument(node))),)
    rules = []
    argument = _first_argument(node)
    if (
        name in _MIXINS
        and argument is not None
        and argument.type in {"constant", "scope_resolution"}
    ):
        rules.append(_rule(EntityKind.IMPLEMENTS, _text(argument), argument))
    if _field(node, "receiver") is not None:
        rules.append(_rule(EntityKind.MEMBER_ACCESS, name))
    if name in _RESPONSES:
        rules.append(_rule(EntityKind.RESPONSE, name))
    if name in _HTTP_VERBS and any(
        child.type in {"do_block", "block"} for child in node.children
    ):
        path = _string_content(_first_argument(node))
        if path is not None:
            return (_rule(EntityKind.ROUTE, name),)
    rules.append(_rule(EntityKind.CALL, name))
    return tuple(rules)


def _function_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _type_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_function_name,
    type_name=_type_name,
    visit_node=_visit,
)
