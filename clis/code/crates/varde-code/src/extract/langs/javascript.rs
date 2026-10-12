//! JavaScript entity extraction.
//!
//! JavaScript shares almost every node kind of the 14-kind checklist with
//! TypeScript (`function_declaration`, `class_declaration`, `call_expression`,
//! `member_expression`, ...); see `super::ts` for the reference mapping. The
//! JS-specific differences:
//! - Interface: carved out — `interface_declaration` is a TypeScript-only
//!   node kind; JavaScript has no interface syntax.
//! - Parameter: JS parameters are bare `identifier` / `assignment_pattern`
//!   (defaults) / `rest_pattern` nodes inside `formal_parameters` — the
//!   `required_parameter`/`optional_parameter` kinds are TypeScript-only.
//! - Export/Route/Response: same node kinds and shapes as ts.rs, reused
//!   verbatim (export_statement, Express-style `app.get` / `res.json`).
//! - Literals in type contexts cannot occur (JS has no type syntax), but the
//!   shared `ctx.in_type` guard is kept for safety.

use crate::extract::entity::{EntityMeta, ExtractCtx, entity};
use crate::extract::field_name;
use crate::extract::langs::{
    boolean_operator_name, chain_status, decorator_name, first_arg_text, visit_do_statement,
};
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const TYPE_SCOPES: &[&str] = &["class_declaration"];

pub const FUNCTION_SCOPES: &[&str] = &[
    "function_declaration",
    "function_expression",
    "arrow_function",
    "generator_function",
    "method_definition",
    "generator_function_declaration",
];

/// Entity kinds the fixtures must produce. Interface is carved out (JS has no
/// interface syntax); the other 13 kinds map to native constructs.
pub const REQUIRED_KINDS: [EntityKind; 13] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Export,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::Catch,
    EntityKind::Throw,
    EntityKind::ControlFlow,
    EntityKind::Route,
    EntityKind::Response,
];

