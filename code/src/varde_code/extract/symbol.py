"""Identifier binding and reference extraction helpers."""

from __future__ import annotations

from tree_sitter import Node

from varde_code.model import Symbol, SymbolKind, span_of

DEFAULT_EXCLUDED_FIELDS = frozenset(
    {"name", "function", "method", "property", "field", "constructor", "declarator"}
)
GENERIC_LANGUAGES = frozenset(
    {
        "bash",
        "c",
        "cpp",
        "dart",
        "elixir",
        "haskell",
        "lua",
        "php",
        "ruby",
        "scala",
        "solidity",
        "swift",
    }
)
JSTS_NAME_POSITION_LANGUAGES = frozenset(
    {
        "csharp",
        "go",
        "java",
        "javascript",
        "typescript",
    }
)
JSTS_TYPE_CONTEXT_OVERRIDE_LANGUAGES = frozenset({"java", "csharp"})
IMPORT_BINDING_LANGUAGES = frozenset({"javascript", "typescript", "tsx"})
IDENTIFIER_KINDS = {
    "bash": frozenset({"variable_name"}),
    "haskell": frozenset({"variable"}),
    "php": frozenset({"name", "variable_name"}),
    "swift": frozenset({"simple_identifier"}),
}
C_RESERVED_KEYWORDS = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "do",
        "switch",
        "case",
        "default",
        "return",
        "break",
        "continue",
        "goto",
        "sizeof",
        "typedef",
        "struct",
        "union",
        "enum",
        "class",
        "template",
        "typename",
        "namespace",
        "using",
        "new",
        "delete",
        "throw",
        "try",
        "catch",
        "operator",
        "const",
        "static",
        "public",
        "private",
        "protected",
        "virtual",
        "friend",
        "inline",
        "explicit",
        "constexpr",
        "noexcept",
        "static_assert",
    }
)


def extract_symbols(
    root: Node,
    file_id: int = 0,
    identifier_kinds: frozenset[str] = frozenset({"identifier"}),
    type_kinds: frozenset[str] = frozenset(),
    excluded_fields: frozenset[str] | None = None,
    language: str | None = None,
) -> list[Symbol]:
    symbols: list[Symbol] = []
    fields_to_exclude = (
        DEFAULT_EXCLUDED_FIELDS if excluded_fields is None else excluded_fields
    )
    if language is not None:
        identifier_kinds = IDENTIFIER_KINDS.get(language, frozenset({"identifier"}))

    def walk(
        node: Node,
        in_type: bool = False,
        parent_is_type: bool = False,
    ) -> None:
        name = ""
        if node.type in identifier_kinds and (
            not in_type or language in JSTS_TYPE_CONTEXT_OVERRIDE_LANGUAGES
        ):
            parent = node.parent
            field = None
            if parent is not None and hasattr(parent, "field_name_for_child"):
                child_index = next(
                    (
                        index
                        for index, child in enumerate(parent.children)
                        if child == node
                    ),
                    None,
                )
                if child_index is not None:
                    field = parent.field_name_for_child(child_index)
            if language in GENERIC_LANGUAGES:
                dart_call_name = language == "dart" and _is_dart_call_name(node, parent)
                variable_name_child = (
                    node.type == "name"
                    and parent is not None
                    and parent.type == "variable_name"
                )
                if (
                    dart_call_name
                    or _is_generic_name_position(node, parent, field)
                    or variable_name_child
                ):
                    name_allowed = False
                else:
                    name_allowed = True
            elif language == "tsx":
                jsx_tag_name = parent is not None and parent.type in {
                    "jsx_opening_element",
                    "jsx_closing_element",
                }
                name_allowed = jsx_tag_name or not _is_jsts_entity_name_position(
                    parent, field
                )
            elif language in JSTS_NAME_POSITION_LANGUAGES or language == "rust":
                name_allowed = not _is_jsts_entity_name_position(parent, field)
            else:
                name_allowed = field not in fields_to_exclude
            if name_allowed:
                value = node.text
                name = (
                    value.decode("utf-8", errors="replace")
                    if isinstance(value, bytes)
                    else str(value)
                )
                if language in {"c", "cpp"} and name in C_RESERVED_KEYWORDS:
                    name_allowed = False
            if name_allowed:
                kind = (
                    SymbolKind.BINDING
                    if _is_import_binding(node, parent, language)
                    else SymbolKind.REFERENCE
                )
                symbols.append(Symbol(kind, name, file_id, span_of(node)))
        if language in {"python", "rust"}:
            child_type = in_type or parent_is_type
            child_parent_is_type = node.type in type_kinds
        else:
            child_type = in_type or node.type in type_kinds
            child_parent_is_type = False
        for child in node.children:
            walk(child, child_type, child_parent_is_type)

    walk(root)
    return symbols


def _is_generic_name_position(
    node: Node, parent: Node | None, field: str | None
) -> bool:
    if parent is None:
        return True
    if field in DEFAULT_EXCLUDED_FIELDS:
        return True
    return "parameter" in parent.type


def _is_dart_call_name(node: Node, parent: Node | None) -> bool:
    if parent is None:
        return False
    if parent.type == "unconditional_assignable_selector":
        return True
    named_children = parent.named_children
    index = next((i for i, child in enumerate(named_children) if child == node), None)
    if index is None:
        return False
    selector_text = (
        named_children[index + 1].text if index + 1 < len(named_children) else None
    )
    return (
        index + 1 < len(named_children)
        and named_children[index + 1].type == "selector"
        and selector_text is not None
        and selector_text.lstrip().startswith((b"(", b"<"))
    )


def _is_jsts_entity_name_position(parent: Node | None, field: str | None) -> bool:
    if parent is None:
        return False
    named_fields = {
        "variable_declarator",
        "function_declaration",
        "class_declaration",
        "interface_declaration",
        "method_definition",
        "function_expression",
        "generator_function_declaration",
        "export_specifier",
    }
    if parent.type in named_fields:
        return field == "name"
    if parent.type in {"required_parameter", "optional_parameter"}:
        return field == "pattern"
    if parent.type == "call_expression":
        return field == "function"
    if parent.type == "member_expression":
        return field == "property"
    return False


def _is_import_binding(node: Node, parent: Node | None, language: str | None) -> bool:
    if language not in IMPORT_BINDING_LANGUAGES or parent is None:
        return False
    if parent.type == "import_specifier":
        alias = parent.child_by_field_name("alias")
        name = parent.child_by_field_name("name")
        return alias == node or alias is None and name == node
    if parent.type == "import_clause":
        return True
    return parent.type == "namespace_import" and node.type in {"identifier", "name"}
