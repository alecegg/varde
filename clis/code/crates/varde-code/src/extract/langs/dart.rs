//! Dart entity extraction.
//!
//! Mapping notes (fixture-driven, superset-safe; node kinds from
//! tree-sitter-dart via ast-grep-language 0.45.1, verified against a grammar
//! dump):
//! - Callable declarations -> Function. Their declaration spans contain the
//!   executable body. The nested signature provides the stable callable name.
//!   Body-less abstract declarations retain their signature entity.
//! - `class_declaration` (plain `class` and `abstract class`) -> Class. Dart's
//!   `abstract class` has no distinct node kind and is Dart's interface analog
//!   (any class can be `implements`-ed), so it stays Class — there is no
//!   separate interface declaration to map.
//! - `mixin_declaration` (`mixin M { ... }`) -> Interface. A mixin is Dart's
//!   reusable-contract / composition mechanism (mixed in with `with`), the
//!   closest structural analog to an interface, so it maps to Interface rather
//!   than being conflated with a concrete Class.
//! - `superclass` clause: its `type` field (`extends Base`) -> Extends; each
//!   `type` under its nested `mixins` child (`with M1, M2`) -> Implements,
//!   owned by the enclosing class. `interfaces` clause (`implements I1, I2`):
//!   each `type` child -> Implements, owned by the class. Generic supertypes
//!   (`Comparable<Animal>`) are reduced to the bare name via the shared
//!   `strip_generic_args` (Dart uses `<...>` for generics).
//! - Fields/`var`/`final`/`const`: `initialized_identifier` (instance field,
//!   `int legs = 4`), `static_final_declaration` (`static const int MAX = 10`),
//!   and `initialized_variable_definition` (locals `var x = 1`, `const msg =
//!   ...`) -> Variable, named after field `name`. A bare `final String name;`
//!   field with no initializer is an `initialized_identifier` too (its `name`
//!   is the identifier).
//! - `formal_parameter` -> Parameter, via field `name`. A `this.x` constructor
//!   parameter is a `constructor_param` (no `name` field, it forwards to a
//!   field) and is intentionally not emitted as a Parameter.
//! - `call_expression` -> Call, named after the callee (`function` field: a
//!   bare `identifier`, or the `property` of a `member_expression` receiver
//!   call `x.foo(...)`).
//! - `member_expression` (`x.foo`) -> MemberAccess for the accessed member
//!   (`property` field). A receiver call `x.foo(...)` therefore emits both a
//!   MemberAccess ("foo") and a Call ("foo").
//! - `import_or_export` directive: a `library_import`/`import_specification`
//!   -> Import; a `library_export` -> Export. The URI is the unquoted
//!   `configurable_uri` string (`'b.dart'` -> `b.dart`), so resolve.rs's shared
//!   file-stem matching resolves a relative sibling import. Dart HAS a genuine
//!   `export` directive (unlike most languages in this model), so Export is NOT
//!   carved out.
//! - Literals: integer/floating-point/string/boolean/null.
//! - `throw_expression` -> Throw, named after the thrown expression (the callee
//!   of `throw E(...)`, else the thrown text); `rethrow_statement` -> Throw
//!   named "rethrow".
//! - `catch_clause` -> legacy Catch plus a body-spanning cognitive-only marker;
//!   type-only `on T { ... }` uses only the cognitive marker.
//! - ControlFlow: `if_statement`, `for_statement`, `while_statement`,
//!   `switch_statement`, `return_statement`, `break_statement`,
//!   `continue_statement`, `try_statement`.
//! - `annotation` (`@override`, `@immutable`) -> Decorator, via field `name`.
//!   Dart has a clean `annotation` node kind with a `name` field.
//! - Route/Response: carved out — Dart has no single idiomatic web-routing DSL
//!   (Flutter is UI, server frameworks like shelf/dart_frog each differ), so no
//!   honest narrow heuristic exists (same stance as C/Scala).

use crate::extract::entity::ExtractCtx;
use crate::extract::field_name;
use crate::extract::langs::{push_type_ref, strip_generic_args, unquote};
use crate::model::EntityKind;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope. Both carry the `name`
/// field the walker reads for `enclosing_function` linkage. `method_signature`
/// (abstract method, no body) wraps a `function_signature`, so matching the
/// signature covers abstract methods too.
pub const FUNCTION_SCOPES: &[&str] = &["function_signature", "constructor_signature"];