/// Emit entities for one node (called for every node in the tree).
// varde-ignore-next-line duplicate-code-clone -- visitor dispatch intentionally mirrors language peers
pub fn visit(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) {
    if FUNCTION_SCOPES.contains(&kind) && is_compensating_usage(node) {
        ctx.push(
            EntityKind::ControlFlow,
            "compensating_usage".to_string(),
            node,
        );
    }
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
    if visit_part_6(node, kind, ctx) {
        return;
    }
    if visit_part_7(node, kind, ctx) {
        return;
    }
    let _ = visit_do_statement(node, kind, ctx);
}

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- structural kinds ----
        "function_declaration" | "generator_function_declaration" => {
            push_named(node, EntityKind::Function, ctx)
        }
        "function_expression" | "generator_function" | "arrow_function" => {
            ctx.push_callable_boundary(node)
        }
        // Class methods — previously invisible to extraction; `owner_type`
        // (set from `ctx.type_scope`) links each back to its class. See ts.rs.
        "method_definition" => push_named(node, EntityKind::Function, ctx),
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
        "class_declaration" => {
            push_named(node, EntityKind::Class, ctx);
            // `class X extends Y {}` -> a single Extends entity naming the
            // superclass, linked back to X via enclosing_function. The
            // superclass lives in an unnamed `class_heritage` child wrapping
            // a single expression (identifier or member_expression).
            let class_name = field_name(node).unwrap_or_default();
            if let Some(heritage) = node.children().find(|c| c.kind() == "class_heritage")
                && let Some(base) = heritage.children().find(|c| c.is_named())
            {
                ctx.out.push(Entity {
                    kind: EntityKind::Extends,
                    name: base.text().into_owned(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(&base),
                    enclosing_function: Some(class_name.clone()),
                    method: None,
                    path: None,
                    status: None,
                    body_shape: None,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    owner_type: None,
                });
            }
            // `@Component class Foo {}` — decorator(s) attach as direct
            // children of class_declaration, preceding the `class` keyword.
            // `name` is the decorator expression text (callee for a call-style
            // decorator factory, otherwise the bare expression).
            for decorator in node.children().filter(|c| c.kind() == "decorator") {
                if let Some(dec_name) = decorator_name(&decorator) {
                    ctx.out.push(Entity {
                        kind: EntityKind::Decorator,
                        name: dec_name,
                        file_id: ctx.file_id,
                        span: crate::extract::span_of(&decorator),
                        enclosing_function: Some(class_name.clone()),
                        method: None,
                        path: None,
                        status: None,
                        body_shape: None,
                        body_minhash: None,
                        is_async: None,
                        is_test: false,
                        owner_type: None,
                    });
                }
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
        // ---- imports ----
        // JS uses the same tree-sitter node shapes as TS.
        "import_statement" => {
            let spec = node
                .field("source")
                .map(|n| super::unquote(n.text().as_ref(), true))
                .unwrap_or_default();
            let imp = entity(
                EntityKind::Import,
                spec,
                ctx.file_id,
                node,
                EntityMeta::default(),
            );
            ctx.out.push(imp);
        }
        // ---- statement-level kinds ----
        // const/let -> lexical_declaration, var -> variable_declaration; one
        // Entity per declarator (handles `const a = 1, b = 2;`).
        "lexical_declaration" | "variable_declaration" => {
            for declarator in node.children() {
                if declarator.kind() == "variable_declarator" {
                    let name = field_name(&declarator).unwrap_or_default();
                    ctx.push(EntityKind::Variable, name, &declarator);
                }
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
    visit_part_4_a(node, kind, ctx) || visit_part_4_b(node, kind, ctx)
}

fn visit_part_4_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // JS parameters are bare identifiers/assignment_patterns/rest_patterns
        // inside formal_parameters (no required_/optional_parameter kinds).
        "formal_parameters" => {
            for child in node.children() {
                let name = match child.kind().as_ref() {
                    "identifier" => Some(child.text().into_owned()),
                    "assignment_pattern" => child.field("left").map(|n| n.text().into_owned()),
                    "rest_pattern" => child
                        .children()
                        .find(|c| c.kind() == "identifier")
                        .map(|c| c.text().into_owned()),
                    _ => None,
                };
                if let Some(name) = name {
                    ctx.push(EntityKind::Parameter, name, &child);
                }
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_4_b(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // export statements: `export { a, b }` yields one Export per
        // specifier; `export function/const/class ...` yields one Export
        // named after the declared symbol.
        "export_statement" => visit_export_statement(node, ctx),
        _ => return false,
    }
    true
}

fn export_clause_names(clause: ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    clause
        .children()
        .filter(|spec| spec.kind() == "export_specifier")
        .filter_map(|spec| field_name(&spec))
        .collect()
}

fn visit_export_statement(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    let mut names: Vec<String> = node
        .children()
        .filter(|child| child.kind() == "export_clause")
        .flat_map(export_clause_names)
        .collect();
    if names.is_empty()
        && let Some(name) = declaration_name(node)
    {
        names.push(name);
    }
    for name in names {
        ctx.push(EntityKind::Export, name, node);
    }
}

fn visit_part_5(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- expression-level kinds ----
        "call_expression" => {
            let name = node
                .field("function")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Call, name.clone(), node);
            if let Some(route) = route_of(node) {
                ctx.out.push(Entity {
                    kind: EntityKind::Route,
                    name: name.clone(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
                    method: Some(route.0),
                    path: Some(route.1),
                    status: None,
                    body_shape: None,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    // Handler function name (final identifier argument) for
                    // route→handler resolution in `detect_routes`.
                    owner_type: crate::extract::langs::last_arg_identifier(node),
                });
            }
            if let Some(resp) = response_of(node) {
                ctx.out.push(Entity {
                    kind: EntityKind::Response,
                    name: name.clone(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
                    method: None,
                    path: None,
                    status: resp.0,
                    body_shape: resp.1,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    owner_type: None,
                });
            }
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
        // Member accesses: property text as name (`a.b` -> "b").
        "member_expression" => {
            let name = node
                .field("property")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::MemberAccess, name, node);
        }
        // Literals: number/string/boolean/null/undefined/template/regex.
        "number" | "string" | "true" | "false" | "null" | "undefined" | "template_string"
        | "regex" => {
            if !ctx.in_type {
                ctx.push(EntityKind::Literal, node.text().into_owned(), node);
            }
        }
        // ---- control-flow/error kinds ----
        // catch (err) -> Catch, named after the exception variable.
        "catch_clause" => {
            let name = node
                .field("parameter")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Catch, name, node);
        }
        // throw <expr> -> Throw, named after the thrown expression. The JS
        // grammar gives throw_statement no field for the expression, so take
        // the text after the 'throw' keyword.
        "throw_statement" => {
            let name = node
                .children()
                .nth(1)
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Throw, name, node);
        }
        _ => return false,
    }
    true
}

fn visit_part_7(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // Control flow: name = tree-sitter node kind (superset-safe minimal
        // shape: kind + span + enclosing linkage).
        "if_statement" => {
            let name = if is_else_if(node) {
                "elseif_statement"
            } else {
                "if_statement"
            };
            ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            if let Some(consequence) = node.field("consequence")
                && let Some(event) = ctx.out.last_mut()
            {
                let span = crate::extract::span_of(&consequence);
                event.span.end_byte = span.end_byte;
                event.span.end_line = span.end_line;
                event.span.end_col = span.end_col;
            }
            if !is_else_if(node)
                && let Some(alternative) =
                    node.children().find(|child| child.kind() == "else_clause")
            {
                ctx.push(
                    EntityKind::ControlFlow,
                    "legacy_nesting".to_string(),
                    &alternative,
                );
            }
        }
        "else_clause" => {
            if let Some(alternative) = node.children().find(|child| child.is_named())
                && alternative.kind() != "if_statement"
            {
                ctx.push(
                    EntityKind::ControlFlow,
                    "else_branch".to_string(),
                    &alternative,
                );
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
        "switch_case" | "switch_default" => {
            ctx.push(EntityKind::ControlFlow, "case_statement".to_string(), node);
        }
        "break_statement" | "continue_statement" => {
            if node.field("label").is_some() {
                ctx.push(EntityKind::ControlFlow, "labeled_jump".to_string(), node);
            }
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        "for_statement" | "for_in_statement" | "for_of_statement" | "while_statement"
        | "switch_statement" | "try_statement" | "ternary_expression" | "return_statement" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        _ => return false,
    }
    true
}

fn is_else_if(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.parent().is_some_and(|parent| {
        parent.kind() == "if_statement"
            || (parent.kind() == "else_clause"
                && parent
                    .parent()
                    .is_some_and(|outer| outer.kind() == "if_statement"))
    })
}

fn is_negated_logical_sequence(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.text().trim_start().starts_with('!')
        && node.dfs().skip(1).any(|child| {
            child.kind() == "binary_expression" && boolean_operator_name(&child).is_some()
        })
}

fn is_compensating_usage(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(body) = node
        .field("body")
        .filter(|body| body.kind() == "statement_block")
    else {
        return false;
    };
    let statements: Vec<_> = body
        .children()
        .filter(|child| child.is_named() && child.kind() != "comment")
        .collect();
    !statements.is_empty()
        && statements
            .iter()
            .all(|statement| is_declarative_statement(statement))
}

fn is_declarative_statement(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    match node.kind().as_ref() {
        "function_declaration"
        | "generator_function_declaration"
        | "lexical_declaration"
        | "variable_declaration" => true,
        "expression_statement" => node.children().find(|child| child.is_named()).is_some_and(
            |expression| match expression.kind().as_ref() {
                "string" | "string_literal" => true,
                "assignment_expression" => expression.field("right").is_some_and(|right| {
                    matches!(
                        right.kind().as_ref(),
                        "function_expression" | "generator_function" | "arrow_function"
                    )
                }),
                _ => false,
            },
        ),
        _ => false,
    }
}

fn push_named(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: EntityKind,
    ctx: &mut ExtractCtx,
) {
    ctx.out.push(entity(
        kind,
        field_name(node).unwrap_or_default(),
        ctx.file_id,
        node,
        EntityMeta {
            owner_type: (kind == EntityKind::Function)
                .then_some(ctx.type_scope)
                .flatten()
                .map(|s| s.to_owned()),
            ..Default::default()
        },
    ));
}

/// Name of the declaration wrapped by an export statement, if it has one
/// (function/class declarations and var/const/let declarators).
fn declaration_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    for child in node.children() {
        match child.kind().as_ref() {
            "function_declaration" | "class_declaration" => return field_name(&child),
            "lexical_declaration" | "variable_declaration" => {
                for declarator in child.children() {
                    if declarator.kind() == "variable_declarator" {
                        return field_name(&declarator);
                    }
                }
            }
            _ => {}
        }
    }
    None
}

// ---- domain-specific detection (Express-style call shapes; same heuristics
// as ts.rs — JS shares the member_expression/call_expression node kinds) ----

const ROUTE_METHODS: &[&str] = &[
    "get", "post", "put", "patch", "delete", "options", "head", "all", "use",
];
const ROUTE_OBJECTS: &[&str] = &["app", "router"];
const RESPONSE_OBJECTS: &[&str] = &["res"];
const RESPONSE_VERBS: &[&str] = &["send", "json", "end", "render", "redirect", "sendFile"];

/// Express-style route registration: `app.get("/path", handler)` ->
/// (method, path). Narrow, fixture-driven heuristic: callee is a
/// member_expression on app/router with an HTTP-method property and a string
/// literal first argument.
fn route_of(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<(String, String)> {
    let fn_node = node.field("function")?;
    if fn_node.kind() != "member_expression" {
        return None;
    }
    let method = fn_node.field("property")?.text().into_owned();
    if !ROUTE_METHODS.contains(&method.as_str()) {
        return None;
    }
    let base = base_identifier(&fn_node)?;
    if !ROUTE_OBJECTS.contains(&base.as_str()) {
        return None;
    }
    let path = first_arg_text(node)?;
    if !path.starts_with('"') && !path.starts_with('\'') && !path.starts_with('`') {
        return None;
    }
    Some((method, super::unquote(&path, true)))
}

/// Express-style response call: `res.send(...)` / `res.json(...)` /
/// `res.status(200).json(...)` / `res.sendStatus(404)` ->
/// (status, body_shape).
fn response_of(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<(Option<String>, Option<String>)> {
    let fn_node = node.field("function")?;
    if fn_node.kind() != "member_expression" {
        return None;
    }
    let verb = fn_node.field("property")?.text().into_owned();
    let base = base_identifier(&fn_node)?;
    if !RESPONSE_OBJECTS.contains(&base.as_str()) {
        return None;
    }
    match verb.as_str() {
        "sendStatus" => Some((first_arg_text(node), None)),
        v if RESPONSE_VERBS.contains(&v) => Some((chain_status(&fn_node), Some(v.to_string()))),
        _ => None,
    }
}

/// Walk a member-expression chain down to its base identifier
/// (`res.status(200).json` -> "res", `app.get` -> "app").
fn base_identifier(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let mut cur = node.clone();
    loop {
        match cur.kind().as_ref() {
            "identifier" => return Some(cur.text().into_owned()),
            "member_expression" => cur = cur.field("object")?,
            "call_expression" => cur = cur.field("function")?,
            _ => return None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::parse::parse_source;

    #[test]
    fn decorator_entity_carries_expression_text_and_owner() {
        let src = "@Component\nclass Foo {}";
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let decorators: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Decorator)
            .collect();
        assert_eq!(decorators.len(), 1, "entities: {entities:?}");
        assert_eq!(decorators[0].name, "Component");
        assert_eq!(decorators[0].enclosing_function.as_deref(), Some("Foo"));
    }

    #[test]
    fn express_routes_accept_all_string_literal_quotes() {
        // `app.get("/users", listUsers)` -> the Route entity carries the
        // handler name so `detect_routes` can resolve it. An inline arrow
        // handler leaves it absent.
        let src = "app.get('/users', listUsers);\napp.post(\"/x\", (req, res) => res.end());\napp.put(`/settings`, saveSettings);\n";
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let routes: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Route)
            .collect();

        let named = routes
            .iter()
            .find(|r| r.path.as_deref() == Some("/users"))
            .expect("GET /users route");
        assert_eq!(named.owner_type.as_deref(), Some("listUsers"));
        let inline = routes
            .iter()
            .find(|r| r.path.as_deref() == Some("/x"))
            .expect("POST /x route");
        assert_eq!(
            inline.owner_type, None,
            "inline arrow handler names no resolvable function"
        );
        assert!(
            routes
                .iter()
                .any(|r| r.path.as_deref() == Some("/settings")),
            "template-literal route missing: {routes:?}"
        );
    }

    #[test]
    fn generator_declarations_and_closures_have_callable_entities() {
        let src = r#"
            function* entries() { yield load(); }
            function outer() {
                const callback = () => remote();
                queue(function () { deferred(); });
                queue(function* () { yield later(); });
            }
        "#;
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let functions: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Function)
            .collect();
        assert!(
            functions.iter().any(|e| e.name == "entries"),
            "{entities:?}"
        );

        let boundaries: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::CallableBoundary)
            .collect();
        assert_eq!(boundaries.len(), 3, "{entities:?}");
        assert!(boundaries.iter().all(|e| e.name.is_empty()));
    }

    #[test]
    fn complexity_events_cover_javascript_decisions() {
        let src = r#"
            function f(a, b, value) {
                if (a && b || a) {} else if (b) {}
                switch (value) { case 1: break; default: break; }
                do {} while (a);
                return a ? 1 : 0;
            }
        "#;
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let flows: Vec<&str> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert!(flows.contains(&"logical_and"), "entities: {entities:?}");
        assert!(flows.contains(&"logical_or"), "entities: {entities:?}");
        assert!(
            flows.contains(&"elseif_statement"),
            "entities: {entities:?}"
        );
        assert!(
            flows.contains(&"do_while_statement"),
            "entities: {entities:?}"
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| **name == "case_statement")
                .count(),
            2,
            "entities: {entities:?}"
        );
    }

    #[test]
    fn complexity_metadata_covers_else_jumps_negation_and_compensation() {
        let src = r#"
            function events(a, b, c) {
                if (a) {} else {}
                outer: while (a) { break outer; }
                return a && !(b && c);
            }
            function declarative(a) {
                var bar = {};
                bar.method = function () { if (a) {} };
            }
            function nondeclarative(a) {
                if (a) {}
                var bar = {};
                bar.method = function () { if (a) {} };
            }
            function callback(xs) { xs.forEach(x => { if (x) {} }); }
        "#;
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let flows: Vec<_> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .collect();

        for name in [
            "else_branch",
            "labeled_jump",
            "negation_break",
            "compensating_usage",
        ] {
            assert!(
                flows.iter().any(|entity| entity.name == name),
                "{name}: {flows:?}"
            );
        }
        let markers: Vec<_> = flows
            .iter()
            .filter(|entity| entity.name == "compensating_usage")
            .collect();
        assert_eq!(markers.len(), 1, "{flows:?}");
        let callback = entities
            .iter()
            .find(|entity| entity.kind == EntityKind::Function && entity.name == "callback")
            .unwrap();
        assert!(!markers.iter().any(|marker| {
            marker.span.start_byte <= callback.span.start_byte
                && callback.span.end_byte <= marker.span.end_byte
        }));
    }

    #[test]
    fn recursion_matcher_marks_direct_cycles_and_calls_in_closures() {
        let src = r#"
            function direct(n) { return direct(n - 1); }
            function closure(n) { const next = () => closure(n - 1); return next(); }
            function cycle_a(n) { return cycle_b(n - 1); }
            function cycle_b(n) { return cycle_a(n - 1); }
            class SelfCall { method(n) { return this.method(n - 1); } }
            class OtherCall {
                method(other, n) { return other.method(n - 1); }
            }
        "#;
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let recursive: Vec<_> = entities
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "recursive_call"
            })
            .collect();
        assert_eq!(recursive.len(), 5, "{entities:?}");
        assert!(
            recursive
                .iter()
                .any(|entity| entity.enclosing_function.as_deref() == Some("direct"))
        );
        assert!(
            recursive
                .iter()
                .any(|entity| entity.enclosing_function.as_deref() == Some("closure"))
        );
        assert!(
            recursive
                .iter()
                .any(|entity| entity.owner_type.as_deref() == Some("SelfCall"))
        );
        assert!(
            recursive
                .iter()
                .any(|entity| entity.enclosing_function.as_deref() == Some("cycle_a"))
        );
        assert!(
            recursive
                .iter()
                .any(|entity| entity.enclosing_function.as_deref() == Some("cycle_b"))
        );
    }
    #[test]
    fn if_alternatives_preserve_legacy_nesting_without_changing_other_metrics() {
        let src = "function f(a, b, c) { if (a) { if (b) { } } else if (b) { if (c) { } } else { if (a) { } } }";
        let parsed = parse_source(&SupportLang::JavaScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let markers: Vec<_> = entities
            .iter()
            .filter(|entity| entity.name == "legacy_nesting")
            .collect();

        assert_eq!(markers.len(), 1, "entities: {entities:?}");
        assert!(markers.iter().all(|marker| {
            src[marker.span.start_byte as usize..marker.span.end_byte as usize].starts_with("else")
        }));
        let metrics = crate::complexity::function_complexities(&entities);
        let metric = metrics.iter().find(|metric| metric.name == "f").unwrap();
        assert_eq!(metric.cyclomatic, 6, "metric: {metric:?}");
        assert_eq!(metric.max_nesting, 1, "metric: {metric:?}");
        assert_eq!(crate::complexity::cyclomatic_for_entities(&entities), 6);
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

    let declarations: Vec<_> = root
        .dfs()
        .filter(|node| is_recursion_callable(&node.kind()) && recursion_name(node).is_some())
        .collect();
    let callables: Vec<_> = declarations
        .iter()
        .map(|node| {
            let name = recursion_name(node).expect("filtered callable has a name");
            let parent = node.ancestors().find(|ancestor| {
                declarations
                    .iter()
                    .any(|candidate| candidate.range() == ancestor.range())
            });
            let nested = parent.is_some();
            let owner_type = enclosing_type_name(node);
            let owner = parent
                .as_ref()
                .and_then(|parent| recursion_name(parent))
                .or_else(|| owner_type.clone());
            let parameters: Vec<_> = node
                .field("parameters")
                .map(|list| {
                    list.children()
                        .filter(|parameter| {
                            matches!(
                                parameter.kind().as_ref(),
                                "identifier" | "assignment_pattern" | "rest_pattern"
                            )
                        })
                        .collect()
                })
                .unwrap_or_default();
            let total_args = u16::try_from(parameters.len()).unwrap_or(u16::MAX);
            let required_args = u16::try_from(
                parameters
                    .iter()
                    .filter(|parameter| {
                        parameter.kind() != "assignment_pattern"
                            && parameter.kind() != "rest_pattern"
                    })
                    .count(),
            )
            .unwrap_or(u16::MAX);
            let name_span = node
                .field("name")
                .map(|name| crate::extract::span_of(&name))
                .unwrap_or_else(|| crate::extract::span_of(node));
            (
                node.clone(),
                Callable {
                    owner,
                    owner_type: owner_type.clone(),
                    unqualified_callable: !is_class_method(node, owner_type.is_some())
                        && (nested || owner_type.is_none()),
                    name,
                    required_args,
                    total_args,
                    file_id: 0,
                    span: crate::extract::span_of(node),
                    name_span,
                },
            )
        })
        .collect();

    let mut references = Vec::new();
    for call in root.dfs().filter(|node| node.kind() == "call_expression") {
        let Some(caller) = call.ancestors().find_map(|ancestor| {
            callables
                .iter()
                .position(|(declaration, _)| declaration.range() == ancestor.range())
        }) else {
            continue;
        };
        let Some(function) = call.field("function") else {
            continue;
        };
        let (name, qualifier, qualifier_name) = match function.kind().as_ref() {
            "identifier" => (function.text().into_owned(), Qualifier::None, None),
            "member_expression" => {
                let Some(property) = function.field("property") else {
                    continue;
                };
                let Some(object) = function.field("object") else {
                    continue;
                };
                let owner_type = callables[caller].1.owner_type.as_deref();
                let object_name = object.text().into_owned();
                let (qualifier, qualifier_name) = if object_name == "this" {
                    (Qualifier::SelfLike, None)
                } else if owner_type == Some(object_name.as_str()) {
                    (Qualifier::NamedType, Some(object_name))
                } else {
                    (Qualifier::Other, None)
                };
                (property.text().into_owned(), qualifier, qualifier_name)
            }
            _ => continue,
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
    (
        callables
            .into_iter()
            .map(|(_, callable)| callable)
            .collect(),
        references,
    )
}

fn is_recursion_callable(kind: &str) -> bool {
    matches!(
        kind,
        "function_declaration"
            | "generator_function_declaration"
            | "function_expression"
            | "generator_function"
            | "method_definition"
    )
}

fn recursion_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    field_name(node).filter(|name| !name.is_empty())
}

fn enclosing_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.ancestors()
        .find(|ancestor| matches!(ancestor.kind().as_ref(), "class_declaration" | "class"))
        .and_then(|ancestor| field_name(&ancestor))
}

fn is_class_method(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    has_owner_type: bool,
) -> bool {
    node.kind() == "method_definition"
        && (has_owner_type
            || node
                .parent()
                .is_some_and(|parent| parent.kind() == "class_body"))
}
