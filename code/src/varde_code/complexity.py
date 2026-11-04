"""Language-neutral complexity metrics over extracted entities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from varde_code.extract.langs.base import registered_flow_role
from varde_code.model import Entity, EntityKind, Span


class FlowRole(StrEnum):
    STRUCTURAL_DECISION = "structural_decision"
    DECISION_CONTAINER = "decision_container"
    DECISION_ARM = "decision_arm"
    ELSE_IF = "else_if"
    LOGICAL_SEQUENCE = "logical_sequence"
    ELSE = "else"
    JUMP = "jump"
    RECURSION = "recursion"
    PREPROC = "preproc"
    COGNITIVE_DECISION = "cognitive_decision"
    LEGACY_ONLY = "legacy_only"
    LEGACY_NESTING = "legacy_nesting"
    CATCH = "catch"
    IGNORED = "ignored"
    UNKNOWN = "unknown"


class ComplexityConfidence(StrEnum):
    HIGH = "high"
    LOW = "low"


@dataclass(frozen=True)
class ComplexityConfidenceReason:
    kind: str
    name: str

    @classmethod
    def unknown_control_flow_role(cls, name: str) -> ComplexityConfidenceReason:
        return cls("unknown_control_flow_role", name)

    @classmethod
    def incomplete_decision_container(cls, name: str) -> ComplexityConfidenceReason:
        return cls("incomplete_decision_container", name)


@dataclass(frozen=True)
class FunctionComplexity:
    name: str
    owner_type: str | None
    file_id: int
    span: Span
    cyclomatic: int
    cognitive: int
    max_nesting: int
    line_span: int
    byte_size: int
    confidence: ComplexityConfidence
    confidence_reasons: list[ComplexityConfidenceReason]


COMPLEXITY_ONLY_NAMES = frozenset(
    {
        "else_branch",
        "goto_jump",
        "labeled_jump",
        "recursive_call",
        "preproc_if",
        "preproc_branch",
        "cognitive_decision",
        "legacy_nesting",
        "pattern_logical_and",
        "pattern_logical_or",
    }
)
COMPLEXITY_MARKER_NAMES = frozenset({"negation_break", "compensating_usage"})
LEGACY_ONLY_NAMES = frozenset({"guard_clause"})

_STRUCTURAL_DECISIONS = frozenset(
    {
        "if",
        "unless",
        "if_statement",
        "if_expression",
        "if_modifier",
        "unless_modifier",
        "conditional",
        "conditional_expression",
        "ternary_expression",
        "for",
        "for_statement",
        "for_expression",
        "for_in_statement",
        "for_of_statement",
        "for_range_loop",
        "foreach_statement",
        "enhanced_for_statement",
        "while",
        "until",
        "while_statement",
        "while_expression",
        "while_modifier",
        "until_modifier",
        "repeat_statement",
        "repeat_while_statement",
        "do_while_statement",
        "loop_expression",
        "guard_statement",
        "guards",
        "rescue_modifier",
    }
)
_DECISION_CONTAINERS = frozenset(
    {
        "switch_statement",
        "switch_expression",
        "expression_switch_statement",
        "type_switch_statement",
        "case",
        "match_expression",
        "when_expression",
        "select_statement",
        "cond",
        "receive",
    }
)
_IGNORED_FLOWS = frozenset(
    {
        "return",
        "return_statement",
        "return_expression",
        "break",
        "break_statement",
        "break_expression",
        "continue",
        "continue_statement",
        "continue_expression",
        "next",
        "redo",
        "retry",
        "yield",
        "jump_expression",
        "control_transfer_statement",
        "try",
        "try_statement",
        "try_expression",
        "try_with_resources_statement",
        "with",
        "with_statement",
        "else",
        "compensating_usage",
        "negation_break",
        "preproc_include_guard",
        "begin",
        "do_statement",
        "let_in",
        "label_statement",
        "go_statement",
        "defer_statement",
    }
)


def flow_role(entity: Entity) -> FlowRole | None:
    """Normalize an extracted entity into a complexity role."""
    if entity.kind == EntityKind.CATCH:
        return (
            FlowRole.LEGACY_ONLY
            if entity.name == "legacy_catch_clause"
            else FlowRole.CATCH
        )
    if entity.kind == EntityKind.CONTROL_FLOW:
        return control_flow_role(entity.name)
    return None


def control_flow_role(name: str) -> FlowRole:
    """Normalize a language-specific control-flow node or keyword."""
    normalized = name.strip().lower()
    registered = registered_flow_role(normalized)
    if registered is not None:
        normalized_role = (
            registered.strip()
            .rsplit(".", 1)[-1]
            .lower()
            .replace("-", "_")
            .replace("_", "")
        )
        for role in FlowRole:
            if normalized_role in {
                role.value.replace("_", ""),
                role.name.lower().replace("_", ""),
            }:
                return role
        return FlowRole.UNKNOWN
    if normalized in _STRUCTURAL_DECISIONS:
        return FlowRole.STRUCTURAL_DECISION
    if normalized in _DECISION_CONTAINERS:
        return FlowRole.DECISION_CONTAINER
    if normalized in {"case_statement", "case_item", "match_arm"}:
        return FlowRole.DECISION_ARM
    if normalized in {"elif_clause", "elseif_statement"}:
        return FlowRole.ELSE_IF
    if normalized in LEGACY_ONLY_NAMES:
        return FlowRole.LEGACY_ONLY
    if normalized in {"else_clause", "else_statement", "else_branch"}:
        return FlowRole.ELSE
    if normalized in {"goto_statement", "goto_jump", "labeled_jump"}:
        return FlowRole.JUMP
    if normalized == "cognitive_decision":
        return FlowRole.COGNITIVE_DECISION
    if normalized == "legacy_nesting":
        return FlowRole.LEGACY_NESTING
    if normalized == "recursive_call":
        return FlowRole.RECURSION
    if normalized in {"preproc_if", "preproc_branch"}:
        return FlowRole.PREPROC
    if normalized in {"logical_and", "logical_or"}:
        return FlowRole.LOGICAL_SEQUENCE
    if normalized in _IGNORED_FLOWS:
        return FlowRole.IGNORED
    return FlowRole.UNKNOWN


def function_complexities(entities: list[Entity]) -> list[FunctionComplexity]:
    """Calculate per-callable metrics from entities spanning one or more files."""
    callables = [
        entity
        for entity in entities
        if entity.kind == EntityKind.FUNCTION and not entity.is_test
    ]
    boundaries = [
        entity
        for entity in entities
        if entity.kind == EntityKind.CALLABLE_BOUNDARY
        and not entity.is_test
        and not any(
            callable_entity.file_id == entity.file_id
            and callable_entity.span == entity.span
            for callable_entity in callables
        )
    ]
    callables.extend(boundaries)

    roles_by_file: dict[int, list[tuple[Entity, FlowRole]]] = {}
    for entity in entities:
        if entity.is_test:
            continue
        role = flow_role(entity)
        if role is not None:
            roles_by_file.setdefault(entity.file_id, []).append((entity, role))

    results = []
    for callable_entity in callables:
        flows = [
            (entity, role)
            for entity, role in roles_by_file.get(callable_entity.file_id, [])
            if contains(callable_entity.span, entity.span)
            or entity.name == "compensating_usage"
            and contains(entity.span, callable_entity.span)
        ]
        results.append(metrics_for(callable_entity, flows, callables))
    return results


def metrics_for(
    callable_entity: Entity,
    flows: list[tuple[Entity, FlowRole]],
    callables: list[Entity],
) -> FunctionComplexity:
    own_flows = [
        (flow, role)
        for flow, role in flows
        if attributed_to(flow, callable_entity, callables)
    ]
    events = complexity_events(flows)
    own_events = complexity_events(own_flows)
    reasons = confidence_reasons(own_flows)
    return FunctionComplexity(
        name=callable_name(callable_entity),
        owner_type=callable_entity.owner_type,
        file_id=callable_entity.file_id,
        span=callable_entity.span,
        cyclomatic=cyclomatic_complexity(own_events),
        cognitive=cognitive_complexity(callable_entity, events, callables),
        max_nesting=maximum_nesting(own_events),
        line_span=line_span(callable_entity.span),
        byte_size=span_size(callable_entity.span),
        confidence=ComplexityConfidence.LOW if reasons else ComplexityConfidence.HIGH,
        confidence_reasons=reasons,
    )


def callable_name(callable_entity: Entity) -> str:
    if callable_entity.kind == EntityKind.CALLABLE_BOUNDARY:
        return f"<anonymous>@{callable_entity.span.start_line}:{callable_entity.span.start_col}"
    return callable_entity.name


def attributed_to(
    flow: Entity, callable_entity: Entity, callables: list[Entity]
) -> bool:
    if flow.file_id != callable_entity.file_id or not contains(
        callable_entity.span, flow.span
    ):
        return False
    containing = [
        candidate
        for candidate in callables
        if candidate.file_id == flow.file_id and contains(candidate.span, flow.span)
    ]
    smallest = min(containing, key=lambda item: span_size(item.span), default=None)
    return smallest is not None and smallest.span == callable_entity.span


def complexity_events(
    flows: list[tuple[Entity, FlowRole]],
) -> list[tuple[Entity, FlowRole]]:
    counted = {
        FlowRole.STRUCTURAL_DECISION,
        FlowRole.DECISION_CONTAINER,
        FlowRole.DECISION_ARM,
        FlowRole.ELSE_IF,
        FlowRole.LOGICAL_SEQUENCE,
        FlowRole.CATCH,
        FlowRole.ELSE,
        FlowRole.JUMP,
        FlowRole.RECURSION,
        FlowRole.PREPROC,
        FlowRole.COGNITIVE_DECISION,
        FlowRole.LEGACY_ONLY,
        FlowRole.LEGACY_NESTING,
    }
    return [
        (entity, role)
        for entity, role in flows
        if role in counted or entity.name in {"negation_break", "compensating_usage"}
    ]


def confidence_reasons(
    flows: list[tuple[Entity, FlowRole]],
) -> list[ComplexityConfidenceReason]:
    reasons: list[ComplexityConfidenceReason] = []
    for entity, role in flows:
        if role == FlowRole.UNKNOWN:
            push_unique_reason(
                reasons,
                ComplexityConfidenceReason.unknown_control_flow_role(entity.name),
            )
        if incomplete_container(entity, flows):
            push_unique_reason(
                reasons,
                ComplexityConfidenceReason.incomplete_decision_container(entity.name),
            )
    return reasons


def push_unique_reason(
    reasons: list[ComplexityConfidenceReason], reason: ComplexityConfidenceReason
) -> None:
    if reason not in reasons:
        reasons.append(reason)


def maximum_nesting(events: list[tuple[Entity, FlowRole]]) -> int:
    nesting_roles = {
        FlowRole.STRUCTURAL_DECISION,
        FlowRole.DECISION_CONTAINER,
        FlowRole.CATCH,
        FlowRole.LEGACY_ONLY,
        FlowRole.LEGACY_NESTING,
    }
    return max(
        (
            structural_depth(flow, events, include_hybrid=False)
            for flow, role in events
            if role in nesting_roles
        ),
        default=0,
    )


def cognitive_complexity(
    callable_entity: Entity,
    events: list[tuple[Entity, FlowRole]],
    callables: list[Entity],
) -> int:
    score = 0
    for flow, role in events:
        if role in {
            FlowRole.STRUCTURAL_DECISION,
            FlowRole.DECISION_CONTAINER,
            FlowRole.CATCH,
            FlowRole.COGNITIVE_DECISION,
        }:
            score += 1 + structural_depth(flow, events, include_hybrid=True)
            score += callable_depth(callable_entity, flow, callables, events)
        elif role in {
            FlowRole.ELSE_IF,
            FlowRole.ELSE,
            FlowRole.JUMP,
            FlowRole.RECURSION,
        }:
            score += 1
        elif role == FlowRole.PREPROC:
            if flow.name == "preproc_if":
                score += 1 + structural_depth(flow, events, include_hybrid=True)
                score += callable_depth(callable_entity, flow, callables, events)
            else:
                score += 1
        elif role == FlowRole.LOGICAL_SEQUENCE:
            score += logical_sequence_point(flow, events, callable_entity, callables)
    return score


def cyclomatic_complexity(events: list[tuple[Entity, FlowRole]]) -> int:
    counted = {
        FlowRole.STRUCTURAL_DECISION,
        FlowRole.DECISION_ARM,
        FlowRole.ELSE_IF,
        FlowRole.LOGICAL_SEQUENCE,
        FlowRole.CATCH,
        FlowRole.LEGACY_ONLY,
    }
    return 1 + sum(role in counted for _, role in events)


def structural_depth(
    flow: Entity,
    events: list[tuple[Entity, FlowRole]],
    *,
    include_hybrid: bool,
) -> int:
    return sum(
        is_structural_parent(parent, role, flow, include_hybrid=include_hybrid)
        for parent, role in events
    )


def is_structural_parent(
    parent: Entity,
    role: FlowRole,
    flow: Entity,
    *,
    include_hybrid: bool,
) -> bool:
    if parent.span == flow.span or not contains(parent.span, flow.span):
        return False
    if role in {
        FlowRole.STRUCTURAL_DECISION,
        FlowRole.DECISION_CONTAINER,
        FlowRole.CATCH,
    }:
        return True
    if not include_hybrid and role in {FlowRole.LEGACY_ONLY, FlowRole.LEGACY_NESTING}:
        return True
    return include_hybrid and role in {
        FlowRole.ELSE,
        FlowRole.ELSE_IF,
        FlowRole.PREPROC,
        FlowRole.COGNITIVE_DECISION,
    }


def callable_depth(
    scorer: Entity,
    flow: Entity,
    callables: list[Entity],
    events: list[tuple[Entity, FlowRole]],
) -> int:
    return sum(
        candidate.file_id == scorer.file_id
        and candidate.span != scorer.span
        and contains(scorer.span, candidate.span)
        and contains(candidate.span, flow.span)
        and not any(
            marker.name == "compensating_usage"
            and contains(marker.span, candidate.span)
            for marker, _ in events
        )
        for candidate in callables
    )


def logical_sequence_point(
    flow: Entity,
    counted: list[tuple[Entity, FlowRole]],
    scorer: Entity,
    callables: list[Entity],
) -> int:
    owner = innermost_callable(flow, scorer, callables)
    parents = [
        parent
        for parent, role in counted
        if role == FlowRole.LOGICAL_SEQUENCE
        and parent.span != flow.span
        and contains(parent.span, flow.span)
        and innermost_callable(parent, scorer, callables) == owner
        and not any(
            marker.name == "negation_break"
            and contains(marker.span, flow.span)
            and contains(parent.span, marker.span)
            for marker, _ in counted
        )
    ]
    nearest = min(parents, key=lambda item: span_size(item.span), default=None)
    if (
        nearest is not None
        and nearest.name.strip().lower() == flow.name.strip().lower()
    ):
        return 0
    return 1


def innermost_callable(flow: Entity, scorer: Entity, callables: list[Entity]) -> Span:
    candidates = [
        candidate
        for candidate in callables
        if candidate.file_id == scorer.file_id
        and contains(scorer.span, candidate.span)
        and contains(candidate.span, flow.span)
    ]
    smallest = min(candidates, key=lambda item: span_size(item.span), default=None)
    return scorer.span if smallest is None else smallest.span


def incomplete_container(entity: Entity, flows: list[tuple[Entity, FlowRole]]) -> bool:
    if entity.kind != EntityKind.CONTROL_FLOW or not is_decision_container(entity.name):
        return False
    return not any(
        role == FlowRole.DECISION_ARM
        and candidate.span != entity.span
        and contains(entity.span, candidate.span)
        for candidate, role in flows
    )


def is_decision_container(name: str) -> bool:
    return normalize_control_flow_name(name) in _DECISION_CONTAINERS


def normalize_control_flow_name(name: str) -> str:
    return name.strip().lower()


def contains(outer: Span, inner: Span) -> bool:
    return outer.start_byte <= inner.start_byte and outer.end_byte >= inner.end_byte


def span_size(span: Span) -> int:
    return min(max(span.end_byte - span.start_byte, 0), 0xFFFFFFFF)


def line_span(span: Span) -> int:
    return min(max(span.end_line - span.start_line, 0) + 1, 0xFFFFFFFF)


def cyclomatic_for_entities(entities: list[Entity]) -> int:
    """Compute the historic file-wide complexity count for a list of entities."""
    return 1 + sum(
        not entity.is_test and counts_toward_file_complexity(entity)
        for entity in entities
    )


def counts_toward_file_complexity(entity: Entity) -> bool:
    """Whether an entity contributes to the historic file complexity value."""
    return (
        entity.kind == EntityKind.CONTROL_FLOW
        and entity.name not in COMPLEXITY_ONLY_NAMES
        and entity.name not in COMPLEXITY_MARKER_NAMES
    )
