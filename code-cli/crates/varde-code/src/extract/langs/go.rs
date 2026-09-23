//! Go entity extraction.
//!
//! Go-specific mapping notes (fixture-driven, superset-safe):
//! - `func` -> Function (function_declaration and method_declaration).
//! - `type X struct {}` -> Class; `type X interface {}` -> Interface.
//! - var/const/short-var declarators -> Variable (one per name).
//! - Exports: Go has no export statement; exported symbols are capitalized
//!   package-level names, so a capitalized top-level declaration name yields
//!   an Export entity alongside its primary entity.
//! - Throw: `panic()` maps to Throw. Go has no catch construct. `recover()` is
//!   an ordinary call because it does not introduce a decision branch.
//! - Route/Response: net/http shapes — `mux.HandleFunc("/path", h)` -> Route;
//!   `w.WriteHeader(n)` / `w.Write(...)` -> Response.

use crate::extract::entity::{EntityMeta, ExtractCtx, entity};
use crate::extract::field_name;
use crate::extract::langs::{boolean_operator_name, first_arg_text};
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

pub const FUNCTION_SCOPES: &[&str] = &["function_declaration", "method_declaration"];

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
    EntityKind::Throw,
    EntityKind::ControlFlow,
    EntityKind::Route,
    EntityKind::Response,
];

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
        // ---- structural ----
        "function_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Function, name.clone(), node);
            maybe_export(node, &name, ctx);
        }
        // A method's receiver type is its owning type. Go methods are declared
        // at file scope (not nested inside the type), so the generic
        // type-scope stack can't supply `owner_type` the way it does for
        // brace-nested languages — read it off the `receiver` field directly
        // and stamp it via `EntityMeta`, matching what `ctx.push` sets for
        // is_async/is_test on a Function.
        "method_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.out.push(entity(
                EntityKind::Function,
                name.clone(),
                ctx.file_id,
                node,
                EntityMeta {
                    is_async: Some(crate::extract::langs::node_is_async(node)),
                    is_test: crate::extract::langs::node_is_test(node),
                    owner_type: receiver_type_name(node),
                    ..Default::default()
                },
            ));
            maybe_export(node, &name, ctx);
        }
        "func_literal" => ctx.push_callable_boundary(node),
        // ---- imports ----
        // `import "fmt"` or a grouped `import (...)` block both parse down to
        // one `import_spec` per imported package; the `path` field carries
        // the quoted import path (e.g. "fmt", "github.com/foo/bar").
        "import_spec" => {
            if let Some(path) = node.field("path") {
                let spec = super::unquote(path.text().as_ref(), true);
                ctx.push(EntityKind::Import, spec, node);
            }
        }
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
        "type_spec" => {
            let name = field_name(node).unwrap_or_default();
            let struct_type = node.children().find(|c| c.kind() == "struct_type");
            let has_interface = node.children().any(|c| c.kind() == "interface_type");
            // Interfaces map to Interface; every other named type — struct, func
            // type (`type X func(...)`), defined type (`type Weekday int`), map/
            // slice/alias — maps to Class so it is captured as a declaration.
            // Previously only struct/interface were kept and all other named
            // types were dropped entirely (audit S3).
            let kind = if has_interface {
                EntityKind::Interface
            } else {
                EntityKind::Class
            };
            ctx.push(kind, name.clone(), node);
            maybe_export(node, &name, ctx);
            // Struct embedding (a `field_declaration` with no `name` field)
            // -> Extends, linking the embedding struct to the embedded
            // type. Implicit interface satisfaction (structural typing) is
            // intentionally excluded: it would require real type inference,
            // not a syntactic pattern, to detect reliably.
            if let Some(struct_type) = &struct_type {
                for embedded in embedded_field_type_names(struct_type) {
                    ctx.out.push(entity(
                        EntityKind::Extends,
                        embedded,
                        ctx.file_id,
                        node,
                        EntityMeta {
                            enclosing: Some(name.clone()),
                            ..Default::default()
                        },
                    ));
                }
            }
        }
        // `type MyAlias = OtherType` — a Go type alias (distinct node kind from
        // `type_spec`); mapped to Class so it surfaces as a declaration.
        "type_alias" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Class, name.clone(), node);
            maybe_export(node, &name, ctx);
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
    visit_part_3_a(node, kind, ctx) || visit_part_3_b(node, kind, ctx)
}

fn visit_part_3_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- variables ----
        "var_spec" | "const_spec" => {
            for n in declarator_names(node) {
                ctx.push(EntityKind::Variable, n.clone(), node);
                maybe_export(node, &n, ctx);
            }
        }
        _ => return false,
    }
    true
}

