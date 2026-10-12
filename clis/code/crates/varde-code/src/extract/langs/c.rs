//! C entity extraction.
//!
//! C-specific mapping notes (fixture-driven, superset-safe), verified against
//! the tree-sitter-c grammar with `examples/dump_c.rs`:
//! - `function_definition` -> Function. The name is nested: the `declarator`
//!   field is a `function_declarator` whose own `declarator` field bottoms out
//!   at an `identifier`, optionally wrapped in `pointer_declarator` /
//!   `reference_declarator` layers for pointer-returning functions. See
//!   [`declarator_identifier`], which peels those wrappers.
//! - `struct_specifier` / `union_specifier` / `enum_specifier` with a `name`
//!   (a `type_identifier`) -> Class. A named record/enum is the closest kind to
//!   a "type with members".
//! - `type_definition` (`typedef ...`) -> Class, named after the introduced
//!   type alias (the trailing `type_identifier` in the `declarator` field).
//!   This is the closest kind — a typedef names a type — even though the alias
//!   carries no members of its own.
//! - `declaration` -> Variable (one per declared name). The `declarator` field
//!   is either a bare `identifier`, an `init_declarator` (`x = 1`), or a
//!   pointer/array wrapper; [`declarator_identifier`] unwraps each to its name.
//!   Function *prototypes* (declarator is a `function_declarator`) are skipped —
//!   they declare no storage.
//! - `parameter_declaration` -> Parameter (name via the unwrapped declarator).
//! - `preproc_include` -> Import; the `path` child is a `string_literal`
//!   (`"helper.h"`) or `system_lib_string` (`<stdio.h>`). Quotes/angle brackets
//!   are stripped. System includes still emit an Import — they simply won't
//!   resolve to a repo file, which resolve.rs handles as an unresolved edge.
//! - `call_expression` (callee = `function` field) -> Call.
//! - `field_expression` (`a.b` / `a->b`) -> MemberAccess, named after the
//!   `field` member.
//! - `number_literal` / `string_literal` / `char_literal` / `true` / `false`
//!   -> Literal. C has no type-annotation context to exclude, so all literals
//!   are emitted.
//! - ControlFlow: if/for/while/do/switch/case/return/break/continue/goto plus
//!   `conditional_expression` (the `?:` ternary).
//! - Carve-outs (see [`REQUIRED_KINDS`]): Interface (C has no interface
//!   construct), Export (no export statement — visibility is `static` linkage,
//!   not a declaration kind we model), Catch/Throw (C has no exceptions),
//!   Route/Response (no dominant in-grammar web framework). Import is exercised
//!   by fixtures + the resolve check but is a bonus kind, not on the required
//!   checklist.

use crate::extract::entity::ExtractCtx;
use crate::model::EntityKind;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

type Node<'a> = ast_grep_core::Node<'a, StrDoc<SupportLang>>;

/// Node kinds that introduce a named function scope.
pub const FUNCTION_SCOPES: &[&str] = &["function_definition"];

/// Node kinds that introduce a named record/enum type scope (for
/// `Entity::owner_type` linkage). C has no methods, but a struct's fields are
/// still owned by the record.
pub const TYPE_SCOPES: &[&str] = &["struct_specifier", "union_specifier", "enum_specifier"];

/// Entity kinds the fixtures must produce. Interface/Export/Catch/Throw/
/// Route/Response are carved out (see module docs). Import is a bonus kind
/// (exercised by fixtures + the resolve check) but not on the required list.
pub const REQUIRED_KINDS: [EntityKind; 8] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::ControlFlow,
];

// varde-ignore-next-line duplicate-code-clone -- visitor dispatch intentionally mirrors language peers
pub fn visit(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) {
    if visit_part_1(node, kind, ctx) {
        return;
    }
    if visit_part_2(node, kind, ctx) {
        return;
    }
    if visit_part_3(node, kind, ctx) {
        return;
    }
    if visit_part_4(node, kind, ctx) {
        return;
    }
    let _ = visit_part_5(node, kind, ctx);
}

