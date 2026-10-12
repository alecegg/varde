//! C++ entity extraction.
//!
//! C++-specific mapping notes (fixture-driven, superset-safe), verified against
//! the tree-sitter-cpp grammar with `examples/dump_cpp.rs`. C++ reuses C's
//! node-kind mapping (shared declarator-unwrap via [`super::c`]) and adds the
//! class/namespace/exception constructs on top:
//! - `function_definition` -> Function (name via the unwrapped `declarator`;
//!   methods carry a `field_identifier` leaf, free functions an `identifier`).
//! - `class_specifier` / `struct_specifier` / `union_specifier` /
//!   `enum_specifier` (named) -> Class. `base_class_clause` (`: public Base`)
//!   -> one Extends per listed base type.
//! - `namespace_definition` -> a type scope (for `owner_type` linkage) and
//!   emits nothing itself; C++ namespaces are grouping scopes, not entities we
//!   model.
//! - `declaration` / `field_declaration` -> Variable (member and local
//!   variables); function prototypes are skipped. `parameter_declaration` ->
//!   Parameter. Names all go through [`super::c::declarator_identifier`].
//! - Import: `preproc_include` (`#include`, same as C) and
//!   `using_declaration` (`using std::string;` / `using namespace std;`) ->
//!   Import, spec taken from the declaration's identifier text. `::` is
//!   normalized to `/` so resolve.rs's shared `/`-segment stem matching applies
//!   (mirrors PHP's `\` handling); a header `#include` resolves to a sibling
//!   file, a `using` typically stays unresolved (a namespace, not a file).
//! - Call: `call_expression` (callee = `function` field) -> Call.
//!   `new_expression` -> Call, named after the constructed type (the closest
//!   kind — a constructor invocation).
//! - `field_expression` (`a.b` / `a->b` / method calls) -> MemberAccess.
//! - `number_literal` / `string_literal` / `char_literal` / `true` / `false`
//!   -> Literal.
//! - `try_statement` -> ControlFlow; `catch_clause` -> Catch, named after the
//!   caught parameter; `throw_statement` / `throw_expression` -> Throw, named
//!   after the thrown expression.
//! - ControlFlow: if/for/while/do/switch/case/return/break/continue/goto/try
//!   plus `conditional_expression`.
//! - Carve-outs (see [`REQUIRED_KINDS`]): Interface (C++ has no interface
//!   keyword — pure-virtual "interfaces" are too fuzzy to detect reliably),
//!   Export (no export statement we model), Route/Response (no dominant
//!   in-grammar web framework). Unlike C, C++ KEEPS Catch/Throw. Import is a
//!   bonus kind (fixtures + resolve check) but not on the required checklist.

use crate::extract::entity::ExtractCtx;
use crate::extract::langs::c::{
    callable_arity, declarator_identifier, end_event_at_consequence, function_declarator,
    function_name, is_reserved_keyword, name_token_span,
};
use crate::model::EntityKind;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

type Node<'a> = ast_grep_core::Node<'a, StrDoc<SupportLang>>;

/// Node kinds that introduce a named function scope.
pub const FUNCTION_SCOPES: &[&str] = &["function_definition"];

/// Node kinds that introduce a named class/record/namespace type scope (for
/// `Entity::owner_type` linkage on methods).
pub const TYPE_SCOPES: &[&str] = &[
    "class_specifier",
    "struct_specifier",
    "union_specifier",
    "enum_specifier",
    "namespace_definition",
];

/// Entity kinds the fixtures must produce. Interface/Export/Route/Response are
/// carved out (see module docs); C++ keeps Catch/Throw. Import is a bonus kind
/// (exercised by fixtures + the resolve check) but not on the required list.
pub const REQUIRED_KINDS: [EntityKind; 10] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::Catch,
    EntityKind::Throw,
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
    if visit_part_5(node, kind, ctx) {
        return;
    }
    let _ = visit_part_6(node, kind, ctx);
}

fn visit_part_1(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    visit_part_1_a(node, kind, ctx) || visit_part_1_b(node, kind, ctx)
}