fn visit_part_3_b(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "short_var_declaration" => {
            for name in short_variable_names(node) {
                ctx.push(EntityKind::Variable, name, node);
            }
        }
        // ---- parameters ----
        "parameter_declaration" | "variadic_parameter_declaration" => {
            for n in declarator_names(node) {
                ctx.push(EntityKind::Parameter, n, node);
            }
        }
        _ => return false,
    }
    true
}

fn short_variable_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    node.field("left")
        .map(|left| identifier_names(left.children()))
        .unwrap_or_default()
}

fn visit_part_4(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    visit_part_4_a(node, kind, ctx)
}

fn visit_part_4_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- expression-level ----
        "call_expression" => visit_call_expression(node, ctx),
        _ => return false,
    }
    true
}

fn visit_call_expression(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    let name = node
        .field("function")
        .map(|function| function.text().into_owned())
        .unwrap_or_default();
    ctx.push(EntityKind::Call, name.clone(), node);
    if name == "panic" {
        ctx.push(
            EntityKind::Throw,
            first_arg_text(node).unwrap_or_default(),
            node,
        );
    }
    if let Some((method, path)) = route_of(node) {
        push_route(node, ctx, &name, method, path);
    }
    if let Some((status, shape)) = response_of(node) {
        push_response(node, ctx, &name, status, shape);
    }
}

fn push_route(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    name: &str,
    method: String,
    path: String,
) {
    ctx.out.push(Entity {
        kind: EntityKind::Route,
        name: name.to_string(),
        file_id: ctx.file_id,
        span: crate::extract::span_of(node),
        enclosing_function: ctx.enclosing.map(str::to_owned),
        method: Some(method),
        path: Some(path),
        status: None,
        body_shape: None,
        body_minhash: None,
        is_async: None,
        is_test: false,
        owner_type: crate::extract::langs::last_arg_identifier(node),
    });
}

fn push_response(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    name: &str,
    status: Option<String>,
    body_shape: Option<String>,
) {
    ctx.out.push(Entity {
        kind: EntityKind::Response,
        name: name.to_string(),
        file_id: ctx.file_id,
        span: crate::extract::span_of(node),
        enclosing_function: ctx.enclosing.map(str::to_owned),
        method: None,
        path: None,
        status,
        body_shape,
        body_minhash: None,
        is_async: None,
        is_test: false,
        owner_type: None,
    });
}

fn visit_part_5(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "selector_expression" => {
            let name = node
                .field("field")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::MemberAccess, name, node);
        }
        "int_literal"
        | "float_literal"
        | "imaginary_literal"
        | "rune_literal"
        | "interpreted_string_literal"
        | "raw_string_literal"
        | "true"
        | "false"
        | "nil" => {
            ctx.push(EntityKind::Literal, node.text().into_owned(), node);
        }
        // ---- control flow ----
        "if_statement"
        | "for_statement"
        | "expression_switch_statement"
        | "type_switch_statement"
        | "select_statement"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "go_statement"
        | "defer_statement" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        "expression_case" | "type_case" | "communication_case" | "default_case" => {
            ctx.push(EntityKind::ControlFlow, "case_statement".to_string(), node);
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
        "binary_expression" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }
        _ => return false,
    }
    true
}

/// Names of a `var_spec`/`const_spec`/`parameter_declaration`: the `name`
/// field may hold one or several identifiers.
fn declarator_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names = identifier_names(node.field_children("name"));
    if names.is_empty() {
        names = identifier_names(node.children());
    }
    names
}

/// Collect unique, non-blank Go identifiers from candidate nodes.
fn identifier_names<'a>(
    nodes: impl Iterator<Item = ast_grep_core::Node<'a, StrDoc<SupportLang>>>,
) -> Vec<String> {
    let mut names = Vec::new();
    for node in nodes.filter(|node| node.kind() == "identifier") {
        let name = node.text().into_owned();
        if name != "_" && !names.contains(&name) {
            names.push(name);
        }
    }
    names
}

