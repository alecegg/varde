"""Rust-specific quality facts."""

from __future__ import annotations

from collections.abc import Mapping

from tree_sitter import Node

_CONVENTIONAL_SHORT_NAMES = frozenset(
    {
        "add",
        "cmp",
        "div",
        "eq",
        "fmt",
        "len",
        "mul",
        "ne",
        "neg",
        "not",
        "ord",
        "pop",
        "rem",
        "sub",
        "sum",
    }
)
_STANDARD_MACROS = frozenset(
    {
        "assert",
        "assert_eq",
        "assert_ne",
        "cfg",
        "column",
        "concat",
        "dbg",
        "debug_assert",
        "debug_assert_eq",
        "debug_assert_ne",
        "eprint",
        "eprintln",
        "file",
        "format",
        "format_args",
        "line",
        "matches",
        "module_path",
        "option_env",
        "panic",
        "print",
        "println",
        "stringify",
        "todo",
        "unimplemented",
        "unreachable",
        "vec",
        "write",
        "writeln",
    }
)


def function_node_types() -> set[str]:
    """Include bodyless trait and extern function declarations."""
    return {"function_signature_item"}


def function_node_name(node: Node, source: bytes) -> str | None:
    """Read the direct identifier used by a bodyless Rust function."""
    if node.type != "function_signature_item":
        return None
    name = next(
        (child for child in node.named_children if child.type == "identifier"), None
    )
    return (
        source[name.start_byte : name.end_byte].decode(errors="replace")
        if name
        else None
    )


def parameter_count(function_node: Node) -> int:
    """Count value parameters while excluding generic, lifetime and self parameters."""
    params = function_node.child_by_field_name("parameters")
    if params is None:
        return 0
    return sum(
        child.type in {"parameter", "variadic_parameter"}
        and not (child.text or b"").lstrip().startswith((b"self:", b"mut self:"))
        for child in params.named_children
    )


def verified_role(record: dict, function_node: Node, _body: Node, _source: bytes):
    """Tag trait-implementation methods as candidate boilerplate roles."""
    parent = function_node.parent
    if parent is not None and parent.type == "declaration_list":
        impl = parent.parent
        if impl is not None and impl.type == "impl_item":
            trait = impl.child_by_field_name("trait")
            if trait is not None:
                return "override"
            if record["name"] == "new" and _returns_self(function_node):
                return "constructor"
    return None


def file_private(
    record: dict, _root: Node, _source: bytes, _references: Mapping[str, int]
):
    """Rust items with any visibility modifier are outside file-private scope."""
    node = record.get("_node")
    return node is not None and not any(
        child.type == "visibility_modifier" for child in node.named_children
    )


def unmeasured_regions(root: Node, source: bytes) -> list[dict]:
    """Report code-expanding macros, not standard-library convenience macros.

    ``macro_rules!`` definitions and invocations of project or third-party macros
    hide expansion from the parser. Standard macros (``println!``, ``assert!``,
    ``vec!`` and the like) are ordinary statements whose bodies the parser keeps,
    so they stay measured.
    """
    regions = []
    stack = [root]
    while stack:
        node = stack.pop()
        stack.extend(node.named_children)
        if node.type == "macro_definition" or (
            node.type == "macro_invocation"
            and _macro_name(node, source) not in _STANDARD_MACROS
        ):
            regions.append(_region("macro", node, source))
    return regions


def filter_name_issues(record: dict, issues: list[str]) -> list[str]:
    """Drop short-name penalties for conventional Rust trait methods."""
    if record["name"] in _CONVENTIONAL_SHORT_NAMES:
        return [
            issue for issue in issues if issue not in {"abbreviation", "single_char"}
        ]
    return issues


def _macro_name(node: Node, source: bytes) -> str:
    macro = node.child_by_field_name("macro")
    if macro is None:
        return ""
    if macro.type == "identifier":
        return source[macro.start_byte : macro.end_byte].decode(errors="replace")
    name = macro.child_by_field_name("name")
    if name is None:
        return ""
    return source[name.start_byte : name.end_byte].decode(errors="replace")


def _region(kind: str, node: Node, source: bytes) -> dict:
    text = source[node.start_byte : node.end_byte].rstrip()
    return {
        "kind": kind,
        "start_line": node.start_point[0] + 1,
        "end_line": node.start_point[0] + 1 + text.count(b"\n"),
    }


def _returns_self(function_node: Node) -> bool:
    return_type = function_node.child_by_field_name("return_type")
    return return_type is not None and b"Self" in (return_type.text or b"")