/// Node kinds that introduce a named class/mixin type scope (for
/// `Entity::owner_type` linkage on methods and Extends/Implements ownership).
pub const TYPE_SCOPES: &[&str] = &["class_declaration", "mixin_declaration"];

/// Entity kinds the fixtures must produce. Route/Response are carved out (no
/// single idiomatic Dart web DSL). Export is INCLUDED — Dart has a real
/// `export` directive. See module docs for the full rationale.
pub const REQUIRED_KINDS: [EntityKind; 13] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Interface,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Export,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::Catch,
    EntityKind::Throw,
    EntityKind::ControlFlow,
    EntityKind::Extends,
];

/// Emit entities for one node (called for every node in the tree).
// varde-ignore-next-line duplicate-code-clone -- visitor dispatch intentionally mirrors language peers
pub fn visit(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) {
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

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- imports / exports ----
        "import_specification" => {
            if let Some(uri) = directive_uri(node) {
                ctx.push(EntityKind::Import, uri, node);
            }
        }
        "library_export" => {
            if let Some(uri) = directive_uri(node) {
                ctx.push(EntityKind::Export, uri, node);
            }
        }
        // ---- structural ----
        "function_declaration"
        | "local_function_declaration"
        | "getter_declaration"
        | "setter_declaration"
        | "method_declaration" => {
            let name = callable_name(node).unwrap_or_default();
            ctx.push(EntityKind::Function, name, node);
        }
        "function_expression" => ctx.push_callable_boundary(node),
        _ => return false,
    }
    true
}