/// Names of embedded types in a `struct_type`'s field list: a
/// `field_declaration` with no `name` field is an embedded (anonymous)
/// field — its `type` field is the embedded type, optionally wrapped in a
/// `pointer_type` (`*Base`) or qualified by package (`pkg.Base`).
fn embedded_field_type_names(
    struct_type: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Vec<String> {
    let Some(list) = struct_type
        .children()
        .find(|c| c.kind() == "field_declaration_list")
    else {
        return Vec::new();
    };
    list.children()
        .filter(|c| c.kind() == "field_declaration" && c.field("name").is_none())
        .filter_map(|c| c.field("type"))
        .map(|t| embedded_type_name(&t))
        .collect()
}

/// The bare type name of a `method_declaration`'s receiver, for `owner_type`
/// linkage. The `receiver` field is a `parameter_list` holding one
/// `parameter_declaration` whose `type` field is the receiver type —
/// `Foo`, `*Foo` (pointer receiver), or a generic `Foo[T]`. Pointer stripping
/// reuses [`embedded_type_name`]; a generic instantiation's `type_arguments`
/// suffix is dropped so `Foo[T]` and `*Foo` both yield `Foo`.
fn receiver_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let receiver = node.field("receiver")?;
    let param = receiver
        .children()
        .find(|c| c.kind() == "parameter_declaration")?;
    let ty = param.field("type")?;
    let base = if ty.kind() == "generic_type" {
        ty.children()
            .find(|c| c.kind() != "type_arguments")
            .map(|c| c.text().into_owned())
            .unwrap_or_else(|| ty.text().into_owned())
    } else {
        embedded_type_name(&ty)
    };
    let base = base.trim();
    (!base.is_empty()).then(|| base.to_string())
}

/// Unwraps a `pointer_type` to its base type text; otherwise the node's own
/// text (covers `type_identifier` and `qualified_type`, e.g. `pkg.Base`).
fn embedded_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    if node.kind() == "pointer_type" {
        node.children()
            .find(|c| c.kind() != "*")
            .map(|c| c.text().into_owned())
            .unwrap_or_else(|| node.text().into_owned())
    } else {
        node.text().into_owned()
    }
}

/// Go exports are capitalized package-level names: emit an Export entity
/// alongside the primary entity for top-level declarations.
fn maybe_export(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    name: &str,
    ctx: &mut ExtractCtx,
) {
    let top_level = node
        .parent()
        .map(|p| p.kind() == "source_file" || p.kind() == "type_declaration")
        .unwrap_or(false);
    if top_level && name.starts_with(|c: char| c.is_uppercase()) {
        ctx.out.push(entity(
            EntityKind::Export,
            name.to_string(),
            ctx.file_id,
            node,
            EntityMeta::default(),
        ));
    }
}

/// HTTP verb methods shared by the common Go router frameworks (gin, echo,
/// chi, fiber). Matched case-insensitively against the selector field so
/// gin's `.GET` and chi's `.Get` both resolve.
const GO_ROUTE_VERBS: &[&str] = &["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"];

