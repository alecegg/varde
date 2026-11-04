"""C# syntax and visibility hooks for quality facts."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

from tree_sitter import Node

_EXTRA_FUNCTION_NODES = {
    "constructor_declaration",
    "accessor_declaration",
    "property_declaration",
    "indexer_declaration",
    "operator_declaration",
    "conversion_operator_declaration",
    "destructor_declaration",
}
_HANDLER_ATTRIBUTES = {
    "Xunit": {"Fact", "Theory"},
    "NUnit.Framework": {
        "Test",
        "TestCase",
        "SetUp",
        "TearDown",
        "OneTimeSetUp",
        "OneTimeTearDown",
        "TestFixture",
    },
    "Microsoft.VisualStudio.TestTools.UnitTesting": {
        "TestMethod",
        "DataTestMethod",
        "TestInitialize",
        "TestCleanup",
        "ClassInitialize",
        "ClassCleanup",
        "TestClass",
    },
}
_GENERATED_ATTRIBUTES = {
    "System.CodeDom.Compiler": {"GeneratedCode"},
    "System.Runtime.CompilerServices": {"CompilerGenerated"},
}


def function_node_types() -> set[str]:
    """Include C# constructors, accessors, operators, and expression properties."""
    return set(_EXTRA_FUNCTION_NODES)


def function_node_name(node: Node, source_bytes: bytes) -> str | None:
    """Map grammar nodes to names used by the C# entity extractor."""
    if node.type == "accessor_declaration":
        return _accessor_node_name(node, source_bytes)
    if node.type == "property_declaration":
        return _expression_property_name(node, source_bytes)
    if node.type == "indexer_declaration":
        return "this.get" if node.child_by_field_name("value") is not None else None
    text = _text(node, source_bytes)
    if node.type == "operator_declaration":
        match = re.search(r"\boperator\s*([^\s(]+)", text)
        return f"operator{match.group(1)}" if match else None
    if node.type == "conversion_operator_declaration":
        match = re.search(r"\b(implicit|explicit)\s+operator\s+([^\s(]+)", text)
        return f"{match.group(1)} operator {match.group(2)}" if match else None
    return None


def function_body(node: Node) -> Node | None:
    """Expose C# arrow clauses stored as values or bodies by this grammar."""
    if node.type == "accessor_declaration":
        body = node.child_by_field_name("body")
        if body is not None and body.type == "arrow_expression_clause":
            return body
    if node.type in {"property_declaration", "indexer_declaration"}:
        return node.child_by_field_name("value")
    if node.type in {
        "operator_declaration",
        "conversion_operator_declaration",
        "method_declaration",
        "local_function_statement",
    }:
        body = node.child_by_field_name("body")
        if body is not None and body.type == "arrow_expression_clause":
            return body
    return None


def parameter_count(function_node: Node) -> int:
    """Count C# parameters, including flattened ``params`` declarations."""
    parameters = function_node.child_by_field_name("parameters")
    if parameters is None or not any(
        child.type != "comment" for child in parameters.named_children
    ):
        return 0
    return sum(child.type == "," for child in parameters.children) + 1


def exported_names(root: Node, source_bytes: bytes) -> set[tuple[str | None, str]]:
    """Return public method identities, including implicit interface members."""
    result = set()
    for node in _walk(root):
        if node.type != "method_declaration":
            continue
        name = node.child_by_field_name("name")
        if name is None:
            continue
        words = _modifiers(node, source_bytes)
        owner = _enclosing_type_node(node)
        if words.intersection({"public", "protected", "internal"}) or (
            owner is not None
            and owner.type == "interface_declaration"
            and "private" not in words
        ):
            result.add((_type_name(owner, source_bytes), _text(name, source_bytes)))
    return result


def file_private(
    record: dict, root: Node, source_bytes: bytes, references: Mapping[str, int]
) -> bool:
    """Honor explicit access and implicit interface visibility for C# members."""
    node = next(
        (item for item in _walk(root) if _matches_record(item, record, source_bytes)),
        None,
    )
    if node is None:
        return references[record["name"]] > 0
    words = _modifiers(node, source_bytes)
    is_private = (
        "private" in words
        or node.type == "destructor_declaration"
        or (
            node.type == "constructor_declaration"
            and not words.intersection({"public", "protected", "internal"})
        )
    )
    owner = _enclosing_type_node(node)
    is_public = bool(words.intersection({"public", "protected", "internal"})) or (
        owner is not None
        and owner.type == "interface_declaration"
        and "private" not in words
    )
    if node.type in {"operator_declaration", "conversion_operator_declaration"}:
        is_public = True
    prop = _property_for_accessor(node)
    if prop is not None:
        prop_words = _modifiers(prop, source_bytes)
        is_private = is_private or "private" in prop_words
        is_public = is_public or bool(
            prop_words.intersection({"public", "protected", "internal"})
        )
    if is_private:
        return True
    if is_public:
        return False
    return references[record["name"]] > 0


