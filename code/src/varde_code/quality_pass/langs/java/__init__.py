"""Java-specific syntax and visibility hooks for quality facts."""

from __future__ import annotations

from collections.abc import Mapping

from tree_sitter import Node

_TYPE_NODES = {
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
}
_TEST_ANNOTATIONS = {
    "org.junit": {"Test"},
    "org.junit.jupiter.api": {
        "Test",
        "BeforeEach",
        "AfterEach",
        "BeforeAll",
        "AfterAll",
        "RepeatedTest",
    },
    "org.junit.jupiter.params": {"ParameterizedTest"},
}
_GENERATED_ANNOTATIONS = {
    "javax.annotation.Generated",
    "javax.annotation.processing.Generated",
    "jakarta.annotation.Generated",
}


def function_node_types() -> set[str]:
    """Include Java explicit and compact constructors in callable facts."""
    return {"constructor_declaration", "compact_constructor_declaration"}


def function_body(node: Node) -> Node | None:
    """Return Java constructor bodies that use grammar-specific node names."""
    if node.type not in {"constructor_declaration", "compact_constructor_declaration"}:
        return None
    return node.child_by_field_name("body") or next(
        (
            child
            for child in node.named_children
            if child.type in {"constructor_body", "block"}
        ),
        None,
    )


def parameter_count(node: Node) -> int | None:
    """Count implicit record components for a Java compact constructor."""
    if node.type != "compact_constructor_declaration":
        return None
    owner = node.parent.parent if node.parent is not None else None
    parameters = owner.child_by_field_name("parameters") if owner is not None else None
    return len(parameters.named_children) if parameters is not None else 0


def exported_names(root: Node, source_bytes: bytes) -> set[tuple[str | None, str]]:
    """Return explicitly exported method identities, including interface members."""
    result = set()
    for node in _walk(root):
        if node.type != "method_declaration":
            continue
        name = node.child_by_field_name("name")
        if name is None:
            continue
        words = _modifiers(node, source_bytes)
        owner = _enclosing_type_node(node)
        if words.intersection({"public", "protected"}) or (
            owner is not None
            and owner.type == "interface_declaration"
            and "private" not in words
        ):
            result.add((_enclosing_type(node, source_bytes), _text(name, source_bytes)))
    return result


def file_private(
    record: dict, root: Node, source_bytes: bytes, references: Mapping[str, int]
) -> bool:
    """Honor declared Java visibility, including public constructors and interfaces."""
    for node in _walk(root):
        if not _matches_record(node, record, source_bytes):
            continue
        owner = _enclosing_type_node(node)
        words = _modifiers(node, source_bytes)
        if (
            owner is not None
            and owner.type == "interface_declaration"
            and "private" not in words
        ):
            return False
        if words.intersection({"public", "protected"}):
            return False
        if "private" in words:
            return True
        return references[record["name"]] > 0
    return references[record["name"]] > 0


def verified_role(
    record: dict, function_node: Node, body: Node | None, source_bytes: bytes
) -> str | None:
    """Tag verified overrides, imported test handlers, and trivial accessors."""
    if function_node.type != "method_declaration":
        return None
    if _has_same_name_base_method(function_node, source_bytes):
        return "override"
    if _is_handler(function_node, source_bytes):
        return "handler"
    if body is None or _leaf_count(function_node) > 40:
        return None
    statements = [
        item
        for item in body.named_children
        if item.type not in {"line_comment", "block_comment"}
    ]
    if len(statements) != 1:
        return None
    statement = statements[0]
    if statement.type == "return_statement" and len(statement.named_children) == 1:
        value = statement.named_children[0]
        if value.type in {"identifier", "field_access"} and record[
            "name"
        ].lower().startswith(("get", "is", "has")):
            return "accessor"
    if (
        record["name"].lower().startswith("set")
        and len(_parameter_names(function_node, source_bytes)) == 1
    ):
        assignment = _unwrap_expression(statement)
        if assignment.type == "assignment_expression":
            left = assignment.child_by_field_name("left")
            right = assignment.child_by_field_name("right")
            if (
                left is not None
                and left.type == "field_access"
                and right is not None
                and _text(right, source_bytes)
                in _parameter_names(function_node, source_bytes)
            ):
                return "accessor"
    return None


def suppress_accessor_fallback(
    record: dict, function_node: Node, body: Node | None, source_bytes: bytes
) -> bool:
    """Use Java's verified getter/setter checks instead of the neutral shape guess."""
    return function_node.type in {
        "method_declaration",
        "constructor_declaration",
        "compact_constructor_declaration",
    }


def markers(root: Node, source_bytes: bytes, path: str) -> list[str]:
    """Recognize imported Java generated-code annotations and wildcard imports."""
    imports = _imports(root, source_bytes)
    if path.lower().endswith((".generated.java", ".g.java")):
        return ["generated"]
    for annotation in _walk(root):
        if annotation.type not in {"annotation", "marker_annotation"}:
            continue
        name = _text(annotation.child_by_field_name("name"), source_bytes)
        if _resolves_annotation(name, imports, _GENERATED_ANNOTATIONS):
            return ["generated"]
    return []