fn visit_part_1_a(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- structural ----
        "function_definition" => {
            if let Some(name) = function_name(node)
                && !is_reserved_keyword(&name)
            {
                ctx.push(EntityKind::Function, name, node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_1_b(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "lambda_expression" => ctx.push_callable_boundary(node),
        "class_specifier" | "struct_specifier" | "union_specifier" | "enum_specifier" => {
            if let Some(name) = node
                .field("name")
                .filter(|n| !is_reserved_keyword(&n.text()))
            {
                let cls = name.text().into_owned();
                ctx.push(EntityKind::Class, cls.clone(), node);
                // Inheritance: each base type in the base_class_clause -> Extends.
                if let Some(clause) = node.children().find(|c| c.kind() == "base_class_clause") {
                    for base in clause.children() {
                        if matches!(
                            base.kind().as_ref(),
                            "type_identifier" | "qualified_identifier" | "template_type"
                        ) {
                            super::push_type_ref(
                                ctx,
                                EntityKind::Extends,
                                base.text().into_owned(),
                                &cls,
                                &base,
                            );
                        }
                    }
                }
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_2(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "type_definition" => {
            if let Some(name) = node
                .field("declarator")
                .and_then(|d| declarator_identifier(&d))
                .filter(|n| !is_reserved_keyword(n))
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
        "using_declaration" => {
            // `using std::string;` / `using namespace std;` — take the
            // trailing identifier/qualified name, normalizing `::` -> `/`.
            if let Some(spec) = using_spec(node) {
                ctx.push(EntityKind::Import, spec, node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_3(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    visit_part_3_a(node, kind, ctx) || visit_part_3_b(node, kind, ctx)
}

fn visit_part_3_a(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        // ---- variables ----
        "declaration" | "field_declaration" => {
            for decl in node.field_children("declarator") {
                if is_function_declarator(&decl) {
                    continue;
                }
                if let Some(name) = declarator_identifier(&decl) {
                    ctx.push(EntityKind::Variable, name, node);
                }
            }
            // A `field_declaration` with an initialized member (`int count = 0;`)
            // exposes its name as a bare `field_identifier` child rather than a
            // `declarator` field.
            if kind == "field_declaration"
                && node.field("declarator").is_none()
                && let Some(fid) = node.children().find(|c| c.kind() == "field_identifier")
            {
                ctx.push(EntityKind::Variable, fid.text().into_owned(), node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_3_b(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
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
        _ => return false,
    }
    true
}

fn visit_part_4(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "new_expression" => {
            // `new Foo(...)` — a constructor invocation; map to Call named
            // after the constructed type.
            let name = node
                .field("type")
                .map(|t| t.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Call, name, node);
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
        // ---- exceptions ----
        "catch_clause" => {
            // Name after the caught parameter (`catch (const E& e)` -> "e").
            let name = node
                .field("parameters")
                .and_then(|p| p.children().find(|c| c.kind() == "parameter_declaration"))
                .and_then(|pd| {
                    pd.field("declarator")
                        .and_then(|d| declarator_identifier(&d))
                })
                .unwrap_or_default();
            ctx.push(EntityKind::Catch, name, node);
        }
        _ => return false,
    }
    true
}

fn visit_part_5(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "throw_statement" | "throw_expression" => {
            // Name after the thrown expression (the first named child).
            let name = node
                .children()
                .find(|c| c.get_inner_node().is_named())
                .map(|c| c.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Throw, name, node);
        }
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
        | "for_range_loop"
        | "while_statement"
        | "switch_statement"
        | "case_statement"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "goto_statement"
        | "try_statement"
        | "conditional_expression" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        _ => return false,
    }
    true
}

fn visit_part_6(node: &Node<'_>, kind: &str, ctx: &mut ExtractCtx) -> bool {
    match kind {
        "do_statement" => {
            ctx.push(
                EntityKind::ControlFlow,
                "do_while_statement".to_string(),
                node,
            );
        }
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

/// Stable complexity name for C++ short-circuit operators.
fn boolean_operator_name(node: &Node<'_>) -> Option<&'static str> {
    match node.field("operator")?.text().as_ref() {
        "&&" | "and" => Some("logical_and"),
        "||" | "or" => Some("logical_or"),
        _ => None,
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

/// True when this declarator (after peeling pointer/array wrappers) is a
/// `function_declarator` — a method/function prototype, not a storage variable.
fn is_function_declarator(node: &Node<'_>) -> bool {
    match node.kind().as_ref() {
        "function_declarator" => true,
        "pointer_declarator"
        | "array_declarator"
        | "reference_declarator"
        | "parenthesized_declarator" => node
            .field("declarator")
            .map(|d| is_function_declarator(&d))
            .unwrap_or(false),
        _ => false,
    }
}

/// Spec of a `using_declaration`: the trailing qualified/plain identifier,
/// with `::` normalized to `/` for the shared stem matcher. Returns `None`
/// when the declaration carries no name (defensive).
fn using_spec(node: &Node<'_>) -> Option<String> {
    let name = node
        .children()
        .filter(|c| {
            matches!(
                c.kind().as_ref(),
                "qualified_identifier" | "identifier" | "namespace_identifier" | "type_identifier"
            )
        })
        .map(|c| c.text().into_owned())
        .next()?;
    Some(name.replace("::", "/"))
}

/// Strip the surrounding quotes/angle brackets from an include `path` node:
/// `"helper.h"` -> `helper.h`, `<string>` -> `string`.
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
        let parsed = parse_source(&SupportLang::Cpp, src);
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
    fn class_with_base_emits_class_and_extends() {
        let src = "class Base {};\nclass Widget : public Base { public: void run(); };\n";
        let e = extract(src);
        let classes = names(&e, EntityKind::Class);
        assert!(classes.contains(&"Base".to_string()), "got {classes:?}");
        assert!(classes.contains(&"Widget".to_string()), "got {classes:?}");
        assert!(
            names(&e, EntityKind::Extends).contains(&"Base".to_string()),
            "extends: {:?}",
            names(&e, EntityKind::Extends)
        );
    }

    #[test]
    fn scoped_enum_keeps_type_name_and_never_emits_the_keyword() {
        // Regression: `enum class Color` is a scoped enum whose type name is
        // `Color`, not the `class` keyword. Under error recovery the keyword can
        // leak as an entity name; the reserved-keyword guard drops it while the
        // real type survives.
        let src = "enum class Color { red, green };\n";
        let e = extract(src);
        let classes = names(&e, EntityKind::Class);
        assert!(classes.contains(&"Color".to_string()), "got {classes:?}");
        assert!(
            !e.iter().any(|x| x.name == "class"),
            "the `class` keyword must never be an entity: {:?}",
            e.iter().map(|x| &x.name).collect::<Vec<_>>()
        );
    }

    #[test]
    fn method_name_and_params() {
        let src = "class W { public: void run(int n) { int x = n; go(x); } };\n";
        let e = extract(src);
        assert!(names(&e, EntityKind::Function).contains(&"run".to_string()));
        assert!(names(&e, EntityKind::Parameter).contains(&"n".to_string()));
        assert!(names(&e, EntityKind::Variable).contains(&"x".to_string()));
        assert!(names(&e, EntityKind::Call).contains(&"go".to_string()));
    }

    #[test]
    fn member_variable_initializer_is_variable() {
        let src = "class W { int count = 0; };\n";
        let e = extract(src);
        assert!(
            names(&e, EntityKind::Variable).contains(&"count".to_string()),
            "got {:?}",
            names(&e, EntityKind::Variable)
        );
    }

    #[test]
    fn try_catch_throw_and_new() {
        let src = "void f() {\n\
                     Base* b = new Base();\n\
                     try { b->go(); throw std::runtime_error(\"x\"); }\n\
                     catch (const std::exception& e) { handle(e); }\n\
                   }\n";
        let e = extract(src);
        assert!(names(&e, EntityKind::ControlFlow).contains(&"try_statement".to_string()));
        assert!(
            names(&e, EntityKind::Catch).contains(&"e".to_string()),
            "catch: {:?}",
            names(&e, EntityKind::Catch)
        );
        assert!(
            !names(&e, EntityKind::Throw).is_empty(),
            "throw missing: {:?}",
            names(&e, EntityKind::Throw)
        );
        // `new Base()` -> Call named after the type.
        assert!(
            names(&e, EntityKind::Call).contains(&"Base".to_string()),
            "call: {:?}",
            names(&e, EntityKind::Call)
        );
    }

    #[test]
    fn includes_and_using_emit_imports() {
        let src = "#include \"helper.h\"\nusing std::string;\n";
        let e = extract(src);
        let imports = names(&e, EntityKind::Import);
        assert!(imports.contains(&"helper.h".to_string()), "got {imports:?}");
        assert!(
            imports.iter().any(|i| i == "std/string"),
            "using not normalized: {imports:?}"
        );
    }

    #[test]
    fn member_access_and_literals() {
        let src = "void f(W* p) { int y = p->count; bool ok = true; double d = 3.14; }\n";
        let e = extract(src);
        assert!(names(&e, EntityKind::MemberAccess).contains(&"count".to_string()));
        let lits = names(&e, EntityKind::Literal);
        assert!(lits.iter().any(|l| l == "true"));
        assert!(lits.iter().any(|l| l == "3.14"));
    }

    #[test]
    fn lambdas_are_callable_boundaries() {
        let e = extract("void outer() { auto callback = [] { remote(); }; }\n");
        assert_eq!(
            e.iter()
                .filter(|e| e.kind == EntityKind::CallableBoundary)
                .count(),
            1,
            "entities: {e:?}"
        );
    }

    #[test]
    fn complexity_events_cover_boolean_switch_else_if_catch_and_lambda() {
        let src = "int f(int x, bool a, bool b, bool c) {\n\
                     if (a and b || c) {} else if (b) {}\n\
                     do { x++; } while (a);\n\
                     switch (x) { case 0: break; case 1: break; default: break; }\n\
                     try { throw 1; } catch (...) { x--; }\n\
                     auto callback = [] { remote(); };\n\
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
        assert_eq!(names(&e, EntityKind::Catch).len(), 1, "entities: {e:?}");
        assert_eq!(
            e.iter()
                .filter(|entity| entity.kind == EntityKind::CallableBoundary)
                .count(),
            1,
            "entities: {e:?}"
        );
    }

    #[test]
    fn unsupported_seh_regions_lower_complexity_confidence() {
        let e = extract("int f() { __try { return 1; } __except (1) { return 0; } }\n");
        assert!(
            names(&e, EntityKind::ControlFlow).contains(&"unknown_seh_region".to_string()),
            "entities: {e:?}"
        );
        let metrics = crate::complexity::function_complexities(&e);
        assert_eq!(
            metrics[0].confidence,
            crate::complexity::ComplexityConfidence::Low
        );
    }

    #[test]
    fn else_branch_lambda_and_negation_roles_are_emitted() {
        let src = "int f(bool a, bool b, bool c) {\n\
                     if (a) { return 1; } else { if (b) { return 2; } }\n\
                     auto callback = [&] { return !(b && c); };\n\
                     return callback() ? 1 : 0;\n\
                   }\n";
        let parsed = parse_source(&SupportLang::Cpp, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        let flows = names(&entities, EntityKind::ControlFlow);
        assert_eq!(
            flows.iter().filter(|name| *name == "else_branch").count(),
            1,
            "entities: {flows:?}"
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "legacy_nesting")
                .count(),
            1
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| *name == "negation_break")
                .count(),
            1
        );
        assert_eq!(
            entities
                .iter()
                .filter(|entity| entity.kind == EntityKind::CallableBoundary)
                .count(),
            1
        );
    }

    #[test]
    fn operators_and_class_scoped_recursion_are_callables() {
        let src = "struct Counter {\n\
                     int value;\n\
                     Counter other;\n\
                     int step(int n) { return this->step(n - 1); }\n\
                     int other_step(int n) { return other.step(n); }\n\
                     Counter operator+(const Counter& rhs) { if (rhs.value) { return rhs; } return *this; }\n\
                     ~Counter() {}\n\
                   };\n";
        let parsed = parse_source(&SupportLang::Cpp, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        assert!(
            names(&entities, EntityKind::Function).contains(&"operator+".to_string()),
            "entities: {:?}",
            names(&entities, EntityKind::Function)
        );
        let metrics = crate::complexity::function_complexities(&entities);
        for (name, cognitive) in [
            ("step", 1),
            ("other_step", 0),
            ("operator+", 1),
            ("Counter", 0),
        ] {
            let metric = metrics.iter().find(|metric| metric.name == name).unwrap();
            assert_eq!(metric.cognitive, cognitive, "{metric:?}");
        }
    }

    #[test]
    fn qualified_and_out_of_line_self_calls_bind() {
        let src = "struct Runner {\n\
                     int direct(int n) { return Runner::direct(n - 1); }\n\
                     int out_of_line(int n);\n\
                   };\n\
                   int Runner::out_of_line(int n) { return out_of_line(n - 1); }\n";
        let parsed = parse_source(&SupportLang::Cpp, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = crate::extract::extract(&parsed, 0).entities;
        let metrics = crate::complexity::function_complexities(&entities);
        for name in ["direct", "out_of_line"] {
            let metric = metrics.iter().find(|metric| metric.name == name).unwrap();
            assert_eq!(metric.cognitive, 1, "{metric:?}");
        }
    }
}

/// Language-specific flow-role overrides, extended by language tasks.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[];

/// Collect method/free-function declarations and same-file call references for
/// the shared class-scoped recursion resolver. `this->f` is self-like,
/// `Type::f` names the enclosing type, and other receivers stay unbound.
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
            let owner = declarator_owner(&node).or_else(|| enclosing_type_name(&node));
            Some(Callable {
                owner: owner.clone(),
                owner_type: owner,
                unqualified_callable: false,
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
        let (name, qualifier, qualifier_name) = match function.kind().as_ref() {
            "identifier" | "field_identifier" => {
                (function.text().into_owned(), Qualifier::None, None)
            }
            "field_expression" => {
                let Some(method) = function.field("field") else {
                    continue;
                };
                let Some(receiver) = function.field("argument") else {
                    continue;
                };
                let receiver_text = receiver.text();
                let owner = callables[caller].owner.as_deref();
                let (qualifier, qualifier_name) = if receiver_text == "this" {
                    (Qualifier::SelfLike, None)
                } else if owner == Some(receiver_text.as_ref()) {
                    (Qualifier::NamedType, Some(receiver_text.into_owned()))
                } else {
                    (Qualifier::Other, None)
                };
                (method.text().into_owned(), qualifier, qualifier_name)
            }
            "qualified_identifier" => {
                let Some(method) = function.field("name") else {
                    continue;
                };
                let Some(scope) = function.field("scope") else {
                    continue;
                };
                let scope = scope.text();
                let qualifier_name = scope
                    .rsplit_once("::")
                    .map_or(scope.as_ref(), |(_, name)| name);
                (
                    method.text().into_owned(),
                    Qualifier::NamedType,
                    Some(qualifier_name.to_owned()),
                )
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
            qualifier_name,
        });
    }
    (callables, references)
}

/// Owner named by an out-of-line definition's qualified declarator
/// (`Vec::~Vec()`), which has no enclosing class in the tree.
fn declarator_owner(node: &Node<'_>) -> Option<String> {
    let inner = function_declarator(node)?.field("declarator")?;
    let scope = inner.field("scope")?;
    let name = scope.text().trim().to_string();
    (!name.is_empty()).then_some(name)
}

fn enclosing_type_name(node: &Node<'_>) -> Option<String> {
    node.ancestors()
        .find(|ancestor| TYPE_SCOPES.contains(&ancestor.kind().as_ref()))
        .and_then(|ancestor| ancestor.field("name").map(|name| name.text().into_owned()))
}
