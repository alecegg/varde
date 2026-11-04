"""Rust entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset(
    {"function_item", "function_signature_item", "closure_expression"}
)
TYPE_SCOPES = frozenset({"impl_item", "trait_item"})
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
)
TYPE_KINDS = frozenset(
    {
        "primitive_type",
        "generic_type",
        "generic_type_with_turbofish",
        "array_type",
        "tuple_type",
        "reference_type",
        "pointer_type",
        "function_type",
        "unit_type",
        "scoped_type_identifier",
        "type_identifier",
        "type_arguments",
        "type_parameters",
        "lifetime",
    }
)
FLOW_NAME_ROLES = {
    "match_expression": "decision_container",
    "legacy_nesting": "legacy_nesting",
}


def _named(node: Node) -> list[Node]:
    return list(node.named_children)


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _pattern_names(node: Node) -> list[str]:
    kind = node.type
    if kind in {"identifier", "shorthand_field_identifier"}:
        name = _text(node)
        return [] if name == "_" else [name]
    children = _named(node)
    type_node = (
        _field(node, "type")
        if kind in {"tuple_struct_pattern", "struct_pattern"}
        else None
    )
    return [
        name
        for child in children
        if child != type_node
        for name in _pattern_names(child)
    ]


def _inline_modules(node: Node) -> list[str]:
    modules = [
        _text(_field(ancestor, "name"))
        for ancestor in _ancestors(node)
        if ancestor.type == "mod_item" and _field(ancestor, "body") is not None
    ]
    return list(reversed(modules))


def _file_relative_use_path(path: str, inline: list[str]) -> str:
    if not inline:
        return path
    parts = path.split("::")
    depth = len(inline)
    if parts[0] == "self":
        parts = parts[1:]
    elif parts[0] == "super":
        while parts and parts[0] == "super" and depth:
            depth -= 1
            parts = parts[1:]
    else:
        return path
    prefix = [] if parts and parts[0] == "super" else ["self", *inline[:depth]]
    return "::".join(prefix + parts)


def _use_path(node: Node) -> str:
    child = next(
        (
            item
            for item in _named(node)
            if item.type
            in {
                "scoped_identifier",
                "scoped_use_list",
                "use_list",
                "identifier",
                "use_as_clause",
                "use_wildcard",
            }
        ),
        None,
    )
    if child is None:
        return _text(node)
    if child.type == "scoped_use_list":
        return _text(
            next(
                (part for part in _named(child) if part.type == "scoped_identifier"),
                None,
            )
        )
    if child.type == "use_list":
        return ""
    if child.type == "use_as_clause":
        return _text(next(iter(_named(child)), None))
    return _text(child)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind in {"function_item", "function_signature_item"}:
        return (_rule(EntityKind.FUNCTION, _text(_field(node, "name"))),) + _export(
            node
        )
    if kind == "closure_expression":
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind in {"struct_item", "enum_item"}:
        return (_rule(EntityKind.CLASS, _text(_field(node, "name"))),) + _export(node)
    if kind == "trait_item":
        return (_rule(EntityKind.INTERFACE, _text(_field(node, "name"))),) + _export(
            node
        )
    if kind == "const_item":
        return _export(node)
    if kind == "impl_item":
        trait = _field(node, "trait")
        target = _field(node, "type")
        return (
            (_rule(EntityKind.IMPLEMENTS, _type_name(trait)),)
            if trait is not None and target is not None
            else ()
        )
    if kind == "mod_item":
        if _field(node, "body") is not None:
            return ()
        name = _text(_field(node, "name"))
        return (_rule(EntityKind.IMPORT, f"mod {name}"),)
    if kind == "use_declaration":
        path = _file_relative_use_path(_use_path(node), _inline_modules(node))
        return (_rule(EntityKind.IMPORT, path),) if path else ()
    if kind == "let_declaration":
        pattern = _field(node, "pattern")
        rules = (
            tuple(_rule(EntityKind.VARIABLE, name) for name in _pattern_names(pattern))
            if pattern
            else ()
        )
        alternative = _field(node, "alternative")
        return rules + (
            (_rule(EntityKind.CONTROL_FLOW, "else_branch"),) if alternative else ()
        )
    if kind == "parameters":
        result = []
        for child in _named(node):
            if child.type == "parameter":
                pattern = _field(child, "pattern")
                if pattern:
                    result.extend(
                        _rule(EntityKind.PARAMETER, name)
                        for name in _pattern_names(pattern)
                    )
            elif child.type == "self_parameter":
                result.append(_rule(EntityKind.PARAMETER, "self"))
        return tuple(result)
    if kind == "call_expression":
        return (_rule(EntityKind.CALL, _text(_field(node, "function"))),)
    if kind == "field_expression":
        return (_rule(EntityKind.MEMBER_ACCESS, _text(_field(node, "field"))),)
    if kind in {
        "integer_literal",
        "float_literal",
        "string_literal",
        "char_literal",
        "boolean_literal",
        "raw_string_literal",
    }:
        if any(ancestor.type in TYPE_KINDS for ancestor in _ancestors(node)):
            return ()
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "macro_invocation":
        macro = _field(node, "macro")
        if macro is not None and _text(macro) == "panic":
            token_tree = next(
                (child for child in _named(node) if child.type == "token_tree"), None
            )
            arg = (
                next(
                    (
                        child
                        for child in _named(token_tree)
                        if child.type not in {",", "(", ")"}
                    ),
                    None,
                )
                if token_tree
                else None
            )
            return (_rule(EntityKind.THROW, _text(arg)),)
        return ()
    controls = {
        "for_expression",
        "while_expression",
        "loop_expression",
        "match_expression",
        "match_arm",
        "return_expression",
        "break_expression",
        "continue_expression",
        "if_expression",
        "else_clause",
    }
    if kind in controls:
        if kind == "else_clause" and any(
            child.type == "if_expression" for child in _named(node)
        ):
            return ()
        name = kind
        if (
            kind == "if_expression"
            and node.parent is not None
            and node.parent.type == "else_clause"
        ):
            name = "elseif_statement"
        elif (
            kind == "break_expression"
            and any(child.type == "label" for child in node.children)
            or kind == "continue_expression"
            and any(child.type == "label" for child in node.children)
        ):
            name = "labeled_jump"
        elif kind == "else_clause":
            name = "else_branch"
        rules = [_rule(EntityKind.CONTROL_FLOW, name)]
        if kind == "if_expression":
            consequence = _field(node, "consequence")
            if name == "elseif_statement":
                rules.append(
                    VisitRule(
                        EntityKind.CONTROL_FLOW,
                        name_field=None,
                        literal="legacy_nesting",
                        span_node=consequence,
                    )
                )
            elif any(child.type == "else_clause" for child in _named(node)):
                alternative = next(
                    (child for child in _named(node) if child.type == "else_clause"),
                    None,
                )
                rules.append(
                    VisitRule(
                        EntityKind.CONTROL_FLOW,
                        name_field=None,
                        literal="legacy_nesting",
                        span_node=alternative,
                    )
                )
            rules[0] = VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal=name,
                span_node=consequence,
            )
        return tuple(rules)
    if kind == "binary_expression":
        operator = _binary_operator(node)
        if operator is not None:
            return (_rule(EntityKind.CONTROL_FLOW, operator),)
    if (
        kind == "unary_expression"
        and _text(node).lstrip().startswith("!")
        and any(
            child.type == "binary_expression"
            and ("&&" in _text(child) or "||" in _text(child))
            for child in _descendants(node)
        )
    ):
        return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    return None


def _binary_operator(node: Node) -> str | None:
    operator = _field(node, "operator")
    if operator is not None:
        value = _text(operator)
    else:
        value = next(
            (_text(child) for child in node.children if _text(child) in {"&&", "||"}),
            "",
        )
    return {"&&": "logical_and", "||": "logical_or"}.get(value)


def _export(node: Node) -> tuple[VisitRule, ...]:
    if (
        node.parent is not None
        and node.parent.type == "source_file"
        and any(child.type == "visibility_modifier" for child in node.children)
    ):
        return (_rule(EntityKind.EXPORT, _text(_field(node, "name"))),)
    return ()


def _type_name(node: Node | None) -> str:
    if node is None:
        return ""
    if node.type == "generic_type":
        return _text(_field(node, "type")) or _text(node)
    return _text(node)


def _function_name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _type_scope_name(node: Node) -> str | None:
    return (
        _type_name(_field(node, "type"))
        if node.type == "impl_item"
        else (_text(_field(node, "name")) or None)
    )


def _ancestors(node: Node):
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def _descendants(node: Node):
    pending = list(node.children)
    while pending:
        child = pending.pop()
        yield child
        pending.extend(child.children)


def _preceding_attributes(node: Node) -> list[str]:
    attributes = []
    sibling = node.prev_sibling
    while sibling is not None and sibling.type in {
        "attribute_item",
        "line_comment",
        "block_comment",
    }:
        if sibling.type == "attribute_item":
            attributes.append(_text(sibling))
        sibling = sibling.prev_sibling
    return attributes


def _attribute_names_test(attribute: str) -> bool:
    value = "".join(attribute.split())
    inner = value.removeprefix("#").removeprefix("[").removesuffix("]")
    path = inner.split("(", 1)[0].split("=", 1)[0]
    return path.rsplit("::", 1)[-1] == "test" or path == "rstest"


def _attribute_enables_test_module(attribute: str) -> bool:
    return "".join(attribute.split()) == "#[cfg(test)]"


def _node_is_test(node: Node) -> bool:
    if any(_attribute_names_test(item) for item in _preceding_attributes(node)):
        return True
    return any(
        any(
            _attribute_enables_test_module(attribute)
            or _attribute_names_test(attribute)
            for attribute in _preceding_attributes(ancestor)
        )
        for ancestor in _ancestors(node)
    )


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    type_kinds=TYPE_KINDS,
    test_node=_node_is_test,
    function_name=_function_name,
    type_name=_type_scope_name,
    visit_node=_visit,
)
