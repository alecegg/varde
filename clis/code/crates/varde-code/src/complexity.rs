//! Language-neutral complexity metrics over extracted entities.
//!
//! Metrics use entity spans instead of language-specific syntax trees.
//! Cyclomatic complexity belongs to the smallest containing callable;
//! cognitive complexity also rolls nested-callable events into each containing
//! callable with one nesting level per callable boundary.

use std::borrow::Cow;

use crate::model::{Entity, EntityKind, Span};

/// A normalized meaning for language-specific control-flow names.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FlowRole {
    StructuralDecision,
    DecisionContainer,
    DecisionArm,
    ElseIf,
    LogicalSequence,
    Else,
    Jump,
    Recursion,
    Preproc,
    CognitiveDecision,
    LegacyOnly,
    /// Counts only in `max_nesting`; a duplicate legacy container.
    LegacyNesting,
    Catch,
    Ignored,
    Unknown,
}

/// Confidence assigned to one function's metrics.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComplexityConfidence {
    High,
    Low,
}

/// Evidence explaining reduced metric confidence.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ComplexityConfidenceReason {
    UnknownControlFlowRole { name: String },
    IncompleteDecisionContainer { name: String },
}

/// Complexity and size metrics for one named function.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FunctionComplexity {
    pub name: String,
    pub owner_type: Option<String>,
    pub file_id: u32,
    pub span: Span,
    pub cyclomatic: u32,
    pub cognitive: u32,
    pub max_nesting: u32,
    pub line_span: u32,
    pub byte_size: u32,
    pub confidence: ComplexityConfidence,
    pub confidence_reasons: Vec<ComplexityConfidenceReason>,
}

/// Normalize an extracted entity into a complexity role.
pub fn flow_role(entity: &Entity) -> Option<FlowRole> {
    match entity.kind {
        EntityKind::Catch if entity.name == "legacy_catch_clause" => Some(FlowRole::LegacyOnly),
        EntityKind::Catch => Some(FlowRole::Catch),
        EntityKind::ControlFlow => Some(control_flow_role(&entity.name)),
        _ => None,
    }
}

/// Normalize a language-specific control-flow node or keyword.
pub fn control_flow_role(name: &str) -> FlowRole {
    let normalized = normalize_control_flow_name(name);
    let normalized = normalized.as_ref();
    if let Some(role) = crate::extract::langs::registered_flow_role(normalized) {
        return role;
    }
    if is_structural_decision(normalized) {
        return FlowRole::StructuralDecision;
    }
    if is_decision_container_normalized(normalized) {
        return FlowRole::DecisionContainer;
    }
    if is_decision_arm(normalized) {
        return FlowRole::DecisionArm;
    }
    if is_else_if(normalized) {
        return FlowRole::ElseIf;
    }
    if LEGACY_ONLY_NAMES.contains(&normalized) {
        return FlowRole::LegacyOnly;
    }
    if matches!(normalized, "else_clause" | "else_statement" | "else_branch") {
        return FlowRole::Else;
    }
    if matches!(normalized, "goto_statement" | "goto_jump" | "labeled_jump") {
        return FlowRole::Jump;
    }
    if normalized == "cognitive_decision" {
        return FlowRole::CognitiveDecision;
    }
    if normalized == "legacy_nesting" {
        return FlowRole::LegacyNesting;
    }
    if normalized == "recursive_call" {
        return FlowRole::Recursion;
    }
    if matches!(normalized, "preproc_if" | "preproc_branch") {
        return FlowRole::Preproc;
    }
    if is_logical_sequence(normalized) {
        return FlowRole::LogicalSequence;
    }
    if is_ignored_flow(normalized) {
        return FlowRole::Ignored;
    }
    FlowRole::Unknown
}

fn is_structural_decision(name: &str) -> bool {
    matches!(
        name,
        "if" | "unless"
            | "if_statement"
            | "if_expression"
            | "if_modifier"
            | "unless_modifier"
            | "conditional"
            | "conditional_expression"
            | "ternary_expression"
            | "for"
            | "for_statement"
            | "for_expression"
            | "for_in_statement"
            | "for_of_statement"
            | "for_range_loop"
            | "foreach_statement"
            | "enhanced_for_statement"
            | "while"
            | "until"
            | "while_statement"
            | "while_expression"
            | "while_modifier"
            | "until_modifier"
            | "repeat_statement"
            | "repeat_while_statement"
            | "do_while_statement"
            | "loop_expression"
            | "guard_statement"
            | "guards"
            | "rescue_modifier"
    )
}

