"""Resolve recursive call relationships among same-file callables."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from tree_sitter import Node

from varde_code.model import Entity, EntityKind, Span, span_of


class Qualifier(Enum):
    NONE = 0
    SELF_LIKE = 1
    NAMED_TYPE = 2
    OTHER = 3


@dataclass(frozen=True)
class Callable:
    owner: str | None
    name: str
    required_args: int
    total_args: int
    file_id: int
    span: Span
    name_span: Span
    owner_type: str | None = None
    unqualified_callable: bool = False


@dataclass(frozen=True)
class CalleeReference:
    caller: int
    name: str
    argument_count: int
    qualifier: Qualifier = Qualifier.NONE
    qualifier_name: str | None = None


def extract_python(root: Node, file_id: int = 0) -> list[Entity]:
    """Find same-file recursive calls in Python function definitions."""
    callables, callable_ids = _python_callables(root, file_id)
    references = _python_references(root, callable_ids)
    return resolve(callables, references)


def extract_rust(root: Node, file_id: int = 0) -> list[Entity]:
    """Find Rust's same-file recursive function cycles."""
    declarations = [node for node in _walk(root) if node.type == "function_item"]
    callables = [
        callable_value
        for node in declarations
        if (callable_value := _rust_callable(node, file_id)) is not None
    ]
    callable_ids = {
        (callable_value.span.start_byte, callable_value.span.end_byte): index
        for index, callable_value in enumerate(callables)
    }
    references = _rust_references(root, callables, callable_ids)
    return resolve(callables, references)


def _rust_callable(node: Node, file_id: int) -> Callable | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    parameters = node.child_by_field_name("parameters")
    argument_count = (
        sum(child.type == "parameter" for child in parameters.children)
        if parameters is not None
        else 0
    )
    owner_type = next(
        (
            _rust_type_scope_name(parent)
            for parent in _ancestors(node)
            if parent.type in {"impl_item", "trait_item"}
        ),
        None,
    )
    lexical_scope = next(
        (
            parent
            for parent in _ancestors(node)
            if parent.type in {"function_item", "impl_item", "trait_item"}
        ),
        None,
    )
    if lexical_scope is not None and lexical_scope.type == "function_item":
        owner = _node_text(lexical_scope.child_by_field_name("name"))
        unqualified_callable = True
    elif lexical_scope is not None:
        owner = _rust_type_scope_name(lexical_scope)
        unqualified_callable = False
    else:
        owner = None
        unqualified_callable = True
    return Callable(
        owner=owner,
        name=_node_text(name_node),
        required_args=argument_count,
        total_args=argument_count,
        file_id=file_id,
        span=span_of(node),
        name_span=span_of(name_node),
        owner_type=owner_type,
        unqualified_callable=unqualified_callable,
    )


def _rust_type_scope_name(node: Node) -> str | None:
    name = (
        node.child_by_field_name("type")
        if node.type == "impl_item"
        else node.child_by_field_name("name")
    )
    if name is None:
        return None
    if node.type == "impl_item" and name.type == "generic_type":
        name = name.child_by_field_name("type") or name
    return _node_text(name) or None


def _rust_references(
    root: Node,
    callables: list[Callable],
    callable_ids: dict[tuple[int, int], int],
) -> list[CalleeReference]:
    references = []
    for call in (node for node in _walk(root) if node.type == "call_expression"):
        caller_node = next(
            (parent for parent in _ancestors(call) if parent.type == "function_item"),
            None,
        )
        if caller_node is None:
            continue
        caller_span = span_of(caller_node)
        caller = callable_ids.get((caller_span.start_byte, caller_span.end_byte))
        function = call.child_by_field_name("function")
        if caller is None or function is None:
            continue
        callee = _rust_callee_reference(function, callables[caller].owner)
        if callee is None:
            continue
        name, qualifier, qualifier_name = callee
        arguments = call.child_by_field_name("arguments")
        argument_count = (
            sum(child.is_named for child in arguments.children)
            if arguments is not None
            else 0
        )
        references.append(
            CalleeReference(
                caller,
                name,
                argument_count,
                qualifier,
                qualifier_name,
            )
        )
    return references


