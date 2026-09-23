//! Rust entity extraction.
//!
//! Rust-specific mapping notes (fixture-driven, superset-safe):
//! - Function: `fn` items -> Function (function_item and
//!   function_signature_item — the latter covers trait method declarations).
//! - Class: `struct` and `enum` items -> Class (enums are type declarations;
//!   documented mapping).
//! - Interface: `trait` items -> Interface (Rust's abstraction mechanism).
//! - Variable: `let` declarations -> one Variable per pattern identifier
//!   (plain identifiers and destructuring: tuple/struct/tuple-struct
//!   patterns).
//! - Parameter: identifiers inside the `parameters` node (`parameter` carries
//!   a `pattern` field; `self_parameter` -> "self").
//! - Export: `pub` items at the top level -> Export entity alongside their
//!   primary entity (narrow: visibility modifier on a top-level
//!   fn/struct/enum/trait/const item).
//! - Call: `call_expression`, callee text as name. `field_expression` ->
//!   MemberAccess (field "field").
//! - Literal: integer/float/string/char/boolean/raw-string literals,
//!   excluding type contexts.
//! - Catch: carved out — Rust has no try/catch construct (Result-based
//!   error handling is not a syntactic counterpart).
//! - Throw: `panic!` macro invocation -> Throw, named after the first
//!   argument (the panic message).
//! - ControlFlow: if/for/while/loop/match/return/break/continue expressions,
//!   each match arm, and short-circuit boolean operators.
//!   (`if let` / `while let` parse as if_expression / while_expression with a
//!   let_condition — tree-sitter-rust has no separate node kinds.)
//! - Route/Response: carved out — Rust has no built-in web framework shapes
//!   that map to a narrow, non-fuzzy heuristic.

use crate::extract::entity::{EntityMeta, ExtractCtx, entity};
use crate::extract::field_name;
use crate::extract::langs::boolean_operator_name;
use crate::model::EntityKind;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const TYPE_SCOPES: &[&str] = &["impl_item", "trait_item"];

pub const FUNCTION_SCOPES: &[&str] = &[
    "function_item",
    "function_signature_item",
    "closure_expression",
];

/// Entity kinds the fixtures must produce. Catch, Route, and Response are
/// carved out (see module docs).
pub const REQUIRED_KINDS: [EntityKind; 11] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Interface,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Export,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::Throw,
    EntityKind::ControlFlow,
];

/// Emit entities for one node (called for every node in the tree).
pub fn visit(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) {
    if visit_declaration(node, kind, ctx) {
        return;
    }
    if visit_binding(node, kind, ctx) {
        return;
    }
    if visit_expression(node, kind, ctx) {
        return;
    }
    visit_control_flow(node, kind, ctx);
}

fn visit_declaration(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "function_item" | "function_signature_item" => {
            emit_named_declaration(node, EntityKind::Function, ctx);
        }
        "closure_expression" => ctx.push_callable_boundary(node),
        "struct_item" | "enum_item" => {
            emit_named_declaration(node, EntityKind::Class, ctx);
        }
        "trait_item" => {
            emit_named_declaration(node, EntityKind::Interface, ctx);
        }
        "const_item" => {
            if let Some(name) = field_name(node) {
                maybe_export(node, &name, ctx);
            }
        }
        "impl_item" => emit_implementation(node, ctx),
        _ => return false,
    }
    true
}

fn emit_named_declaration(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    entity_kind: EntityKind,
    ctx: &mut ExtractCtx,
) {
    let name = field_name(node).unwrap_or_default();
    ctx.push(entity_kind, name.clone(), node);
    maybe_export(node, &name, ctx);
}

fn emit_implementation(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    let (Some(trait_node), Some(type_node)) = (node.field("trait"), node.field("type")) else {
        return;
    };
    let trait_name = impl_type_name(&trait_node);
    let type_name = impl_type_name(&type_node);
    if trait_name.is_empty() || type_name.is_empty() {
        return;
    }
    ctx.out.push(entity(
        EntityKind::Implements,
        trait_name,
        ctx.file_id,
        node,
        EntityMeta {
            enclosing: Some(type_name),
            ..Default::default()
        },
    ));
}

fn visit_binding(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "use_declaration" => emit_import(node, ctx),
        "let_declaration" => emit_variables(node, ctx),
        "parameters" => emit_parameters(node, ctx),
        _ => return false,
    }
    true
}

fn emit_import(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    ctx.out.push(entity(
        EntityKind::Import,
        rust_use_info(node),
        ctx.file_id,
        node,
        EntityMeta::default(),
    ));
}

fn emit_variables(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    if let Some(pattern) = node.field("pattern") {
        for name in pattern_identifiers(&pattern) {
            ctx.push(EntityKind::Variable, name, node);
        }
    }
}