fn visit_part_2(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // Abstract and redirecting declarations have no executable body.
        "function_signature"
        | "constructor_signature"
        | "factory_constructor_signature"
        | "redirecting_factory_constructor_signature"
        | "getter_signature"
        | "setter_signature"
            if !signature_has_body_spanning_declaration(node) =>
        {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Function, name, node);
        }
        "class_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Class, name.clone(), node);
            visit_supertypes(node, &name, ctx);
        }
        "mixin_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Interface, name, node);
        }
        // ---- variables (fields, statics, locals) ----
        "initialized_identifier"
        | "static_final_declaration"
        | "initialized_variable_definition" => {
            if let Some(name) = field_name(node) {
                ctx.push(EntityKind::Variable, name, node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_3(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- parameters ----
        "formal_parameter" => {
            if let Some(name) = field_name(node) {
                ctx.push(EntityKind::Parameter, name, node);
            }
        }
        // ---- annotations ----
        "annotation" => {
            if let Some(name) = field_name(node) {
                ctx.push(EntityKind::Decorator, name, node);
            }
        }
        // ---- expression-level ----
        "call_expression" => {
            ctx.push(EntityKind::Call, call_name(node), node);
        }
        "member_expression" => {
            if let Some(prop) = node.field("property") {
                ctx.push(EntityKind::MemberAccess, prop.text().into_owned(), node);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_4(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "decimal_integer_literal"
        | "hex_integer_literal"
        | "decimal_floating_point_literal"
        | "string_literal"
        | "true"
        | "false"
        | "null_literal" => {
            if !ctx.in_type {
                ctx.push(EntityKind::Literal, node.text().into_owned(), node);
            }
        }
        // ---- error handling ----
        "throw_expression" => {
            ctx.push(EntityKind::Throw, thrown_name(node), node);
        }
        "rethrow_statement" => {
            ctx.push(EntityKind::Throw, "rethrow".to_string(), node);
        }
        "catch_clause" => {
            ctx.push(EntityKind::Catch, "legacy_catch_clause".to_string(), node);
            ctx.push(
                EntityKind::ControlFlow,
                "cognitive_decision".to_string(),
                node,
            );
            extend_last_span_to(ctx, following_handler_block_end(node));
        }
        "type"
            if node
                .parent()
                .is_some_and(|parent| parent.kind() == "try_statement") =>
        {
            if on_clause_has_catch_clause(node) {
                return true;
            }
            ctx.push(
                EntityKind::ControlFlow,
                "cognitive_decision".to_string(),
                node,
            );
            extend_last_span_to(ctx, on_clause_block_end(node));
        }
        _ => return false,
    }
    true
}

fn visit_part_5(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- control flow ----
        "if_statement" => {
            let name = if is_else_if(node) {
                "elseif_statement"
            } else {
                "if_statement"
            };
            ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            if name == "elseif_statement"
                && let Some(consequence) = node.field("consequence")
            {
                shrink_last_span_to_point(ctx, crate::extract::span_of(&consequence));
            }
            if let Some(alternative) = node.field("alternative")
                && alternative.kind() != "if_statement"
            {
                ctx.push(
                    EntityKind::ControlFlow,
                    "else_branch".to_string(),
                    &alternative,
                );
                shrink_last_span_to_point(ctx, crate::extract::span_of(&alternative));
            }
        }
        "for_statement"
        | "while_statement"
        | "switch_statement"
        | "conditional_expression"
        | "return_statement"
        | "try_statement" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        "switch_expression" => {
            ctx.push(
                EntityKind::ControlFlow,
                "cognitive_decision".to_string(),
                node,
            );
        }
        "do_statement" => {
            ctx.push(
                EntityKind::ControlFlow,
                "do_while_statement".to_string(),
                node,
            );
        }
        "switch_statement_case" | "switch_statement_default" => {
            ctx.push(EntityKind::ControlFlow, "case_statement".to_string(), node);
        }
        "break_statement" | "continue_statement" if has_jump_label(node) => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
            ctx.push(EntityKind::ControlFlow, "labeled_jump".to_string(), node);
        }
        "break_statement" | "continue_statement" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        _ => return false,
    }
    true
}

fn visit_part_6(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "unary_expression" if node.text().trim_start().starts_with('!') => {
            ctx.push(EntityKind::ControlFlow, "negation_break".to_string(), node);
        }
        "logical_and_expression" => {
            ctx.push(EntityKind::ControlFlow, "logical_and".to_string(), node);
        }
        "logical_or_expression" => {
            ctx.push(EntityKind::ControlFlow, "logical_or".to_string(), node);
        }
        _ => return false,
    }
    true
}

/// True for the nested `if_statement` stored as an alternative.
fn is_else_if(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(parent) = node
        .parent()
        .filter(|parent| parent.kind() == "if_statement")
    else {
        return false;
    };
    parent
        .field("alternative")
        .is_some_and(|alternative| alternative.range() == node.range())
}

fn has_jump_label(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.children().any(|child| child.kind() == "identifier")
}

/// An `on T catch (e)` clause has one `catch_clause`; the type node alone only
/// needs to represent the `on T { ... }` form.
fn on_clause_has_catch_clause(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(parent) = node.parent() else {
        return false;
    };
    let mut after_type = false;
    for sibling in parent.children() {
        if sibling.range() == node.range() {
            after_type = true;
            continue;
        }
        if !after_type {
            continue;
        }
        match sibling.kind().as_ref() {
            "catch_clause" => return true,
            "block" | "type" | "finally_clause" => return false,
            _ => {}
        }
    }
    false
}

fn on_clause_block_end(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<crate::model::Span> {
    let parent = node.parent()?;
    let mut after_type = false;
    for sibling in parent.children() {
        if sibling.range() == node.range() {
            after_type = true;
            continue;
        }
        if !after_type {
            continue;
        }
        match sibling.kind().as_ref() {
            "block" => return Some(crate::extract::span_of(&sibling)),
            "catch_clause" | "type" | "finally_clause" => return None,
            _ => {}
        }
    }
    None
}

fn following_handler_block_end(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<crate::model::Span> {
    let parent = node.parent()?;
    let mut after_clause = false;
    for sibling in parent.children() {
        if sibling.range() == node.range() {
            after_clause = true;
            continue;
        }
        if !after_clause {
            continue;
        }
        match sibling.kind().as_ref() {
            "block" => return Some(crate::extract::span_of(&sibling)),
            "catch_clause" | "type" | "finally_clause" => return None,
            _ => {}
        }
    }
    None
}

fn extend_last_span_to(ctx: &mut ExtractCtx, end: Option<crate::model::Span>) {
    if let Some(end) = end
        && let Some(entity) = ctx.out.last_mut()
    {
        entity.span.end_byte = end.end_byte;
        entity.span.end_line = end.end_line;
        entity.span.end_col = end.end_col;
    }
}

/// Hybrid `else` markers must not make their branch bodies appear one level
/// deeper. Store a zero-width marker at the branch boundary while retaining
/// the full declaration span for callable attribution.
fn shrink_last_span_to_point(ctx: &mut ExtractCtx, point: crate::model::Span) {
    if let Some(entity) = ctx.out.last_mut() {
        entity.span.start_byte = point.start_byte;
        entity.span.end_byte = point.start_byte;
        entity.span.start_line = point.start_line;
        entity.span.start_col = point.start_col;
        entity.span.end_line = point.start_line;
        entity.span.end_col = point.start_col;
    }
}

/// Emit Extends (the `superclass`'s extended `type`) + Implements (each mixin
/// under `with`, and each `implements` interface), owned by `owner`.
fn visit_supertypes(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    owner: &str,
    ctx: &mut ExtractCtx,
) {
    if let Some(superclass) = node.children().find(|c| c.kind() == "superclass") {
        if let Some(base) = superclass.field("type") {
            push_type_ref(ctx, EntityKind::Extends, type_name(&base), owner, &base);
        }
        // `with M1, M2` mixins live under a nested `mixins` child.
        if let Some(mixins) = superclass.children().find(|c| c.kind() == "mixins") {
            for m in mixins.children().filter(|c| c.kind() == "type") {
                push_type_ref(ctx, EntityKind::Implements, type_name(&m), owner, &m);
            }
        }
    }
    // `implements I1, I2` is a sibling `interfaces` clause.
    if let Some(interfaces) = node.children().find(|c| c.kind() == "interfaces") {
        for i in interfaces.children().filter(|c| c.kind() == "type") {
            push_type_ref(ctx, EntityKind::Implements, type_name(&i), owner, &i);
        }
    }
}

/// Bare name of a supertype `type` node, with any `<...>` generic arguments
/// stripped (`Comparable<Animal>` -> `"Comparable"`).
fn type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    strip_generic_args(node.text().trim())
}

/// Callee name of a `call_expression`: the `function` field is a bare
/// `identifier` (`foo(...)`) or a `member_expression` receiver call
/// (`x.foo(...)`, whose `property` is the method name).
fn call_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let Some(func) = node.field("function") else {
        return String::new();
    };
    if func.kind() == "member_expression"
        && let Some(prop) = func.field("property")
    {
        return prop.text().into_owned();
    }
    func.text().into_owned()
}

/// Name of a thrown expression: `throw E(...)` -> "E" (the constructed type /
/// callee), otherwise the thrown expression's text.
fn thrown_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let Some(value) = node.field("value") else {
        return String::new();
    };
    if value.kind() == "call_expression" {
        return call_name(&value);
    }
    value.text().into_owned()
}

/// Callable declarations own their signature through the `signature` field.
/// The nested signature carries the stable identifier, while the declaration
/// span reaches the block or expression body.
fn callable_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let signature = node.field("signature").or_else(|| {
        node.children()
            .find(|child| child.kind() == "function_signature")
    })?;
    field_name(&signature).or_else(|| signature.children().find_map(|child| field_name(&child)))
}

