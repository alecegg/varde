from __future__ import annotations

import re
from collections import Counter

from item_spec_cognitive import tree_cognitive
from item_spec_extract_types import ANONYMOUS, TOKEN, Function, SourceSyntaxError
from item_spec_languages import CALL_NODES, FUNCTION_NODES, RETURN_TYPE_FIELDS
from varde_code.parse import parse_source

IDENTIFIER = re.compile(r"[A-Za-z_]\w*")

CPP_DECLARATORS = frozenset(
    {
        "function_declarator",
        "pointer_declarator",
        "reference_declarator",
        "parenthesized_declarator",
        "array_declarator",
        "attributed_declarator",
        "init_declarator",
    }
)
CPP_QUALIFIED = frozenset(
    {"qualified_identifier", "template_function", "operator_name", "destructor_name"}
)
ASSIGNMENT_FIELDS = {
    "variable_declarator": "name",
    "init_declarator": "declarator",
    "short_var_declaration": "left",
    "assignment_expression": "left",
    "let_declaration": "pattern",
    "var_spec": "name",
    "const_spec": "name",
}
ASSIGNMENT_CONTAINERS = frozenset(
    {
        "expression_list",
        "equals_value_clause",
        "value_equals_clause",
        "parenthesized_expression",
        "variable_declaration",
        "lexical_declaration",
    }
)

PARAMETER_BINDING_FIELDS = {
    "typescript": {
        "required_parameter": "pattern",
        "optional_parameter": "pattern",
        "rest_parameter": "pattern",
    },
    "java": {
        "formal_parameter": "name",
        "spread_parameter": "name",
        "receiver_parameter": "name",
    },
    "csharp": {"parameter": "name"},
    "go": {"parameter_declaration": "name"},
    "rust": {"parameter": "pattern"},
    "cpp": {"parameter_declaration": "declarator"},
}
LOCAL_BINDING_FIELDS = {
    "typescript": {
        "variable_declarator": "name",
        "required_parameter": "pattern",
        "optional_parameter": "pattern",
        "rest_parameter": "pattern",
    },
    "java": {
        "variable_declarator": "name",
        "formal_parameter": "name",
        "spread_parameter": "name",
        "catch_formal_parameter": "name",
    },
    "csharp": {"variable_declarator": "name", "parameter": "name"},
    "go": {
        "short_var_declaration": "left",
        "var_spec": "name",
        "const_spec": "name",
        "parameter_declaration": "name",
        "range_clause": "left",
    },
    "rust": {"let_declaration": "pattern", "parameter": "pattern"},
    "cpp": {"init_declarator": "declarator", "parameter_declaration": "declarator"},
}
MEMBER_ACCESS_NODES = {
    "member_expression",
    "member_access_expression",
    "selector_expression",
    "field_expression",
    "field_access",
    "scoped_identifier",
    "qualified_identifier",
}
LITERAL_KEY_NODES = {
    "pair",
    "keyed_element",
    "literal_element",
    "field_initializer",
    "field_designator",
}


def _tree(language: str, source: str) -> list[Function]:
    parsed = parse_source(language, source)
    if parsed.has_error():
        raise SourceSyntaxError(f"{language} source has syntax errors")
    data = parsed.source
    nodes = FUNCTION_NODES[language]

    def is_extracted(node) -> bool:
        return _tree_name(node, data) != ANONYMOUS

    function_nodes = _function_nodes(parsed.root, nodes, data)
    functions = [
        _tree_function(
            node, _tree_name(node, data), data, language, nodes, is_extracted
        )
        for node in function_nodes
    ]
    names = {function.name for function in functions}
    method_counts = Counter(
        _tree_name(node, data)
        for node in function_nodes
        if _tree_is_method(node, language, data)
    )
    methods = {name for name, count in method_counts.items() if count == 1}
    class_names = {
        _tree_name(current, data)
        for current in _walk_named(parsed.root)
        if current.type
        in {
            "class_declaration",
            "class_specifier",
            "struct_item",
            "struct_specifier",
            *({"type_spec"} if language == "go" else set()),
        }
    }
    for function, node in zip(functions, function_nodes, strict=True):
        shadowed = _tree_shadowed_names(node, language, nodes, data)
        direct_calls = _tree_call_kinds(node, data, language, names, nodes)
        direct_calls.difference_update(
            name for name, count in method_counts.items() if count > 1
        )
        direct_calls.update(
            _tree_method_calls(
                node,
                data,
                language,
                names,
                (nodes, class_names, methods, shadowed),
            )
        )
        references = _function_value_references(
            node, names, data, nodes, language, shadowed
        )
        function.edges = sorted((direct_calls | set(references)) - shadowed)
    return functions