fn emit_parameters(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    for child in node.children() {
        match child.kind().as_ref() {
            "parameter" => {
                if let Some(pattern) = child.field("pattern") {
                    for name in pattern_identifiers(&pattern) {
                        ctx.push(EntityKind::Parameter, name, node);
                    }
                }
            }
            "self_parameter" => ctx.push(EntityKind::Parameter, "self".to_string(), node),
            _ => {}
        }
    }
}

fn visit_expression(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "call_expression" => {
            let name = node
                .field("function")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Call, name, node);
        }
        "field_expression" => {
            let name = node
                .field("field")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::MemberAccess, name, node);
        }
        "integer_literal" | "float_literal" | "string_literal" | "char_literal"
        | "boolean_literal" | "raw_string_literal" => {
            if !in_rust_type_context(node) {
                ctx.push(EntityKind::Literal, node.text().into_owned(), node);
            }
        }
        // `panic!(...)` -> Throw, named after the panic message argument.
        "macro_invocation" => {
            let is_panic = node
                .field("macro")
                .map(|m| m.text() == "panic")
                .unwrap_or(false);
            if is_panic {
                ctx.push(
                    EntityKind::Throw,
                    macro_first_arg(node).unwrap_or_default(),
                    node,
                );
            }
        }
        _ => return false,
    }
    true
}

fn visit_control_flow(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) {
    match kind {
        "if_expression"
        | "for_expression"
        | "while_expression"
        | "loop_expression"
        | "match_expression"
        | "match_arm"
        | "return_expression"
        | "break_expression"
        | "continue_expression" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        "binary_expression" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }

        _ => {}
    }
}

/// Stable complexity name for Rust's short-circuit boolean operators.
/// All bound identifiers in a let/parameter pattern, recursing through
/// tuple/struct/tuple-struct/ref/mut/or patterns and skipping the type name
/// of struct-like patterns.
fn pattern_identifiers(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names: Vec<String> = Vec::new();
    collect_pattern_ids(node, &mut names, 0);
    names
}

fn collect_pattern_ids(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    names: &mut Vec<String>,
    depth: u32,
) {
    // Guard against stack overflow on pathologically nested patterns; a real
    // pattern is never anywhere near this deep, so bailing loses nothing.
    if depth >= crate::extract::MAX_WALK_DEPTH {
        return;
    }
    match node.kind().as_ref() {
        "identifier" | "shorthand_field_identifier" => {
            let t = node.text().into_owned();
            if t != "_" {
                names.push(t);
            }
        }
        // Skip the type name (`Some(v)` -> only `v`; `Point { x }` -> only
        // `x`); the struct's name lives on the Class entity instead.
        "tuple_struct_pattern" | "struct_pattern" => {
            for child in node.children() {
                let is_type = node
                    .field("type")
                    .map(|t| t.node_id() == child.node_id())
                    .unwrap_or(false);
                if !is_type {
                    collect_pattern_ids(&child, names, depth + 1);
                }
            }
        }
        _ => {
            for child in node.children() {
                collect_pattern_ids(&child, names, depth + 1);
            }
        }
    }
}

/// Rust `pub` items at the top level emit an Export entity alongside their
/// primary entity (narrow: parent must be the source file).
fn maybe_export(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    name: &str,
    ctx: &mut ExtractCtx,
) {
    let top_level = node
        .parent()
        .map(|p| p.kind() == "source_file")
        .unwrap_or(false);
    let is_pub = node.children().any(|c| c.kind() == "visibility_modifier");
    if top_level && is_pub {
        ctx.out.push(entity(
            EntityKind::Export,
            name.to_string(),
            ctx.file_id,
            node,
            EntityMeta::default(),
        ));
    }
}

/// Base type name of an `impl_item`'s `trait`/`type` field: unwraps a
/// `generic_type` (`Wrapper<T>` -> "Wrapper") to its base; otherwise the
/// node's own text (covers `type_identifier` and `scoped_type_identifier`,
/// e.g. `std::fmt::Display`).
fn impl_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    if node.kind() == "generic_type" {
        node.field("type")
            .map(|t| t.text().into_owned())
            .unwrap_or_else(|| node.text().into_owned())
    } else {
        node.text().into_owned()
    }
}