fn is_decision_arm(name: &str) -> bool {
    matches!(name, "case_statement" | "case_item" | "match_arm")
}

fn is_else_if(name: &str) -> bool {
    matches!(name, "elif_clause" | "elseif_statement")
}

fn is_logical_sequence(name: &str) -> bool {
    matches!(name, "logical_and" | "logical_or")
}

fn is_ignored_flow(name: &str) -> bool {
    matches!(
        name,
        "return"
            | "return_statement"
            | "return_expression"
            | "break"
            | "break_statement"
            | "break_expression"
            | "continue"
            | "continue_statement"
            | "continue_expression"
            | "next"
            | "redo"
            | "retry"
            | "yield"
            | "jump_expression"
            | "control_transfer_statement"
            | "try"
            | "try_statement"
            | "try_expression"
            | "try_with_resources_statement"
            | "with"
            | "with_statement"
            | "else"
            | "compensating_usage"
            | "negation_break"
            | "preproc_include_guard"
            | "begin"
            | "do_statement"
            | "let_in"
            | "label_statement"
            | "go_statement"
            | "defer_statement"
    )
}

/// Calculate per-callable metrics from one or more files' entities.
pub fn function_complexities(entities: &[Entity]) -> Vec<FunctionComplexity> {
    let mut callables: Vec<&Entity> = entities
        .iter()
        .filter(|entity| entity.kind == EntityKind::Function && !entity.is_test)
        .collect();
    let boundaries: Vec<&Entity> = entities
        .iter()
        .filter(|entity| {
            entity.kind == EntityKind::CallableBoundary
                && !entity.is_test
                && !callables.iter().any(|callable| {
                    callable.file_id == entity.file_id && callable.span == entity.span
                })
        })
        .collect();
    callables.extend(boundaries);

    callables
        .iter()
        .map(|callable| {
            let flows: Vec<(&Entity, FlowRole)> = entities
                .iter()
                .filter(|entity| !entity.is_test)
                .filter_map(|entity| flow_role(entity).map(|role| (entity, role)))
                .filter(|(flow, _)| {
                    flow.file_id == callable.file_id
                        && (contains(callable.span, flow.span)
                            || flow.name == "compensating_usage"
                                && contains(flow.span, callable.span))
                })
                .collect();
            metrics_for(callable, &flows, &callables)
        })
        .collect()
}

fn attributed_to(flow: &Entity, callable: &Entity, callables: &[&Entity]) -> bool {
    if flow.file_id != callable.file_id || !contains(callable.span, flow.span) {
        return false;
    }

    let smallest_callable = callables
        .iter()
        .filter(|candidate| {
            candidate.file_id == flow.file_id && contains(candidate.span, flow.span)
        })
        .min_by_key(|candidate| span_size(candidate.span));
    smallest_callable.map(|candidate| candidate.span) == Some(callable.span)
}

fn metrics_for(
    callable: &Entity,
    flows: &[(&Entity, FlowRole)],
    callables: &[&Entity],
) -> FunctionComplexity {
    let own_flows: Vec<_> = flows
        .iter()
        .copied()
        .filter(|(flow, _)| attributed_to(flow, callable, callables))
        .collect();
    let events = complexity_events(flows);
    let own_events = complexity_events(&own_flows);
    let confidence_reasons = confidence_reasons(&own_flows);
    FunctionComplexity {
        name: callable_name(callable),
        owner_type: callable.owner_type.clone(),
        file_id: callable.file_id,
        span: callable.span,
        cyclomatic: cyclomatic_complexity(&own_events),
        cognitive: cognitive_complexity(callable, &events, callables),
        max_nesting: maximum_nesting(&own_events),
        line_span: line_span(callable.span),
        byte_size: span_size(callable.span),
        confidence: confidence_for(&confidence_reasons),
        confidence_reasons,
    }
}

fn callable_name(callable: &Entity) -> String {
    if callable.kind == EntityKind::CallableBoundary {
        format!(
            "<anonymous>@{}:{}",
            callable.span.start_line, callable.span.start_col
        )
    } else {
        callable.name.clone()
    }
}

