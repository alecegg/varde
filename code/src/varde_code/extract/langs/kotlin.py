"""Kotlin entity rules for the tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text, strip_generic_args

BACKEND = "tree-sitter"
TYPE_SCOPES = frozenset(
    {"class_declaration", "object_declaration", "companion_object", "object_literal"}
)
FUNCTION_SCOPES = frozenset({"function_declaration", "getter", "setter"})
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


def _rule(kind: EntityKind, name: str) -> VisitRule:
    return VisitRule(kind, name_field=None, literal=name)


def _first(
    node: Node, kinds: tuple[str, ...] = ("simple_identifier", "type_identifier")
) -> Node | None:
    return next((child for child in node.named_children if child.type in kinds), None)


def _name(node: Node) -> str | None:
    return _text(_first(node)) or None


def _type_name(node: Node) -> str | None:
    return (
        _name(node) or "Companion" if node.type == "companion_object" else _name(node)
    )


def _is_public_top_level(node: Node) -> bool:
    parent = node.parent
    if parent is None or parent.type != "source_file":
        return False
    modifiers = next(
        (child for child in node.named_children if child.type == "modifiers"), None
    )
    return modifiers is not None and "public" in _text(modifiers)


def _inside_type(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type in {
            "user_type",
            "type_identifier",
            "function_type",
            "nullable_type",
        }:
            return True
        parent = parent.parent
    return False


def _callee(node: Node) -> str:
    callee = node.named_children[0] if node.named_children else None
    return _text(callee)


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import_header":
        path = (
            _text(node)
            .strip()
            .removeprefix("import")
            .strip()
            .split(" as ", 1)[0]
            .removesuffix(".*")
        )
        return (_rule(EntityKind.IMPORT, path.replace(".", "/")),)
    if kind == "function_declaration":
        name = _name(node) or ""
        rules = [VisitRule(EntityKind.FUNCTION, literal=name)]
        if _is_public_top_level(node):
            rules.append(_rule(EntityKind.EXPORT, name))
        return tuple(rules)
    if kind in {"getter", "setter"}:
        parent = node.parent
        variable = (
            next(
                (c for c in parent.named_children if c.type == "variable_declaration"),
                None,
            )
            if parent
            else None
        )
        return (
            VisitRule(
                EntityKind.FUNCTION,
                literal=f"{_name(variable) if variable is not None else ''}.{kind[:3]}",
            ),
        )
    if kind in {"class_declaration", "object_declaration", "companion_object"}:
        name = _name(node) or ("Companion" if kind == "companion_object" else "")
        is_interface = kind == "class_declaration" and _text(
            node
        ).lstrip().removeprefix(
            _text(next((c for c in node.named_children if c.type == "modifiers"), None))
        ).lstrip().startswith(("interface", "fun interface"))
        rules = (
            [_rule(EntityKind.INTERFACE if is_interface else EntityKind.CLASS, name)]
            if name
            else []
        )
        if name and _is_public_top_level(node):
            rules.append(_rule(EntityKind.EXPORT, name))
        for spec in (
            c for c in node.named_children if c.type == "delegation_specifier"
        ):
            target = spec.named_children[0] if spec.named_children else None
            if target is not None:
                ref = (
                    target.named_children[0]
                    if target.type == "constructor_invocation" and target.named_children
                    else target
                )
                rules.append(
                    VisitRule(
                        EntityKind.EXTENDS
                        if target.type == "constructor_invocation"
                        else EntityKind.IMPLEMENTS,
                        name_field=None,
                        literal=strip_generic_args(_text(ref)),
                        span_node=ref,
                    )
                )
        return tuple(rules)
    if kind == "object_literal":
        row, column = node.start_point
        return (_rule(EntityKind.CLASS, f"<anonymous@{row + 1}:{column}>"),)
    if kind == "property_declaration":
        var = next(
            (c for c in node.named_children if c.type == "variable_declaration"), None
        )
        name = _name(var) if var else None
        if name and _is_public_top_level(node):
            return (_rule(EntityKind.EXPORT, name),)
    if kind == "variable_declaration":
        name = _name(node)
        return (_rule(EntityKind.VARIABLE, name),) if name and name != "_" else ()
    if kind == "parameter":
        name = _name(node)
        return (_rule(EntityKind.PARAMETER, name),) if name else ()
    if kind in {"lambda_literal", "anonymous_function"}:
        return (_rule(EntityKind.CALLABLE_BOUNDARY, ""),)
    if kind == "call_expression":
        callee = _callee(node)
        name = callee.rsplit(".", 1)[-1]
        rules = [_rule(EntityKind.CALL, callee)]
        if name in {
            "GetMapping",
            "PostMapping",
            "PutMapping",
            "DeleteMapping",
            "PatchMapping",
        }:
            rules.append(_rule(EntityKind.ROUTE, callee))
        if name in {
            "respond",
            "respondText",
            "respondBytes",
            "respondTextBytes",
        } and callee.startswith("call."):
            rules.append(_rule(EntityKind.RESPONSE, callee))
        return tuple(rules)
    if kind == "navigation_expression":
        suffix = next(
            (c for c in node.named_children if c.type == "navigation_suffix"), None
        )
        member = (
            next(
                (c for c in suffix.named_children if c.type == "simple_identifier"),
                None,
            )
            if suffix
            else None
        )
        return (_rule(EntityKind.MEMBER_ACCESS, _text(member)),) if member else ()
    if kind in {
        "integer_literal",
        "real_literal",
        "string_literal",
        "boolean_literal",
        "null_literal",
        "character_literal",
    } and not _inside_type(node):
        return (_rule(EntityKind.LITERAL, _text(node)),)
    if kind == "catch_block":
        return (_rule(EntityKind.CATCH, _text(_first(node)) or ""),)
    if kind == "jump_expression":
        text = _text(node).strip()
        if text.startswith("throw"):
            return (_rule(EntityKind.THROW, text.removeprefix("throw").strip()),)
        keyword = next(
            (k for k in ("return", "break", "continue") if text.startswith(k)),
            "jump_expression",
        )
        name = {
            "return": "return_statement",
            "break": "break_statement",
            "continue": "continue_statement",
        }.get(keyword, keyword)
        rules = [_rule(EntityKind.CONTROL_FLOW, name)]
        if text.startswith(("break@", "continue@")):
            rules.append(_rule(EntityKind.CONTROL_FLOW, "labeled_jump"))
        return tuple(rules)
    if kind == "if_expression":
        parent = node.parent
        is_else_if = (
            parent is not None
            and parent.type == "control_structure_body"
            and parent.parent is not None
            and parent.parent.type == "if_expression"
            and _field(parent.parent, "alternative") == parent
        )
        rules = [
            _rule(
                EntityKind.CONTROL_FLOW,
                "elseif_statement" if is_else_if else "if_expression",
            )
        ]
        alternative = _field(node, "alternative")
        if alternative is not None and "if_expression" not in [
            c.type for c in alternative.named_children
        ]:
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    literal="else_branch",
                    span_node=alternative,
                )
            )
        return tuple(rules)
    if kind in {
        "when_expression",
        "for_statement",
        "while_statement",
        "do_while_statement",
        "try_expression",
        "when_entry",
        "conjunction_expression",
        "disjunction_expression",
    }:
        return (
            _rule(
                EntityKind.CONTROL_FLOW,
                {
                    "when_entry": "match_arm",
                    "conjunction_expression": "logical_and",
                    "disjunction_expression": "logical_or",
                }.get(kind, kind),
            ),
        )
    if kind == "annotation":
        stack = list(node.children)
        ident = None
        while stack and ident is None:
            current = stack.pop(0)
            if current.type in {"type_identifier", "simple_identifier"}:
                ident = current
            else:
                stack[0:0] = list(current.children)
        name = _text(ident)
        return (_rule(EntityKind.DECORATOR, name),) if name else ()
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    type_kinds=frozenset(
        {"user_type", "type_identifier", "function_type", "nullable_type"}
    ),
    function_name=_name,
    type_name=_type_name,
    visit_node=_visit,
)