def _function_nodes(root, nodes, data):
    found = []
    pending = [root]
    while pending:
        node = pending.pop()
        if node.type in nodes and _tree_name(node, data) != ANONYMOUS:
            found.append(node)
        pending.extend(reversed(node.named_children))
    return found


def _function_value_references(node, names, data, function_nodes, language, shadowed):
    declaration = _declaration_node(node, data)
    declared_at = _node_span(declaration)
    references = set()
    for identifier in _scoped_tree_nodes(node, function_nodes, data):
        if not _tree_is_value_identifier(identifier, node, language):
            continue
        name = identifier.text.decode()
        if (
            name in names
            and name not in shadowed
            and _node_span(identifier) != declared_at
        ):
            references.add(name)
    return sorted(references)


def _declaration_node(node, data):
    declaration = node.child_by_field_name("name")
    if declaration is not None or node.type != "function_definition":
        return declaration
    declarator = node.child_by_field_name("declarator")
    return next(
        (
            child
            for child in _walk_named(declarator)
            if _is_identifier_leaf(child)
            and child.text.decode() == _tree_name(node, data)
        ),
        None,
    )


def _node_span(node):
    return (node.start_byte, node.end_byte) if node is not None else None


def _scoped_tree_nodes(node, function_nodes, data):
    pending = list(reversed(node.named_children))
    while pending:
        current = pending.pop()
        if current.type in function_nodes and _tree_name(current, data) != ANONYMOUS:
            continue
        yield current
        pending.extend(reversed(current.named_children))


def _tree_is_value_identifier(identifier, function, language):
    parent = identifier.parent
    field = _field_name(parent, identifier)
    if not _is_identifier_leaf(identifier) or parent is None:
        return False
    if _is_member_name(parent, field) or _is_literal_key(parent, field):
        return False
    if _is_binding_identifier(parent, field, language):
        return False
    if _is_object_initializer_key(identifier, function):
        return False
    if _is_named_argument_label(identifier):
        return False
    return not _has_non_value_ancestor(identifier, function)


def _is_identifier_leaf(identifier):
    return (
        identifier.type
        in {
            "identifier",
            "package_identifier",
            "shorthand_property_identifier",
        }
        and not identifier.named_children
    )


def _is_member_name(parent, field):
    return parent.type in MEMBER_ACCESS_NODES and field in {"field", "property", "name"}


def _is_literal_key(parent, field):
    return parent.type in LITERAL_KEY_NODES and field in {"key", "field"}


def _is_binding_identifier(parent, field, language):
    if parent.type in {
        "object_pattern",
        "object_binding_pattern",
        "shorthand_property_identifier_pattern",
    }:
        return True
    bindings = PARAMETER_BINDING_FIELDS.get(language, {})
    bindings = {**bindings, **LOCAL_BINDING_FIELDS.get(language, {})}
    binding_field = bindings.get(parent.type)
    return (binding_field is not None and field == binding_field) or (
        parent.type == "function_declaration" and field == "name"
    )


def _is_object_initializer_key(identifier, function):
    assignment = identifier.parent
    if assignment.type != "assignment_expression":
        return False
    if _field_name(assignment, identifier) != "left":
        return False
    return any(
        ancestor.type == "initializer_expression"
        for ancestor in _ancestors_until(identifier, function)
    )