fn complexity_events<'a>(flows: &[(&'a Entity, FlowRole)]) -> Vec<(&'a Entity, FlowRole)> {
    flows
        .iter()
        .filter_map(|(entity, role)| {
            (matches!(
                role,
                FlowRole::StructuralDecision
                    | FlowRole::DecisionContainer
                    | FlowRole::DecisionArm
                    | FlowRole::ElseIf
                    | FlowRole::LogicalSequence
                    | FlowRole::Catch
                    | FlowRole::Else
                    | FlowRole::Jump
                    | FlowRole::Recursion
                    | FlowRole::Preproc
                    | FlowRole::CognitiveDecision
                    | FlowRole::LegacyOnly
                    | FlowRole::LegacyNesting
            ) || matches!(
                entity.name.as_str(),
                "negation_break" | "compensating_usage"
            ))
            .then_some((*entity, *role))
        })
        .collect()
}

fn confidence_reasons(flows: &[(&Entity, FlowRole)]) -> Vec<ComplexityConfidenceReason> {
    let mut confidence_reasons = Vec::new();
    for (entity, role) in flows {
        if *role == FlowRole::Unknown {
            push_unique_reason(
                &mut confidence_reasons,
                ComplexityConfidenceReason::UnknownControlFlowRole {
                    name: entity.name.clone(),
                },
            );
        }
        if incomplete_container(entity, flows) {
            push_unique_reason(
                &mut confidence_reasons,
                ComplexityConfidenceReason::IncompleteDecisionContainer {
                    name: entity.name.clone(),
                },
            );
        }
    }
    confidence_reasons
}

fn push_unique_reason(
    reasons: &mut Vec<ComplexityConfidenceReason>,
    reason: ComplexityConfidenceReason,
) {
    if !reasons.contains(&reason) {
        reasons.push(reason);
    }
}

fn maximum_nesting(events: &[(&Entity, FlowRole)]) -> u32 {
    events
        .iter()
        .filter(|(_, role)| {
            matches!(
                role,
                FlowRole::StructuralDecision
                    | FlowRole::DecisionContainer
                    | FlowRole::Catch
                    | FlowRole::LegacyOnly
                    | FlowRole::LegacyNesting
            )
        })
        .map(|(flow, _)| structural_depth(flow, events, false))
        .max()
        .unwrap_or(0)
}

fn cognitive_complexity(
    callable: &Entity,
    events: &[(&Entity, FlowRole)],
    callables: &[&Entity],
) -> u32 {
    events
        .iter()
        .map(|(flow, role)| match role {
            FlowRole::StructuralDecision
            | FlowRole::DecisionContainer
            | FlowRole::Catch
            | FlowRole::CognitiveDecision => {
                1 + structural_depth(flow, events, true)
                    + callable_depth(callable, flow, callables, events)
            }
            FlowRole::ElseIf | FlowRole::Else | FlowRole::Jump | FlowRole::Recursion => 1,
            FlowRole::Preproc if flow.name == "preproc_if" => {
                1 + structural_depth(flow, events, true)
                    + callable_depth(callable, flow, callables, events)
            }
            FlowRole::Preproc => 1,
            FlowRole::LogicalSequence => logical_sequence_point(flow, events, callable, callables),
            FlowRole::DecisionArm
            | FlowRole::Ignored
            | FlowRole::Unknown
            | FlowRole::LegacyOnly
            | FlowRole::LegacyNesting => 0,
        })
        .sum()
}

fn cyclomatic_complexity(events: &[(&Entity, FlowRole)]) -> u32 {
    1 + events
        .iter()
        .filter(|(_, role)| {
            matches!(
                role,
                FlowRole::StructuralDecision
                    | FlowRole::DecisionArm
                    | FlowRole::ElseIf
                    | FlowRole::LogicalSequence
                    | FlowRole::Catch
                    | FlowRole::LegacyOnly
            )
        })
        .count() as u32
}

fn structural_depth(flow: &Entity, events: &[(&Entity, FlowRole)], include_hybrid: bool) -> u32 {
    events
        .iter()
        .filter(|(parent, role)| is_structural_parent(parent, *role, flow, include_hybrid))
        .count() as u32
}