fn visit_part_1(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- structural ----
        "function_definition" => {
            let name = node
                .field("declarator")
                .and_then(|d| declarator_identifier(&d))
                .unwrap_or_default();
            if !is_reserved_keyword(&name) {
                ctx.push(EntityKind::Function, name, node);
            }
        }
        "struct_specifier" | "union_specifier" | "enum_specifier" => {
            // Only *named* records/enums are types; an anonymous record used
            // inline (`struct { int x; } v;`) has no `name` field and is
            // covered by the surrounding declaration's Variable.
            if let Some(name) = node.field("name") {
                ctx.push(EntityKind::Class, name.text().into_owned(), node);
            }
        }
        "type_definition" => {
            // `typedef <type> Alias;` — the introduced alias is the
            // `type_identifier` in the `declarator` field.
            if let Some(name) = node
                .field("declarator")
                .and_then(|d| declarator_identifier(&d))
            {
                ctx.push(EntityKind::Class, name, node);
            }
        }
        // ---- imports ----
        "preproc_include" => {
            if let Some(path) = node.field("path") {
                let spec = include_path(&path);
                if !spec.is_empty() {
                    ctx.push(EntityKind::Import, spec, node);
                }
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_2(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    visit_part_2_a(node, kind, ctx) || visit_part_2_b(node, kind, ctx)
}

fn visit_part_2_a(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- variables ----
        "declaration" => {
            // A `declaration` can declare several names (`int a, b;`). Each
            // top-level declarator child is one declared entity. Function
            // prototypes (declarator is a function_declarator) declare no
            // storage, so they are skipped.
            for decl in node.field_children("declarator") {
                if is_function_declarator(&decl) {
                    // Function prototype (`int ini_parse(const char*);`):
                    // declares no storage but names an API function. Emit it as
                    // a Function so header APIs are queryable — previously
                    // dropped, so every header-only prototype was invisible
                    // (audit S3: all 5 ini.h API prototypes missing).
                    if let Some(name) = declarator_identifier(&decl)
                        && !is_reserved_keyword(&name)
                    {
                        ctx.push(EntityKind::Function, name, node);
                    }
                    continue;
                }
                if let Some(name) = declarator_identifier(&decl) {
                    ctx.push(EntityKind::Variable, name, node);
                }
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_2_b(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- preprocessor macros ----
        // `#define MAX 100` — object-like macro, a named compile-time constant;
        // mapped to Variable. `#define SQUARE(x) ((x)*(x))` — function-like
        // macro; mapped to Function. Previously neither was captured (audit S3:
        // all ~19 header macros dropped).
        "preproc_def" => {
            if let Some(name) = node.field("name") {
                ctx.push(EntityKind::Variable, name.text().into_owned(), node);
            }
        }
        "preproc_function_def" => {
            if let Some(name) = node.field("name") {
                ctx.push(EntityKind::Function, name.text().into_owned(), node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_3(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- parameters ----
        "parameter_declaration" => {
            if let Some(name) = node
                .field("declarator")
                .and_then(|d| declarator_identifier(&d))
            {
                ctx.push(EntityKind::Parameter, name, node);
            }
        }
        // ---- expression-level ----
        "call_expression" => {
            let name = node
                .field("function")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            if !is_reserved_keyword(&name) {
                ctx.push(EntityKind::Call, name, node);
            }
        }
        "field_expression" => {
            if let Some(field) = node.field("field") {
                ctx.push(EntityKind::MemberAccess, field.text().into_owned(), node);
            }
        }
        // ---- literals ----
        "number_literal" | "string_literal" | "char_literal" | "true" | "false" => {
            ctx.push(EntityKind::Literal, node.text().into_owned(), node);
        }
        _ => return false,
    }
    true
}

fn visit_part_4(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- control flow ----
        "if_statement" => {
            let else_if = is_else_if(node);
            let name = if else_if {
                "elseif_statement"
            } else {
                "if_statement"
            };
            ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            end_event_at_consequence(node, ctx);
            if let Some(alternative) = node.field("alternative") {
                // The pre-change event covered the whole `else` tail and was
                // its max-nesting parent. The trim above ended the event at
                // the consequence, so keep a legacy nesting marker over the
                // tail (`legacy_nesting` counts only in `max_nesting`).
                if !else_if {
                    ctx.push(
                        EntityKind::ControlFlow,
                        "legacy_nesting".to_string(),
                        &alternative,
                    );
                }
                // A plain `else` is a hybrid increment. An `else` that
                // directly wraps an `if` stays the `elseif_statement` event
                // above (`spec:176-179`, `491-518`).
                if let Some(body) = alternative
                    .children()
                    .find(|child| child.is_named() && child.kind() != "comment")
                    && body.kind() != "if_statement"
                {
                    ctx.push(EntityKind::ControlFlow, "else_branch".to_string(), &body);
                }
            }
        }
        "binary_expression" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }
        "unary_expression" if is_negated_logical_sequence(node) => {
            ctx.push(EntityKind::ControlFlow, "negation_break".to_string(), node);
        }
        "for_statement"
        | "while_statement"
        | "switch_statement"
        | "case_statement"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "goto_statement"
        | "conditional_expression" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        "do_statement" => {
            ctx.push(
                EntityKind::ControlFlow,
                "do_while_statement".to_string(),
                node,
            );
        }
        _ => return false,
    }
    true
}

fn visit_part_5(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "seh_try_statement" | "seh_except_clause" | "seh_finally_clause" => {
            ctx.push(
                EntityKind::ControlFlow,
                "unknown_seh_region".to_string(),
                node,
            );
        }
        _ => return false,
    }
    true
}

/// Stable complexity name for C's short-circuit boolean operators.
fn boolean_operator_name(node: &Node<'_>) -> Option<&'static str> {
    match node.field("operator")?.text().as_ref() {
        "&&" => Some("logical_and"),
        "||" => Some("logical_or"),
        _ => None,
    }
}

/// End the event just pushed at this `if`'s consequence. The syntax span
/// covers the whole `else` tail; ending it earlier keeps later branches at the
/// root `if` body's nesting level (`spec:502-518`). Shared with C++.
pub(crate) fn end_event_at_consequence(node: &Node<'_>, ctx: &mut ExtractCtx) {
    let Some(consequence) = node.field("consequence") else {
        return;
    };
    let span = crate::extract::span_of(&consequence);
    if let Some(event) = ctx.out.last_mut() {
        event.span.end_byte = span.end_byte;
        event.span.end_line = span.end_line;
        event.span.end_col = span.end_col;
    }
}

/// Whether this unary expression is a negated binary logical sequence, which
/// starts a new like-operator run (`spec:207-229`, `254-256`).
fn is_negated_logical_sequence(node: &Node<'_>) -> bool {
    node.field("operator")
        .is_some_and(|operator| matches!(operator.text().as_ref(), "!" | "not"))
        && node.dfs().skip(1).any(|child| {
            child.kind() == "binary_expression" && boolean_operator_name(&child).is_some()
        })
}

/// Whether this `if` is the direct branch of an `else` clause.
fn is_else_if(node: &Node<'_>) -> bool {
    node.parent().is_some_and(|parent| {
        parent.kind() == "else_clause"
            && parent
                .parent()
                .is_some_and(|outer| outer.kind() == "if_statement")
    })
}

/// C/C++ reserved keywords that must never surface as an entity name. Under
/// preprocessor confusion or error recovery, tree-sitter can reparse
/// `if (...)`, `while (...)`, `switch (...)`, or a `template`/`class`/
/// `namespace` head as a `function_definition`/`call_expression`/type whose
/// name text is the keyword itself. Since a reserved word can never be a valid
/// identifier, dropping these at the name-bearing push sites removes the noise
/// with no risk of discarding a real declaration. Shared with the C++ extractor.
pub(crate) fn is_reserved_keyword(name: &str) -> bool {
    matches!(
        name,
        "if" | "else"
            | "for"
            | "while"
            | "do"
            | "switch"
            | "case"
            | "default"
            | "return"
            | "break"
            | "continue"
            | "goto"
            | "sizeof"
            | "typedef"
            | "struct"
            | "union"
            | "enum"
            | "class"
            | "template"
            | "typename"
            | "namespace"
            | "using"
            | "new"
            | "delete"
            | "throw"
            | "try"
            | "catch"
            | "operator"
            | "const"
            | "static"
            | "public"
            | "private"
            | "protected"
            | "virtual"
            | "friend"
            | "inline"
            | "explicit"
            | "constexpr"
            | "noexcept"
            | "static_assert"
    )
}

/// Peels the declarator layers of a `function_definition` down to its
/// `function_declarator` (pointer-returning functions wrap it in a
/// `pointer_declarator`). Shared with C++.
pub(crate) fn function_declarator<'a>(node: &Node<'a>) -> Option<Node<'a>> {
    let mut current = node.field("declarator")?;
    loop {
        match current.kind().as_ref() {
            "function_declarator" => return Some(current),
            "pointer_declarator" | "array_declarator" | "parenthesized_declarator" => {
                current = current.field("declarator")?;
            }
            _ => return None,
        }
    }
}

/// Callable name of a `function_definition`: the operator's own text for an
/// `operator+`-style declarator (so overloaded operators are callables),
/// otherwise the unwrapped identifier. Shared with C++.
pub(crate) fn function_name(node: &Node<'_>) -> Option<String> {
    let declarator = node.field("declarator")?;
    if let Some(operator) = declarator
        .dfs()
        .find(|child| child.kind() == "operator_name")
    {
        let name = operator.text().trim().to_string();
        return (!name.is_empty()).then_some(name);
    }
    declarator_identifier(&declarator)
}

/// Inclusive `parameter_list` bounds `(required, total)` for a function
/// definition, or `(0, 0)` when it has no parameter list. Defaulted
/// parameters are optional; a variadic tail makes the total unbounded.
/// Shared with C++.
pub(crate) fn callable_arity(node: &Node<'_>) -> (u16, u16) {
    let Some(parameters) = function_declarator(node).and_then(|fd| fd.field("parameters")) else {
        return (0, 0);
    };
    let mut required = 0u16;
    let mut total = 0u16;
    let mut variadic = false;
    for parameter in parameters.children() {
        match parameter.kind().as_ref() {
            // A `(void)` parameter list declares no parameters.
            "parameter_declaration"
                if parameter.field("declarator").is_none() && parameter.text().trim() == "void" => {
            }
            "parameter_declaration" | "identifier" => {
                required = required.saturating_add(1);
                total = total.saturating_add(1);
            }
            "optional_parameter_declaration" => total = total.saturating_add(1),
            "variadic_parameter_declaration" => variadic = true,
            _ => {}
        }
    }
    if variadic {
        total = u16::MAX;
    }
    (required, total)
}

/// Span of the callable's name token, used for the emitted `recursive_call`
/// marker. Falls back to the definition span when no name token is found.
/// Shared with C++.
pub(crate) fn name_token_span(node: &Node<'_>) -> Option<crate::model::Span> {
    let declarator = node.field("declarator")?;
    let target = declarator
        .dfs()
        .find(|child| matches!(child.kind().as_ref(), "operator_name" | "destructor_name"))
        .or_else(|| {
            declarator
                .dfs()
                .find(|child| matches!(child.kind().as_ref(), "identifier" | "field_identifier"))
        })?;
    Some(crate::extract::span_of(&target))
}

/// Peel a declarator down to its bottom `identifier` / `field_identifier`
/// name. C nests declarators: a `function_declarator` / `init_declarator` /
/// `pointer_declarator` / `reference_declarator` / `array_declarator` /
/// `parenthesized_declarator` each carry an inner `declarator` field (or, for
/// `type_definition`, a trailing `type_identifier`). Returns the innermost
/// name, or `None` for abstract declarators with no name.
pub(crate) fn declarator_identifier(node: &Node<'_>) -> Option<String> {
    match node.kind().as_ref() {
        "identifier" | "field_identifier" | "type_identifier" => Some(node.text().into_owned()),
        // Wrappers that carry the real declarator in their `declarator` field
        // (`pointer_declarator`/`function_declarator` in a `declaration`), or,
        // when that field is absent (e.g. a `reference_declarator` inside a
        // catch/param list), directly as an identifier child. Try the field
        // first, then fall through to the child scan below.
        "function_declarator"
        | "init_declarator"
        | "pointer_declarator"
        | "reference_declarator"
        | "array_declarator"
        | "parenthesized_declarator" => node
            .field("declarator")
            .and_then(|d| declarator_identifier(&d))
            .or_else(|| child_identifier(node)),
        // `type_definition`'s declarator field is a bare `type_identifier`
        // (handled above) but the trailing alias may also appear as a child
        // when wrapped; fall back to the first named identifier-ish child.
        _ => child_identifier(node),
    }
}

/// Scan a node's direct children for the first identifier-ish name, recursing
/// into further declarator wrappers. Used as the fallback when a wrapper has no
/// `declarator` field (its inner declarator is a plain child).
fn child_identifier(node: &Node<'_>) -> Option<String> {
    node.children().find_map(|c| match c.kind().as_ref() {
        "identifier" | "field_identifier" | "type_identifier" => Some(c.text().into_owned()),
        "pointer_declarator"
        | "reference_declarator"
        | "array_declarator"
        | "parenthesized_declarator"
        | "function_declarator"
        | "init_declarator" => declarator_identifier(&c),
        _ => None,
    })
}

/// True when this declarator (after peeling pointer/array wrappers) is a
/// `function_declarator` — i.e. a function prototype, not a storage variable.
fn is_function_declarator(node: &Node<'_>) -> bool {
    match node.kind().as_ref() {
        "function_declarator" => true,
        "pointer_declarator" | "array_declarator" | "parenthesized_declarator" => node
            .field("declarator")
            .map(|d| is_function_declarator(&d))
            .unwrap_or(false),
        _ => false,
    }
}

/// Strip the surrounding quotes/angle brackets from an include `path` node:
/// `"helper.h"` -> `helper.h`, `<stdio.h>` -> `stdio.h`.
fn include_path(node: &Node<'_>) -> String {
    let raw = node.text();
    let t = raw.trim();
    let bytes = t.as_bytes();
    if t.len() >= 2 {
        let stripped = (bytes[0] == b'"' && bytes[t.len() - 1] == b'"')
            || (bytes[0] == b'<' && bytes[t.len() - 1] == b'>');
        if stripped {
            return t[1..t.len() - 1].to_string();
        }
    }
    t.to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::model::{Entity, EntityKind};
    use crate::parse::parse_source;

    fn extract(src: &str) -> Vec<Entity> {
        let parsed = parse_source(&SupportLang::C, src);
        crate::extract::extract(&parsed, 0).entities
    }

    fn names(entities: &[Entity], kind: EntityKind) -> Vec<String> {
        entities
            .iter()
            .filter(|e| e.kind == kind)
            .map(|e| e.name.clone())
            .collect()
    }

    #[test]
    fn macros_and_header_prototypes_are_captured() {
        // Audit S3: object-like macros, function-like macros, and header
        // function prototypes were all dropped.
        let src = "#define MAX 100\n\
                   #define SQUARE(x) ((x)*(x))\n\
                   int ini_parse(const char* path);\n";
        let es = extract(src);
        let funcs = names(&es, EntityKind::Function);
        let vars = names(&es, EntityKind::Variable);
        assert!(vars.contains(&"MAX".to_string()), "object macro: {vars:?}");
        assert!(funcs.contains(&"SQUARE".to_string()), "fn macro: {funcs:?}");
        assert!(
            funcs.contains(&"ini_parse".to_string()),
            "prototype: {funcs:?}"
        );
    }

    #[test]
    fn reserved_keywords_are_recognized_but_real_names_are_not() {
        for kw in [
            "if",
            "while",
            "for",
            "switch",
            "return",
            "class",
            "template",
            "namespace",
        ] {
            assert!(is_reserved_keyword(kw), "{kw} should be reserved");
        }
        for name in ["add", "ini_parse", "handler", "Color", "user_data"] {
            assert!(!is_reserved_keyword(name), "{name} is a real identifier");
        }
    }

    #[test]
    fn control_flow_keyword_is_not_emitted_as_a_function() {
        // A normal `if` is a control-flow entity named after its node kind, never
        // a Function/Call named `if` (the error-recovery artifact this guards).
        let src = "int f(int x) { if (x) { g(); } return x; }\n";
        let e = extract(src);
        assert!(
            !names(&e, EntityKind::Function).contains(&"if".to_string())
                && !names(&e, EntityKind::Call).contains(&"if".to_string()),
            "`if` must not be a function/call: {:?}",
            e.iter().map(|x| (&x.kind, &x.name)).collect::<Vec<_>>()
        );
        assert!(names(&e, EntityKind::Function).contains(&"f".to_string()));
    }

    #[test]
    fn function_name_unwraps_declarator_nesting() {
        let src = "int add(int a, int b) { return a + b; }\n\
                   char *dup(const char *s) { return 0; }\n";
        let e = extract(src);
        let fns = names(&e, EntityKind::Function);
        assert!(fns.contains(&"add".to_string()), "got {fns:?}");
        // Pointer-returning function: name is under a pointer_declarator layer.
        assert!(fns.contains(&"dup".to_string()), "got {fns:?}");
    }

    #[test]
    fn records_and_typedef_map_to_class() {
        let src = "struct Point { int x; int y; };\n\
                   union U { int i; float f; };\n\
                   enum Color { RED, GREEN };\n\
                   typedef int MyInt;\n";
        let e = extract(src);
        let classes = names(&e, EntityKind::Class);
        for want in ["Point", "U", "Color", "MyInt"] {
            assert!(
                classes.contains(&want.to_string()),
                "missing {want}: {classes:?}"
            );
        }
    }

    #[test]
    fn variables_params_and_calls() {
        let src = "int counter = 0;\n\
                   int f(int n) { int x = n; g(x); return x; }\n";
        let e = extract(src);
        assert!(names(&e, EntityKind::Variable).contains(&"counter".to_string()));
        assert!(names(&e, EntityKind::Variable).contains(&"x".to_string()));
        assert!(names(&e, EntityKind::Parameter).contains(&"n".to_string()));
        assert!(names(&e, EntityKind::Call).contains(&"g".to_string()));
    }

    #[test]
    fn member_access_from_dot_and_arrow() {
        let src = "int f(struct S *p, struct S q) { return p->a + q.b; }\n";
        let e = extract(src);
        let ma = names(&e, EntityKind::MemberAccess);
        assert!(ma.contains(&"a".to_string()), "got {ma:?}");
        assert!(ma.contains(&"b".to_string()), "got {ma:?}");
    }

    #[test]
    fn includes_emit_imports_stripped() {
        let src = "#include <stdio.h>\n#include \"helper.h\"\n";
        let e = extract(src);
        let imports = names(&e, EntityKind::Import);
        assert!(imports.contains(&"stdio.h".to_string()), "got {imports:?}");
        assert!(imports.contains(&"helper.h".to_string()), "got {imports:?}");
    }

    #[test]
    fn control_flow_and_literals() {
        let src = "int f(int a) {\n\
                     if (a) { return 1; }\n\
                     for (int i = 0; i < 3; i++) {}\n\
                     while (a) { break; }\n\
                     switch (a) { case 1: continue; }\n\
                     int t = a ? 2 : 3;\n\
                     char c = 'x';\n\
                     const char *s = \"hi\";\n\
                     return 0;\n\
                   }\n";
        let e = extract(src);
        let cf = names(&e, EntityKind::ControlFlow);
        for want in [
            "if_statement",
            "for_statement",
            "while_statement",
            "return_statement",
        ] {
            assert!(cf.contains(&want.to_string()), "missing {want}: {cf:?}");
        }
        let lits = names(&e, EntityKind::Literal);
        assert!(lits.iter().any(|l| l == "'x'"));
        assert!(lits.iter().any(|l| l == "\"hi\""));
    }

    #[test]
    fn complexity_events_cover_boolean_switch_else_if_and_seh() {
        let src = "int f(int x, int a, int b, int c) {\n\
                     if (a && b || c) {} else if (b) {}\n\
                     do { x++; } while (a);\n\
                     switch (x) { case 0: break; case 1: break; default: break; }\n\
                     __try { x++; } __except (1) { x--; }\n\
                     return x;\n\
                   }\n";
        let e = extract(src);
        let cf = names(&e, EntityKind::ControlFlow);

        assert_eq!(cf.iter().filter(|name| *name == "if_statement").count(), 1);
        assert_eq!(
            cf.iter().filter(|name| *name == "elseif_statement").count(),
            1
        );
        assert!(cf.contains(&"logical_and".to_string()), "events: {cf:?}");
        assert!(cf.contains(&"logical_or".to_string()), "events: {cf:?}");
        assert!(
            cf.contains(&"do_while_statement".to_string()),
            "events: {cf:?}"
        );
        assert_eq!(
            cf.iter().filter(|name| *name == "case_statement").count(),
            3
        );
        assert!(
            cf.contains(&"unknown_seh_region".to_string()),
            "events: {cf:?}"
        );
        let metrics = crate::complexity::function_complexities(&e);
        assert_eq!(
            metrics[0].confidence,
            crate::complexity::ComplexityConfidence::Low
        );
    }

    #[test]
    fn else_chain_emits_else_branch_and_legacy_nesting() {
        let src = "int f(int a, int b, int c) {\n\
                     if (a) { return 1; } else if (b) { if (c) { return 2; } } else { if (a) { return 3; } }\n\
                     return 0;\n\
                   }\n";
        let parsed = parse_source(&SupportLang::C, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        let flows = names(&entities, EntityKind::ControlFlow);
        assert_eq!(
            flows.iter().filter(|name| *name == "if_statement").count(),
            3,
            "entities: {flows:?}"
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "elseif_statement")
                .count(),
            1
        );
        assert_eq!(
            flows.iter().filter(|name| *name == "else_branch").count(),
            1
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "legacy_nesting")
                .count(),
            1
        );
        let metric = &crate::complexity::function_complexities(&entities)[0];
        // root if 1 + else if 1 + its body if 2 + else 1 + its body if 2.
        assert_eq!(metric.cognitive, 7, "metric: {metric:?}");
        assert_eq!(metric.cyclomatic, 5, "metric: {metric:?}");
        assert_eq!(metric.max_nesting, 1, "metric: {metric:?}");
        // One point per control-flow row: three ifs, the else if, and four
        // returns; `else_branch` and `legacy_nesting` are complexity-only.
        assert_eq!(crate::complexity::cyclomatic_for_entities(&entities), 9);
    }

    #[test]
    fn negation_goto_and_recursion_roles_score_once() {
        let src = "int f(int a, int b) {\n\
                     if (a && !(b && a)) { goto done; }\n\
                   done:\n\
                     return f(a - 1, b);\n\
                   }\n";
        let parsed = parse_source(&SupportLang::C, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        let flows = names(&entities, EntityKind::ControlFlow);
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "negation_break")
                .count(),
            1,
            "entities: {flows:?}"
        );
        assert!(
            flows.iter().any(|name| name == "goto_statement"),
            "entities: {flows:?}"
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "recursive_call")
                .count(),
            1
        );
        let metric = &crate::complexity::function_complexities(&entities)[0];
        // if 1 + outer run 1 + negated inner run 1 + goto 1 + recursion 1.
        assert_eq!(metric.cognitive, 5, "metric: {metric:?}");
        assert_eq!(metric.cyclomatic, 4, "metric: {metric:?}");
    }

    #[test]
    fn receiver_calls_and_missing_peers_do_not_create_recursion() {
        let src = "struct Ops { int (*through_ptr)(struct Ops *ops, int n); };\n\
                   int through_ptr(struct Ops *ops, int n) { return ops->through_ptr(ops, n); }\n\
                   int missing(int n) { return absent_peer(n); }\n";
        let parsed = parse_source(&SupportLang::C, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        let metrics = crate::complexity::function_complexities(&entities);
        for name in ["through_ptr", "missing"] {
            let metric = metrics.iter().find(|metric| metric.name == name).unwrap();
            assert_eq!(metric.cognitive, 0, "{metric:?}");
        }
    }
}

/// Language-specific flow-role overrides, extended by language tasks.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[];

/// Collect free-function declarations and same-file call references for the
/// shared recursion resolver. C functions are module-level, so every callable
/// is a valid unqualified target.
pub fn match_callees(
    root: &super::ParsedNode<'_>,
) -> (
    Vec<crate::extract::recursion::Callable>,
    Vec<crate::extract::recursion::CalleeReference>,
) {
    use crate::extract::recursion::{Callable, CalleeReference, Qualifier};

    let callables: Vec<_> = root
        .dfs()
        .filter(|node| FUNCTION_SCOPES.contains(&node.kind().as_ref()))
        .filter_map(|node| {
            let name = function_name(&node)?;
            let (required_args, total_args) = callable_arity(&node);
            Some(Callable {
                owner: None,
                owner_type: None,
                unqualified_callable: true,
                name,
                required_args,
                total_args,
                file_id: 0,
                span: crate::extract::span_of(&node),
                name_span: name_token_span(&node).unwrap_or_else(|| crate::extract::span_of(&node)),
            })
        })
        .collect();

    let mut references = Vec::new();
    for call in root.dfs().filter(|node| node.kind() == "call_expression") {
        let Some(caller_node) = call
            .ancestors()
            .find(|ancestor| FUNCTION_SCOPES.contains(&ancestor.kind().as_ref()))
        else {
            continue;
        };
        let caller_span = crate::extract::span_of(&caller_node);
        let Some(caller) = callables.iter().position(|item| item.span == caller_span) else {
            continue;
        };
        let Some(function) = call.field("function") else {
            continue;
        };
        let (name, qualifier) = match function.kind().as_ref() {
            "identifier" => (function.text().into_owned(), Qualifier::None),
            // A struct-member call (`table->handler(x)`) goes through a
            // function-pointer field, not the current free function.
            "field_expression" => {
                let Some(field) = function.field("field") else {
                    continue;
                };
                (field.text().into_owned(), Qualifier::Other)
            }
            _ => continue,
        };
        let argument_count = call
            .field("arguments")
            .map(|arguments| {
                arguments
                    .children()
                    .filter(|child| child.is_named())
                    .count()
            })
            .unwrap_or(0);
        references.push(CalleeReference {
            caller,
            name,
            argument_count: u16::try_from(argument_count).unwrap_or(u16::MAX),
            qualifier,
            qualifier_name: None,
        });
    }
    (callables, references)
}