/// Owning-type name for a `TYPE_SCOPES` node: an `impl_item`'s `type` field
/// (the concrete type being implemented, not the `trait` field — methods
/// inside `impl Trait for Type` belong to `Type`), or `trait_item`'s `name`
/// field for trait default-method bodies.
pub(crate) fn type_scope_name(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<String> {
    match node.kind().as_ref() {
        "impl_item" => node.field("type").map(|t| impl_type_name(&t)),
        _ => field_name(node),
    }
}

/// First argument text of a `panic!(...)`-style macro invocation: the first
/// non-punctuation token inside the token_tree.
fn macro_first_arg(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let tree = node.children().find(|c| c.kind() == "token_tree")?;
    tree.children()
        .find(|c| !matches!(c.kind().as_ref(), "(" | ")" | "[" | "]" | "{" | "}" | ","))
        .map(|c| c.text().into_owned())
}

/// Rust node kinds that mark the start of a type context (primitive/generic/
/// array/reference/function types, a bare or scoped type name, a lifetime,
/// ...). Rust's grammar names these differently from the shared TS/JS-centric
/// `crate::extract::TYPE_KINDS` list (review fix M4) — kept here as the single
/// source of truth for Rust and dispatched to by `crate::extract::is_type_kind`
/// so the language-agnostic `in_type` propagation (which feeds symbol
/// classification — see `crate::extract::symbol::classify`) recognizes Rust
/// type contexts too, not just this module's own literal-suppression check.
pub(crate) const TYPE_KINDS: &[&str] = &[
    "primitive_type",
    "generic_type",
    "generic_type_with_turbofish",
    "array_type",
    "tuple_type",
    "reference_type",
    "pointer_type",
    "function_type",
    "unit_type",
    "scoped_type_identifier",
    "type_identifier",
    "type_arguments",
    "type_parameters",
    "lifetime",
];

/// True when `kind` is a Rust type-context node kind. See [`TYPE_KINDS`].
pub(crate) fn is_type_kind(kind: &str) -> bool {
    TYPE_KINDS.contains(&kind)
}

/// True when the node sits inside a Rust type context (parameter type,
/// return type, array/generic/reference/function types, ...). Prevents type
/// spellings like `[u8; 4]` from surfacing as expression literals.
fn in_rust_type_context(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.ancestors()
        .skip(1)
        .any(|a| is_type_kind(a.kind().as_ref()))
}

/// Extract the module path from a Rust `use` statement.
///
/// AST shapes (tree-sitter-rust):
/// - `use crate::helper::util;`      -> scoped_identifier, name "crate::helper::util"
/// - `use crate::helper::{a, b};`    -> scoped_use_list, name "crate::helper"
/// - `use foo;` / `use foo as bar;`  -> identifier / use_as_clause
/// - `use std::collections::*;`      -> scoped_identifier + use_wildcard
fn rust_use_info(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let arg = node.children().find(|c| {
        matches!(
            c.kind().as_ref(),
            "scoped_identifier"
                | "scoped_use_list"
                | "use_list"
                | "identifier"
                | "use_as_clause"
                | "use_wildcard"
        )
    });
    let Some(arg) = arg else {
        return node.text().into_owned();
    };
    match arg.kind().as_ref() {
        "scoped_use_list" => arg
            .children()
            .find(|c| c.kind() == "scoped_identifier")
            .map(|c| c.text().into_owned())
            .unwrap_or_default(),
        "use_list" => String::new(),
        // `use foo as bar;` — the module path is the first named child ("foo").
        "use_as_clause" => arg
            .children()
            .find(|c| c.is_named())
            .map(|c| c.text().into_owned())
            .unwrap_or_default(),
        _ => arg.text().into_owned(),
    }
}

#[cfg(test)]
mod tests {
    use crate::extract;
    use crate::model::EntityKind;
    use crate::parse::parse_source;
    use ast_grep_language::SupportLang;

    #[test]
    fn closures_are_callable_boundaries() {
        let parsed = parse_source(
            &SupportLang::Rust,
            "fn outer() { let callback = || remote(); }",
        );
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        assert_eq!(
            entities
                .iter()
                .filter(|e| e.kind == EntityKind::CallableBoundary)
                .count(),
            1,
            "entities: {entities:?}"
        );
    }

    #[test]
    fn match_arms_and_boolean_operators_are_control_flow() {
        let parsed = parse_source(
            &SupportLang::Rust,
            r#"
fn accepts(value: i32, ready: bool, enabled: bool) -> bool {
    match value {
        0 => ready && enabled,
        _ => ready || enabled,
    }
}
"#,
        );
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let names: Vec<&str> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert_eq!(
            names.iter().filter(|name| **name == "match_arm").count(),
            2,
            "entities: {entities:?}"
        );
        assert!(names.contains(&"logical_and"), "entities: {entities:?}");
        assert!(names.contains(&"logical_or"), "entities: {entities:?}");
    }

    #[test]
    fn non_boolean_binary_expressions_are_not_control_flow() {
        let parsed = parse_source(
            &SupportLang::Rust,
            "fn calculate(a: i32, b: i32) -> bool { (a + b) * 2 > a }",
        );
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        assert!(
            entities
                .iter()
                .all(|entity| entity.kind != EntityKind::ControlFlow),
            "entities: {entities:?}"
        );
    }
}