def verified_role(
    record: dict, function_node: Node, body: Node | None, source_bytes: bytes
) -> str | None:
    """Tag only trivial accessors, imported handlers, and resolved base methods."""
    if function_node.type in {
        "accessor_declaration",
        "property_declaration",
        "indexer_declaration",
    }:
        return (
            "accessor" if _trivial_accessor(function_node, body, source_bytes) else None
        )
    if function_node.type != "method_declaration":
        return None
    if _has_same_name_base_method(function_node, source_bytes):
        return "override"
    if _is_handler(function_node, source_bytes):
        return "handler"
    return (
        "accessor"
        if _trivial_method_accessor(function_node, body, source_bytes)
        else None
    )


def suppress_accessor_fallback(
    record: dict, function_node: Node, body: Node | None, source_bytes: bytes
) -> bool:
    """Use C# declaration-aware accessor rules instead of the neutral shape guess."""
    return function_node.type in _EXTRA_FUNCTION_NODES | {
        "method_declaration",
        "local_function_statement",
    }


def markers(root: Node, source_bytes: bytes, path: str) -> list[str]:
    """Recognize C# generated-code attributes and conventional generated paths."""
    if path.lower().endswith((".g.cs", ".g.i.cs", ".generated.cs", ".designer.cs")):
        return ["generated"]
    imports, aliases = _imports(root, source_bytes)
    for node in _walk(root):
        if node.type != "attribute":
            continue
        name = _attribute_name(
            _text(node.child_by_field_name("name"), source_bytes), aliases
        )
        if _resolves(name, imports, _GENERATED_ATTRIBUTES):
            return ["generated"]
    return []


def call_site(call_node: Node, source_bytes: bytes) -> dict | None:
    """Normalize C# member, generic, and conditional calls and their receivers."""
    function = call_node.child_by_field_name("function")
    if function is None:
        return None
    receiver = None
    receiver_text = None
    if function.type == "member_access_expression":
        name_node = _generic_identifier(function.child_by_field_name("name"))
        receiver_node = function.child_by_field_name("expression")
        receiver = (
            "self" if _text(receiver_node, source_bytes) in {"this", "base"} else None
        )
        receiver_text = _plain_chain(_text(receiver_node, source_bytes))
    elif function.type == "generic_name":
        name_node = next(
            (child for child in function.named_children if child.type == "identifier"),
            None,
        )
    elif function.type == "conditional_access_expression":
        member = next(
            (
                child
                for child in function.named_children
                if child.type == "member_binding_expression"
            ),
            None,
        )
        name_node = member.child_by_field_name("name") if member is not None else None
        expression = function.named_children[0] if function.named_children else None
        receiver = (
            "self" if _text(expression, source_bytes) in {"this", "base"} else None
        )
    else:
        return None
    if name_node is None:
        return None
    arguments = call_node.child_by_field_name("arguments")
    call = {
        "name": _text(name_node, source_bytes),
        "receiver": receiver,
        "arity": len(arguments.named_children) if arguments is not None else 0,
    }
    if receiver_text is not None:
        call["receiver_text"] = receiver_text
    return call


def _generic_identifier(name_node: Node | None) -> Node | None:
    """Return the method name of `Name<T>`, or the node itself when plain."""
    if name_node is None or name_node.type != "generic_name":
        return name_node
    return next(
        (child for child in name_node.named_children if child.type == "identifier"),
        None,
    )


def _plain_chain(text: str) -> str | None:
    """Return a dotted identifier receiver such as `a.b`; None for any expression."""
    return text if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", text) else None


def _trivial_accessor(node: Node, body: Node | None, source: bytes) -> bool:
    if _leaf_count(node) > 40:
        return False
    if node.type in {"property_declaration", "indexer_declaration"}:
        if body is None or body.type != "arrow_expression_clause":
            return False
        values = body.named_children
        return len(values) == 1 and values[0].type in {
            "identifier",
            "member_access_expression",
            "element_access_expression",
        }
    if body is None:
        return False
    if body.type == "arrow_expression_clause":
        values = body.named_children
        return len(values) == 1 and (
            values[0].type
            in {"identifier", "member_access_expression", "element_access_expression"}
            or _value_assignment(values[0], source)
        )
    statements = [
        child
        for child in body.named_children
        if child.type not in {"line_comment", "block_comment"}
    ]
    if len(statements) != 1:
        return False
    statement = statements[0]
    if statement.type == "return_statement":
        values = statement.named_children
        return len(values) == 1 and values[0].type in {
            "identifier",
            "member_access_expression",
            "element_access_expression",
        }
    assignment = (
        statement.named_children[0]
        if statement.type == "expression_statement"
        and len(statement.named_children) == 1
        else statement
    )
    return _value_assignment(assignment, source)