def _rust_callee_reference(
    function: Node,
    caller_owner: str | None,
) -> tuple[str, Qualifier, str | None] | None:
    if function.type == "identifier":
        return _node_text(function), Qualifier.NONE, None
    if function.type == "generic_function":
        name_node = function.child_by_field_name("function")
        return _node_text(name_node or function), Qualifier.NONE, None
    if function.type == "field_expression":
        method = function.child_by_field_name("field")
        receiver = function.child_by_field_name("value")
        if method is None or receiver is None:
            return None
        receiver_name = _node_text(receiver)
        if receiver_name == "self":
            return _node_text(method), Qualifier.SELF_LIKE, None
        if caller_owner == receiver_name:
            return _node_text(method), Qualifier.NAMED_TYPE, receiver_name
        return _node_text(method), Qualifier.OTHER, None
    if function.type == "scoped_identifier":
        path = _node_text(function)
        if "::" not in path:
            return None
        owner, name = path.rsplit("::", 1)
        if owner == "Self":
            return name, Qualifier.SELF_LIKE, None
        if caller_owner == owner:
            return name, Qualifier.NAMED_TYPE, owner
        return name, Qualifier.OTHER, None
    return None


def _python_callables(
    root: Node, file_id: int
) -> tuple[list[Callable], dict[tuple[int, int], int]]:
    declarations = [node for node in _walk(root) if node.type == "function_definition"]
    callables = []
    callable_ids = {}
    for node in declarations:
        callable_value = _python_callable(node, file_id)
        if callable_value is None:
            continue
        node_span = callable_value.span
        callable_ids[(node_span.start_byte, node_span.end_byte)] = len(callables)
        callables.append(callable_value)
    return callables, callable_ids


def _python_callable(node: Node, file_id: int) -> Callable | None:
    name_node = node.child_by_field_name("name")
    if name_node is None:
        return None
    name = _node_text(name_node)
    parameters = node.child_by_field_name("parameters")
    parameter_nodes = (
        [child for child in parameters.children if _is_python_parameter(child.type)]
        if parameters is not None
        else []
    )
    lexical_parent = next(
        (
            _node_text(parent.child_by_field_name("name"))
            for parent in _ancestors(node)
            if parent.type == "function_definition"
            and parent.child_by_field_name("name") is not None
        ),
        None,
    )
    owner_type = _enclosing_python_type(node)
    callable_parameters = parameter_nodes
    if lexical_parent is None and owner_type is not None:
        first_name = (
            _python_parameter_name(callable_parameters[0])
            if callable_parameters
            else None
        )
        if first_name in {"self", "cls"}:
            callable_parameters = callable_parameters[1:]
    return Callable(
        owner=lexical_parent or owner_type,
        name=name,
        required_args=sum(
            "default" not in parameter.type for parameter in callable_parameters
        ),
        total_args=len(callable_parameters),
        file_id=file_id,
        span=span_of(node),
        name_span=span_of(name_node),
        owner_type=owner_type,
        unqualified_callable=lexical_parent is not None or owner_type is None,
    )


def _python_references(
    root: Node, callable_ids: dict[tuple[int, int], int]
) -> list[CalleeReference]:
    references = []
    for call in (node for node in _walk(root) if node.type == "call"):
        reference = _python_callee_reference(call, callable_ids)
        if reference is not None:
            references.append(reference)
    return references


def _python_callee_reference(
    call: Node,
    callable_ids: dict[tuple[int, int], int],
) -> CalleeReference | None:
    caller_node = next(
        (parent for parent in _ancestors(call) if parent.type == "function_definition"),
        None,
    )
    if caller_node is None:
        return None
    caller_span = span_of(caller_node)
    caller = callable_ids.get((caller_span.start_byte, caller_span.end_byte))
    if caller is None:
        return None
    function = call.child_by_field_name("function")
    if function is None:
        return None
    name, qualifier = _python_callee_name(function)
    if name is None:
        return None
    arguments = call.child_by_field_name("arguments")
    argument_count = (
        sum(child.is_named and child.type != "comment" for child in arguments.children)
        if arguments is not None
        else 0
    )
    return CalleeReference(caller, name, argument_count, qualifier)


