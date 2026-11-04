"""Go-specific quality facts."""

from __future__ import annotations

from collections.abc import Mapping

from tree_sitter import Node

_TEST_PREFIXES = ("Test", "Benchmark", "Fuzz")
_CONVENTIONAL_SHORT_NAMES = frozenset(
    {"b", "ctx", "db", "err", "id", "n", "ok", "p", "r", "rw", "s", "t", "w"}
)


def file_private(
    record: dict, _root: Node, _source: bytes, references: Mapping[str, int]
):
    """Treat locally used, unexported declarations as file-private helpers."""
    return references[record["name"]] > 0 and not record["name"][:1].isupper()


def parameter_count(function_node: Node) -> int:
    """Count each declared name in grouped Go parameters; omit receivers."""
    params = function_node.child_by_field_name("parameters")
    if params is None:
        return 0
    count = 0
    for parameter in params.named_children:
        names = [
            child for child in parameter.named_children if child.type == "identifier"
        ]
        count += max(1, len(names))
    return count


def verified_role(
    record: dict, function_node: Node, _body: Node, source: bytes
) -> str | None:
    """Tag Test/Benchmark/Fuzz functions whose single parameter is a testing type."""
    name = record["name"]
    if not any(
        name.startswith(prefix) and name[len(prefix) : len(prefix) + 1].isupper()
        for prefix in _TEST_PREFIXES
    ):
        return None
    params = function_node.child_by_field_name("parameters")
    if params is None or len(params.named_children) != 1:
        return None
    parameter = params.named_children[0]
    text = source[parameter.start_byte : parameter.end_byte].decode(errors="replace")
    return "test" if "testing." in text else None


def filter_name_issues(record: dict, issues: list[str]) -> list[str]:
    """Drop short-name penalties for conventional Go names."""
    if record["name"].strip("_") in _CONVENTIONAL_SHORT_NAMES:
        return [
            issue for issue in issues if issue not in {"abbreviation", "single_char"}
        ]
    return issues