def _value_assignment(assignment: Node, source: bytes) -> bool:
    if assignment.type != "assignment_expression":
        return False
    left = assignment.child_by_field_name("left")
    right = assignment.child_by_field_name("right")
    return (
        left is not None
        and left.type in {"identifier", "member_access_expression"}
        and right is not None
        and right.type == "identifier"
        and _text(right, source) == "value"
    )


def _trivial_method_accessor(node: Node, body: Node | None, source: bytes) -> bool:
    name = _text(node.child_by_field_name("name"), source).lower()
    if body is None or _leaf_count(node) > 40:
        return False
    statements = [
        child
        for child in body.named_children
        if child.type not in {"line_comment", "block_comment"}
    ]
    if len(statements) != 1:
        return False
    statement = statements[0]
    if name.startswith(("get", "is", "has")) and statement.type == "return_statement":
        values = statement.named_children
        return len(values) == 1 and values[0].type in {
            "identifier",
            "member_access_expression",
        }
    if not name.startswith("set"):
        return False
    params = node.child_by_field_name("parameters")
    if params is None or len(params.named_children) != 1:
        return False
    parameter_name = params.named_children[0].child_by_field_name("name")
    assignment = (
        statement.named_children[0]
        if statement.type == "expression_statement"
        and len(statement.named_children) == 1
        else statement
    )
    if assignment.type != "assignment_expression":
        return False
    left = assignment.child_by_field_name("left")
    right = assignment.child_by_field_name("right")
    return (
        left is not None
        and left.type in {"identifier", "member_access_expression"}
        and right is not None
        and right.type == "identifier"
        and _text(right, source) == _text(parameter_name, source)
    )


def _has_same_name_base_method(node: Node, source: bytes) -> bool:
    owner = _enclosing_type_node(node)
    if owner is None:
        return False
    root = _root(node)
    owner_name = _type_name(owner, source)
    partials = [
        item
        for item in _walk(root)
        if item.type == owner.type and _type_name(item, source) == owner_name
    ]
    base_names = set()
    for declaration in partials:
        base_list = next(
            (
                child
                for child in declaration.named_children
                if child.type == "base_list"
            ),
            None,
        )
        if base_list is not None:
            base_names.update(
                _type_terminal(_text(child, source))
                for child in base_list.named_children
            )
    if not base_names:
        return False
    name = _text(node.child_by_field_name("name"), source)
    arity = _arity(node)
    for base in _walk(root):
        if base.type not in {
            "class_declaration",
            "interface_declaration",
            "record_declaration",
            "struct_declaration",
        }:
            continue
        if _type_name(base, source) not in base_names:
            continue
        is_interface = base.type == "interface_declaration"
        if not is_interface and "override" not in _modifiers(node, source):
            continue
        if any(
            member.type == "method_declaration"
            and _text(member.child_by_field_name("name"), source) == name
            and _arity(member) == arity
            for member in _direct_members(base)
        ):
            return True
    return False


def _matches_record(node: Node, record: dict, source: bytes) -> bool:
    if node.start_byte != record.get("_start_byte"):
        return False
    expected = function_node_name(node, source)
    if expected is None:
        expected = _text(node.child_by_field_name("name"), source)
    return (
        expected == record["name"]
        and _type_name(_enclosing_type_node(node), source) == record["owner"]
    )


def _property_for_accessor(node: Node) -> Node | None:
    if (
        node.type != "accessor_declaration"
        or node.parent is None
        or node.parent.parent is None
    ):
        return None
    prop = node.parent.parent
    return (
        prop if prop.type in {"property_declaration", "indexer_declaration"} else None
    )


def _accessor_node_name(node: Node, source: bytes) -> str | None:
    prop = node.parent.parent if node.parent is not None else None
    if prop is None or prop.type not in {"property_declaration", "indexer_declaration"}:
        return None
    owner = (
        "this"
        if prop.type == "indexer_declaration"
        else _text(prop.child_by_field_name("name"), source)
    )
    return f"{owner}.{_text(node.child_by_field_name('name'), source)}"


def _expression_property_name(node: Node, source: bytes) -> str | None:
    if node.child_by_field_name("value") is None:
        return None
    return f"{_text(node.child_by_field_name('name'), source)}.get"


