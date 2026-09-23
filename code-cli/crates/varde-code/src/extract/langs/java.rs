//! Java entity extraction.
//!
//! Java-specific mapping notes (fixture-driven, superset-safe):
//! - method_declaration / constructor_declaration / compact_constructor_declaration
//!   -> Function.
//! - class_declaration -> Class; interface_declaration -> Interface.
//! - field_declaration / local_variable_declaration / constant_declaration ->
//!   Variable, one Entity per variable_declarator name (handles `int a = 1,
//!   b = 2;`).
//! - formal_parameter -> Parameter.
//! - Exports: Java has no export statement; the closest analog is `public`
//!   visibility on a top-level type, so a top-level (parent is the `program`
//!   root) `public` class/interface yields an Export entity alongside its
//!   Class/Interface entity.
//! - Catch/Throw: native try/catch — catch_clause -> Catch (named after the
//!   exception variable, from catch_formal_parameter), throw_statement ->
//!   Throw (named after the thrown expression).
//! - Route: Spring MVC `@GetMapping("/path")`-style annotations — an
//!   annotation node named GetMapping/PostMapping/PutMapping/DeleteMapping/
//!   PatchMapping whose argument list carries a string-literal path.
//! - Response: servlet-style `response.setStatus(200)` / `res.setStatus(n)`
//!   method invocations -> status.

use crate::extract::entity::{EntityMeta, ExtractCtx, entity};
use crate::extract::field_name;
use crate::extract::langs::{
    boolean_operator_name, first_arg_text, push_type_ref, strip_generic_args, visit_do_statement,
};
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const TYPE_SCOPES: &[&str] = &["class_declaration", "interface_declaration"];
pub const FUNCTION_SCOPES: &[&str] = &[
    "method_declaration",
    "constructor_declaration",
    "compact_constructor_declaration",
];

/// Entity kinds the fixtures must produce.
pub const REQUIRED_KINDS: [EntityKind; 14] = [
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
    EntityKind::Route,
    EntityKind::Response,
];