fn is_structural_parent(
    parent: &Entity,
    role: FlowRole,
    flow: &Entity,
    include_hybrid: bool,
) -> bool {
    matches!(
        role,
        FlowRole::StructuralDecision | FlowRole::DecisionContainer | FlowRole::Catch
    ) && parent.span != flow.span
        && contains(parent.span, flow.span)
        // Legacy-only decisions (C# guards, Scala comprehensions) still nest `max_nesting`.
        || !include_hybrid
            && matches!(role, FlowRole::LegacyOnly | FlowRole::LegacyNesting)
            && parent.span != flow.span
            && contains(parent.span, flow.span)
        || include_hybrid
            && matches!(
                role,
                FlowRole::Else | FlowRole::ElseIf | FlowRole::Preproc | FlowRole::CognitiveDecision
            )
            && parent.span != flow.span
            && contains(parent.span, flow.span)
}

fn callable_depth(
    scorer: &Entity,
    flow: &Entity,
    callables: &[&Entity],
    events: &[(&Entity, FlowRole)],
) -> u32 {
    callables
        .iter()
        .filter(|candidate| {
            candidate.file_id == scorer.file_id
                && candidate.span != scorer.span
                && contains(scorer.span, candidate.span)
                && contains(candidate.span, flow.span)
                && !events.iter().any(|(marker, _)| {
                    marker.name == "compensating_usage" && contains(marker.span, candidate.span)
                })
        })
        .count() as u32
}

fn line_span(span: Span) -> u32 {
    span.end_line
        .saturating_sub(span.start_line)
        .saturating_add(1)
}

fn confidence_for(reasons: &[ComplexityConfidenceReason]) -> ComplexityConfidence {
    if reasons.is_empty() {
        ComplexityConfidence::High
    } else {
        ComplexityConfidence::Low
    }
}

fn logical_sequence_point(
    flow: &Entity,
    counted: &[(&Entity, FlowRole)],
    scorer: &Entity,
    callables: &[&Entity],
) -> u32 {
    let owner = innermost_callable(flow, scorer, callables);
    let nearest_logical_parent = counted
        .iter()
        .filter(|(parent, role)| {
            *role == FlowRole::LogicalSequence
                && parent.span != flow.span
                && contains(parent.span, flow.span)
                && innermost_callable(parent, scorer, callables) == owner
                && !counted.iter().any(|(marker, _)| {
                    marker.name == "negation_break"
                        && contains(marker.span, flow.span)
                        && contains(parent.span, marker.span)
                })
        })
        .min_by_key(|(parent, _)| span_size(parent.span));

    match nearest_logical_parent {
        Some((parent, _)) if parent.name.trim().eq_ignore_ascii_case(flow.name.trim()) => 0,
        _ => 1,
    }
}

fn innermost_callable<'a>(flow: &Entity, scorer: &'a Entity, callables: &[&'a Entity]) -> Span {
    callables
        .iter()
        .copied()
        .filter(|candidate| {
            candidate.file_id == scorer.file_id
                && contains(scorer.span, candidate.span)
                && contains(candidate.span, flow.span)
        })
        .min_by_key(|candidate| span_size(candidate.span))
        .map(|candidate| candidate.span)
        .unwrap_or(scorer.span)
}

fn incomplete_container(entity: &Entity, flows: &[(&Entity, FlowRole)]) -> bool {
    if entity.kind != EntityKind::ControlFlow || !is_decision_container(&entity.name) {
        return false;
    }
    !flows.iter().any(|(candidate, role)| {
        *role == FlowRole::DecisionArm
            && candidate.span != entity.span
            && contains(entity.span, candidate.span)
    })
}

fn is_decision_container(name: &str) -> bool {
    is_decision_container_normalized(normalize_control_flow_name(name).as_ref())
}

fn is_decision_container_normalized(name: &str) -> bool {
    matches!(
        name,
        "switch_statement"
            | "switch_expression"
            | "expression_switch_statement"
            | "type_switch_statement"
            | "case"
            | "match_expression"
            | "when_expression"
            | "select_statement"
            | "cond"
            | "receive"
    )
}

fn normalize_control_flow_name(name: &str) -> Cow<'_, str> {
    let trimmed = name.trim();
    if trimmed.bytes().any(|byte| byte.is_ascii_uppercase()) {
        Cow::Owned(trimmed.to_ascii_lowercase())
    } else {
        Cow::Borrowed(trimmed)
    }
}