def _is_handler(node: Node, source: bytes) -> bool:
    imports, aliases = _imports(_root(node), source)
    for attribute_list in (
        child for child in node.children if child.type == "attribute_list"
    ):
        for attribute in (
            child
            for child in attribute_list.named_children
            if child.type == "attribute"
        ):
            name = _attribute_name(
                _text(attribute.child_by_field_name("name"), source), aliases
            )
            if _resolves(name, imports, _HANDLER_ATTRIBUTES):
                return True
    return False


def _imports(root: Node, source: bytes) -> tuple[set[str], dict[str, str]]:
    imports = set()
    aliases = {}
    for node in _walk(root):
        if node.type != "using_directive":
            continue
        value = (
            _text(node, source).strip().removesuffix(";").removeprefix("using ").strip()
        )
        if value.startswith("static "):
            continue
        match = re.fullmatch(r"([A-Za-z_]\w*)\s*=\s*([\w.]+)", value)
        if match:
            aliases[match.group(1)] = match.group(2)
        elif value:
            imports.add(value)
    return imports, aliases


def _attribute_name(name: str, aliases: dict[str, str]) -> str:
    parts = name.split(".")
    if parts[0] in aliases:
        parts[0] = aliases[parts[0]]
    parts[-1] = parts[-1].removesuffix("Attribute")
    return ".".join(parts)


def _resolves(name: str, imports: set[str], known: dict[str, set[str]]) -> bool:
    if any(
        name == f"{namespace}.{attribute}"
        for namespace, attributes in known.items()
        for attribute in attributes
    ):
        return True
    if "." in name:
        return False
    return any(name in known.get(namespace, set()) for namespace in imports)


def _enclosing_type_node(node: Node) -> Node | None:
    parent = node.parent
    while parent is not None:
        if parent.type in {
            "class_declaration",
            "struct_declaration",
            "record_declaration",
            "interface_declaration",
        }:
            return parent
        parent = parent.parent
    return None


def _type_name(node: Node | None, source: bytes) -> str | None:
    return _text(node.child_by_field_name("name"), source) if node else None


def _direct_members(node: Node):
    body = next(
        (child for child in node.named_children if child.type == "declaration_list"),
        None,
    )
    return body.named_children if body is not None else []


def _arity(node: Node) -> int:
    params = node.child_by_field_name("parameters")
    return len(params.named_children) if params is not None else 0


def _type_terminal(value: str) -> str:
    return value.rsplit(".", 1)[-1].split("<", 1)[0]


def _modifiers(node: Node, source: bytes) -> set[str]:
    return {_text(child, source) for child in node.children if child.type == "modifier"}


def _leaf_count(node: Node) -> int:
    return sum(
        1
        for item in _walk(node)
        if not item.children and item.type not in {"line_comment", "block_comment"}
    )


def _walk(root: Node | None):
    if root is None:
        return ()
    if root.parent is None:
        return _walk_root(root)
    return _walk_uncached(root)


@lru_cache(maxsize=4)
def _walk_root(root: Node) -> tuple[Node, ...]:
    """Cache whole-file walks: every method of a file walks its root again."""
    return tuple(_walk_uncached(root))


def _walk_uncached(root: Node):
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


_RETURNING = {
    "method_declaration",
    "local_function_statement",
    "property_declaration",
    "indexer_declaration",
}


def implicit_creation_type(node: Node, source_bytes: bytes) -> str | None:
    """Name the type a target-typed `new(...)` builds from its declaration.

    Only a declared variable, field, property initializer or the return value of
    a method or property names the type; any other position returns None.
    """
    parent = node.parent
    if parent is None:
        return None
    declared = None
    if parent.type == "variable_declarator" and parent.parent is not None:
        declared = parent.parent.child_by_field_name("type")
    elif parent.type == "property_declaration":
        declared = parent.child_by_field_name("type")
    elif parent.type in {"arrow_expression_clause", "return_statement"}:
        declared = _return_type(parent)
    return _declared_type_name(declared, source_bytes)


def _return_type(node: Node) -> Node | None:
    owner = node.parent
    while owner is not None and owner.type not in _RETURNING:
        if owner.type in {"lambda_expression", "anonymous_method_expression"}:
            return None
        owner = owner.parent
    if owner is None:
        return None
    return owner.child_by_field_name("returns") or owner.child_by_field_name("type")


def _declared_type_name(type_node: Node | None, source_bytes: bytes) -> str | None:
    """Return a plain or qualified type name without type arguments or `?`."""
    if type_node is None or type_node.type in {"implicit_type", "predefined_type"}:
        return None
    text = _text(type_node, source_bytes).strip().removesuffix("?")
    name = text.split("<", 1)[0]
    return name if re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*", name) else None
