"""Entity corrections where extraction and Sonar increments disagree.

Every correction is a pure function of the extracted entities and the parsed
source. The shared engine and the fast index stay unchanged (decision D28);
these overlays only shape the entities the score-grade path scores.
"""

from __future__ import annotations

import re
from pathlib import Path

from tree_sitter import Node

from varde_code.complexity import FlowRole, contains, flow_role
from varde_code.model import Entity, EntityKind, Span, span_of
from varde_code.parse import parse_source_for_path

_LABELED_JUMP = re.compile(r"(?:break|continue)\s+'?[A-Za-z_]\w*\s*;?")
_JUMP_STATEMENTS = frozenset({"break_statement", "continue_statement"})
_DO_WHILE = "do_while_statement"
_JAVA = "java"
# Python's extractor gives an `if` its consequence span
# (extract/langs/python.py, span_node=consequence), which is the only extractor
# observed to hide a nesting level this way. Other languages must opt in with
# evidence before the shared-span correction applies to them.
EQUAL_SPAN_LANGUAGES = frozenset({"python"})
_STRUCTURAL_ROLES = frozenset(
    {FlowRole.STRUCTURAL_DECISION, FlowRole.DECISION_CONTAINER, FlowRole.CATCH}
)


def with_labeled_jump_markers(
    entities: list[Entity], source: str | bytes
) -> list[Entity]:
    """Add a jump flow for `break label` where extraction emits only a break.

    SonarSource white paper B1: "goto LABEL, break LABEL, continue LABEL". An
    extractor that already reports the jump keeps the only increment.
    """
    raw = _source_bytes(source)
    counted = [item for item in entities if flow_role(item) == FlowRole.JUMP]
    markers = [
        Entity(
            kind=EntityKind.CONTROL_FLOW,
            name="labeled_jump",
            file_id=item.file_id,
            span=item.span,
            enclosing_function=item.enclosing_function,
            owner_type=item.owner_type,
        )
        for item in entities
        if _is_uncounted_labeled_jump(item, raw, counted)
    ]
    return [*entities, *markers]


def _is_uncounted_labeled_jump(
    entity: Entity, raw: bytes, counted: list[Entity]
) -> bool:
    if entity.kind != EntityKind.CONTROL_FLOW:
        return False
    if entity.name not in _JUMP_STATEMENTS:
        return False
    text = raw[entity.span.start_byte : entity.span.end_byte].decode(
        "utf-8", errors="replace"
    )
    if not _LABELED_JUMP.fullmatch(text.strip()):
        return False
    return not any(
        jump.file_id == entity.file_id and _overlaps(jump.span, entity.span)
        for jump in counted
    )


def with_do_while_markers(
    entities: list[Entity], source: str | bytes, language: str, path: str | Path
) -> list[Entity]:
    """Add the do-while flow Java extraction omits (white paper B1: do while)."""
    if language != _JAVA:
        return list(entities)
    text = _source_bytes(source).decode("utf-8", errors="replace")
    root = parse_source_for_path(language, path, text).root
    functions = [item for item in entities if item.kind == EntityKind.FUNCTION]
    reported = [item.span for item in entities if item.name == _DO_WHILE]
    markers = []
    pending = [root]
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.type != "do_statement":
            continue
        span = span_of(node)
        if any(span == existing for existing in reported):
            continue
        owner = min(
            (item for item in functions if contains(item.span, span)),
            key=lambda item: item.span.end_byte - item.span.start_byte,
            default=None,
        )
        if owner is None:
            continue
        markers.append(
            Entity(
                kind=EntityKind.CONTROL_FLOW,
                name=_DO_WHILE,
                file_id=owner.file_id,
                span=span,
                enclosing_function=owner.name,
                owner_type=owner.owner_type,
            )
        )
    return [*entities, *markers]


def without_else_if_branches(
    entities: list[Entity], source: str | bytes, language: str, path: str | Path
) -> list[Entity]:
    """Fold `else if` into one hybrid branch, as Sonar assesses it.

    SonarSource white paper B1 assesses a hybrid increment for `else if` and
    no nesting increment; an else whose body is an if is not a separate `else`.
    The test is the parse node: an `else_clause` whose first named child is an
    `if_statement`. A braced `else { if ... }` keeps its own `else` branch.
    """
    spans = _else_if_spans(source, language, path)
    if not spans:
        return list(entities)
    return [
        item
        for item in entities
        if (item.span.start_byte, item.span.end_byte) not in spans
    ]


def _else_if_spans(
    source: str | bytes, language: str, path: str | Path
) -> set[tuple[int, int]]:
    text = _source_bytes(source).decode("utf-8", errors="replace")
    root = parse_source_for_path(language, path, text).root
    spans = set()
    pending = [root]
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.type != "else_clause" or not _wraps_if_statement(node):
            continue
        spans.add((node.start_byte, node.end_byte))
    return spans


def _wraps_if_statement(node: Node) -> bool:
    children = node.named_children
    return bool(children) and children[0].type == "if_statement"


def equal_span_nesting_pairs(
    entities: list[Entity], language: str | None
) -> list[tuple[int, int, int]]:
    """Return one entry per nesting level hidden by a shared span.

    Extraction can give a block-wrapped decision the same span as its only
    statement (Python `if` keeps its body span). The engine skips a parent with
    an equal span, while Sonar still nests the inner structure, so each pair of
    distinct structures sharing a span is one missing nesting increment. Limited
    to the languages whose extractor is known to do this.
    """
    if language not in EQUAL_SPAN_LANGUAGES:
        return []
    structures: dict[tuple[int, int, int], set[tuple[EntityKind, str]]] = {}
    for item in entities:
        if flow_role(item) not in _STRUCTURAL_ROLES:
            continue
        key = (item.file_id, item.span.start_byte, item.span.end_byte)
        structures.setdefault(key, set()).add((item.kind, item.name))
    pairs = []
    for key, names in structures.items():
        pairs.extend([key] * (len(names) * (len(names) - 1) // 2))
    return pairs


def _source_bytes(source: str | bytes) -> bytes:
    return source if isinstance(source, bytes) else source.encode("utf-8")


def _overlaps(first: Span, second: Span) -> bool:
    return first.start_byte < second.end_byte and second.start_byte < first.end_byte
