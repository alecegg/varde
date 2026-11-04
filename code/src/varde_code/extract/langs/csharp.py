"""C# entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, strip_generic_args

BACKEND = "tree-sitter"
TYPE_SCOPES = frozenset(
    {
        "class_declaration",
        "interface_declaration",
        "record_declaration",
        "struct_declaration",
    }
)
FUNCTION_SCOPES = frozenset(
    {
        "method_declaration",
        "constructor_declaration",
        "local_function_statement",
        "accessor_declaration",
        "operator_declaration",
        "conversion_operator_declaration",
        "destructor_declaration",
        "property_declaration",
        "indexer_declaration",
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
FLOW_NAME_ROLES = {
    "switch_statement": "decision_container",
    "switch_expression": "decision_container",
    "pattern_logical_and": "else",
    "pattern_logical_or": "else",
}
_LITERALS = frozenset(
    {
        "integer_literal",
        "real_literal",
        "string_literal",
        "character_literal",
        "boolean_literal",
        "null_literal",
        "verbatim_string_literal",
    }
)
_TYPE_NODES = frozenset(
    {
        "predefined_type",
        "identifier",
        "qualified_name",
        "generic_name",
        "nullable_type",
        "array_type",
        "pointer_type",
        "tuple_type",
        "ref_type",
    }
)


def _field_name(node: Node) -> str:
    return _text(_field(node, "name"))


def _function_name(node: Node) -> str | None:
    kind = node.type
    if kind == "accessor_declaration":
        owner = (
            node.parent.parent
            if node.parent is not None and node.parent.parent is not None
            else None
        )
        owner_name = _field_name(owner) if owner is not None else ""
        if owner is not None and owner.type == "indexer_declaration":
            owner_name = "this"
        return (
            f"{owner_name}.{_field_name(node)}"
            if owner_name
            else _field_name(node) or None
        )
    if kind == "operator_declaration":
        operator = _field(node, "operator")
        return f"operator{_text(operator)}" if operator is not None else None
    if kind == "conversion_operator_declaration":
        modifier = next(
            (
                child
                for child in node.children
                if child.type in {"implicit", "explicit"}
            ),
            None,
        )
        ty = _field(node, "type")
        return (
            f"{_text(modifier)} operator {_text(ty)}"
            if modifier is not None and ty is not None
            else None
        )
    if kind in {"property_declaration", "indexer_declaration"}:
        return f"{_field_name(node) or 'this'}.get"
    return _field_name(node) or None


def _type_name(node: Node) -> str | None:
    return _field_name(node) or None


def _rule(kind: EntityKind, name: str, span_node: Node | None = None) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name, span_node=span_node)


def _walk(node: Node, kind: str) -> list[Node]:
    return [child for child in node.named_children if child.type == kind]


def _top_level(node: Node) -> bool:
    parent = node.parent
    return parent is not None and parent.type in {
        "compilation_unit",
        "namespace_declaration",
        "file_scoped_namespace_declaration",
    }


def _public(node: Node) -> bool:
    return any(
        child.type == "modifier" and _text(child).strip() == "public"
        for child in node.children
    )


def _export_rule(node: Node, name: str) -> tuple[VisitRule, ...]:
    return (
        (_rule(EntityKind.EXPORT, name),) if _top_level(node) and _public(node) else ()
    )


def _base_rules(node: Node, *, interface_only: bool = False) -> tuple[VisitRule, ...]:
    base = next(iter(_walk(node, "base_list")), None)
    if base is None:
        return ()
    types = list(base.named_children)
    result: list[VisitRule] = []
    for index, type_node in enumerate(types):
        name = strip_generic_args(_text(type_node))
        if interface_only:
            kind = EntityKind.EXTENDS
        elif index > 0 or (
            len(name) > 1 and name.startswith("I") and name[1].isupper()
        ):
            kind = EntityKind.IMPLEMENTS
        else:
            kind = EntityKind.EXTENDS
        result.append(
            VisitRule(kind, name_field=None, literal=name, span_node=type_node)
        )
    return tuple(result)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "using_directive":
        children = list(node.named_children)
        alias = _field(node, "name")
        target = next((child for child in children if child != alias), None)
        return (
            (_rule(EntityKind.IMPORT, _text(target).replace(".", "/")),)
            if target is not None
            else ()
        )
    if kind in FUNCTION_SCOPES and kind not in {
        "property_declaration",
        "indexer_declaration",
    }:
        if kind in {"property_declaration", "indexer_declaration"}:
            value = _field(node, "value")
            return (
                (
                    VisitRule(
                        EntityKind.FUNCTION,
                        name_field=None,
                        literal=_function_name(node) or "",
                    ),
                )
                if value is not None and value.type == "arrow_expression_clause"
                else ()
            )
        if kind == "accessor_declaration":
            body = _field(node, "body")
            return (
                (
                    VisitRule(
                        EntityKind.FUNCTION,
                        name_field=None,
                        literal=_function_name(node) or "",
                    ),
                )
                if body is not None
                and body.type in {"block", "arrow_expression_clause"}
                else ()
            )
        return (
            VisitRule(
                EntityKind.FUNCTION, name_field=None, literal=_function_name(node) or ""
            ),
        )
    if kind in {"property_declaration", "indexer_declaration"}:
        name = _field_name(node) or "this"
        ty = _field(node, "type")
        rules = [VisitRule(EntityKind.VARIABLE, literal=name)]
        if ty is not None:
            rules.append(
                VisitRule(
                    EntityKind.TYPE_REF,
                    name_field=None,
                    literal=strip_generic_args(_text(ty)),
                )
            )
        value = _field(node, "value")
        if value is not None and value.type == "arrow_expression_clause":
            rules.append(
                VisitRule(EntityKind.FUNCTION, name_field=None, literal=f"{name}.get")
            )
        return tuple(rules)
    if kind == "accessor_declaration":
        return ()
    if kind in {"class_declaration", "record_declaration"}:
        name = _field_name(node)
        return (
            VisitRule(EntityKind.CLASS, literal=name),
            *_export_rule(node, name),
            *_base_rules(node),
        )
    if kind == "interface_declaration":
        name = _field_name(node)
        return (
            VisitRule(EntityKind.INTERFACE, literal=name),
            *_export_rule(node, name),
            *_base_rules(node, interface_only=True),
        )
    if kind in {"struct_declaration", "enum_declaration"}:
        name = _field_name(node)
        rules = [VisitRule(EntityKind.CLASS, literal=name), *_export_rule(node, name)]
        if kind == "struct_declaration":
            rules.extend(_base_rules(node, interface_only=True))
        return tuple(rules)
    if kind in {"field_declaration", "local_declaration_statement"}:
        declaration = next(iter(_walk(node, "variable_declaration")), None)
        declarators = (
            _walk(declaration, "variable_declarator") if declaration is not None else []
        )
        rules: list[VisitRule] = []
        ty = _field(declaration, "type")
        for item in declarators:
            rules.append(VisitRule(EntityKind.VARIABLE, literal=_field_name(item)))
            if ty is not None:
                rules.append(
                    VisitRule(
                        EntityKind.TYPE_REF,
                        name_field=None,
                        literal=strip_generic_args(_text(ty)),
                    )
                )
        return tuple(rules)
    if kind == "parameter":
        ty = _field(node, "type")
        rules = [VisitRule(EntityKind.PARAMETER)]
        if ty is not None:
            rules.append(
                VisitRule(
                    EntityKind.TYPE_REF,
                    name_field=None,
                    literal=strip_generic_args(_text(ty)),
                )
            )
        return tuple(rules)
    if kind in {"lambda_expression", "anonymous_method_expression"}:
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind == "invocation_expression":
        callee = _field(node, "function")
        name = _text(callee)
        rules = [VisitRule(EntityKind.CALL, name_field="function")]
        if callee is not None and callee.type == "member_access_expression":
            method = _text(_field(callee, "name"))
            receiver = _text(_field(callee, "expression"))
            args = _field(node, "arguments")
            first_arg = (
                next(iter(args.named_children), None) if args is not None else None
            )
            first = (
                next(iter(first_arg.named_children), None)
                if first_arg is not None
                else None
            )
            if (
                receiver == "app"
                and method in {"MapGet", "MapPost", "MapPut", "MapDelete", "MapPatch"}
                and first is not None
                and "string_literal" in first.type
            ):
                rules.append(_rule(EntityKind.ROUTE, name))
            if receiver == "Results" and method in {"Ok", "Json"}:
                rules.append(_rule(EntityKind.RESPONSE, name))
        return tuple(rules)
    if kind == "object_creation_expression":
        return (VisitRule(EntityKind.CALL, name_field="type"),)
    if kind == "member_access_expression":
        return (VisitRule(EntityKind.MEMBER_ACCESS, name_field="name"),)
    if kind in _LITERALS:
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "catch_clause":
        declaration = next(iter(_walk(node, "catch_declaration")), None)
        return (
            _rule(
                EntityKind.CATCH,
                _field_name(declaration) if declaration is not None else "",
            ),
        )
    if kind == "throw_statement":
        value = next(
            (child for child in node.named_children if child.type not in {"throw"}),
            None,
        )
        return (_rule(EntityKind.THROW, _text(value)),)
    if kind == "if_statement":
        parent = node.parent
        is_else_if = (
            parent is not None
            and parent.type == "if_statement"
            and any(
                child.type == "else"
                for child in parent.children[: max(0, parent.children.index(node))]
            )
        )
        name = "elseif_statement" if is_else_if else "if_statement"
        consequence = _field(node, "consequence")
        rules = [
            VisitRule(
                EntityKind.CONTROL_FLOW,
                literal=name,
                span_start_node=node if consequence is not None else None,
                span_end_node=consequence if consequence is not None else None,
            )
        ]
        alternative = _field(node, "alternative")
        else_token = next(
            (child for child in node.children if child.type == "else"), None
        )
        if alternative is not None and else_token is not None:
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    literal="legacy_nesting",
                    span_start_node=else_token,
                    span_end_node=alternative,
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
        source = _text(node)
        rules = [
            VisitRule(EntityKind.CONTROL_FLOW, literal=name)
            for token, name in (("&&", "logical_and"), ("||", "logical_or"))
            if token in source
        ]
        return tuple(rules) or None
    if kind in {"switch_section", "switch_expression_arm"}:
        return tuple(
            _rule(EntityKind.CONTROL_FLOW, "case_statement")
            for _ in range(
                max(1, sum(c.type in {"case", "default"} for c in node.children))
            )
        )
    if kind in {"when_clause", "catch_filter_clause"}:
        return (_rule(EntityKind.CONTROL_FLOW, "guard_clause"),)
    if kind == "goto_statement":
        return (_rule(EntityKind.CONTROL_FLOW, "goto_jump"),)
    if kind in {
        "return_statement",
        "break_statement",
        "continue_statement",
        "try_statement",
        "switch_statement",
        "switch_expression",
        "for_statement",
        "foreach_statement",
        "while_statement",
        "conditional_expression",
    }:
        return (_rule(EntityKind.CONTROL_FLOW, kind),)
    if kind == "do_statement":
        return (_rule(EntityKind.CONTROL_FLOW, "do_while_statement"),)
    if kind in {"and_pattern", "or_pattern"}:
        if node.parent is not None and node.parent.type == kind:
            return ()
        return (
            _rule(
                EntityKind.CONTROL_FLOW,
                "pattern_logical_and"
                if kind == "and_pattern"
                else "pattern_logical_or",
            ),
        )
    if (
        kind == "prefix_unary_expression"
        and _text(node).lstrip().startswith("!")
        and ("&&" in _text(node) or "||" in _text(node))
    ):
        return (_rule(EntityKind.CONTROL_FLOW, "negation_break"),)
    if kind == "attribute_list":
        rules = []
        for attribute in _walk(node, "attribute"):
            rules.append(_rule(EntityKind.DECORATOR, _field_name(attribute)))
        return tuple(rules)
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    type_kinds=_TYPE_NODES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_function_name,
    type_name=_type_name,
    visit_node=_visit,
)
