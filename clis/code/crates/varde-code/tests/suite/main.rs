use std::sync::Mutex;

/// Serializes integration tests that mutate process-global environment variables.
pub(crate) static ENV_LOCK: Mutex<()> = Mutex::new(());

#[path = "builtin_pattern_contracts.rs"]
mod builtin_pattern_contracts;
#[path = "code_map_index_prune.rs"]
mod code_map_index_prune;
#[path = "complexity_conformance.rs"]
mod complexity_conformance;
#[path = "cpp_parse_recovery.rs"]
mod cpp_parse_recovery;
#[path = "csharp_parse_recovery.rs"]
mod csharp_parse_recovery;
#[path = "extract_control_error.rs"]
mod extract_control_error;
#[path = "extract_domain_specific.rs"]
mod extract_domain_specific;
#[path = "extract_expression_level.rs"]
mod extract_expression_level;
#[path = "extract_statement_level.rs"]
mod extract_statement_level;
#[path = "extract_structural.rs"]
mod extract_structural;
#[path = "extract_symbols.rs"]
mod extract_symbols;
#[path = "find_pattern.rs"]
mod find_pattern;
#[path = "function_complexity_gating.rs"]
mod function_complexity_gating;
#[path = "function_complexity_languages.rs"]
mod function_complexity_languages;
#[path = "legacy_file_complexity_golden.rs"]
mod legacy_file_complexity_golden;
#[path = "language_evidence/mod.rs"]
mod language_evidence;
#[path = "overrides.rs"]
mod overrides;
#[path = "parse_ts.rs"]
mod parse_ts;
#[path = "pattern_rule_perf.rs"]
mod pattern_rule_perf;
#[path = "query_graph_counts.rs"]
mod query_graph_counts;
#[path = "query_graph_traversal.rs"]
mod query_graph_traversal;
#[path = "query_map_and_changes.rs"]
mod query_map_and_changes;
#[path = "query_simple_lookups.rs"]
mod query_simple_lookups;
#[path = "query_symbol_impact.rs"]
mod query_symbol_impact;
#[path = "rule_pack_loading.rs"]
mod rule_pack_loading;
#[path = "structural_policy_gates.rs"]
mod structural_policy_gates;
#[path = "tracing_persistence.rs"]
mod tracing_persistence;
#[path = "worktree_base_index.rs"]
mod worktree_base_index;