def _is_named_argument_label(identifier):
    argument = identifier.parent
    if argument.type != "argument" or argument.named_children[0] != identifier:
        return False
    suffix = argument.text.decode()[len(identifier.text.decode()) :].lstrip()
    return suffix.startswith(":")


def _has_non_value_ancestor(identifier, function):
    if not function.start_byte <= identifier.start_byte < function.end_byte:
        return False
    for ancestor in _ancestors_until(identifier, function):
        if ancestor.type in LITERAL_KEY_NODES:
            return True
        if ancestor.type in {
            "type_annotation",
            "type_arguments",
            "generic_type",
            "type_identifier",
        }:
            return True
    return False


def _tree_shadowed_names(node, language, function_nodes, data):
    parameters = _parameter_nodes(node, language)
    names = {
        child.text.decode()
        for parameter in parameters
        for child in _binding_leaves(parameter, language)
    }

    pending = list(reversed(node.named_children))
    while pending:
        current = pending.pop()
        if current.type in function_nodes and _tree_name(current, data) != ANONYMOUS:
            names.add(_tree_name(current, data))
            continue
        names.update(_local_binding_names(current, language))
        pending.extend(reversed(current.named_children))
    return names


def _local_binding_names(node, language):
    field = LOCAL_BINDING_FIELDS.get(language, {}).get(node.type)
    if field is None:
        return set()
    binding = node.child_by_field_name(field)
    return {child.text.decode() for child in _binding_leaves(binding, language)}


def _parameter_nodes(node, language):
    parameters = node.child_by_field_name("parameters")
    if parameters is None and language == "cpp":
        declarator = node.child_by_field_name("declarator")
        parameters = next(
            (
                child.child_by_field_name("parameters")
                for child in _walk_named(declarator)
                if child.type == "function_declarator"
            ),
            None,
        )
    return [
        current
        for current in _walk_named(parameters)
        if current.type in PARAMETER_BINDING_FIELDS.get(language, {})
    ]


def _binding_leaves(node, language):
    if node is None:
        return
    pending = [node]
    while pending:
        current = pending.pop()
        if current.type in {"pair_pattern", "field_pattern"}:
            pending.extend(
                child
                for child in reversed(current.named_children)
                if _is_binding_pattern_child(current, child)
            )
            continue
        if _is_binding_leaf(current):
            yield current
            continue
        pending.extend(reversed(current.named_children))


def _is_binding_pattern_child(parent, child):
    return _field_name(parent, child) in {"value", "pattern"} or child.type in {
        "shorthand_property_identifier_pattern",
        "shorthand_field_identifier",
    }


def _is_binding_leaf(node):
    return (
        node.type
        in {
            "identifier",
            "field_identifier",
            "shorthand_property_identifier_pattern",
            "shorthand_field_identifier",
        }
        and not node.named_children
    )


def _field_name(parent, child):
    if parent is None:
        return None
    for index, item in enumerate(parent.children):
        if item == child:
            return parent.field_name_for_child(index)
    return None


def _ancestors_until(node, stop):
    current = node.parent
    while current is not None and current != stop:
        yield current
        current = current.parent


def _tree_call_kinds(node, data, language, names, function_nodes):
    direct = set()
    call_nodes = CALL_NODES[language]
    for current in _scoped_tree_nodes(node, function_nodes, data):
        target = _direct_call_target(current, call_nodes, names, data)
        if target is not None:
            direct.add(target)
    return direct


def _direct_call_target(current, call_nodes, names, data):
    if current.type not in call_nodes:
        return None
    for field in ("function", "name", "macro", "constructor", "type"):
        target = current.child_by_field_name(field)
        if target is None:
            continue
        called = _last_identifier(_text(target, data))
        if called not in names:
            return None
        if target.type in MEMBER_ACCESS_NODES and _same_file_receiver(target, data):
            return called
        if target.type not in {"identifier", "package_identifier"}:
            return None
        return called
    return None