fn contains(outer: Span, inner: Span) -> bool {
    outer.start_byte <= inner.start_byte && outer.end_byte >= inner.end_byte
}

fn span_size(span: Span) -> u32 {
    span.end_byte.saturating_sub(span.start_byte)
}

/// Cyclomatic complexity of a single file given its entities.
///
/// This compatibility helper retains the original file-wide behavior.
pub fn cyclomatic_for_entities(entities: &[Entity]) -> u32 {
    1 + entities
        .iter()
        .filter(|entity| !entity.is_test && counts_toward_file_complexity(entity))
        .count() as u32
}

/// Names added for cognitive scoring that must not change the legacy file
/// complexity or cyclomatic count.
pub const COMPLEXITY_ONLY_NAMES: &[&str] = &[
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
];

/// Scorer metadata markers rather than control-flow decisions.
pub const COMPLEXITY_MARKER_NAMES: &[&str] = &["negation_break", "compensating_usage"];

/// Names retained for legacy counts while excluded from cognitive scoring.
pub const LEGACY_ONLY_NAMES: &[&str] = &["guard_clause"];

/// Whether an entity contributes to the historic file complexity value.
pub fn counts_toward_file_complexity(entity: &Entity) -> bool {
    entity.kind == EntityKind::ControlFlow
        && !COMPLEXITY_ONLY_NAMES.contains(&entity.name.as_str())
        && !COMPLEXITY_MARKER_NAMES.contains(&entity.name.as_str())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entity(kind: EntityKind, name: &str, start: u32, end: u32) -> Entity {
        Entity {
            kind,
            name: name.to_string(),
            file_id: 0,
            span: Span {
                start_byte: start,
                end_byte: end,
                start_line: start / 10 + 1,
                start_col: 0,
                end_line: end / 10 + 1,
                end_col: 0,
            },
            enclosing_function: None,
            method: None,
            path: None,
            status: None,
            body_shape: None,
            body_minhash: None,
            is_async: None,
            is_test: false,
            owner_type: None,
        }
    }

    #[test]
    fn early_returns_do_not_inflate_complexity() {
        let entities = vec![
            entity(EntityKind::Function, "parse", 0, 100),
            entity(EntityKind::ControlFlow, "if_statement", 10, 40),
            entity(EntityKind::ControlFlow, "return_statement", 20, 25),
            entity(EntityKind::ControlFlow, "return_statement", 80, 85),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 2);
        assert_eq!(metric.cognitive, 1);
        assert_eq!(metric.max_nesting, 0);
    }

    #[test]
    fn test_callable_boundaries_do_not_produce_metrics() {
        let mut boundary = entity(EntityKind::CallableBoundary, "closure", 0, 100);
        boundary.is_test = true;
        assert!(function_complexities(&[boundary]).is_empty());
    }

    #[test]
    fn exits_and_wrappers_have_ignored_roles() {
        for name in [
            "return_statement",
            "break_statement",
            "continue_statement",
            "try_statement",
            "with_statement",
            "do_statement",
        ] {
            assert_eq!(control_flow_role(name), FlowRole::Ignored, "{name}");
        }
        assert_eq!(
            control_flow_role("if_statement"),
            FlowRole::StructuralDecision
        );
        assert_eq!(control_flow_role("match_arm"), FlowRole::DecisionArm);
        assert_eq!(control_flow_role("logical_and"), FlowRole::LogicalSequence);
        assert_eq!(control_flow_role("logical_or"), FlowRole::LogicalSequence);
        assert_eq!(
            control_flow_role("match_expression"),
            FlowRole::DecisionContainer
        );
        assert_eq!(control_flow_role("goto_statement"), FlowRole::Jump);
        assert_eq!(control_flow_role("else_clause"), FlowRole::Else);
        assert_eq!(control_flow_role("else_branch"), FlowRole::Else);
        assert_eq!(control_flow_role("recursive_call"), FlowRole::Recursion);
        assert_eq!(control_flow_role("preproc_if"), FlowRole::Preproc);
    }

    #[test]
    fn nesting_costs_more_than_flat_branches() {
        let flat = vec![
            entity(EntityKind::Function, "flat", 0, 100),
            entity(EntityKind::ControlFlow, "if_statement", 10, 20),
            entity(EntityKind::ControlFlow, "if_statement", 30, 40),
        ];
        let nested = vec![
            entity(EntityKind::Function, "nested", 0, 100),
            entity(EntityKind::ControlFlow, "if_statement", 10, 60),
            entity(EntityKind::ControlFlow, "if_statement", 20, 40),
        ];

        let flat = &function_complexities(&flat)[0];
        let nested = &function_complexities(&nested)[0];
        assert_eq!(flat.cyclomatic, nested.cyclomatic);
        assert_eq!(flat.cognitive, 2);
        assert_eq!(nested.cognitive, 3);
        assert_eq!(nested.max_nesting, 1);
    }

    #[test]
    fn logical_sequences_receive_no_nesting_penalty() {
        let entities = vec![
            entity(EntityKind::Function, "nested", 0, 120),
            entity(EntityKind::ControlFlow, "if_statement", 10, 100),
            entity(EntityKind::ControlFlow, "if_statement", 20, 80),
            entity(EntityKind::ControlFlow, "logical_and", 30, 40),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 4);
        assert_eq!(metric.cognitive, 4);
        assert_eq!(metric.max_nesting, 1);
    }

    #[test]
    fn repeated_logical_operators_form_one_cognitive_sequence() {
        let entities = vec![
            entity(EntityKind::Function, "check", 0, 100),
            entity(EntityKind::ControlFlow, "logical_and", 10, 80),
            entity(EntityKind::ControlFlow, "logical_and", 20, 50),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 3);
        assert_eq!(metric.cognitive, 1);
    }

    #[test]
    fn changing_logical_operators_starts_another_sequence() {
        let entities = vec![
            entity(EntityKind::Function, "check", 0, 100),
            entity(EntityKind::ControlFlow, "logical_or", 10, 80),
            entity(EntityKind::ControlFlow, "logical_and", 20, 50),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 3);
        assert_eq!(metric.cognitive, 2);
    }

    #[test]
    fn else_if_chains_do_not_compound_nesting() {
        let entities = vec![
            entity(EntityKind::Function, "choose", 0, 140),
            entity(EntityKind::ControlFlow, "if_statement", 10, 130),
            entity(EntityKind::ControlFlow, "elseif_statement", 40, 120),
            entity(EntityKind::ControlFlow, "elif_clause", 70, 110),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 4);
        assert_eq!(metric.cognitive, 3);
        assert_eq!(metric.max_nesting, 0);
    }

    #[test]
    fn empty_decision_containers_lower_confidence() {
        let entities = vec![
            entity(EntityKind::Function, "choose", 0, 100),
            entity(EntityKind::ControlFlow, "match_expression", 20, 80),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 1);
        assert_eq!(metric.cognitive, 1);
        assert_eq!(metric.confidence, ComplexityConfidence::Low);
        assert_eq!(
            metric.confidence_reasons,
            vec![ComplexityConfidenceReason::IncompleteDecisionContainer {
                name: "match_expression".to_string()
            }]
        );
    }

    #[test]
    fn emitted_arms_complete_decision_containers() {
        let entities = vec![
            entity(EntityKind::Function, "choose", 0, 100),
            entity(EntityKind::ControlFlow, "match_expression", 20, 80),
            entity(EntityKind::ControlFlow, "match_arm", 30, 50),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 2);
        assert_eq!(metric.cognitive, 1);
        assert_eq!(metric.confidence, ComplexityConfidence::High);
    }

    #[test]
    fn flat_match_arms_only_increase_cyclomatic_complexity() {
        let mut entities = vec![
            entity(EntityKind::Function, "choose", 0, 500),
            entity(EntityKind::ControlFlow, "match_expression", 10, 490),
        ];
        for index in 0..10 {
            let start = 20 + index * 40;
            entities.push(entity(
                EntityKind::ControlFlow,
                "match_arm",
                start,
                start + 20,
            ));
        }

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 11);
        assert_eq!(metric.cognitive, 1);
        assert_eq!(metric.max_nesting, 0);
        assert_eq!(metric.confidence, ComplexityConfidence::High);
    }

    #[test]
    fn decisions_inside_match_arms_receive_container_nesting() {
        let mut entities = vec![
            entity(EntityKind::Function, "choose", 0, 500),
            entity(EntityKind::ControlFlow, "match_expression", 10, 490),
        ];
        for index in 0..10 {
            let start = 20 + index * 40;
            entities.push(entity(
                EntityKind::ControlFlow,
                "match_arm",
                start,
                start + 20,
            ));
        }
        entities.push(entity(EntityKind::ControlFlow, "if_statement", 25, 35));

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 12);
        assert_eq!(metric.cognitive, 3);
        assert_eq!(metric.max_nesting, 1);
    }

    #[test]
    fn try_is_ignored_but_catch_adds_a_path() {
        let entities = vec![
            entity(EntityKind::Function, "load", 0, 100),
            entity(EntityKind::ControlFlow, "try_statement", 10, 90),
            entity(EntityKind::Catch, "error", 60, 85),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 2);
        assert_eq!(metric.cognitive, 1);
        assert_eq!(metric.confidence, ComplexityConfidence::High);
    }

    #[test]
    fn overloads_are_attributed_by_span() {
        let mut second = entity(EntityKind::Function, "send", 100, 200);
        second.owner_type = Some("Client".to_string());
        let entities = vec![
            entity(EntityKind::Function, "send", 0, 90),
            second,
            entity(EntityKind::ControlFlow, "if_statement", 120, 160),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics[0].cyclomatic, 1);
        assert_eq!(metrics[1].cyclomatic, 2);
        assert_eq!(metrics[1].owner_type.as_deref(), Some("Client"));
    }

    #[test]
    fn nested_functions_do_not_inflate_parents() {
        let entities = vec![
            entity(EntityKind::Function, "outer", 0, 200),
            entity(EntityKind::Function, "inner", 50, 150),
            entity(EntityKind::ControlFlow, "if_statement", 70, 100),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics[0].cyclomatic, 1);
        assert_eq!(metrics[1].cyclomatic, 2);
    }

    #[test]
    fn nested_callable_events_roll_up_with_nesting() {
        let entities = vec![
            entity(EntityKind::Function, "outer", 0, 300),
            entity(EntityKind::CallableBoundary, "lambda", 20, 100),
            entity(EntityKind::ControlFlow, "if_statement", 30, 50),
            entity(EntityKind::Function, "local", 150, 250),
            entity(EntityKind::ControlFlow, "if_statement", 160, 180),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics[0].cognitive, 4);
        let local = metrics
            .iter()
            .find(|metric| metric.name == "local")
            .expect("local function has its own metric");
        let lambda = metrics
            .iter()
            .find(|metric| metric.name.starts_with("<anonymous>"))
            .expect("lambda has its own metric");
        assert_eq!(local.cognitive, 1);
        assert_eq!(lambda.cognitive, 1);
    }

    #[test]
    fn compensating_usage_suppresses_callable_nesting() {
        let entities = vec![
            entity(EntityKind::Function, "wrapper", 0, 200),
            entity(EntityKind::ControlFlow, "compensating_usage", 0, 200),
            entity(EntityKind::CallableBoundary, "lambda", 30, 150),
            entity(EntityKind::ControlFlow, "if_statement", 50, 120),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics[0].cognitive, 1);
        assert_eq!(metrics[1].cognitive, 1);
    }

    #[test]
    fn complexity_only_entities_leave_legacy_counts_unchanged() {
        let entities = vec![
            entity(EntityKind::ControlFlow, "if_statement", 0, 10),
            entity(EntityKind::ControlFlow, "else_branch", 10, 20),
            entity(EntityKind::ControlFlow, "goto_jump", 20, 21),
            entity(EntityKind::ControlFlow, "guard_clause", 21, 25),
            entity(EntityKind::ControlFlow, "negation_break", 30, 31),
            entity(EntityKind::ControlFlow, "compensating_usage", 32, 40),
        ];

        assert_eq!(cyclomatic_for_entities(&entities), 3);
        assert!(counts_toward_file_complexity(&entities[3]));
        assert!(!counts_toward_file_complexity(&entities[1]));
        assert!(!counts_toward_file_complexity(&entities[4]));
        assert!(!counts_toward_file_complexity(&entities[5]));
    }

    #[test]
    fn legacy_only_guard_clause_does_not_score_cognitively() {
        let entities = vec![
            entity(EntityKind::Function, "guarded", 0, 100),
            entity(EntityKind::ControlFlow, "guard_clause", 10, 50),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 2);
        assert_eq!(metric.cognitive, 0);
        assert_eq!(metric.max_nesting, 0);
    }

    #[test]
    fn legacy_only_decisions_still_nest_max_nesting_but_not_cognitive_depth() {
        let entities = vec![
            entity(EntityKind::Function, "comprehension", 0, 100),
            entity(EntityKind::ControlFlow, "guard_clause", 10, 90),
            entity(EntityKind::ControlFlow, "if_statement", 20, 40),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 3);
        // max_nesting counts the legacy-only parent as before; cognitive adds no depth for it.
        assert_eq!(metric.max_nesting, 1);
        assert_eq!(metric.cognitive, 1);
    }

    #[test]
    fn cognitive_decision_scores_and_nests_without_touching_legacy_counts() {
        let entities = vec![
            entity(EntityKind::Function, "arith", 0, 100),
            entity(EntityKind::ControlFlow, "cognitive_decision", 10, 90),
            entity(EntityKind::ControlFlow, "if_statement", 20, 40),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cognitive, 3);
        assert_eq!(metric.cyclomatic, 2);
        assert_eq!(metric.max_nesting, 0);
        assert!(!counts_toward_file_complexity(&entities[1]));
    }

    #[test]
    fn negation_marker_breaks_same_operator_run() {
        let entities = vec![
            entity(EntityKind::Function, "check", 0, 100),
            entity(EntityKind::ControlFlow, "logical_and", 10, 90),
            entity(EntityKind::ControlFlow, "negation_break", 40, 80),
            entity(EntityKind::ControlFlow, "logical_and", 50, 70),
        ];

        assert_eq!(function_complexities(&entities)[0].cognitive, 2);
    }

    #[test]
    fn logical_runs_do_not_cross_callable_boundaries() {
        let entities = vec![
            entity(EntityKind::Function, "outer", 0, 100),
            entity(EntityKind::ControlFlow, "logical_and", 10, 90),
            entity(EntityKind::CallableBoundary, "lambda", 30, 80),
            entity(EntityKind::ControlFlow, "logical_and", 40, 60),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics[0].cognitive, 2);
        assert!(
            metrics
                .iter()
                .any(|metric| metric.name.starts_with("<anonymous>") && metric.cognitive == 1)
        );
    }

    #[test]
    fn condition_decisions_include_ternary_nesting() {
        let entities = vec![
            entity(EntityKind::Function, "choose", 0, 100),
            entity(EntityKind::ControlFlow, "if_statement", 10, 90),
            entity(EntityKind::ControlFlow, "conditional_expression", 20, 40),
        ];

        assert_eq!(function_complexities(&entities)[0].cognitive, 3);
    }

    #[test]
    fn anonymous_callables_receive_independent_metrics() {
        let entities = vec![
            entity(EntityKind::Function, "outer", 0, 200),
            entity(EntityKind::CallableBoundary, "", 50, 150),
            entity(EntityKind::ControlFlow, "if_statement", 70, 100),
        ];

        let metrics = function_complexities(&entities);
        assert_eq!(metrics.len(), 2);
        assert_eq!(metrics[0].cyclomatic, 1);
        assert_eq!(metrics[1].cyclomatic, 2);
        assert_eq!(metrics[1].name, "<anonymous>@6:0");
    }

    #[test]
    fn unknown_roles_lower_confidence_without_inflating_metrics() {
        let entities = vec![
            entity(EntityKind::Function, "work", 0, 100),
            entity(EntityKind::ControlFlow, "mystery_clause", 20, 40),
        ];

        let metric = &function_complexities(&entities)[0];
        assert_eq!(metric.cyclomatic, 1);
        assert_eq!(metric.confidence, ComplexityConfidence::Low);
        assert_eq!(
            metric.confidence_reasons,
            vec![ComplexityConfidenceReason::UnknownControlFlowRole {
                name: "mystery_clause".to_string()
            }]
        );
    }

    #[test]
    fn reports_function_size() {
        let metric = function_complexities(&[entity(EntityKind::Function, "work", 10, 59)])
            .pop()
            .unwrap();

        assert_eq!(metric.line_span, 5);
        assert_eq!(metric.byte_size, 49);
    }
}
