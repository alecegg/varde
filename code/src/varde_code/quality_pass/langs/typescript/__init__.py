"""TypeScript, JavaScript and TSX exports, visibility, names and verified roles.

The language loader maps ``javascript`` and ``tsx`` onto this module because the
grammars share their node names. ``.d.ts`` path exclusion belongs to
path-classes.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from functools import lru_cache

from tree_sitter import Node

_FRAMEWORK_DECORATORS = {
    "Get": "handler",
    "Post": "handler",
    "Put": "handler",
    "Patch": "handler",
    "Delete": "handler",
}
_FRAMEWORK_MODULES = {"@nestjs/common"}
_FUNCTION_TYPES = {
    "function_declaration",
    "generator_function_declaration",
    "function_expression",
    "arrow_function",
    "method_definition",
}


def exported_names(root: Node, source: bytes) -> set[tuple[None, str]]:
    """Return module-scoped local bindings exported by this module."""
    return _index(root, source)["exports"]


def file_private(
    record: dict, root: Node, source: bytes, references: Mapping[str, int]
) -> bool:
    """Use the core reference counter, ignoring export-only references."""
    index = _index(root, source)
    if (record["owner"], record["name"]) in index["exports"]:
        return False
    export_references = (
        index["export_references"][record["name"]] if record["owner"] is None else 0
    )
    remaining = references[record["name"]] - export_references
    return remaining > 0 and index["usage_counts"][record["name"]] > 0


def parameter_count(function_node: Node) -> int | None:
    """Count TypeScript parameter declarations, excluding comments and ``this``."""
    parameters = function_node.child_by_field_name("parameters")
    if parameters is None:
        return None
    count = 0
    for parameter in parameters.named_children:
        if parameter.type == "comment":
            continue
        pattern = parameter.child_by_field_name("pattern")
        if pattern is None:
            pattern = parameter.child_by_field_name("name")
        if pattern is not None and _text(pattern, _source_for(function_node)) == "this":
            continue
        count += 1
    return count


def verified_role(
    record: dict, function_node: Node, body: Node | None, source: bytes
) -> str | None:
    """Recognize setters, explicit overrides, same-file bases and known decorators."""
    if _is_setter_for_parameter(function_node, body, source):
        return "accessor"
    class_body = function_node.parent
    if class_body is None or class_body.type != "class_body":
        return None
    class_node = class_body.parent
    if class_node is not None and class_node.type in {
        "class_declaration",
        "abstract_class_declaration",
        "class",
    }:
        if record["name"] == "constructor" and _has_parameter_property(function_node):
            return "constructor"
        if any(child.type == "override_modifier" for child in function_node.children):
            return "override"
        bases = _base_names(class_node, source)
        if bases and _has_base_method(
            _root(function_node), bases, record["name"], source
        ):
            return "override"
    imported = _index(_root(function_node), source)["decorators"]
    for name in _decorator_names(class_body, function_node, source):
        if name in imported and imported[name] in _FRAMEWORK_DECORATORS:
            return _FRAMEWORK_DECORATORS[imported[name]]
    return None


def _has_parameter_property(function_node: Node) -> bool:
    parameters = function_node.child_by_field_name("parameters")
    if parameters is None:
        return False
    return any(
        child.type in {"accessibility_modifier", "readonly"}
        for parameter in parameters.named_children
        for child in parameter.named_children
    )


def convention_issues(record: dict) -> list[str]:
    """Flag snake_case function names, preserving PascalCase components."""
    return ["convention"] if re.search(r"_[a-z]", record["name"]) else []


def call_site(call_node: Node, source: bytes) -> dict:
    """Recognize ``this`` aliases and namespace-import call receivers."""
    function = call_node.child_by_field_name("function")
    if function is None or function.type != "member_expression":
        return {}
    receiver = function.child_by_field_name("object")
    property_node = function.child_by_field_name("property")
    if receiver is None or property_node is None:
        return {}
    receiver_name = _text(receiver, source)
    name = _text(property_node, source)
    if receiver_name in {"this", "self"} or receiver_name in _this_aliases(
        call_node, source
    ):
        return {"name": name, "receiver": "self"}
    if (
        _leftmost_identifier(receiver, source)
        in _index(_root(call_node), source)["module_aliases"]
    ):
        return {"name": name, "receiver": "mod"}
    return {}


@lru_cache(maxsize=32)
def _index(root: Node, source: bytes) -> dict:
    exports: set[tuple[None, str]] = set()
    export_references: Counter[str] = Counter()
    module_aliases: set[str] = set()
    decorators: dict[str, str] = {}
    class_nodes: dict[str, object] = {}
    for statement in root.named_children:
        if statement.type == "import_statement":
            _read_import(statement, source, module_aliases, decorators)
        elif statement.type in {"class_declaration", "abstract_class_declaration"}:
            name = statement.child_by_field_name("name")
            if name is not None:
                class_nodes[_text(name, source)] = statement
        elif statement.type == "lexical_declaration":
            _index_class_expressions(statement, source, class_nodes)
        elif statement.type == "export_statement":
            _read_export(statement, source, exports, export_references)
        elif statement.type == "export_assignment":
            value = statement.child_by_field_name("value")
            if value is not None:
                for name in _local_value_names(value, source):
                    exports.add((None, name))
                    export_references[name] += 1
    return {
        "exports": exports,
        "export_references": export_references,
        "module_aliases": module_aliases,
        "decorators": decorators,
        "class_nodes": class_nodes,
        "usage_counts": _usage_counts(root, source),
    }


def _usage_counts(root: Node, source: bytes) -> Counter[str]:
    counts: Counter[str] = Counter()
    for node in _walk(root):
        if node.type not in {
            "identifier",
            "property_identifier",
            "shorthand_property_identifier",
        }:
            continue
        name = _text(node, source)
        if not name or _is_declaration_or_key(node):
            continue
        if _inside_export(node) or _shadowed_by_parameter(node, name, source):
            continue
        counts[name] += 1
    return counts


def _is_declaration_or_key(node: Node) -> bool:
    parent = node.parent
    if parent is None:
        return True
    for field in ("name", "pattern", "alias"):
        field_node = parent.child_by_field_name(field)
        if field_node is not None and field_node.start_byte == node.start_byte:
            return True
    return parent.type == "pair" and parent.child_by_field_name("key") == node


def _inside_export(node: Node) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.type == "export_statement":
            declaration = parent.child_by_field_name("declaration")
            return not (
                declaration is not None
                and declaration.start_byte <= node.start_byte
                and node.end_byte <= declaration.end_byte
            )
        parent = parent.parent
    return False


def _shadowed_by_parameter(node: Node, name: str, source: bytes) -> bool:
    parent = node.parent
    while parent is not None and parent.type not in _FUNCTION_TYPES:
        parent = parent.parent
    if parent is None:
        return False
    parameters = parent.child_by_field_name("parameters")
    if parameters is None:
        return False
    for parameter in parameters.named_children:
        pattern = parameter.child_by_field_name("pattern")
        if pattern is None:
            pattern = parameter.child_by_field_name("name")
        if pattern is not None and _text(pattern, source) == name:
            return True
    return False


def _read_import(
    statement: Node,
    source: bytes,
    module_aliases: set[str],
    decorators: dict[str, str],
) -> None:
    module_node = statement.child_by_field_name("source")
    module = _text(module_node, source).strip("'\"") if module_node else ""
    clause = next(
        (child for child in statement.named_children if child.type == "import_clause"),
        None,
    )
    if clause is None:
        return
    for child in clause.named_children:
        if child.type == "identifier":
            module_aliases.add(_text(child, source))
        elif child.type == "namespace_import":
            alias = next(
                (n for n in child.named_children if n.type == "identifier"), None
            )
            if alias is not None:
                module_aliases.add(_text(alias, source))
        elif child.type == "named_imports" and module in _FRAMEWORK_MODULES:
            for specifier in child.named_children:
                if specifier.type != "import_specifier":
                    continue
                original = specifier.child_by_field_name("name")
                alias = specifier.child_by_field_name("alias")
                if original is not None:
                    local_name = (
                        _text(alias, source) if alias else _text(original, source)
                    )
                    decorators[local_name] = _text(original, source)


def _read_export(
    statement: Node,
    source: bytes,
    exports: set[tuple[None, str]],
    export_references: Counter[str],
) -> None:
    declaration = statement.child_by_field_name("declaration")
    if declaration is not None:
        for name in _declaration_names(declaration, source):
            exports.add((None, name))
        return
    value = statement.child_by_field_name("value")
    if value is not None:
        for name in _local_value_names(value, source):
            exports.add((None, name))
            export_references[name] += 1
        return
    if statement.child_by_field_name("source") is not None:
        return
    for clause in statement.named_children:
        if clause.type != "export_clause":
            continue
        for specifier in clause.named_children:
            if specifier.type != "export_specifier":
                continue
            name = specifier.child_by_field_name("name")
            if name is not None:
                local_name = _text(name, source)
                exports.add((None, local_name))
                export_references[local_name] += 1


def _declaration_names(declaration: Node, source: bytes) -> set[str]:
    if declaration.type in {
        "function_declaration",
        "generator_function_declaration",
        "function_signature",
        "class_declaration",
        "abstract_class_declaration",
        "interface_declaration",
        "type_alias_declaration",
        "enum_declaration",
    }:
        name = declaration.child_by_field_name("name")
        return {_text(name, source)} if name is not None else set()
    if declaration.type in {"lexical_declaration", "variable_declaration"}:
        return {
            _text(name, source)
            for item in declaration.named_children
            if item.type == "variable_declarator"
            if (name := item.child_by_field_name("name")) is not None
        }
    return set()


def _local_value_names(value: Node, source: bytes) -> set[str]:
    if value.type in {"identifier", "type_identifier"}:
        return {_text(value, source)}
    if value.type == "call_expression":
        arguments = value.child_by_field_name("arguments")
        if arguments is not None:
            return {
                _text(node, source)
                for node in arguments.named_children
                if node.type in {"identifier", "type_identifier"}
            }
    return set()


def _index_class_expressions(statement: Node, source: bytes, classes: dict) -> None:
    for declarator in statement.named_children:
        if declarator.type != "variable_declarator":
            continue
        name = declarator.child_by_field_name("name")
        value = declarator.child_by_field_name("value")
        if name is not None and value is not None and value.type == "class":
            classes[_text(name, source)] = value


def _base_names(class_node: Node, source: bytes) -> set[str]:
    heritage = next(
        (
            child
            for child in class_node.named_children
            if child.type == "class_heritage"
        ),
        None,
    )
    if heritage is None:
        return set()
    extends = [node for node in _walk(heritage) if node.type == "extends_clause"]
    roots = extends or [
        child for child in heritage.named_children if child.type != "implements_clause"
    ]
    return {
        _text(node, source)
        for root in roots
        for node in _walk(root)
        if node.type in {"identifier", "type_identifier"}
    }


def _has_base_method(root: Node, bases: set[str], name: str, source: bytes) -> bool:
    pending = list(bases)
    seen = set()
    classes = _index(root, source)["class_nodes"]
    while pending:
        base_name = pending.pop()
        if base_name in seen:
            continue
        seen.add(base_name)
        base = classes.get(base_name)
        if base is None:
            continue
        body = base.child_by_field_name("body")
        if body is None:
            continue
        for member in body.named_children:
            method_name = member.child_by_field_name("name")
            if (
                member.type == "method_definition"
                and method_name is not None
                and _text(method_name, source) == name
            ):
                return True
        pending.extend(_base_names(base, source) - seen)
    return False


def _decorator_names(class_body: Node, method: Node, source: bytes) -> set[str]:
    siblings = class_body.named_children
    try:
        position = next(
            index for index, child in enumerate(siblings) if child.id == method.id
        )
    except StopIteration:
        return set()
    decorators = []
    for sibling in reversed(siblings[:position]):
        if sibling.type != "decorator":
            break
        decorators.append(sibling)
    result = set()
    for decorator in decorators:
        expression = decorator.named_children[0] if decorator.named_children else None
        callee = (
            expression.child_by_field_name("function")
            if expression and expression.type == "call_expression"
            else expression
        )
        if callee is None:
            continue
        if callee.type == "identifier":
            result.add(_text(callee, source))
        elif callee.type == "member_expression":
            property_node = callee.child_by_field_name("property")
            if property_node is not None:
                result.add(_text(property_node, source))
    return result


def _is_setter_for_parameter(
    function_node: Node, body: Node | None, source: bytes
) -> bool:
    if body is None or not any(child.type == "set" for child in function_node.children):
        return False
    parameters = function_node.child_by_field_name("parameters")
    if parameters is None:
        return False
    parameter_names = {
        _text(node, source) for node in _walk(parameters) if node.type == "identifier"
    }
    assignments = [node for node in _walk(body) if node.type == "assignment_expression"]
    if len(assignments) != 1:
        return False
    right = assignments[0].child_by_field_name("right")
    left = assignments[0].child_by_field_name("left")
    return (
        right is not None
        and right.type == "identifier"
        and _text(right, source) in parameter_names
        and left is not None
        and left.type in {"member_expression", "subscript_expression"}
    )


def _this_aliases(call_node: Node, source: bytes) -> set[str]:
    function = call_node.parent
    while function is not None and function.type not in _FUNCTION_TYPES:
        function = function.parent
    if function is None:
        return set()
    aliases = set()
    for node in _walk_without_nested_functions(function):
        if node.type != "variable_declarator":
            continue
        value = node.child_by_field_name("value")
        name = node.child_by_field_name("name")
        if value is not None and value.type == "this" and name is not None:
            aliases.add(_text(name, source))
    return aliases


def _walk_without_nested_functions(root: Node):
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(
            child
            for child in reversed(node.named_children)
            if child is root or child.type not in _FUNCTION_TYPES
        )


def _root(node: Node) -> Node:
    while node.parent is not None:
        node = node.parent
    return node


def _leftmost_identifier(node: Node, source: bytes) -> str:
    current = node
    while current.type == "member_expression":
        current = current.child_by_field_name("object")
        if current is None:
            return ""
    return _text(current, source) if current.type == "identifier" else ""


def _source_for(node: Node) -> bytes:
    # Tree-sitter nodes retain source bytes only on the parsed tree,
    # passed by the caller.
    root = _root(node)
    return root.text or b""


def _text(node: Node | None, source: bytes) -> str:
    return (
        source[node.start_byte : node.end_byte].decode(errors="replace")
        if node is not None
        else ""
    )


def _walk(node: Node):
    stack = [node]
    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.named_children))
