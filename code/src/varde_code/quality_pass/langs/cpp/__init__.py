"""C++-specific quality facts."""

from __future__ import annotations

import re
from collections.abc import Mapping

from tree_sitter import Node

_CONVENTIONAL_SHORT_NAMES = frozenset(
    {"buf", "cb", "cmp", "dst", "idx", "len", "num", "pos", "ptr", "src", "val"}
)
_GTEST_MACROS = frozenset({"TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P"})
_UNMEASURED_NODE_KINDS = {
    "template_declaration": "template",
    "preproc_def": "preprocessor",
    "preproc_function_def": "preprocessor",
    "preproc_if": "preprocessor",
    "preproc_ifdef": "preprocessor",
}
_GUARD_CONDITION = re.compile(
    r"^#ifndef\s+(\w+)\s*$|^#if\s+!\s*defined\s*\(?\s*(\w+)\s*\)?\s*$"
)


def parameter_count(function_node: Node) -> int:
    """Count C++ parameters through pointer/reference declarator wrappers."""
    declarator = function_node.child_by_field_name("declarator")
    while declarator is not None and declarator.type != "function_declarator":
        declarator = declarator.child_by_field_name("declarator")
    params = declarator.child_by_field_name("parameters") if declarator else None
    if params is None:
        return 0
    declarations = [
        child
        for child in params.named_children
        if child.type
        in {
            "parameter_declaration",
            "optional_parameter_declaration",
            "variadic_parameter_declaration",
        }
    ]
    if len(declarations) == 1 and (declarations[0].text or b"").strip() == b"void":
        return 0
    return len(declarations) + sum(child.type == "..." for child in params.children)


def file_private(
    record: dict, _root: Node, _source: bytes, _references: Mapping[str, int]
):
    """Recognize file-private C++ functions and non-public class members."""
    node = record.get("_node")
    if node is None:
        return False
    if any(_is_static(child) for child in node.named_children):
        return True
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "namespace_definition":
            name = ancestor.child_by_field_name("name")
            if name is None:
                return True
        if ancestor.type in {"class_specifier", "struct_specifier"}:
            body = ancestor.child_by_field_name("body")
            if body is None:
                return ancestor.type == "class_specifier"
            access = "private" if ancestor.type == "class_specifier" else "public"
            for child in body.named_children:
                if child.start_byte >= node.start_byte:
                    break
                if child.type == "access_specifier":
                    access = child.text.decode(errors="replace").strip()
            return access != "public"
        if ancestor.type in {"declaration_list", "translation_unit"}:
            break
        if ancestor.type == "declaration" and any(
            _is_static(child) for child in ancestor.named_children
        ):
            return True
        ancestor = ancestor.parent
    return False


def verified_role(record: dict, function_node: Node, body: Node, source: bytes):
    """Tag gtest macro cases and exempt an empty C++ constructor."""
    del body, source
    if record["name"] in _GTEST_MACROS and function_node.type == "function_definition":
        return "test"
    body_node = function_node.child_by_field_name("body")
    if (
        record["owner"]
        and record["name"] == record["owner"]
        and function_node.type == "function_definition"
        and body_node is not None
        and not body_node.named_children
    ):
        return "constructor"
    return None


def overload_pairs(records: list[dict], _root: Node, _source: bytes) -> list[tuple]:
    """Pair const and non-const member overloads that share owner, name and arity."""
    groups: dict[tuple, list[dict]] = {}
    for record in records:
        if record["owner"] is None:
            continue
        groups.setdefault(
            (record["owner"], record["name"], record["params"]), []
        ).append(record)
    pairs = []
    for group in groups.values():
        if len(group) != 2:
            continue
        first, second = group
        if _is_const_member(first["_node"]) != _is_const_member(second["_node"]):
            pairs.append((first["id"], second["id"]))
    return pairs


def unmeasured_regions(root: Node, source: bytes) -> list[dict]:
    """Report template declarations and preprocessor blocks as unmeasured.

    A canonical header guard (``#ifndef X``/``#if !defined(X)`` whose first inner
    declaration is the empty ``#define X``) hides nothing, so neither the
    conditional nor that marker definition is reported; macros and templates
    inside the guarded body still are.
    """
    guard_conditions, guard_definitions = _header_guards(root, source)
    regions = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.id in guard_conditions or node.id in guard_definitions:
            continue
        kind = _UNMEASURED_NODE_KINDS.get(node.type)
        if kind is not None:
            regions.append(_region(kind, node, source))
    return regions


def filter_name_issues(record: dict, issues: list[str]) -> list[str]:
    """Drop short-name penalties for conventional C++ names."""
    if record["name"] in _CONVENTIONAL_SHORT_NAMES:
        return [
            issue for issue in issues if issue not in {"abbreviation", "single_char"}
        ]
    return issues


def _is_static(node: Node) -> bool:
    return (
        node.type == "storage_class_specifier"
        and (node.text or b"").strip() == b"static"
    )


def _header_guards(root: Node, source: bytes) -> tuple[set[int], set[int]]:
    """Return the ids of top-level guard conditionals and their marker defines."""
    conditions: set[int] = set()
    definitions: set[int] = set()
    for statement in root.named_children:
        macro = _guard_macro(statement, source)
        if macro is None:
            continue
        definition = next(
            (
                child
                for child in statement.named_children
                if child.type == "preproc_def"
            ),
            None,
        )
        if definition is None or _defined_macro(definition, source) != macro:
            continue
        conditions.add(statement.id)
        definitions.add(definition.id)
    return conditions, definitions


def _guard_macro(node: Node, source: bytes) -> str | None:
    """Name of the macro a ``#ifndef``/``#if !defined`` line tests, if any."""
    if node.type not in {"preproc_ifdef", "preproc_if"}:
        return None
    header = source[node.start_byte : node.end_byte].split(b"\n", 1)[0]
    match = _GUARD_CONDITION.match(header.decode(errors="replace").strip())
    if match is None:
        return None
    return match.group(1) or match.group(2)


def _defined_macro(definition: Node, source: bytes) -> str:
    name = next(
        (child for child in definition.named_children if child.type == "identifier"),
        None,
    )
    if name is None:
        return ""
    return source[name.start_byte : name.end_byte].decode(errors="replace")


def _is_const_member(node: Node | None) -> bool:
    declarator = node.child_by_field_name("declarator") if node is not None else None
    while declarator is not None and declarator.type != "function_declarator":
        declarator = declarator.child_by_field_name("declarator")
    if declarator is None:
        return False
    return any(
        child.type == "type_qualifier" and (child.text or b"").strip() == b"const"
        for child in declarator.named_children
    )


def _region(kind: str, node: Node, source: bytes) -> dict:
    text = source[node.start_byte : node.end_byte].rstrip()
    return {
        "kind": kind,
        "start_line": node.start_point[0] + 1,
        "end_line": node.start_point[0] + 1 + text.count(b"\n"),
    }
