from varde_code import complexity
from varde_code.complexity import (
    ComplexityConfidence,
    ComplexityConfidenceReason,
    FlowRole,
    control_flow_role,
    counts_toward_file_complexity,
    cyclomatic_for_entities,
    flow_role,
    function_complexities,
)
from varde_code.model import Entity, EntityKind, Span


def entity(kind, name, start, end, *, file_id=0, is_test=False, owner_type=None):
    return Entity(
        kind=kind,
        name=name,
        file_id=file_id,
        span=Span(start, end, start // 10 + 1, 0, end // 10 + 1, 0),
        is_test=is_test,
        owner_type=owner_type,
    )


def metric(entities, name=None):
    metrics = function_complexities(entities)
    return next(item for item in metrics if name is None or item.name == name)


def test_control_flow_roles_and_legacy_markers():
    assert flow_role(entity(EntityKind.CATCH, "error", 1, 2)) == FlowRole.CATCH
    assert (
        flow_role(entity(EntityKind.CATCH, "legacy_catch_clause", 1, 2))
        == FlowRole.LEGACY_ONLY
    )
    assert flow_role(entity(EntityKind.FUNCTION, "work", 1, 2)) is None
    assert control_flow_role(" IF_STATEMENT ") == FlowRole.STRUCTURAL_DECISION
    assert control_flow_role("match_arm") == FlowRole.DECISION_ARM
    assert control_flow_role("return_statement") == FlowRole.IGNORED
    assert control_flow_role("mystery_clause") == FlowRole.UNKNOWN


def test_registered_flow_role_overrides_builtin_classification(monkeypatch):
    monkeypatch.setattr(
        complexity, "registered_flow_role", lambda name: "DecisionContainer"
    )

    assert control_flow_role("if_statement") == FlowRole.DECISION_CONTAINER


def test_nested_decisions_add_cognitive_and_nesting_cost():
    entities = [
        entity(EntityKind.FUNCTION, "work", 0, 100),
        entity(EntityKind.CONTROL_FLOW, "if_statement", 10, 80),
        entity(EntityKind.CONTROL_FLOW, "if_statement", 20, 40),
    ]

    result = metric(entities)

    assert (result.cyclomatic, result.cognitive, result.max_nesting) == (3, 3, 1)


def test_repeated_logical_operators_are_one_cognitive_sequence():
    entities = [
        entity(EntityKind.FUNCTION, "check", 0, 100),
        entity(EntityKind.CONTROL_FLOW, "logical_and", 10, 80),
        entity(EntityKind.CONTROL_FLOW, "logical_and", 20, 50),
    ]

    result = metric(entities)

    assert (result.cyclomatic, result.cognitive) == (3, 1)


def test_functions_own_cyclomatic_events_but_outer_cognitive_rolls_up():
    entities = [
        entity(EntityKind.FUNCTION, "outer", 0, 200),
        entity(EntityKind.FUNCTION, "inner", 50, 150),
        entity(EntityKind.CONTROL_FLOW, "if_statement", 70, 100),
    ]

    outer = metric(entities, "outer")
    inner = metric(entities, "inner")

    assert (outer.cyclomatic, outer.cognitive) == (1, 2)
    assert (inner.cyclomatic, inner.cognitive) == (2, 1)


def test_anonymous_callable_gets_its_own_metric():
    entities = [
        entity(EntityKind.FUNCTION, "outer", 0, 200),
        entity(EntityKind.CALLABLE_BOUNDARY, "", 50, 150),
        entity(EntityKind.CONTROL_FLOW, "if_statement", 70, 100),
    ]

    result = function_complexities(entities)

    assert [item.name for item in result] == ["outer", "<anonymous>@6:0"]
    assert [(item.cyclomatic, item.cognitive) for item in result] == [(1, 2), (2, 1)]


def test_unknown_role_lowers_confidence_without_changing_scores():
    entities = [
        entity(EntityKind.FUNCTION, "work", 0, 100),
        entity(EntityKind.CONTROL_FLOW, "mystery_clause", 20, 40),
    ]

    result = metric(entities)

    assert result.cyclomatic == 1
    assert result.confidence == ComplexityConfidence.LOW
    assert result.confidence_reasons == [
        ComplexityConfidenceReason.unknown_control_flow_role("mystery_clause")
    ]


def test_incomplete_decision_container_lowers_confidence():
    entities = [
        entity(EntityKind.FUNCTION, "choose", 0, 100),
        entity(EntityKind.CONTROL_FLOW, "match_expression", 20, 80),
    ]

    result = metric(entities)

    assert result.cyclomatic == 1
    assert result.cognitive == 1
    assert result.confidence == ComplexityConfidence.LOW
    assert result.confidence_reasons == [
        ComplexityConfidenceReason.incomplete_decision_container("match_expression")
    ]


def test_test_entities_are_excluded_and_function_size_is_reported():
    entities = [
        entity(EntityKind.FUNCTION, "work", 10, 59),
        entity(EntityKind.CONTROL_FLOW, "if_statement", 20, 30, is_test=True),
        entity(EntityKind.FUNCTION, "test_work", 60, 90, is_test=True),
    ]

    result = metric(entities)

    assert (result.cyclomatic, result.cognitive, result.max_nesting) == (1, 0, 0)
    assert (result.line_span, result.byte_size) == (5, 49)


def test_legacy_file_count_excludes_complexity_only_markers():
    entities = [
        entity(EntityKind.CONTROL_FLOW, "if_statement", 0, 10),
        entity(EntityKind.CONTROL_FLOW, "else_branch", 10, 20),
        entity(EntityKind.CONTROL_FLOW, "goto_jump", 20, 21),
        entity(EntityKind.CONTROL_FLOW, "guard_clause", 21, 25),
        entity(EntityKind.CONTROL_FLOW, "negation_break", 30, 31),
        entity(EntityKind.CONTROL_FLOW, "compensating_usage", 32, 40),
    ]

    assert cyclomatic_for_entities(entities) == 3
    assert counts_toward_file_complexity(entities[3])
    assert not counts_toward_file_complexity(entities[1])
    assert not counts_toward_file_complexity(entities[4])
    assert not counts_toward_file_complexity(entities[5])


def _reference_function_complexities(entities):
    """Copy of the pre-cache algorithm: roles computed per callable."""
    callables = [e for e in entities if e.kind == EntityKind.FUNCTION and not e.is_test]
    callables.extend(
        e
        for e in entities
        if e.kind == EntityKind.CALLABLE_BOUNDARY
        and not e.is_test
        and not any(c.file_id == e.file_id and c.span == e.span for c in callables)
    )
    results = []
    for callable_entity in callables:
        flows = [
            (e, role)
            for e in entities
            if not e.is_test
            if (role := flow_role(e)) is not None
            if e.file_id == callable_entity.file_id
            and (
                complexity.contains(callable_entity.span, e.span)
                or e.name == "compensating_usage"
                and complexity.contains(e.span, callable_entity.span)
            )
        ]
        results.append(complexity.metrics_for(callable_entity, flows, callables))
    return results


def _multi_file_entities():
    entities = []
    for file_id in (0, 1, 2):
        entities += [
            entity(EntityKind.FUNCTION, "outer", 0, 200, file_id=file_id),
            entity(EntityKind.FUNCTION, "inner", 50, 150, file_id=file_id),
            entity(EntityKind.CALLABLE_BOUNDARY, "lambda", 60, 90, file_id=file_id),
            entity(EntityKind.CALLABLE_BOUNDARY, "outer", 0, 200, file_id=file_id),
            entity(EntityKind.CONTROL_FLOW, "if_statement", 70, 100, file_id=file_id),
            entity(EntityKind.CONTROL_FLOW, "logical_and", 72, 80, file_id=file_id),
            entity(EntityKind.CATCH, "error", 110, 120, file_id=file_id),
            entity(EntityKind.CONTROL_FLOW, "if_statement", 5, 8, file_id=file_id),
            entity(EntityKind.FUNCTION, "t", 10, 20, file_id=file_id, is_test=True),
            entity(
                EntityKind.CONTROL_FLOW,
                "if_statement",
                12,
                14,
                file_id=file_id,
                is_test=True,
            ),
        ]
    entities.append(entity(EntityKind.CONTROL_FLOW, "compensating_usage", 0, 400))
    entities.append(
        entity(EntityKind.CONTROL_FLOW, "compensating_usage", 0, 400, file_id=2)
    )
    return entities


def test_function_complexities_match_reference_algorithm():
    entities = _multi_file_entities()

    assert function_complexities(entities) == _reference_function_complexities(entities)


def test_flow_role_called_once_per_entity(monkeypatch):
    entities = _multi_file_entities()
    calls = []
    real = complexity.flow_role
    monkeypatch.setattr(
        complexity, "flow_role", lambda item: calls.append(id(item)) or real(item)
    )

    function_complexities(entities)

    assert len(calls) <= len(entities)
    assert len(calls) == len(set(calls))


def test_discover_runs_once_across_lookups(monkeypatch):
    from varde_code.extract.langs import base

    base._folded_flow_roles.cache_clear()
    count = []
    real = base.discover
    monkeypatch.setattr(base, "discover", lambda: count.append(1) or real())

    for name in ("if_statement", "match_arm", "unknown_node", "IF_STATEMENT"):
        base.registered_flow_role(name)

    assert len(count) == 1
    base._folded_flow_roles.cache_clear()