def _tree_method_calls(node, data, language, names, context):
    function_nodes, class_names, methods, shadowed = context
    calls = set()
    for current in _scoped_tree_nodes(node, function_nodes, data):
        called = _direct_call_target(current, CALL_NODES[language], names, data)
        if called:
            calls.add(called)
            continue
        if current.type not in CALL_NODES[language]:
            continue
        target = next(
            (
                current.child_by_field_name(field)
                for field in ("function", "name", "constructor", "type")
                if current.child_by_field_name(field) is not None
            ),
            None,
        )
        if target is None:
            continue
        called = _last_identifier(_text(target, data))
        if called in methods and called not in shadowed:
            receiver = _call_receiver(current, target)
            receiver_text = (
                _text(receiver, data).strip() if receiver is not None else ""
            )
            receiver_types = _tree_receiver_types(node, language, data)
            receiver_type = receiver_types.get(receiver_text)
            is_simple_receiver = bool(re.fullmatch(r"[A-Za-z_]\w*", receiver_text))
            if (
                receiver_text in {"self", "this", "Self"}
                or (
                    is_simple_receiver
                    and (receiver_type is None or receiver_type in class_names)
                )
                or language == "rust"
                and "::" in _text(target, data)
                or receiver_text.startswith("new ")
            ):
                calls.add(called)
        if called == "new" and language == "rust" and "::" in _text(target, data):
            calls.update(name for name in methods if name == "new")
        if _last_identifier(_text(target, data)) in class_names:
            calls.update(
                name for name in names if name in {"__init__", "new", "constructor"}
            )
    return calls


def _call_receiver(call, target):
    for node in (call, target):
        for field in ("object", "scope"):
            receiver = node.child_by_field_name(field)
            if receiver is not None:
                return receiver
    if target.type in MEMBER_ACCESS_NODES:
        return target.named_children[0] if target.named_children else None
    return None


def _tree_receiver_types(function, language, data):
    types = {}
    pending = list(function.named_children)
    while pending:
        current = pending.pop()
        if current.type in FUNCTION_NODES[language] and current is not function:
            continue
        if current.type in PARAMETER_BINDING_FIELDS.get(language, {}):
            type_node = current.child_by_field_name("type")
            name_node = current.child_by_field_name("name")
            if type_node is not None and name_node is not None:
                types[_last_identifier(_text(name_node, data))] = _last_identifier(
                    _text(type_node, data)
                )
        if current.type == "variable_declarator":
            name_node = current.child_by_field_name("name")
            parent = current.parent
            type_node = parent.child_by_field_name("type") if parent else None
            value_node = current.child_by_field_name("value")
            if name_node is not None and (
                type_node is not None or value_node is not None
            ):
                value = (
                    _text(type_node, data)
                    if type_node is not None
                    else _text(value_node, data)
                )
                inferred = re.search(
                    r"\bnew\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)", value
                )
                type_name = (
                    _last_identifier(value)
                    if type_node is not None
                    else (_last_identifier(inferred.group(1)) if inferred else None)
                )
                if type_name:
                    types[_last_identifier(_text(name_node, data))] = type_name
        pending.extend(current.named_children)
    return types


def _tree_is_method(node, language, data):
    if language == "go" and node.child_by_field_name("receiver") is not None:
        return True
    if language == "go":
        return False
    method_containers = {
        "typescript": {"class_body"},
        "java": {"class_body", "interface_body", "enum_body"},
        "csharp": {"declaration_list"},
        "cpp": {"field_declaration_list"},
        "rust": {"impl_item"},
    }[language]
    return any(ancestor.type in method_containers for ancestor in _ancestors(node))


def _ancestors(node):
    current = node.parent
    while current is not None:
        yield current
        current = current.parent


def _same_file_receiver(target, data):
    receiver = target.child_by_field_name("object")
    if receiver is None:
        receiver = target.child_by_field_name("scope")
    if receiver is None:
        return False
    text = _text(receiver, data).strip()
    return text in {"self", "this"} or text.startswith("new ")


def _walk_named(node):
    if node is None:
        return
    yield node
    for child in node.named_children:
        yield from _walk_named(child)


