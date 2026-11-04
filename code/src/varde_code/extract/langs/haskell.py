"""Entity rules for Haskell's tree-sitter grammar."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import EntityKind

from .base import LanguageTables, VisitRule, _field, _text

BACKEND = "tree-sitter"
FUNCTION_SCOPES = frozenset({"function", "bind"})
TYPE_SCOPES = frozenset({"data_type", "newtype", "type_synonym", "class"})
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
    EntityKind.IMPORT,
)
FLOW_NAME_ROLES: dict[str, str] = {}

_THROWS = frozenset({"error", "throw", "throwIO", "ioError", "errorWithoutStackTrace"})
_CATCHES = frozenset({"catch", "handle", "try"})
_LITERALS = frozenset({"integer", "float", "string", "char"})


def _name(node: Node) -> str | None:
    return _text(_field(node, "name")) or None


def _qualified_member(node: Node) -> str:
    for child in reversed(node.named_children):
        if child.type in {"variable", "constructor", "operator"}:
            return _text(child)
    return ""


def _apply_head(node: Node) -> Node | None:
    head = _field(node, "function")
    while head is not None and head.type == "apply":
        head = _field(head, "function")
    return head


def _callee_name(head: Node | None) -> str:
    if head is None:
        return ""
    if head.type == "qualified":
        return _qualified_member(head)
    return _text(head)


def _pattern_names(node: Node) -> tuple[str, ...]:
    names: list[str] = []

    def visit(current: Node) -> None:
        if current.type == "variable":
            value = _text(current)
            if value and value != "_":
                names.append(value)
            return
        for child in current.named_children:
            visit(child)

    for child in node.named_children:
        visit(child)
    return tuple(names)


def _import_name(node: Node) -> str:
    module = _field(node, "module")
    return _text(module).strip().replace(".", "/")


def _has_descendant(node: Node, kind: str) -> bool:
    return any(
        child.type == kind or _has_descendant(child, kind)
        for child in node.named_children
    )


def _sibling_function_clause(node: Node, name: str) -> bool:
    parent = node.parent
    return parent is not None and any(
        sibling != node and sibling.type == "function" and _name(sibling) == name
        for sibling in parent.named_children
    )


def _enclosing_binding_name(node: Node) -> str | None:
    parent = node.parent
    while parent is not None:
        if parent.type in {"function", "bind"}:
            return _name(parent)
        parent = parent.parent
    return None


def _visit(node: Node) -> tuple[VisitRule, ...] | None:
    kind = node.type
    if kind == "import":
        name = _import_name(node)
        return (
            (VisitRule(EntityKind.IMPORT, name_field=None, literal=name),)
            if name
            else ()
        )
    if kind == "export":
        return (VisitRule(EntityKind.EXPORT, name_field=None, literal=_text(node)),)
    if kind == "function":
        if _field(node, "patterns") is None:
            return None
        name = _name(node) or ""
        rules = [VisitRule(EntityKind.FUNCTION)]
        if _sibling_function_clause(node, name):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="haskell_multi_clause_grouping",
                )
            )
        if any(
            match.child_by_field_name("guards") is not None
            for match in node.children_by_field_name("match")
        ):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="haskell_guard_container",
                )
            )
        return tuple(rules)
    if kind == "bind":
        return (VisitRule(EntityKind.VARIABLE),) if _name(node) else None
    if kind in {"data_type", "newtype", "type_synonym"}:
        return (VisitRule(EntityKind.CLASS),) if _name(node) else None
    if kind in {"type_family", "data_family"}:
        return (VisitRule(EntityKind.INTERFACE),) if _name(node) else None
    if kind == "class":
        return (VisitRule(EntityKind.INTERFACE),) if _name(node) else None
    if kind == "instance":
        name = _name(node) or ""
        return (VisitRule(EntityKind.IMPLEMENTS, name_field=None, literal=name),)
    if kind == "patterns":
        return tuple(
            VisitRule(EntityKind.PARAMETER, name_field=None, literal=name)
            for name in _pattern_names(node)
        )
    if kind == "lambda":
        return (VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),)
    if kind in {"lambda_case", "lambda_cases"}:
        return (
            VisitRule(EntityKind.CALLABLE_BOUNDARY, name_field=None, literal=""),
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="case"),
        )
    if kind == "apply":
        head = _apply_head(node)
        name = _callee_name(head)
        if not name:
            return None
        if name in _THROWS:
            return (VisitRule(EntityKind.THROW, name_field=None, literal=name),)
        if name in _CATCHES:
            parent = node.parent
            if (
                parent is not None
                and parent.type == "apply"
                and _field(parent, "function") == node
            ):
                return ()
            return (VisitRule(EntityKind.CATCH, name_field=None, literal=name),)
        rules: list[VisitRule] = []
        if name == _enclosing_binding_name(node):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW, name_field=None, literal="recursive_call"
                )
            )
        if head is not None and head.type == "qualified":
            rules.append(
                VisitRule(
                    EntityKind.MEMBER_ACCESS,
                    name_field=None,
                    literal=_qualified_member(head),
                )
            )
        rules.append(VisitRule(EntityKind.CALL, name_field=None, literal=name))
        return tuple(rules)
    if kind == "qualified":
        parent = node.parent
        if (
            parent is not None
            and parent.type == "apply"
            and _field(parent, "function") == node
        ):
            return ()
        if (
            parent is not None
            and parent.type == "apply"
            and _field(parent, "argument") == node
        ):
            return None
        member = _qualified_member(node)
        return (
            (VisitRule(EntityKind.MEMBER_ACCESS, name_field=None, literal=member),)
            if member
            else None
        )
    if kind in _LITERALS:
        return (VisitRule(EntityKind.LITERAL, name_field=None, literal=_text(node)),)
    if kind == "conditional":
        else_arm = _field(node, "else")
        then_arm = _field(node, "then")
        is_else_if = (
            node.parent is not None
            and node.parent.type == "conditional"
            and _field(node.parent, "else") == node
        )
        rules: list[VisitRule] = []
        if is_else_if or (else_arm is not None and else_arm.type == "conditional"):
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="legacy_nesting",
                )
            )
        name = "elseif_statement" if is_else_if else "conditional"
        rules.append(
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal=name,
                span_start_node=node,
                span_end_node=then_arm,
            )
        )
        if else_arm is not None and else_arm.type != "conditional":
            rules.append(
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="else_branch",
                    span_node=else_arm,
                )
            )
        return tuple(rules)
    if kind == "case":
        name = "case" if _has_descendant(node, "alternative") else "case_inner"
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal=name),)
    if kind == "let_in":
        return (VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="let_in"),)
    if kind == "alternative":
        return (
            VisitRule(EntityKind.CONTROL_FLOW, name_field=None, literal="case_item"),
        )
    if kind == "guards":
        guards = tuple(
            VisitRule(
                EntityKind.CONTROL_FLOW,
                name_field=None,
                literal="cognitive_decision",
                span_node=guard,
            )
            for guard in node.children_by_field_name("guard")
        )
        return guards + tuple(
            VisitRule(
                EntityKind.CONTROL_FLOW, name_field=None, literal="haskell_guard_legacy"
            )
            for _ in range(max(0, len(guards) - 1))
        )
    if kind == "infix":
        operator = _text(_field(node, "operator"))
        if operator in {"&&", "||", "and", "or"}:
            return (
                VisitRule(
                    EntityKind.CONTROL_FLOW,
                    name_field=None,
                    literal="logical_and"
                    if operator in {"&&", "and"}
                    else "logical_or",
                ),
            )
    return None


LANG = LanguageTables(
    function_scopes=FUNCTION_SCOPES,
    type_scopes=TYPE_SCOPES,
    required_kinds=REQUIRED_KINDS,
    flow_roles=FLOW_NAME_ROLES,
    function_name=_name,
    type_name=_name,
    visit_node=_visit,
)