/// Emit entities for one node (called for every node in the tree).
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
    if visit_do_statement(node, kind, ctx) {
        return;
    }
    let _ = visit_part_7(node, kind, ctx);
}

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- imports ----
        // `import com.foo.Bar;` / `import static com.foo.Bar.baz;` /
        // `import com.foo.*;`. No dedicated field for the path (children are
        // just identifier/scoped_identifier/asterisk), so the dotted path is
        // recovered from the node text; the trailing `.*` wildcard segment is
        // dropped since it names no single file. Normalized to a
        // slash-separated path (`com/foo/Bar`) so resolve.rs's existing
        // `/`-segment matching (shared with every other language) applies
        // unchanged.
        "import_declaration" => {
            let spec = java_import_path(node);
            ctx.push(EntityKind::Import, spec, node);
        }
        // ---- structural ----
        "method_declaration" | "constructor_declaration" | "compact_constructor_declaration" => {
            ctx.push(
                EntityKind::Function,
                function_scope_name(node).unwrap_or_default(),
                node,
            );
        }
        "lambda_expression" => ctx.push_callable_boundary(node),
        "class_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Class, name.clone(), node);
            maybe_export(node, &name, ctx);
            if let Some(superclass) = node.field("superclass")
                && let Some(ty) = superclass.children().find(|c| c.is_named())
            {
                push_type_ref(
                    ctx,
                    EntityKind::Extends,
                    strip_generic_args(&ty.text()),
                    &name,
                    &superclass,
                );
            }
            if let Some(interfaces) = node.field("interfaces") {
                for iface in type_list_names(&interfaces) {
                    push_type_ref(ctx, EntityKind::Implements, iface, &name, &interfaces);
                }
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
        "interface_declaration" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Interface, name.clone(), node);
            maybe_export(node, &name, ctx);
            // `interface Foo extends Bar, Baz` — an interface's own extends
            // list has no dedicated field; recovered from the
            // `extends_interfaces` child (see `type_list_names`).
            if let Some(extends) = node.children().find(|c| c.kind() == "extends_interfaces") {
                for parent in type_list_names(&extends) {
                    push_type_ref(ctx, EntityKind::Extends, parent, &name, &extends);
                }
            }
        }
        // ---- variables / parameters ----
        "field_declaration" | "local_variable_declaration" | "constant_declaration" => {
            for n in declarator_names(node) {
                ctx.push(EntityKind::Variable, n, node);
            }
        }
        "formal_parameter" => {
            ctx.push(
                EntityKind::Parameter,
                field_name(node).unwrap_or_default(),
                node,
            );
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
        // ---- expression-level ----
        "method_invocation" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Call, name.clone(), node);
            // servlet-style `response.setStatus(n)` / `res.setStatus(n)`.
            if let Some(status) = response_of(node) {
                ctx.out.push(Entity {
                    kind: EntityKind::Response,
                    name: name.clone(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
                    method: None,
                    path: None,
                    status: Some(status),
                    body_shape: None,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    owner_type: None,
                });
            }
        }
        "object_creation_expression" => {
            let name = node
                .field("type")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Call, name, node);
        }
        "field_access" => {
            let name = node
                .field("field")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::MemberAccess, name, node);
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
        | "octal_integer_literal"
        | "binary_integer_literal"
        | "decimal_floating_point_literal"
        | "hex_floating_point_literal"
        | "string_literal"
        | "character_literal"
        | "true"
        | "false"
        | "null_literal" => {
            if !ctx.in_type {
                ctx.push(EntityKind::Literal, node.text().into_owned(), node);
            }
        }
        // ---- error handling / control flow ----
        "catch_clause" => {
            let name = node
                .children()
                .find(|c| c.kind() == "catch_formal_parameter")
                .and_then(|c| field_name(&c))
                .unwrap_or_default();
            ctx.push(EntityKind::Catch, name, node);
        }
        "throw_statement" => {
            let name = node
                .children()
                .nth(1)
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Throw, name, node);
        }
        "if_statement" => {
            let name = if is_else_if(node) {
                "elseif_statement"
            } else {
                "if_statement"
            };
            ctx.push(EntityKind::ControlFlow, name.to_string(), node);
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
        "binary_expression" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }
        "switch_label" => {
            ctx.push(EntityKind::ControlFlow, "case_statement".to_string(), node);
        }
        "guard" => {
            ctx.push(EntityKind::ControlFlow, "guard_statement".to_string(), node);
        }
        "for_statement"
        | "enhanced_for_statement"
        | "while_statement"
        | "switch_expression"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "try_statement"
        | "try_with_resources_statement"
        | "ternary_expression" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
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
        // ---- domain-specific (Spring route annotations) ----
        "annotation" | "marker_annotation" => {
            if let Some((method, path)) = spring_route_of(node) {
                ctx.out.push(Entity {
                    kind: EntityKind::Route,
                    name: field_name(node).unwrap_or_default(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
                    method: Some(method),
                    path: Some(path),
                    status: None,
                    body_shape: None,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    owner_type: None,
                });
            }
            // Generic decorator entity: any annotation (`@Override`,
            // `@GetMapping`, ...) -> `name` is the bare annotation type name,
            // `enclosing_function` is the annotated class/interface/method's
            // own name (nearest declaration ancestor).
            if let Some((owner, declaration_span)) = annotation_owner(node) {
                let ann_name = field_name(node).unwrap_or_default();
                let (method, path) = java_route_meta(node, &ann_name);
                ctx.out.push(Entity {
                    kind: EntityKind::Decorator,
                    name: ann_name,
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: Some(owner),
                    method,
                    path,
                    status: None,
                    body_shape: None,
                    body_minhash: None,
                    is_async: None,
                    is_test: false,
                    owner_type: Some(declaration_span),
                });
            }
        }
        _ => return false,
    }
    true
}

/// Stable complexity name for Java short-circuit operators.
/// Whether this `if` occupies its parent's alternative branch.
fn is_else_if(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(parent) = node.parent() else {
        return false;
    };
    parent.kind() == "if_statement"
        && parent
            .field("alternative")
            .is_some_and(|alternative| alternative.range() == node.range())
}

/// Names of the `declarator` field(s) of a field/local/constant declaration:
/// one Entity per `variable_declarator` (handles `int a = 1, b = 2;`).
fn declarator_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    node.field_children("declarator")
        .filter(|c| c.kind() == "variable_declarator")
        .filter_map(|c| field_name(&c))
        .collect()
}

/// Java exports are `public` top-level types: emit an Export entity alongside
/// the Class/Interface entity for a `public` declaration whose parent is the
/// `program` root.
fn maybe_export(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    name: &str,
    ctx: &mut ExtractCtx,
) {
    let top_level = node
        .parent()
        .map(|p| p.kind() == "program")
        .unwrap_or(false);
    let is_public = node
        .children()
        .any(|c| c.kind() == "modifiers" && c.children().any(|k| k.kind() == "public"));
    if top_level && is_public {
        ctx.out.push(entity(
            EntityKind::Export,
            name.to_string(),
            ctx.file_id,
            node,
            EntityMeta::default(),
        ));
    }
}