def _tree_function(
    node, name: str, data: bytes, language: str, nodes, is_extracted
) -> Function:
    calls, nested = _tree_calls(node, data, language, nodes, is_extracted)
    own = bytearray(data[node.start_byte : node.end_byte])
    for start, end in nested:
        own[start - node.start_byte : end - node.start_byte] = b" " * (end - start)
    return Function(
        name,
        len(TOKEN.findall(own.decode())),
        node.end_point[0] - node.start_point[0] + 1,
        calls,
        tree_cognitive(node, language, is_extracted)
        + sum(call == name for call in calls),
        _signature(node, data, language),
    )


def _tree_calls(node, data: bytes, language: str, nodes, is_extracted):
    calls: list[str] = []
    nested: list[tuple[int, int]] = []
    pending = list(reversed(node.named_children))
    while pending:
        current = pending.pop()
        if current.type in nodes and is_extracted(current):
            nested.append((current.start_byte, current.end_byte))
            continue
        called = (
            _call_name(current, data) if current.type in CALL_NODES[language] else None
        )
        if called:
            calls.append(called)
        pending.extend(reversed(current.named_children))
    return calls, nested


def _call_name(call, data: bytes) -> str | None:
    for field in ("function", "name", "macro", "constructor", "type"):
        target = call.child_by_field_name(field)
        if target is not None:
            return _last_identifier(_text(target, data))
    return None


def _tree_name(node, data: bytes) -> str:
    if node.type == "function_definition":
        return _cpp_name(node, data)
    named = node.child_by_field_name("name")
    if named is not None:
        return _text(named, data)
    return _assigned_name(node, data) or ANONYMOUS


def _cpp_name(node, data: bytes) -> str:
    declarator = node.child_by_field_name("declarator")
    while declarator is not None and declarator.type in CPP_DECLARATORS:
        declarator = declarator.child_by_field_name("declarator")
    if declarator is None:
        return _assigned_name(node, data) or ANONYMOUS
    if declarator.type in CPP_QUALIFIED:
        named = declarator.child_by_field_name("name")
        if named is not None:
            return _text(named, data)
    return _text(declarator, data)


def _assigned_name(node, data: bytes) -> str | None:
    current = node.parent
    for _ in range(4):
        if current is None:
            return None
        field = ASSIGNMENT_FIELDS.get(current.type)
        if field:
            target = current.child_by_field_name(field)
            return _last_identifier(_text(target, data)) if target is not None else None
        if current.type not in ASSIGNMENT_CONTAINERS:
            return None
        current = current.parent
    return None


def _signature(node, data: bytes, language: str) -> str:
    parts = []
    returned = _return_type_node(node, language)
    if returned is not None:
        parts.append(_text(returned, data))
    params = node.child_by_field_name("parameters") or node.child_by_field_name(
        "parameter"
    )
    if params is None and language == "cpp":
        params = _cpp_parameters(node)
    if params is None:
        params = next(
            (
                child
                for child in node.named_children
                if child.type == "closure_parameters"
            ),
            None,
        )
    if params is not None:
        parts.append(_text(params, data))
    return " ".join(parts)


def _return_type_node(node, language: str):
    field = RETURN_TYPE_FIELDS.get(language, "")
    if field:
        returned = node.child_by_field_name(field)
        if returned is not None:
            return returned
    if language != "csharp":
        return None
    name = node.child_by_field_name("name")
    if name is None:
        return None
    before = [
        child for child in node.named_children if child.start_byte < name.start_byte
    ]
    return before[-1] if before else None


def _cpp_parameters(node):
    declarator = node.child_by_field_name("declarator")
    while declarator is not None and declarator.type in CPP_DECLARATORS:
        params = declarator.child_by_field_name("parameters")
        if params is not None:
            return params
        declarator = declarator.child_by_field_name("declarator")
    return None


def _text(node, data: bytes) -> str:
    return data[node.start_byte : node.end_byte].decode()


def _last_identifier(text: str) -> str | None:
    identifiers = IDENTIFIER.findall(text)
    return identifiers[-1] if identifiers else None
