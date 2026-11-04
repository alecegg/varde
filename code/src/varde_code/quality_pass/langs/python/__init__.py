"""Python-specific exports, visibility, names and verified roles.

``.d.ts`` path exclusion belongs to path-classes. pytest items and methods of
``unittest.TestCase`` subclasses keep ``is_test=False`` from ``extract_file`` and
are tagged here by their test naming convention.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from tree_sitter import Node

_FRAMEWORK_ROLES = {
    "pytest": {"fixture": "fixture"},
    "flask": {"route": "handler", "get": "handler", "post": "handler"},
    "fastapi": {
        "get": "handler",
        "post": "handler",
        "put": "handler",
        "patch": "handler",
        "delete": "handler",
        "api_route": "handler",
        "websocket": "handler",
    },
}
_PYTHON_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")
_PYTEST_ITEM = re.compile(r"^test_[a-z0-9_]+$")


def exported_names(root: Node, source: bytes) -> set[tuple[None, str]]:
    """Return module-scoped names explicitly added to ``__all__``."""
    return {(None, name) for name in _all_names(root, source)}


def file_private(
    record: dict, root: Node, source: bytes, references: Mapping[str, int]
) -> bool:
    """Mark underscore names or in-file-used names private unless exported."""
    if (record["owner"], record["name"]) in _index(root, source)["exports"]:
        return False
    return record["name"].startswith("_") or references[record["name"]] > 0


def parameter_count(function_node: Node) -> int | None:
    """Count declared parameters, excluding separators and comments."""
    parameters = function_node.child_by_field_name("parameters")
    if parameters is None:
        return None
    ignored = {"comment", "positional_separator", "keyword_separator"}
    return sum(child.type not in ignored for child in parameters.named_children)


def verified_role(
    record: dict, function_node: Node, body: Node | None, source: bytes
) -> str | None:
    """Recognize protocol dunders, real overrides, test items and framework roles."""
    if _is_test_item(record, function_node, source):
        return "test"
    if record["owner"] and record["name"] == "__init__":
        return "constructor"
    if record["owner"] and _is_protocol_dunder(record["name"]):
        return "override"
    class_node = _direct_class(function_node)
    if class_node is not None and _overrides(
        record["name"], class_node, _index(_root(function_node), source)
    ):
        return "override"
    for framework, name, receiver in _decorator_calls(function_node, source):
        index = _index(_root(function_node), source)
        if receiver is None:
            binding = index["imports"].get(name)
            if binding is not None:
                role = (
                    _FRAMEWORK_ROLES.get(framework, {}).get(binding[1])
                    if framework is not None
                    else None
                )
                if role is None:
                    role = _FRAMEWORK_ROLES.get(binding[0], {}).get(binding[1])
                if role:
                    return role
            module = index["modules"].get(name)
            if module:
                role = _FRAMEWORK_ROLES.get(module, {}).get(name)
                if role:
                    return role
        else:
            resolved_framework = index["instances"].get(receiver) or index[
                "modules"
            ].get(receiver)
            if resolved_framework:
                role = _FRAMEWORK_ROLES.get(resolved_framework, {}).get(name)
                if role:
                    return role
    return None


def convention_issues(record: dict) -> list[str]:
    """Flag non-snake-case Python function names, except protocol dunders."""
    name = record["name"]
    if name.startswith("__") and name.endswith("__"):
        return []
    return ["convention"] if not _PYTHON_NAME.fullmatch(name) else []


def _is_test_item(record: dict, function_node: Node, source: bytes) -> bool:
    """Match pytest's collection rules and ``unittest.TestCase`` subclasses.

    The hook has no file path, so a production module-level ``test_*`` function is
    indistinguishable from a pytest item; the scorer must restrict this exemption
    to files in the tests path class.
    """
    if _PYTEST_ITEM.fullmatch(record["name"]) is None:
        return False
    if record["owner"] is None:
        return True
    class_node = _direct_class(function_node)
    if class_node is None:
        return False
    if record["owner"].startswith("Test"):
        return not _has_direct_method(class_node, "__init__", source)
    return any(
        base == "TestCase" or base.endswith("TestCase")
        for base in _base_names(class_node, source)
    )


def call_site(call_node: Node, source: bytes) -> dict:
    """Normalize Python ``cls`` and imported module receivers."""
    function = call_node.child_by_field_name("function")
    if function is None or function.type != "attribute":
        return {}
    receiver = function.child_by_field_name("object")
    attribute = function.child_by_field_name("attribute")
    if receiver is None or attribute is None:
        return {}
    receiver_name = _text(receiver, source)
    if receiver_name in {"self", "cls"}:
        return {"name": _text(attribute, source), "receiver": "self"}
    root = _root(call_node)
    if _leftmost_identifier(receiver, source) in _index(root, source)["module_aliases"]:
        return {"name": _text(attribute, source), "receiver": "mod"}
    return {}


@lru_cache(maxsize=32)
def _index(root: Node, source: bytes) -> dict[str, Any]:
    imports: dict[str, tuple[str, str]] = {}
    modules: dict[str, str] = {}
    module_aliases: set[str] = set()
    classes: dict[str, object] = {}
    for statement in root.named_children:
        if statement.type == "import_from_statement":
            module_node = statement.child_by_field_name("module_name")
            module = _text(module_node, source) if module_node else ""
            framework = _framework(module)
            if framework:
                for item in statement.named_children:
                    if item.type == "aliased_import":
                        original = item.child_by_field_name("name")
                        alias = item.child_by_field_name("alias")
                        if original is not None:
                            original_name = _text(original, source).split(".")[-1]
                            imports[
                                _text(alias, source) if alias else original_name
                            ] = (
                                framework,
                                original_name,
                            )
                    elif item.type == "dotted_name":
                        original_name = _text(item, source).split(".")[-1]
                        imports[original_name] = (framework, original_name)
        elif statement.type == "import_statement":
            for item in statement.named_children:
                if item.type == "dotted_name":
                    module = _text(item, source)
                    local = module.split(".")[0]
                elif item.type == "aliased_import":
                    name = item.child_by_field_name("name")
                    alias = item.child_by_field_name("alias")
                    if name is None:
                        continue
                    module = _text(name, source)
                    local = _text(alias, source) if alias else module.split(".")[0]
                else:
                    continue
                module_aliases.add(local)
                framework = _framework(module)
                if framework:
                    modules[local] = framework
        elif statement.type == "class_definition":
            name = statement.child_by_field_name("name")
            if name is not None:
                classes[_text(name, source)] = statement
    exports = {(None, name) for name in _all_names(root, source)}
    instances = _framework_instances(root, source, imports, modules)
    return {
        "imports": imports,
        "modules": modules,
        "module_aliases": module_aliases,
        "classes": classes,
        "exports": exports,
        "instances": instances,
        "source": source,
    }


def _all_names(root: Node, source: bytes) -> set[str]:
    names: set[str] = set()
    for statement in root.named_children:
        candidates = [statement]
        if statement.type == "expression_statement":
            candidates = list(statement.named_children)
        for assignment in candidates:
            if assignment.type in {"assignment", "augmented_assignment"}:
                left = assignment.child_by_field_name("left")
                right = assignment.child_by_field_name("right")
                if (
                    left is not None
                    and _text(left, source) == "__all__"
                    and right is not None
                ):
                    names.update(_string_values(right, source))
            if assignment.type == "call":
                function = assignment.child_by_field_name("function")
                arguments = assignment.child_by_field_name("arguments")
                if (
                    function is not None
                    and function.type == "attribute"
                    and _text(function.child_by_field_name("object"), source)
                    == "__all__"
                    and _text(function.child_by_field_name("attribute"), source)
                    in {"append", "extend"}
                    and arguments is not None
                ):
                    names.update(_string_values(arguments, source))
    return names


def _string_values(node: Node, source: bytes) -> set[str]:
    result = set()
    for child in _walk(node):
        if child.type != "string":
            continue
        value = _text(child, source)
        match = re.match(r"^[rubfRUBF]*(['\"])(.*?)\1$", value, re.DOTALL)
        if match:
            result.add(match.group(2))
    return result


def _framework_instances(
    root: Node,
    source: bytes,
    imports: dict[str, tuple[str, str]],
    modules: dict[str, str],
) -> dict[str, str]:
    instances = {}
    for statement in root.named_children:
        if statement.type not in {"assignment", "expression_statement"}:
            continue
        assignment = (
            statement.named_children[0]
            if statement.type == "expression_statement" and statement.named_children
            else statement
        )
        if assignment.type != "assignment":
            continue
        left = assignment.child_by_field_name("left")
        right = assignment.child_by_field_name("right")
        if left is None or right is None or right.type != "call":
            continue
        target = right.child_by_field_name("function")
        if target is None:
            continue
        if target.type == "identifier":
            binding = imports.get(_text(target, source))
            framework = _framework_constructor(binding)
        elif target.type == "attribute":
            object_node = target.child_by_field_name("object")
            attribute = target.child_by_field_name("attribute")
            framework_module = (
                modules.get(_text(object_node, source)) if object_node else None
            )
            framework = _framework_constructor(
                (framework_module, _text(attribute, source))
            )
        else:
            framework = None
        if framework and left.type == "identifier":
            instances[_text(left, source)] = framework
    return instances


def _framework_constructor(binding: tuple[str | None, str] | None) -> str | None:
    if binding in {
        ("flask", "Flask"),
        ("fastapi", "FastAPI"),
        ("fastapi", "APIRouter"),
    }:
        return "flask" if binding == ("flask", "Flask") else "fastapi"
    return None


def _decorator_calls(
    function_node: Node, source: bytes
) -> list[tuple[str | None, str, str | None]]:
    parent = function_node.parent
    if parent is None or parent.type != "decorated_definition":
        return []
    result = []
    for decorator in parent.named_children:
        if decorator.type != "decorator" or not decorator.named_children:
            continue
        expression = decorator.named_children[0]
        callee = (
            expression.child_by_field_name("function")
            if expression.type == "call"
            else expression
        )
        if callee is None:
            continue
        if callee.type == "attribute":
            receiver = callee.child_by_field_name("object")
            attribute = callee.child_by_field_name("attribute")
            if receiver is not None and attribute is not None:
                receiver_name = _text(receiver, source)
                framework = (
                    _framework(_text(receiver, source))
                    if receiver.type == "identifier"
                    else None
                )
                result.append((framework, _text(attribute, source), receiver_name))
        elif callee.type == "identifier":
            result.append((None, _text(callee, source), None))
    return result


def _direct_class(function_node: Node) -> Node | None:
    statement = function_node.parent
    if statement is not None and statement.type == "decorated_definition":
        statement = statement.parent
    if statement is None or statement.type != "block":
        return None
    class_node = statement.parent
    return (
        class_node
        if class_node is not None and class_node.type == "class_definition"
        else None
    )


def _overrides(name: str, class_node: Node, index: dict) -> bool:
    pending = _base_names(class_node, index["source"]) if "source" in index else set()
    # The source is stored in the index to keep this traversal cached per file.
    seen = set()
    classes = index["classes"]
    while pending:
        base_name = pending.pop()
        if base_name in seen:
            continue
        seen.add(base_name)
        base = classes.get(base_name)
        if base is None:
            continue
        if _has_direct_method(base, name, index["source"]):
            return True
        pending.update(_base_names(base, index["source"]) - seen)
    return False


def _base_names(class_node: Node, source: bytes) -> set[str]:
    bases = class_node.child_by_field_name("superclasses")
    if bases is None:
        return set()
    result = set()
    for expression in bases.named_children:
        if expression.type == "keyword_argument":
            continue
        if expression.type == "identifier":
            result.add(_text(expression, source))
        elif expression.type == "attribute":
            attribute = expression.child_by_field_name("attribute")
            if attribute is not None:
                result.add(_text(attribute, source))
    return result


def _has_direct_method(class_node: Node, name: str, source: bytes) -> bool:
    body = class_node.child_by_field_name("body")
    if body is None:
        return False
    for statement in body.named_children:
        function = (
            statement.child_by_field_name("definition")
            if statement.type == "decorated_definition"
            else statement
        )
        if function is None or function.type != "function_definition":
            continue
        function_name = function.child_by_field_name("name")
        if function_name is not None and _text(function_name, source) == name:
            return True
    return False


def _is_protocol_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__") and len(name) > 4


def _framework(module: str) -> str | None:
    for framework in _FRAMEWORK_ROLES:
        if module == framework or module.startswith(framework + "."):
            return framework
    return None


def _root(node: Node) -> Node:
    while node.parent is not None:
        node = node.parent
    return node


def _leftmost_identifier(node: Node, source: bytes) -> str:
    current = node
    while current.type == "attribute":
        current = current.child_by_field_name("object")
        if current is None:
            return ""
    return _text(current, source) if current.type == "identifier" else ""


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