/// A route-registration call -> `(method, path)`.
///
/// Recognizes net/http's `mux.HandleFunc("/p", h)` / `mux.Handle("/p", h)`
/// (verb not in the call -> `"*"`) and the verb-method form shared by
/// gin/echo/chi/fiber (`r.GET("/p", h)` / `r.Get("/p", h)`). Guarded by
/// requiring the first argument to be a string literal beginning with `/`, so
/// ordinary member calls like `cache.Get("key")` are not mistaken for routes.
fn route_of(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<(String, String)> {
    let fn_node = node.field("function")?;
    if fn_node.kind() != "selector_expression" {
        return None;
    }
    let field = fn_node.field("field")?.text().into_owned();
    let raw = first_arg_text(node)?;
    if !raw.starts_with('"') && !raw.starts_with('`') {
        return None;
    }
    let path = super::unquote(&raw, true);
    if !path.starts_with('/') {
        return None;
    }
    if field == "HandleFunc" || field == "Handle" {
        return Some(("*".to_string(), path));
    }
    let method = field.to_ascii_uppercase();
    if GO_ROUTE_VERBS.contains(&method.as_str()) {
        return Some((method, path));
    }
    None
}

/// net/http response: `w.WriteHeader(n)` -> (status, None);
/// `w.Write(...)` / `w.WriteString(...)` / `w.WriteHeader(n)` -> responses.
fn response_of(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<(Option<String>, Option<String>)> {
    let fn_node = node.field("function")?;
    if fn_node.kind() != "selector_expression" {
        return None;
    }
    let field = fn_node.field("field")?.text().into_owned();
    let base = fn_node.field("operand")?.text().into_owned();
    if base != "w" && base != "res" {
        return None;
    }
    match field.as_str() {
        "WriteHeader" => Some((first_arg_text(node), None)),
        "Write" | "WriteString" => Some((None, Some(field))),
        _ => None,
    }
}

#[cfg(test)]
mod tests {
    use crate::extract;
    use crate::model::{Entity, EntityKind};
    use crate::parse::parse_source;
    use ast_grep_language::SupportLang;

    fn routes(src: &str) -> Vec<(Option<String>, Option<String>)> {
        let parsed = parse_source(&SupportLang::Go, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        extract::extract(&parsed, 0)
            .entities
            .into_iter()
            .filter(|e: &Entity| e.kind == EntityKind::Route)
            .map(|e| (e.method, e.path))
            .collect()
    }

    #[test]
    fn named_non_struct_types_are_captured() {
        // Audit S3: `type X func(...)`, `type X int`, and `type X = alias` were
        // dropped — only struct/interface types survived.
        let src = "package m\n\
                   type PositionalArgs func(args []string) error\n\
                   type Weekday int\n\
                   type MyAlias = OtherType\n\
                   type Command struct{ Name string }\n";
        let parsed = parse_source(&SupportLang::Go, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let names: Vec<String> = extract::extract(&parsed, 0)
            .entities
            .into_iter()
            .filter(|e: &Entity| e.kind == EntityKind::Class)
            .map(|e| e.name)
            .collect();
        for expect in ["PositionalArgs", "Weekday", "MyAlias", "Command"] {
            assert!(
                names.contains(&expect.to_string()),
                "missing {expect}: {names:?}"
            );
        }
    }

    #[test]
    fn gin_echo_chi_verb_routes_capture_method_and_path() {
        // gin/echo `.GET`, chi `.Get`, and net/http `.HandleFunc` (verb `*`).
        let src = "package main\nfunc setup(r Router) {\n\tr.GET(\"/users\", list)\n\tr.Get(\"/health\", ok)\n\tr.HandleFunc(\"/legacy\", h)\n}\n";
        let got = routes(src);
        let has = |m: &str, p: &str| {
            got.iter()
                .any(|(gm, gp)| gm.as_deref() == Some(m) && gp.as_deref() == Some(p))
        };
        assert!(has("GET", "/users"), "routes: {got:?}");
        assert!(has("GET", "/health"), "routes: {got:?}");
        assert!(has("*", "/legacy"), "routes: {got:?}");
    }

    #[test]
    fn method_receiver_type_recorded_as_owner_and_plain_func_has_none() {
        // A method's receiver type is its owning type: `func (f Foo) Bar()`
        // -> owner_type "Foo"; a pointer receiver `func (s *Store) Save()`
        // strips the `*` -> "Store"; a plain `func free()` has no owner.
        let src = "package m\ntype Foo struct{}\ntype Store struct{}\nfunc (f Foo) Bar() {}\nfunc (s *Store) Save() {}\nfunc free() {}\n";
        let parsed = parse_source(&SupportLang::Go, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let owner = |name: &str| {
            entities
                .iter()
                .find(|e: &&Entity| e.kind == EntityKind::Function && e.name == name)
                .unwrap_or_else(|| panic!("function {name} present: {entities:?}"))
                .owner_type
                .clone()
        };
        assert_eq!(owner("Bar").as_deref(), Some("Foo"));
        assert_eq!(owner("Save").as_deref(), Some("Store"));
        assert_eq!(owner("free"), None);
    }

    #[test]
    fn non_route_member_calls_are_not_routes() {
        // `cache.Get("key")` shares the verb-method name but its argument is
        // not a `/`-path, so it must not be mistaken for a route.
        let src =
            "package main\nfunc f(cache C) {\n\tcache.Get(\"key\")\n\tdb.Delete(\"row-1\")\n}\n";
        assert!(
            routes(src).is_empty(),
            "unexpected routes: {:?}",
            routes(src)
        );
    }

    #[test]
    fn function_literals_are_callable_boundaries() {
        let parsed = parse_source(
            &SupportLang::Go,
            "package main\nfunc outer() { defer func() { remote() }() }\n",
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
    fn complexity_events_cover_go_switch_select_and_booleans() {
        let parsed = parse_source(
            &SupportLang::Go,
            r#"package main
func f(a, b bool, value any, channel chan int) {
    if a && b || a {}
    switch value { case 1, 2: return; default: return }
    select { case <-channel: return; default: return }
    _ = recover()
}
"#,
        );
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let flow_names: Vec<&str> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert!(
            flow_names.contains(&"logical_and"),
            "entities: {entities:?}"
        );
        assert!(flow_names.contains(&"logical_or"), "entities: {entities:?}");
        assert_eq!(
            flow_names
                .iter()
                .filter(|name| **name == "case_statement")
                .count(),
            4,
            "entities: {entities:?}"
        );
        assert!(
            entities
                .iter()
                .any(|entity| entity.kind == EntityKind::Call && entity.name == "recover"),
            "entities: {entities:?}"
        );
        assert!(
            entities
                .iter()
                .all(|entity| entity.kind != EntityKind::Catch),
            "entities: {entities:?}"
        );

        let metrics = crate::complexity::function_complexities(&entities);
        let function = metrics
            .iter()
            .find(|metric| metric.name == "f")
            .expect("f metric");
        assert_eq!(function.cyclomatic, 8, "metric: {function:?}");
        assert_eq!(function.cognitive, 5, "metric: {function:?}");
        assert_eq!(function.max_nesting, 0, "metric: {function:?}");
    }
}