def _is_handler(node: Node, source: bytes) -> bool:
    imports = _imports(_root(node), source)
    modifiers = _modifiers_node(node)
    if modifiers is None:
        return False
    for annotation in modifiers.named_children:
        if annotation.type not in {"annotation", "marker_annotation"}:
            continue
        name = _text(annotation.child_by_field_name("name"), source)
        if _resolves_annotation(name, imports, _TEST_ANNOTATIONS):
            return True
    return False


def _resolves_annotation(name: str, imports: set[str], known: dict | set[str]) -> bool:
    if isinstance(known, dict):
        packages = known
        fully_qualified = {
            f"{package}.{annotation}"
            for package, names in known.items()
            for annotation in names
        }
    else:
        fully_qualified = set(known)
        packages = {}
        for item in known:
            package, annotation = item.rsplit(".", 1)
            packages.setdefault(package, set()).add(annotation)
    if name in fully_qualified:
        return True
    simple = name.rsplit(".", 1)[-1]
    if "." in name:
        return False
    for imported in imports:
        if imported in fully_qualified and imported.rsplit(".", 1)[-1] == simple:
            return True
        if (
            imported.endswith(".*")
            and imported[:-2] in packages
            and simple in packages[imported[:-2]]
        ):
            return True
    return False


def _has_same_name_base_method(node: Node, source: bytes) -> bool:
    owner = _enclosing_type_node(node)
    if owner is None:
        return False
    root = _root(node)
    declarations = [
        item
        for item in _walk(root)
        if item.type == owner.type
        and _text(item.child_by_field_name("name"), source)
        == _enclosing_type(node, source)
    ]
    base_names = set()
    for declaration in declarations:
        for field in (
            "superclass",
            "super_interfaces",
            "extends_interfaces",
            "interfaces",
        ):
            container = declaration.child_by_field_name(field)
            if container is not None:
                base_names.update(_type_names(container, source))
    if not base_names:
        return False
    function_name = _text(node.child_by_field_name("name"), source)
    arity = _arity(node)
    for base in _walk(root):
        if (
            base.type not in _TYPE_NODES
            or _text(base.child_by_field_name("name"), source) not in base_names
        ):
            continue
        if any(
            member.type == "method_declaration"
            and _text(member.child_by_field_name("name"), source) == function_name
            and _arity(member) == arity
            for member in _direct_members(base)
        ):
            return True
    return False


def _matches_record(node: Node, record: dict, source: bytes) -> bool:
    if node.type not in {
        "method_declaration",
        "constructor_declaration",
        "compact_constructor_declaration",
    }:
        return False
    if _enclosing_type(node, source) != record["owner"]:
        return False
    if node.start_point[0] + 1 != record["line"]:
        return False
    if (
        record.get("_start_byte") is not None
        and node.start_byte != record["_start_byte"]
    ):
        return False
    name_node = node.child_by_field_name("name")
    return _text(name_node, source) == record["name"]


def _enclosing_type_node(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type in _TYPE_NODES:
            return parent
        parent = parent.parent
    return None


def _enclosing_type(node: Node, source: bytes) -> str | None:
    owner = _enclosing_type_node(node)
    return _text(owner.child_by_field_name("name"), source) if owner else None


def _direct_members(node: Node):
    body = next(
        (
            child
            for child in node.named_children
            if child.type in {"class_body", "interface_body", "enum_body"}
        ),
        None,
    )
    return body.named_children if body is not None else []


def _type_names(node: Node, source: bytes) -> set[str]:
    names = set()
    for child in _walk(node):
        if child.type in {"type_identifier", "scoped_type_identifier"}:
            names.add(_text(child, source).split(".")[-1])
    return names


def _arity(node: Node) -> int:
    parameters = node.child_by_field_name("parameters")
    return len(parameters.named_children) if parameters is not None else 0


def _parameter_names(node: Node, source: bytes) -> set[str]:
    parameters = node.child_by_field_name("parameters")
    if parameters is None:
        return set()
    return {
        _text(name, source)
        for parameter in parameters.named_children
        if (name := parameter.child_by_field_name("name")) is not None
    }


def _imports(root: Node, source: bytes) -> set[str]:
    values = set()
    for node in _walk(root):
        if node.type == "import_declaration":
            value = (
                _text(node, source).removeprefix("import ").removesuffix(";").strip()
            )
            if not value.startswith("static "):
                values.add(value)
    return values


def _leaf_count(node: Node) -> int:
    return sum(
        1
        for item in _walk(node)
        if not item.children and item.type not in {"line_comment", "block_comment"}
    )


def _unwrap_expression(node: Node) -> Node:
    return (
        node.named_children[0]
        if node.type == "expression_statement" and len(node.named_children) == 1
        else node
    )


def _modifiers(node: Node, source: bytes) -> set[str]:
    modifiers = _modifiers_node(node)
    return (
        {_text(child, source) for child in modifiers.children} if modifiers else set()
    )


def _modifiers_node(node: Node) -> Node | None:
    return next(
        (item for item in node.named_children if item.type == "modifiers"), None
    )


def _walk(root: Node | None):
    if root is None:
        return
    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(reversed(node.named_children))


def _root(node: Node) -> Node:
    while node.parent is not None:
        node = node.parent
    return node


def _text(node: Node | None, source: bytes) -> str:
    return (
        source[node.start_byte : node.end_byte].decode(errors="replace") if node else ""
    )
