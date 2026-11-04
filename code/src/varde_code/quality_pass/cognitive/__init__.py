"""Score-grade cognitive complexity over the shared complexity engine."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from varde_code.complexity import (
    FlowRole,
    FunctionComplexity,
    flow_role,
    function_complexities,
)
from varde_code.model import Entity, EntityKind, span_of
from varde_code.parse import parse_source_for_path

from .entities import (
    equal_span_nesting_pairs,
    with_do_while_markers,
    with_labeled_jump_markers,
    without_else_if_branches,
)
from .logical import logical_sequence_totals

# The extraction engine emits recursion markers for Python and Rust. Other
# release-language plugins expose call entities but no marker, so synthesize
# one for a direct self-call. The engine then applies its existing recursion
# rule without changing fast-index behavior.
COGNITIVE_OVERLAYS = {
    "direct_recursive_call": {"self_receivers": frozenset({"self", "this", "this->"})},
    "cpp_lambda_nesting": {
        "language": "cpp",
        "node_types": frozenset({"lambda_expression"}),
    },
    "java_else_loop": {
        "language": "java",
        "increment": -1,
        "loop_nodes": frozenset(
            {
                "for_statement",
                "enhanced_for_statement",
                "while_statement",
                "do_statement",
            }
        ),
    },
}
OVERLAY_VERSION = "sonar-cognitive-overlay-1"


def _unqualified_self_call(call: Entity, source: str | bytes) -> bool:
    raw = source if isinstance(source, bytes) else source.encode("utf-8")
    call_text = raw[call.span.start_byte : call.span.end_byte].decode(
        "utf-8", errors="replace"
    )
    callee = call_text.split("(", 1)[0].strip()
    receiver = COGNITIVE_OVERLAYS["direct_recursive_call"]["self_receivers"]
    if callee == call.name:
        return True
    # CALL entities do not include resolved receiver identity. Qualified class
    # aliases are therefore excluded; self/this spellings are the supported form.
    return any(
        callee in {f"{name}{call.name}", f"{name}.{call.name}"} for name in receiver
    )


def _direct_recursion_markers(
    entities: list[Entity], source: str | bytes
) -> list[Entity]:
    functions = [item for item in entities if item.kind == EntityKind.FUNCTION]
    existing = [
        item
        for item in entities
        if item.kind == EntityKind.CONTROL_FLOW and item.name == "recursive_call"
    ]
    calls = [item for item in entities if item.kind == EntityKind.CALL]
    markers = []
    for call in calls:
        if not _unqualified_self_call(call, source):
            continue
        owners = [
            function
            for function in functions
            if function.file_id == call.file_id
            and function.name == call.name
            and function.span.start_byte <= call.span.start_byte
            and call.span.end_byte <= function.span.end_byte
        ]
        owner = min(
            owners,
            key=lambda item: item.span.end_byte - item.span.start_byte,
            default=None,
        )
        if owner is None or any(
            marker.file_id == call.file_id
            and owner.span.start_byte <= marker.span.start_byte
            and marker.span.end_byte <= owner.span.end_byte
            for marker in existing
        ):
            continue
        markers.append(
            Entity(
                kind=EntityKind.CONTROL_FLOW,
                name="recursive_call",
                file_id=call.file_id,
                span=call.span,
                enclosing_function=owner.name,
                owner_type=owner.owner_type,
            )
        )
    return markers


def _anonymous_boundaries(
    entities: list[Entity], source: str | bytes, language: str, path: str | Path
) -> list[Entity]:
    overlay = COGNITIVE_OVERLAYS.get("cpp_lambda_nesting", {})
    node_types = (
        overlay.get("node_types", frozenset())
        if language == overlay.get("language")
        else frozenset()
    )
    if not node_types:
        return []
    text = (
        source.decode("utf-8", errors="replace")
        if isinstance(source, bytes)
        else source
    )
    root = parse_source_for_path(language, path, text).root
    functions = [item for item in entities if item.kind == EntityKind.FUNCTION]
    existing = {
        (item.file_id, item.span.start_byte, item.span.end_byte)
        for item in entities
        if item.kind == EntityKind.CALLABLE_BOUNDARY
    }
    pending = [root]
    boundaries = []
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.type not in node_types:
            continue
        span = span_of(node)
        owner = min(
            (
                item
                for item in functions
                if item.span.start_byte <= span.start_byte
                and span.end_byte <= item.span.end_byte
            ),
            key=lambda item: item.span.end_byte - item.span.start_byte,
            default=None,
        )
        if owner is None or (owner.file_id, span.start_byte, span.end_byte) in existing:
            continue
        boundaries.append(
            Entity(
                kind=EntityKind.CALLABLE_BOUNDARY,
                name="",
                file_id=owner.file_id,
                span=span,
                enclosing_function=owner.name,
                owner_type=owner.owner_type,
            )
        )
    return boundaries


def _with_logical_sequences(
    results: list[FunctionComplexity],
    entities: list[Entity],
    source: str | bytes,
    language: str,
    path: str | Path,
) -> list[FunctionComplexity]:
    totals = logical_sequence_totals(
        _source_text(source), language, path, [item.span for item in results]
    )
    if not totals:
        return results
    without_logical = [
        item for item in entities if flow_role(item) != FlowRole.LOGICAL_SEQUENCE
    ]
    engine = {
        (item.file_id, item.span.start_byte, item.span.end_byte): item.cognitive
        for item in function_complexities(without_logical)
    }
    adjusted = []
    for item in results:
        key = (item.span.start_byte, item.span.end_byte)
        engine_sequences = item.cognitive - engine[(item.file_id, *key)]
        adjusted.append(
            replace(item, cognitive=item.cognitive - engine_sequences + totals[key])
        )
    return adjusted


def _with_equal_span_nesting(
    results: list[FunctionComplexity], entities: list[Entity], language: str | None
) -> list[FunctionComplexity]:
    pairs = equal_span_nesting_pairs(entities, language)
    if not pairs:
        return results
    return [
        replace(
            item,
            cognitive=item.cognitive
            + sum(
                item.file_id == file_id
                and item.span.start_byte <= start
                and end <= item.span.end_byte
                for file_id, start, end in pairs
            ),
        )
        for item in results
    ]


def _source_text(source: str | bytes) -> str:
    if isinstance(source, bytes):
        return source.decode("utf-8", errors="replace")
    return source


def _java_direct_else_loop_counts(
    entities: list[Entity], source: str | bytes, path: str | Path
) -> dict[tuple[int, int], int]:
    overlay = COGNITIVE_OVERLAYS["java_else_loop"]
    functions = [item for item in entities if item.kind == EntityKind.FUNCTION]
    root = parse_source_for_path("java", path, _source_text(source)).root
    pending = [root]
    affected: dict[tuple[int, int], int] = {}
    while pending:
        node = pending.pop()
        pending.extend(node.children)
        if node.type != "if_statement":
            continue
        alternative = node.child_by_field_name("alternative")
        if alternative is None or alternative.type != "block":
            continue
        loop_count = sum(
            child.type in overlay["loop_nodes"] for child in alternative.named_children
        )
        if not loop_count:
            continue
        owner = next(
            (
                function
                for function in functions
                if function.span.start_byte <= node.start_byte
                and node.end_byte <= function.span.end_byte
            ),
            None,
        )
        if owner is not None:
            key = (owner.file_id, owner.span.start_byte)
            affected[key] = affected.get(key, 0) + loop_count
    return affected


def score_grade_complexities(
    entities: list[Entity],
    *,
    source: str | bytes | None = None,
    language: str | None = None,
    path: str | Path = "<memory>",
) -> list[FunctionComplexity]:
    """Score named and test callables without changing fast-index semantics."""
    normalized = [replace(entity, is_test=False) for entity in entities]
    if source is not None and language is not None:
        normalized.extend(_direct_recursion_markers(normalized, source))
        normalized.extend(_anonymous_boundaries(normalized, source, language, path))
        normalized = with_labeled_jump_markers(normalized, source)
        normalized = with_do_while_markers(normalized, source, language, path)
        normalized = without_else_if_branches(normalized, source, language, path)
    results = function_complexities(normalized)
    if source is not None and language is not None:
        results = _with_logical_sequences(results, normalized, source, language, path)
    results = _with_equal_span_nesting(results, normalized, language)
    if source is None or language != COGNITIVE_OVERLAYS["java_else_loop"]["language"]:
        return results
    adjustments = _java_direct_else_loop_counts(normalized, source, path)
    increment = COGNITIVE_OVERLAYS["java_else_loop"]["increment"]
    return [
        replace(
            item,
            cognitive=max(
                0,
                item.cognitive
                + increment * adjustments.get((item.file_id, item.span.start_byte), 0),
            ),
        )
        if (item.file_id, item.span.start_byte) in adjustments
        else item
        for item in results
    ]