/// True when a signature belongs to a declaration with an executable body.
fn signature_has_body_spanning_declaration(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> bool {
    let Some(parent) = node.parent() else {
        return false;
    };
    let declaration = if parent.kind() == "method_signature" {
        parent.parent()
    } else {
        Some(parent)
    };
    declaration.is_some_and(|node| {
        matches!(
            node.kind().as_ref(),
            "function_declaration"
                | "local_function_declaration"
                | "getter_declaration"
                | "setter_declaration"
                | "method_declaration"
        )
    })
}

/// Unquoted URI of an `import_specification` / `library_export` directive: the
/// `configurable_uri`'s inner string literal, quotes stripped (`'b.dart'` ->
/// `b.dart`). Dart string quotes are single or double, so backticks are not
/// allowed.
fn directive_uri(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let uri = node.children().find(|c| c.kind() == "configurable_uri")?;
    let s = uri.children().find(|c| c.kind() == "uri")?;
    Some(unquote(s.text().trim(), false))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::model::Entity;
    use crate::parse::parse_source;

    fn entities(src: &str) -> Vec<Entity> {
        let parsed = parse_source(&SupportLang::Dart, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        extract::extract(&parsed, 0).entities
    }

    fn find<'a>(es: &'a [Entity], kind: EntityKind, name: &str) -> Option<&'a Entity> {
        es.iter().find(|e| e.kind == kind && e.name == name)
    }

    #[test]
    fn factory_constructors_and_getters_are_captured() {
        // Audit S3: factory constructors and getters/setters were dropped.
        let es = entities(
            "class Client {\n  factory Client() => Client._();\n  Client._();\n  Client? get zoneClient => null;\n  set mode(int v) {}\n}\n",
        );
        assert!(
            find(&es, EntityKind::Function, "zoneClient").is_some(),
            "getter: {es:?}"
        );
        assert!(
            find(&es, EntityKind::Function, "mode").is_some(),
            "setter: {es:?}"
        );
        // At least two Function entities named "Client" (factory + named ctor).
        let ctors = es
            .iter()
            .filter(|e| e.kind == EntityKind::Function && e.name == "Client")
            .count();
        assert!(ctors >= 2, "factory + named ctor both captured: {es:?}");
    }

    #[test]
    fn callable_spans_contain_their_body_calls() {
        let es = entities(
            "void topLevel() { remoteTopLevel(); }\nclass Client {\n  Client() { remoteConstructor(); }\n  factory Client.create() { remoteFactory(); return Client(); }\n  int get value { return remoteGetter(); }\n  set value(int next) { remoteSetter(next); }\n}\n",
        );
        for (call, function) in [
            ("remoteTopLevel", "topLevel"),
            ("remoteConstructor", "Client"),
            ("remoteFactory", "Client"),
            ("remoteGetter", "value"),
            ("remoteSetter", "value"),
        ] {
            let call = find(&es, EntityKind::Call, call).expect("body call");
            assert!(
                es.iter().any(|candidate| {
                    candidate.kind == EntityKind::Function
                        && candidate.name == function
                        && candidate.span.start_byte <= call.span.start_byte
                        && call.span.end_byte <= candidate.span.end_byte
                }),
                "a {function} Function must contain {call:?}: {es:?}",
            );
        }
    }

    #[test]
    fn anonymous_function_expressions_are_callable_boundaries() {
        let es = entities("void outer() { queue(() { deferred(); }); }");
        assert!(
            es.iter()
                .any(|entity| entity.kind == EntityKind::CallableBoundary),
            "anonymous function boundary: {es:?}"
        );
    }

    #[test]
    fn class_mixin_and_functions_map_to_expected_kinds() {
        let es = entities(
            "abstract class Animal {\n  void speak() {}\n}\nmixin Walker {\n  void walk() {}\n}\nint add(int a, int b) => a + b;\n",
        );
        assert!(find(&es, EntityKind::Class, "Animal").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Function, "speak").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Interface, "Walker").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Function, "walk").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Function, "add").is_some(), "{es:?}");
    }

    #[test]
    fn extends_with_and_implements_split_correctly() {
        let es =
            entities("class Service extends Base with Mixin implements Comparable<Service> {}\n");
        let ext = find(&es, EntityKind::Extends, "Base").expect("Extends Base");
        assert_eq!(ext.enclosing_function.as_deref(), Some("Service"));
        let mix = find(&es, EntityKind::Implements, "Mixin").expect("Implements Mixin");
        assert_eq!(mix.enclosing_function.as_deref(), Some("Service"));
        let cmp = find(&es, EntityKind::Implements, "Comparable").expect("Implements Comparable");
        assert_eq!(cmp.enclosing_function.as_deref(), Some("Service"));
    }

    #[test]
    fn fields_locals_and_params_map_to_variable_and_parameter() {
        let es = entities(
            "class C {\n  final String name;\n  int legs = 4;\n  static const int MAX = 10;\n  void f(int a, String b) {\n    var x = 1;\n    const msg = \"hi\";\n  }\n}\n",
        );
        assert!(find(&es, EntityKind::Variable, "name").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "legs").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "MAX").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "x").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "msg").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Parameter, "a").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Parameter, "b").is_some(), "{es:?}");
    }

    #[test]
    fn receiver_call_emits_member_access_and_call() {
        let es = entities("void f() {\n  repo.save();\n}\n");
        assert!(
            find(&es, EntityKind::MemberAccess, "save").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Call, "save").is_some(), "{es:?}");
    }

    #[test]
    fn throw_rethrow_and_catch_are_extracted() {
        let es = entities(
            "void f() {\n  try {\n    throw Exception(\"boom\");\n  } on FormatException catch (e) {\n    rethrow;\n  } catch (err) {\n    print(err);\n  }\n}\n",
        );
        assert!(
            find(&es, EntityKind::Throw, "Exception").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Throw, "rethrow").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Catch, "legacy_catch_clause").is_some(),
            "{es:?}"
        );
        assert_eq!(
            es.iter()
                .filter(|entity| entity.kind == EntityKind::Catch)
                .count(),
            2,
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "try_statement").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn control_flow_is_extracted() {
        let es = entities(
            "void f(int n) {\n  if (n > 0) {}\n  for (var i = 0; i < n; i++) { continue; }\n  while (n > 0) { break; }\n  switch (n) { case 1: return; }\n}\n",
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "if_statement").is_some(),
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "for_statement").is_some(),
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "while_statement").is_some(),
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "switch_statement").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn import_and_export_directives_yield_unquoted_uris() {
        let es = entities("import 'b.dart';\nexport 'c.dart';\nimport 'package:x/y.dart' as y;\n");
        assert!(find(&es, EntityKind::Import, "b.dart").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Export, "c.dart").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Import, "package:x/y.dart").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn literals_and_annotations_are_extracted() {
        let es = entities(
            "class C {\n  @override\n  void f() {\n    var a = 42;\n    var b = \"hi\";\n    var c = true;\n  }\n}\n",
        );
        assert!(find(&es, EntityKind::Literal, "42").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Literal, "true").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Decorator, "override").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn complexity_events_cover_dart_decisions_and_local_functions() {
        let es = entities(
            r#"
                void outer(bool a, bool b, int value) {
                  if (a && b || a) {} else if (b) {}
                  switch (value) { case 1: break; default: break; }
                  do {} while (a);
                  var choice = a ? 1 : 0;
                  var anonymous = (int n) { if (n > 0) return; };
                  void local() { if (a) {} }
                  try {} catch (error) {}
                }
            "#,
        );
        let flow_names: Vec<&str> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert!(flow_names.contains(&"logical_and"), "entities: {es:?}");
        assert!(flow_names.contains(&"logical_or"), "entities: {es:?}");
        assert!(flow_names.contains(&"elseif_statement"), "entities: {es:?}");
        assert_eq!(
            flow_names
                .iter()
                .filter(|name| **name == "case_statement")
                .count(),
            2,
            "entities: {es:?}"
        );
        assert!(
            flow_names.contains(&"conditional_expression"),
            "entities: {es:?}"
        );
        assert!(
            find(&es, EntityKind::Catch, "legacy_catch_clause").is_some(),
            "{es:?}"
        );
        assert!(
            es.iter()
                .any(|entity| entity.kind == EntityKind::CallableBoundary),
            "entities: {es:?}"
        );

        let metrics = crate::complexity::function_complexities(&es);
        let outer = metrics
            .iter()
            .find(|metric| metric.name == "outer")
            .expect("outer metric");
        let local = metrics
            .iter()
            .find(|metric| metric.name == "local")
            .expect("local metric");
        assert_eq!(outer.cyclomatic, 10, "metric: {outer:?}; entities: {es:?}");
        assert_eq!(local.cyclomatic, 2, "metric: {local:?}");
    }

    #[test]
    fn recursion_matcher_finds_class_method_self_calls() {
        let source = "class C { int f(int n) { if (n > 0) return f(n - 1); return 0; } }";
        let parsed = crate::parse::parse_source(&SupportLang::Dart, source);
        let root = parsed.root.root();
        let (callables, references) = match_callees(&root);
        assert_eq!(callables.len(), 1);
        assert_eq!(callables[0].name, "f");
        assert_eq!(callables[0].required_args, 1);
        assert!(callables[0].span.end_byte > callables[0].name_span.end_byte);
        assert_eq!(references.len(), 1);
        let markers = crate::extract::recursion::resolve(&callables, &references, true);
        assert_eq!(markers.len(), 1);
        assert_eq!(markers[0].name, "recursive_call");
    }

    #[test]
    fn recursion_inside_closure_belongs_to_enclosing_method() {
        let source = "class C { int f(int n) { final recurse = () { return f(n - 1); }; return n > 0 ? recurse() : 0; } }";
        let parsed = crate::parse::parse_source(&SupportLang::Dart, source);
        let root = parsed.root.root();
        let (callables, references) = match_callees(&root);
        let markers = crate::extract::recursion::resolve(&callables, &references, true);
        assert_eq!(markers.len(), 1, "{callables:#?}\n{references:#?}");
        assert_eq!(markers[0].name, "recursive_call");
    }

    #[test]
    fn collection_control_flow_keeps_legacy_metrics_without_cognitive_points() {
        let es = entities(
            "int f(List<int> values, bool enabled) => [if (enabled) for (final value in values) value].length;",
        );
        let flows: Vec<_> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();
        assert!(flows.is_empty(), "entities: {es:?}");
        let metric = crate::complexity::function_complexities(&es)
            .into_iter()
            .find(|metric| metric.name == "f")
            .expect("function metric");
        assert_eq!(metric.cognitive, 0, "metric: {metric:?}");
        assert_eq!(metric.cyclomatic, 1, "metric: {metric:?}");
        assert_eq!(metric.max_nesting, 0, "metric: {metric:?}");
    }

    #[test]
    fn on_only_and_on_catch_handlers_each_span_their_body() {
        let es = entities(
            "int f(int n) { try { if (n > 0) throw StateError('x'); } on StateError { if (n == 1) return 1; } on FormatException catch (error) { if (n == 2) return 2; } return 0; }",
        );
        let catches: Vec<_> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::Catch)
            .collect();
        assert_eq!(catches.len(), 1, "entities: {es:?}");
        assert!(
            catches
                .iter()
                .all(|entity| entity.name == "legacy_catch_clause")
        );
        let cognitive_handlers = es
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "cognitive_decision"
            })
            .count();
        assert_eq!(cognitive_handlers, 2, "entities: {es:?}");
        let metrics = crate::complexity::function_complexities(&es);
        let metric = metrics.iter().find(|metric| metric.name == "f").unwrap();
        assert_eq!(metric.cognitive, 7, "metric: {metric:?}");
        assert_eq!(metric.cyclomatic, 5, "metric: {metric:?}");
        assert_eq!(metric.max_nesting, 0, "metric: {metric:?}");
    }

    #[test]
    fn cognitive_only_dart_constructs_preserve_legacy_file_complexity() {
        let source = "int f(int x, List<int> values) { final y = switch (x) { 1 => 1, _ => 0 }; try { throw StateError('x'); } on StateError { } on FormatException catch (e) { } return [if (x > 0) for (final value in values) value].length + y; }";
        let es = entities(source);
        let legacy_count = es
            .iter()
            .filter(|entity| crate::complexity::counts_toward_file_complexity(entity))
            .count();
        let legacy_names: Vec<_> = es
            .iter()
            .filter(|entity| crate::complexity::counts_toward_file_complexity(entity))
            .map(|entity| entity.name.as_str())
            .collect();
        assert_eq!(
            legacy_count, 2,
            "legacy names: {legacy_names:?}; entities: {es:?}"
        );
        assert_eq!(
            crate::complexity::cyclomatic_for_entities(&es),
            3,
            "legacy names: {legacy_names:?}; entities: {es:?}"
        );
        assert!(es.iter().any(|entity| {
            entity.kind == EntityKind::ControlFlow && entity.name == "cognitive_decision"
        }));
        assert!(!es.iter().any(|entity| {
            entity.name == "comprehension_if" || entity.name == "comprehension_for"
        }));

        let fixture = entities(include_str!(
            "../../../tests/fixtures/complexity/dart/conformance.dart"
        ));
        let fixture_legacy_count = fixture
            .iter()
            .filter(|entity| crate::complexity::counts_toward_file_complexity(entity))
            .count();
        assert_eq!(fixture_legacy_count, 99);
        assert_eq!(crate::complexity::cyclomatic_for_entities(&fixture), 100);
    }
}