def _python_callee_name(function: Node) -> tuple[str | None, Qualifier]:
    if function.type == "identifier":
        return _node_text(function), Qualifier.NONE
    if function.type != "attribute":
        return None, Qualifier.NONE
    method = function.child_by_field_name("attribute")
    receiver = function.child_by_field_name("object")
    if method is None or receiver is None:
        return None, Qualifier.NONE
    qualifier = (
        Qualifier.SELF_LIKE
        if _node_text(receiver) in {"self", "cls"}
        else Qualifier.OTHER
    )
    return _node_text(method), qualifier


def _is_python_parameter(kind: str) -> bool:
    return kind in {
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
    }


def _walk(root: Node):
    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(node.children))


def _ancestors(node: Node):
    parent = node.parent
    while parent is not None:
        yield parent
        parent = parent.parent


def _node_text(node: Node | None) -> str:
    if node is None:
        return ""
    value = node.text
    return (
        value.decode("utf-8", errors="replace")
        if isinstance(value, bytes)
        else str(value)
    )


def _python_parameter_name(node: Node) -> str | None:
    if node.type == "identifier":
        return _node_text(node)
    name = node.child_by_field_name("name")
    if name is None:
        name = next(
            (child for child in node.children if child.type == "identifier"), None
        )
    return _node_text(name) if name is not None else None


def _enclosing_python_type(node: Node) -> str | None:
    for parent in _ancestors(node):
        if parent.type != "class_definition":
            continue
        name = parent.child_by_field_name("name")
        return _node_text(name) if name is not None else None
    return None


def resolve(
    callables: list[Callable],
    references: list[CalleeReference],
    owner_scoped_unqualified: bool = False,
) -> list[Entity]:
    edges = [set() for _ in callables]
    for reference in references:
        if not 0 <= reference.caller < len(callables):
            continue
        caller = callables[reference.caller]
        for target_id, target in enumerate(callables):
            if (
                target.file_id != caller.file_id
                or target.name != reference.name
                or not target.required_args
                <= reference.argument_count
                <= target.total_args
            ):
                continue
            if reference.qualifier == Qualifier.OTHER:
                continue
            if reference.qualifier == Qualifier.SELF_LIKE:
                matches = target.owner == caller.owner
            elif reference.qualifier == Qualifier.NAMED_TYPE:
                matches = reference.qualifier_name == target.owner == caller.owner
            elif owner_scoped_unqualified:
                matches = target.owner == caller.owner
            else:
                matches = target.unqualified_callable and target.owner == caller.owner
            if matches:
                edges[reference.caller].add(target_id)
    recursive = _recursive_members(edges)
    return [
        Entity(
            EntityKind.CONTROL_FLOW,
            "recursive_call",
            callables[i].file_id,
            callables[i].name_span,
            enclosing_function=callables[i].name,
            owner_type=callables[i].owner_type,
        )
        for i in range(len(callables))
        if recursive[i]
    ]


def _recursive_members(edges: list[set[int]]) -> list[bool]:
    visited: set[int] = set()
    order: list[int] = []
    for start in range(len(edges)):
        if start in visited:
            continue
        pending = [(start, False)]
        while pending:
            node, expanded = pending.pop()
            if expanded:
                order.append(node)
            elif node not in visited:
                visited.add(node)
                pending.append((node, True))
                pending.extend(
                    (target, False) for target in edges[node] if target not in visited
                )
    reverse = [set() for _ in edges]
    for source, targets in enumerate(edges):
        for target in targets:
            reverse[target].add(source)
    visited.clear()
    recursive = [False] * len(edges)
    for start in reversed(order):
        if start in visited:
            continue
        component, pending = [], [start]
        visited.add(start)
        while pending:
            node = pending.pop()
            component.append(node)
            for parent in reverse[node] - visited:
                visited.add(parent)
                pending.append(parent)
        if len(component) > 1 or start in edges[start]:
            for node in component:
                recursive[node] = True
    return recursive