/// Spring MVC route annotation: `@GetMapping("/path")` (or with a named
/// `value = "/path"` pair) -> (HTTP method, path).
fn spring_route_of(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<(String, String)> {
    const ROUTES: &[(&str, &str)] = &[
        ("GetMapping", "GET"),
        ("PostMapping", "POST"),
        ("PutMapping", "PUT"),
        ("DeleteMapping", "DELETE"),
        ("PatchMapping", "PATCH"),
    ];
    let name = field_name(node)?;
    let method = ROUTES.iter().find(|(n, _)| *n == name).map(|(_, m)| m)?;
    let args = node.field("arguments")?;
    let path = first_string_literal(&args)?;
    Some((method.to_string(), path))
}

/// Route `(method, path)` carried by a Spring/JAX-RS annotation, for stamping
/// onto its `Decorator` entity so `entrypoints::detect` can render the handler
/// as `"<VERB> <path>"`. The verb comes from the annotation name
/// (`@GetMapping` -> GET); a prefix annotation (`@RequestMapping("/api")`) has
/// no verb but still contributes its base path. `(None, None)` for a
/// non-route annotation (`@Override`, ...).
fn java_route_meta(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    name: &str,
) -> (Option<String>, Option<String>) {
    let verb = super::http_verb_for_annotation(name);
    if verb.is_none() && !super::is_route_prefix_annotation(name) {
        return (None, None);
    }
    let path = node
        .field("arguments")
        .as_ref()
        .and_then(first_string_literal);
    (verb.map(|v| v.to_string()), path)
}

/// First string-literal argument of an annotation, either directly in the
/// argument list (`@GetMapping("/todos")`) or as an element-value pair value
/// (`@PostMapping(value = "/todos")`).
fn first_string_literal(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    for child in node.children() {
        if child.kind() == "string_literal" {
            return Some(super::unquote(&child.text(), false));
        }
        if child.kind() == "element_value_pair"
            && let Some(v) = child.field("value")
            && v.kind() == "string_literal"
        {
            return Some(super::unquote(&v.text(), false));
        }
    }
    None
}

/// Servlet-style response: `response.setStatus(n)` / `res.setStatus(n)` ->
/// status text.
fn response_of(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let name = field_name(node)?;
    if name != "setStatus" {
        return None;
    }
    let base = node.field("object")?.text().into_owned();
    if base != "response" && base != "res" {
        return None;
    }
    first_arg_text(node)
}

/// Recover the slash-separated import path from an `import_declaration`
/// node's raw text (no dedicated path field exists on this grammar).
fn java_import_path(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let text = node.text();
    let t = text
        .trim()
        .trim_end_matches(';')
        .trim_start_matches("import")
        .trim()
        .trim_start_matches("static")
        .trim();
    let t = t.strip_suffix(".*").unwrap_or(t);
    t.replace('.', "/")
}

/// Names of the `_type` children of a `type_list` node (`super_interfaces`'s
/// or `extends_interfaces`'s inner type list): one name per comma-separated
/// supertype/interface.
fn type_list_names(wrapper: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    wrapper
        .children()
        .find(|c| c.kind() == "type_list")
        .map(|list| {
            list.children()
                .filter(|c| c.is_named())
                .map(|c| strip_generic_args(&c.text()))
                .collect()
        })
        .unwrap_or_default()
}

/// Nearest enclosing declaration's own name for an `annotation`/
/// `marker_annotation` node: the class/interface/enum/method/constructor
/// this annotation is attached to (climbing ancestors past the intervening
/// `modifiers` wrapper).
fn annotation_owner(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<(String, String)> {
    const OWNER_KINDS: &[&str] = &[
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
        "method_declaration",
        "constructor_declaration",
    ];
    node.ancestors()
        .find(|a| OWNER_KINDS.contains(&a.kind().as_ref()))
        .and_then(|owner| {
            let name = field_name(&owner)?;
            let span = crate::extract::span_of(&owner);
            Some((name, format!("{}:{}", span.start_byte, span.end_byte)))
        })
}

/// Stable name for a Java callable scope.
///
/// Compact record constructors have no direct `name` field. Their record
/// declaration supplies the constructor name instead.
pub fn function_scope_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    field_name(node).or_else(|| {
        (node.kind() == "compact_constructor_declaration")
            .then(|| {
                node.ancestors()
                    .find(|ancestor| ancestor.kind() == "record_declaration")
                    .and_then(|ancestor| field_name(&ancestor))
            })
            .flatten()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::parse::parse_source;

    #[test]
    fn extends_implements_entities_carry_raw_name_and_owner() {
        let src = "class Foo extends Base implements IFoo, IBar { }";
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let extends: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Extends)
            .collect();
        assert_eq!(extends.len(), 1, "entities: {entities:?}");
        assert_eq!(extends[0].name, "Base");
        assert_eq!(extends[0].enclosing_function.as_deref(), Some("Foo"));

        let mut implements: Vec<&str> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Implements)
            .map(|e| e.name.as_str())
            .collect();
        implements.sort_unstable();
        assert_eq!(implements, vec!["IBar", "IFoo"]);
        assert!(
            entities
                .iter()
                .filter(|e| e.kind == EntityKind::Implements)
                .all(|e| e.enclosing_function.as_deref() == Some("Foo"))
        );
    }

    #[test]
    fn generic_supertype_names_are_stripped_to_bare_identifier() {
        // CORRECTNESS-002: `Comparable<Foo>` must resolve to bare
        // "Comparable" so it matches the in-repo `Comparable` entity name.
        let src = "class Foo extends Base<T> implements Comparable<Foo> { }";
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let extends: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Extends)
            .collect();
        assert_eq!(extends.len(), 1, "entities: {entities:?}");
        assert_eq!(extends[0].name, "Base");

        let implements: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Implements)
            .collect();
        assert_eq!(implements.len(), 1, "entities: {entities:?}");
        assert_eq!(implements[0].name, "Comparable");
    }

    #[test]
    fn decorator_entity_carries_annotation_name_and_owner() {
        let src = "class Foo { @Override void bar() {} }";
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let decorators: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Decorator)
            .collect();
        assert_eq!(decorators.len(), 1, "entities: {entities:?}");
        assert_eq!(decorators[0].name, "Override");
        assert_eq!(decorators[0].enclosing_function.as_deref(), Some("bar"));
    }

    #[test]
    fn compact_record_constructor_is_a_named_function_scope() {
        let src = "record Order(String id) { Order { validate(id); } }";
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let functions: Vec<&Entity> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::Function)
            .collect();
        assert_eq!(functions.len(), 1, "entities: {entities:?}");
        assert_eq!(functions[0].name, "Order");

        let call = entities
            .iter()
            .find(|entity| entity.kind == EntityKind::Call)
            .expect("compact constructor call");
        assert_eq!(call.enclosing_function.as_deref(), Some("Order"));
    }

    #[test]
    fn lambda_expressions_are_callable_boundaries() {
        let src = "class Jobs { void outer() { queue(() -> deferred()); } }";
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        assert!(
            entities
                .iter()
                .any(|entity| entity.kind == EntityKind::CallableBoundary),
            "lambda boundary: {entities:?}"
        );
    }

    #[test]
    fn complexity_events_cover_boolean_switch_else_if_catch_and_lambda() {
        let src = r#"
class Demo {
    int f(int x, boolean a, boolean b, boolean c) {
        if (a && b || c) { x++; } else if (b) { x--; }
        do { x++; } while (a);
        try { work(); } catch (RuntimeException error) { recover(error); }
        Runnable callback = () -> deferred();
        return switch (x) {
            case 0 -> 0;
            case 1 -> 1;
            default -> 2;
        };
    }
}
"#;
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let control_flow: Vec<&str> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert_eq!(
            control_flow
                .iter()
                .filter(|name| **name == "if_statement")
                .count(),
            1
        );
        assert_eq!(
            control_flow
                .iter()
                .filter(|name| **name == "elseif_statement")
                .count(),
            1
        );
        assert!(
            control_flow.contains(&"logical_and"),
            "events: {control_flow:?}"
        );
        assert!(
            control_flow.contains(&"logical_or"),
            "events: {control_flow:?}"
        );
        assert!(
            control_flow.contains(&"do_while_statement"),
            "events: {control_flow:?}"
        );
        assert_eq!(
            control_flow
                .iter()
                .filter(|name| **name == "case_statement")
                .count(),
            3
        );
        assert_eq!(
            entities
                .iter()
                .filter(|entity| entity.kind == EntityKind::Catch)
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
    fn guarded_switch_labels_emit_guard_events() {
        let src = r#"
class Demo {
    int classify(Object value) {
        return switch (value) {
            case String text when !text.isEmpty() -> 1;
            default -> 0;
        };
    }
}
"#;
        let parsed = parse_source(&SupportLang::Java, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        assert!(
            entities.iter().any(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "guard_statement"
            }),
            "entities: {entities:?}"
        );
    }
}