/// Language-specific flow-role overrides, extended by language tasks.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[];

/// Shared recursion matcher hook; populated by this language task.
pub fn match_callees(
    root: &super::ParsedNode<'_>,
) -> (
    Vec<crate::extract::recursion::Callable>,
    Vec<crate::extract::recursion::CalleeReference>,
) {
    use crate::extract::recursion::{Callable, CalleeReference, Qualifier};

    const DECLARATIONS: &[&str] = &[
        "function_declaration",
        "local_function_declaration",
        "getter_declaration",
        "setter_declaration",
        "method_declaration",
    ];

    let declarations: Vec<_> = root
        .dfs()
        .filter(|node| DECLARATIONS.contains(&node.kind().as_ref()))
        .filter(|node| enclosing_type_name(node).is_some())
        .collect();
    let callables: Vec<_> = declarations
        .iter()
        .filter_map(|node| {
            let name = callable_name(node)?;
            let owner = enclosing_type_name(node)?;
            let signature = node.field("signature").or_else(|| {
                node.children()
                    .find(|child| child.kind() == "function_signature")
            });
            let name_node = signature.as_ref().and_then(|signature| {
                signature
                    .dfs()
                    .find(|candidate| candidate.kind() == "identifier" && candidate.text() == name)
            });
            let params = signature.as_ref().and_then(|signature| {
                signature
                    .dfs()
                    .find(|candidate| candidate.kind() == "formal_parameter_list")
            });
            let (required_args, total_args) =
                params.as_ref().map(parameter_arity).unwrap_or_default();
            Some(Callable {
                owner: Some(owner.clone()),
                owner_type: Some(owner),
                unqualified_callable: false,
                name,
                required_args,
                total_args,
                file_id: 0,
                span: crate::extract::span_of(node),
                name_span: name_node
                    .as_ref()
                    .map(crate::extract::span_of)
                    .unwrap_or_else(|| crate::extract::span_of(node)),
            })
        })
        .collect();

    let mut references = Vec::new();
    for call in root.dfs().filter(|node| node.kind() == "call_expression") {
        let Some(caller_node) = call.ancestors().find(|ancestor| {
            DECLARATIONS.contains(&ancestor.kind().as_ref())
                && enclosing_type_name(ancestor).is_some()
        }) else {
            continue;
        };
        let caller_span = crate::extract::span_of(&caller_node);
        let Some(caller) = callables.iter().position(|item| item.span == caller_span) else {
            continue;
        };
        let Some(function) = call.field("function") else {
            continue;
        };
        let (name, qualifier, qualifier_name) = if function.kind() == "member_expression" {
            let Some(method) = function.field("property") else {
                continue;
            };
            let Some(receiver) = function.field("object") else {
                continue;
            };
            let receiver_name = receiver.text();
            let owner = callables[caller].owner.as_deref();
            let (qualifier, qualifier_name) = if receiver_name == "this" {
                (Qualifier::SelfLike, None)
            } else if owner == Some(receiver_name.as_ref()) {
                (Qualifier::NamedType, Some(receiver_name.into_owned()))
            } else {
                (Qualifier::Other, None)
            };
            (method.text().into_owned(), qualifier, qualifier_name)
        } else if function.kind() == "identifier" {
            (function.text().into_owned(), Qualifier::None, None)
        } else {
            continue;
        };
        let argument_count = call
            .field("arguments")
            .map(|arguments| {
                arguments
                    .children()
                    .filter(|child| child.is_named() && child.kind() != "comment")
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

fn enclosing_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.ancestors()
        .find(|ancestor| TYPE_SCOPES.contains(&ancestor.kind().as_ref()))
        .and_then(|scope| field_name(&scope))
}

fn parameter_arity(params: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> (u16, u16) {
    let formal_parameters: Vec<_> = params
        .dfs()
        .filter(|child| child.kind() == "formal_parameter")
        .collect();
    let required = formal_parameters
        .iter()
        .filter(|parameter| {
            parameter.parent().is_some_and(|parent| {
                parent.kind() == "formal_parameter_list"
                    || parameter.text().trim_start().starts_with("required ")
            })
        })
        .count();
    (
        u16::try_from(required).unwrap_or(u16::MAX),
        u16::try_from(formal_parameters.len()).unwrap_or(u16::MAX),
    )
}
