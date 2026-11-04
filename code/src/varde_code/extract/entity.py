"""Tree walk that emits entities from language visit tables."""

from __future__ import annotations

from dataclasses import dataclass

from tree_sitter import Node

from varde_code.extract.adapter import ParserAdapter
from varde_code.extract.langs import tables_for
from varde_code.extract.langs.base import LanguageTables, VisitRule, _field, _text
from varde_code.model import Entity, EntityKind, ExtractOutput, Span, span_of

from .minhash import body_minhash

MAX_WALK_DEPTH = 2000


@dataclass
class EntityExtractOutput(ExtractOutput):
    has_parse_error: bool = False


def extract_file(
    path: str, source: str, language: str, file_id: int = 0
) -> EntityExtractOutput:
    """Extract table-driven entities and identifier references from source."""
    from varde_code.parse import parse_source_for_path

    parsed = parse_source_for_path(language, path, source, parser=ParserAdapter())
    tables = tables_for(parsed.lang)
    output = EntityExtractOutput(has_parse_error=parsed.has_error())
    enclosing: list[str] = []
    type_scope: list[str] = []

    def walk(node: Node, in_type: bool, depth: int) -> None:
        if depth >= MAX_WALK_DEPTH:
            return
        kind = node.type
        rules: tuple[VisitRule, ...] | None = (
            tables.visit_node(node) if tables.visit_node is not None else None
        )
        if rules is None:
            rule = tables.visits.get(kind)
            rules = (rule,) if rule is not None else ()
        for rule in rules:
            name_node = _field(node, rule.name_field)
            if rule.name_kind and name_node is None:
                name_node = next(
                    (
                        child
                        for child in node.named_children
                        if child.type == rule.name_kind
                    ),
                    None,
                )
            name = rule.literal if rule.literal is not None else _text(name_node)
            body = _text(node)
            span = span_of(rule.span_node or node)
            span_end_node = rule.span_end_node
            if isinstance(span_end_node, Node):
                start: Node = node
                if isinstance(rule.span_node, Node):
                    start = rule.span_node
                if isinstance(rule.span_start_node, Node):
                    start = rule.span_start_node
                end = span_end_node
                start_row, start_column = start.start_point
                end_row, end_column = end.end_point
                span = Span(
                    start.start_byte,
                    end.end_byte,
                    start_row + 1,
                    start_column,
                    end_row + 1,
                    end_column,
                )
            output.entities.append(
                Entity(
                    kind=rule.kind,
                    name=name,
                    file_id=file_id,
                    span=span,
                    enclosing_function=enclosing[-1] if enclosing else None,
                    body_minhash=body_minhash(body)
                    if rule.kind == EntityKind.FUNCTION
                    else None,
                    is_async=has_async_modifier(node)
                    if rule.kind == EntityKind.FUNCTION
                    else None,
                    is_test=node_is_test(node, tables),
                    owner_type=type_scope[-1] if type_scope else None,
                )
            )
        is_function = kind in tables.function_scopes
        is_type = kind in tables.type_scopes
        if is_function:
            name = (
                tables.function_name(node)
                if tables.function_name
                else _text(_field(node, "name"))
            )
            enclosing.append(name or "")
        if is_type:
            name = (
                tables.type_name(node)
                if tables.type_name
                else _text(_field(node, "name"))
            )
            type_scope.append(name or "")
        node_type = kind in tables.type_kinds
        for child in node.children:
            walk(child, in_type or node_type, depth + 1)
        if is_type:
            type_scope.pop()
        if is_function:
            enclosing.pop()

    walk(parsed.root, False, 0)
    if parsed.lang == "python":
        from .recursion import extract_python as extract_python_recursion

        output.entities.extend(extract_python_recursion(parsed.root, file_id))
    elif parsed.lang == "rust":
        from .recursion import extract_rust as extract_rust_recursion

        output.entities.extend(extract_rust_recursion(parsed.root, file_id))
    if parsed.lang in {"c", "cpp", "csharp", "swift", "haskell"}:
        from .preproc import attribute_top_level_regions
        from .preproc import scan as scan_preprocessor

        preprocessor_entities = scan_preprocessor(
            source, file_id, haskell_cpp=parsed.lang == "haskell"
        )
        attribute_top_level_regions(preprocessor_entities, output.entities)
        output.entities.extend(preprocessor_entities)
    from .symbol import extract_symbols

    excluded_symbol_fields: frozenset[str] | None = None
    if parsed.lang == "python":
        excluded_symbol_fields = frozenset(
            {"method", "property", "field", "constructor", "declarator"}
        )
    output.symbols.extend(
        extract_symbols(
            parsed.root,
            file_id,
            type_kinds=tables.type_kinds,
            excluded_fields=excluded_symbol_fields,
            language=parsed.lang,
        )
    )
    return output


def has_async_modifier(node: Node) -> bool:
    return any(
        child.type == "async"
        or (child.type == "modifier" and _text(child).strip() in {"async", "suspend"})
        for child in node.children
    )


def node_is_test(node: Node, tables: LanguageTables | None = None) -> bool:
    if tables is not None and tables.test_node is not None:
        return bool(tables.test_node(node))
    return any(
        _text(child).strip().lower() in {"test", "pytest", "istest"}
        for child in node.children
        if "decorator" in child.type or "attribute" in child.type
    )
