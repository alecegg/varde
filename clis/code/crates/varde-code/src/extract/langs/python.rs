//! Python entity extraction.
//!
//! Python-specific mapping notes (fixture-driven, superset-safe):
//! - `def` -> Function (function_definition, name via field "name").
//! - `class` -> Class (class_definition).
//! - Interface: carved out — Python has no native interface construct
//!   (ABCs/protocols are runtime classes, not syntax).
//! - Variable: narrow — `assignment` statements whose `left` is an identifier
//!   or a pattern_list of identifiers (`x = 1`, `a, b = 1, 2`).
//! - Parameter: identifiers inside the `parameters` node (plain identifiers,
//!   default/typed variants carry `name`, splat patterns wrap an identifier).
//! - Export: carved out — Python has no export statement; `__all__` is a
//!   convention, not syntax.
//! - Call: `call` node, callee text as name. `attribute` -> MemberAccess
//!   (field "attribute").
//! - Literal: integer/float/string/true/false/none, excluding type contexts.
//! - Catch/Throw: `except_clause` (named after the exception variable) and
//!   `raise_statement` (named after the raised expression).
//! - ControlFlow: decisions, boolean sequences, comprehensions, match arms,
//!   transfers, and non-decision structural regions.
//! - Route: narrow Flask shape — `@app.route("/path")` (or a blueprint
//!   object) decorator; method from `methods=[...]` kwarg, default "GET".
//! - Response: narrow Flask shape — calls to Flask's response-producing
//!   functions (`jsonify`, `render_template`, `make_response`, `redirect`,
//!   `send_file`, `send_from_directory`); body_shape is the function name.

use crate::extract::entity::ExtractCtx;
use crate::extract::field_name;
use crate::extract::langs::first_arg_text;
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const FUNCTION_SCOPES: &[&str] = &["function_definition"];

/// Node kinds that introduce a named type scope, so a `def` nested inside a
/// `class` records its owning class on `Entity::owner_type` (see
/// `crate::extract::langs::type_scopes`). This lets navigation surfaces
/// disambiguate common method names — `on` in `event_bus.py` becomes
/// `EventBus.on` — and gives class-membership consumers the owner linkage.
pub const TYPE_SCOPES: &[&str] = &["class_definition"];

/// Entity kinds the fixtures must produce. Interface and Export are carved
/// out (see module docs); Route/Response use narrow Flask-style shapes.
pub const REQUIRED_KINDS: [EntityKind; 12] = [
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
    let _ = visit_part_8(node, kind, ctx);
}

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- imports ----
        // `import a.b, c as d` -> one Import entity per name in the `name`
        // field (dotted_name directly, or the `name` field of an
        // aliased_import for the `as` form). Dotted paths are normalized to
        // slash-separated form so resolve.rs's shared `/`-segment matching
        // applies unchanged.
        "import_statement" => {
            for name_node in node.field_children("name") {
                if let Some(spec) = python_dotted_path(&name_node) {
                    ctx.push(EntityKind::Import, spec, node);
                    // Record the local module-binding name (`import x as y` -> y,
                    // `import a.b.c` -> c) on `owner_type` so resolve.rs can
                    // resolve a receiver-qualified call (`y.fn()` / `c.fn()`) to
                    // the bound module's file.
                    if let Some(binding) = python_import_binding(&name_node)
                        && let Some(last) = ctx.out.last_mut()
                    {
                        last.owner_type = Some(binding);
                    }
                    mark_if_type_checking_only(node, ctx);
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
    visit_part_2_a(node, kind, ctx)
}

fn visit_part_2_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // `from a.b import c` / `from . import c` / `from ..pkg import c`.
        // `module_name` is either a plain dotted_name (absolute) or a
        // relative_import (leading dots + an optional dotted_name). Leading
        // dots are converted to `./`/`../` segments the same way resolve.rs
        // already resolves Rust's `super::`/`self::` prefixes, so a same-repo
        // relative import resolves via its existing relative-path matching.
        "import_from_statement" => visit_import_from(node, ctx),
        _ => return false,
    }
    true
}

fn visit_import_from(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    let Some(module) = node.field("module_name") else {
        return;
    };
    let mut spec = python_import_module(&module);
    append_relative_import_name(node, &mut spec);
    if spec.is_empty() {
        return;
    }
    let bindings: Vec<String> = node
        .field_children("name")
        .filter_map(|name| python_import_binding(&name))
        .collect();
    ctx.push(EntityKind::Import, spec, node);
    if !bindings.is_empty()
        && let Some(import) = ctx.out.last_mut()
    {
        import.owner_type = Some(bindings.join(","));
    }
    mark_if_type_checking_only(node, ctx);
}

fn python_import_module(module: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    match module.kind().as_ref() {
        "relative_import" => python_relative_import_path(module),
        _ => python_dotted_path(module).unwrap_or_default(),
    }
}

fn append_relative_import_name(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    spec: &mut String,
) {
    if !(spec.ends_with('/') || spec.is_empty()) {
        return;
    }
    if let Some(name) = node
        .field_children("name")
        .next()
        .and_then(|name| python_dotted_path(&name))
    {
        spec.push_str(&name);
    }
}

fn visit_part_3(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- structural ----
        "function_definition" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Function, name, node);
            if is_compensating_usage(node) {
                ctx.push(
                    EntityKind::ControlFlow,
                    "compensating_usage".to_string(),
                    node,
                );
            }
        }
        "lambda" if node.is_named() => ctx.push_callable_boundary(node),
        "class_definition" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Class, name.clone(), node);
            // `class Sub(Base1, Base2):` -> one Extends entity per base class
            // named in the `superclasses` argument_list. Keyword arguments
            // (e.g. `metaclass=Meta`) are not base classes and are skipped.
            if let Some(superclasses) = node.field("superclasses") {
                for base in superclasses.children() {
                    let base_name = match base.kind().as_ref() {
                        "identifier" | "attribute" => Some(base.text().into_owned()),
                        _ => None,
                    };
                    if let Some(base_name) = base_name {
                        ctx.out.push(Entity {
                            kind: EntityKind::Extends,
                            name: base_name,
                            file_id: ctx.file_id,
                            span: crate::extract::span_of(&base),
                            enclosing_function: Some(name.clone()),
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
    visit_part_4_a(node, kind, ctx)
}

fn visit_part_4_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // Flask routes live in decorators, which wrap the definition.
        "decorated_definition" => visit_decorated_definition(node, ctx),
        _ => return false,
    }
    true
}

fn visit_decorated_definition(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    if let Some((method, path)) = route_of(node) {
        ctx.out.push(Entity {
            kind: EntityKind::Route,
            name: "app.route".to_string(),
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
            owner_type: None,
        });
    }
    let Some(definition) = node.field("definition") else {
        return;
    };
    let owner = field_name(&definition).unwrap_or_default();
    for decorator in node.children().filter(|child| child.kind() == "decorator") {
        push_python_decorator(&decorator, ctx, &owner);
    }
}

fn push_python_decorator(
    decorator: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    owner: &str,
) {
    let Some(name) = python_decorator_name(decorator) else {
        return;
    };
    let (method, path) = python_route_meta(decorator, &name);
    ctx.out.push(Entity {
        kind: EntityKind::Decorator,
        name,
        file_id: ctx.file_id,
        span: crate::extract::span_of(decorator),
        enclosing_function: Some(owner.to_string()),
        method,
        path,
        status: None,
        body_shape: None,
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
        // ---- variables ----
        // Narrow: assignment where `left` is an identifier or identifier list.
        "assignment" => {
            if let Some(left) = node.field("left") {
                for name in assignment_target_names(&left) {
                    ctx.push(EntityKind::Variable, name, node);
                }
            }
        }
        // ---- parameters ----
        "parameters" => {
            for name in parameter_names(node) {
                ctx.push(EntityKind::Parameter, name, node);
            }
        }
        // ---- expression-level ----
        "call" => {
            let name = node
                .field("function")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Call, name.clone(), node);
            // Flask responses: jsonify(...), render_template(...), etc.
            if let Some(body_shape) = response_of(node) {
                ctx.out.push(Entity {
                    kind: EntityKind::Response,
                    name: name.clone(),
                    file_id: ctx.file_id,
                    span: crate::extract::span_of(node),
                    enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
                    method: None,
                    path: None,
                    status: None,
                    body_shape: Some(body_shape),
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
        "attribute" => {
            let name = node
                .field("attribute")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::MemberAccess, name, node);
        }
        // Literals: exclude values inside type annotations (e.g.
        // `Literal["a"]` in `x: Literal["a"]`).
        "integer" | "float" | "string" | "true" | "false" | "none" => {
            if !in_python_type_context(node) {
                ctx.push(EntityKind::Literal, node.text().into_owned(), node);
            }
        }
        // ---- control-flow / error ----
        // `except ValueError as err` -> Catch, named after the exception var.
        "except_clause" => {
            let name = exception_var(node);
            ctx.push(EntityKind::Catch, name, node);
        }
        // `raise ValueError("empty")` -> Throw, named after the raised expr.
        "raise_statement" => {
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
        "boolean_operator" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }
        "elif_clause" => {
            ctx.push(
                EntityKind::ControlFlow,
                "elseif_statement".to_string(),
                node,
            );
        }
        "match_statement" => {
            ctx.push(
                EntityKind::ControlFlow,
                "match_expression".to_string(),
                node,
            );
        }
        "case_clause" => {
            ctx.push(EntityKind::ControlFlow, "match_arm".to_string(), node);
        }
        "not_operator" if contains_boolean_operator(node) => {
            ctx.push(EntityKind::ControlFlow, "negation_break".to_string(), node);
        }
        _ => return false,
    }
    true
}

fn visit_part_8(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "else_clause"
            if node
                .parent()
                .is_some_and(|parent| parent.kind() == "if_statement") =>
        {
            ctx.push(EntityKind::ControlFlow, "else_branch".to_string(), node);
        }
        "if_statement" => {
            let consequence = node.field("consequence");
            if let Some(consequence) = consequence.as_ref() {
                ctx.push(
                    EntityKind::ControlFlow,
                    "if_statement".to_string(),
                    consequence,
                );
            } else {
                ctx.push(EntityKind::ControlFlow, "if_statement".to_string(), node);
            }
            if let Some(condition) = node.field("condition") {
                ctx.push(EntityKind::ControlFlow, "legacy_nesting".to_string(), node);
                if let Some(marker) = ctx.out.last_mut() {
                    let condition_span = crate::extract::span_of(&condition);
                    let marker_end = consequence
                        .as_ref()
                        .filter(|consequence| if_consequence_needs_legacy_nesting(consequence))
                        .map(crate::extract::span_of)
                        .unwrap_or(condition_span);
                    marker.span.end_byte = marker_end.end_byte;
                    marker.span.end_line = marker_end.end_line;
                    marker.span.end_col = marker_end.end_col;
                }
            }
            push_if_alternative_legacy_nesting(node, ctx);
        }
        "for_in_clause" => ctx.push(
            EntityKind::ControlFlow,
            "comprehension_for".to_string(),
            node,
        ),
        "if_clause" => ctx.push(
            EntityKind::ControlFlow,
            "comprehension_if".to_string(),
            node,
        ),
        "for_statement"
        | "while_statement"
        | "with_statement"
        | "try_statement"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "conditional_expression" => {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        _ => return false,
    }
    true
}

/// Preserve legacy nesting over all alternatives without extending the new `if` decision.
fn push_if_alternative_legacy_nesting(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    let Some(alternative) = node.field("alternative") else {
        return;
    };
    let node_span = crate::extract::span_of(node);
    ctx.push(
        EntityKind::ControlFlow,
        "legacy_nesting".to_string(),
        &alternative,
    );
    if let Some(marker) = ctx.out.last_mut() {
        marker.span.end_byte = node_span.end_byte;
        marker.span.end_line = node_span.end_line;
        marker.span.end_col = node_span.end_col;
    }
}

/// Restore the old parent edge when a single flow statement shares the clipped `if` span.
fn if_consequence_needs_legacy_nesting(
    consequence: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> bool {
    let consequence_span = crate::extract::span_of(consequence);
    let direct_flow = if python_node_emits_its_full_span(consequence) {
        Some(consequence.clone())
    } else {
        consequence.children().find(|child| {
            python_node_emits_its_full_span(child)
                && crate::extract::span_of(child) == consequence_span
        })
    };
    let Some(direct_flow) = direct_flow else {
        return false;
    };

    !direct_flow.dfs().any(|child| {
        let span = crate::extract::span_of(&child);
        span != consequence_span
            && span.start_byte >= consequence_span.start_byte
            && span.end_byte <= consequence_span.end_byte
            && python_node_contributes_to_max_nesting(&child)
    })
}

fn python_node_emits_its_full_span(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.kind() != "if_statement" && python_node_contributes_to_max_nesting(node)
}

fn python_node_contributes_to_max_nesting(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> bool {
    let kind = node.kind();
    match kind.as_ref() {
        "except_clause" | "for_in_clause" | "if_clause" | "match_statement" => true,
        "if_statement"
        | "for_statement"
        | "while_statement"
        | "with_statement"
        | "try_statement"
        | "return_statement"
        | "break_statement"
        | "continue_statement"
        | "conditional_expression" => matches!(
            crate::complexity::control_flow_role(kind.as_ref()),
            crate::complexity::FlowRole::StructuralDecision
                | crate::complexity::FlowRole::DecisionContainer
                | crate::complexity::FlowRole::Catch
                | crate::complexity::FlowRole::LegacyOnly
                | crate::complexity::FlowRole::LegacyNesting
        ),
        _ => false,
    }
}

fn boolean_operator_name(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<&'static str> {
    node.children()
        .find(|child| matches!(child.text().as_ref(), "and" | "or"))
        .and_then(|operator| match operator.text().as_ref() {
            "and" => Some("logical_and"),
            "or" => Some("logical_or"),
            _ => None,
        })
}

fn contains_boolean_operator(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.dfs().any(|child| child.kind() == "boolean_operator")
}

fn is_compensating_usage(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(body) = node.field("body") else {
        return false;
    };
    let statements: Vec<_> = body.children().filter(|child| child.is_named()).collect();
    statements.len() == 2
        && statements
            .iter()
            .any(|child| child.kind() == "function_definition")
        && statements
            .iter()
            .any(|child| child.kind() == "return_statement")
}

/// Names assigned by an assignment statement's `left` (an identifier or a
/// pattern_list of identifiers). Narrow by design: only plain identifier
/// targets produce Variable entities.
fn assignment_target_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names = Vec::new();
    match node.kind().as_ref() {
        "identifier" => {
            let t = node.text().into_owned();
            if t != "_" {
                names.push(t);
            }
        }
        "pattern_list" => {
            for child in node.children() {
                if child.kind() == "identifier" {
                    let t = child.text().into_owned();
                    if t != "_" {
                        names.push(t);
                    }
                }
            }
        }
        _ => {}
    }
    names
}

/// Parameter names inside a `parameters` node: plain identifiers,
/// default/typed defaults (field "name"), typed/splat patterns wrapping an
/// identifier.
fn parameter_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names = Vec::new();
    for child in node.children() {
        let name = match child.kind().as_ref() {
            "identifier" => Some(child.text().into_owned()),
            "default_parameter" | "typed_default_parameter" => field_name(&child),
            "typed_parameter" | "list_splat_pattern" | "dictionary_splat_pattern" => child
                .children()
                .find(|c| c.kind() == "identifier")
                .map(|c| c.text().into_owned()),
            _ => None,
        };
        if let Some(name) = name
            && name != "_"
        {
            names.push(name);
        }
    }
    names
}

/// The exception variable of an `except` clause (`except ValueError as err`
/// -> "err"; bare `except:` -> "").
fn exception_var(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    for descendant in node.dfs() {
        if descendant.kind() == "as_pattern_target"
            && let Some(id) = descendant.children().find(|c| c.kind() == "identifier")
        {
            return id.text().into_owned();
        }
    }
    String::new()
}

/// If `import_node` is lexically nested inside an `if TYPE_CHECKING:` block
/// (the standard `typing.TYPE_CHECKING` guard used to import a name only for
/// type hints, never at runtime), tag the entity just pushed for it as
/// `body_shape = "type_only"`. Reused (not a new column) because Import
/// entities don't otherwise use `body_shape` — see `circular_import.toml`,
/// which excludes these from the runtime import graph: Python never executes
/// a `TYPE_CHECKING`-guarded import, so it can't participate in a real
/// load-order cycle.
fn mark_if_type_checking_only(
    import_node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    let guarded = import_node.ancestors().skip(1).any(|a| {
        a.kind().as_ref() == "if_statement"
            && a.field("condition")
                .is_some_and(|c| c.text().as_ref().contains("TYPE_CHECKING"))
    });
    if guarded && let Some(last) = ctx.out.last_mut() {
        last.body_shape = Some("type_only".to_string());
    }
}

/// True when the node sits inside a Python type annotation. Python's
/// annotation node kind is `type`; `Literal[...]`/`Union[...]` spellings use
/// generic_type/union_type.
fn in_python_type_context(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    const TYPE_KINDS: &[&str] = &[
        "type",
        "generic_type",
        "union_type",
        "splat_type",
        "type_parameter",
        "type_argument_list",
    ];
    node.ancestors()
        .skip(1)
        .any(|a| TYPE_KINDS.contains(&a.kind().as_ref()))
}

// ---- domain-specific detection (Flask-style shapes) ----

const ROUTE_OBJECTS: &[&str] = &["app", "blueprint"];
const RESPONSE_FUNCTIONS: &[&str] = &[
    "jsonify",
    "render_template",
    "make_response",
    "redirect",
    "send_file",
    "send_from_directory",
];

/// Flask-style route: a `@app.route("/path", methods=["POST"])` decorator on
/// a decorated_definition. Returns (method, path); method defaults to "GET"
/// unless a single-string `methods=[...]` kwarg is present. The decorator
/// attribute is literally `route` — the HTTP verb lives in the `methods`
/// keyword argument.
fn route_of(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<(String, String)> {
    for decorator in node.children() {
        if decorator.kind() != "decorator" {
            continue;
        }
        let Some(call) = decorator.children().find(|c| c.kind() == "call") else {
            continue;
        };
        let fn_node = call.field("function")?;
        if fn_node.kind() != "attribute" {
            continue;
        }
        let attr = fn_node.field("attribute")?.text();
        if attr != "route" {
            continue;
        }
        let base = fn_node.field("object")?.text();
        if !ROUTE_OBJECTS.contains(&base.as_ref()) {
            continue;
        }
        let path = first_arg_text(&call)?;
        if !path.starts_with('"') && !path.starts_with('\'') {
            continue;
        }
        let method = methods_kwarg(&call).unwrap_or_else(|| "GET".to_string());
        return Some((method, super::unquote(&path, false)));
    }
    None
}

/// `methods=["POST"]` keyword argument of a route call -> "POST" (only when
/// the list holds a single string literal).
fn methods_kwarg(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let args = node.field("arguments")?;
    for child in args.children() {
        if child.kind() == "keyword_argument"
            && child.field("name").map(|n| n.text()) == Some("methods".into())
        {
            let value = child.field("value")?;
            if value.kind() == "list"
                && let Some(s) = value.children().find(|c| c.kind() == "string")
            {
                return Some(super::unquote(&s.text(), false));
            }
        }
    }
    None
}

/// Route `(method, path)` carried by a single `@decorator` node, for stamping
/// onto its `Decorator` entity. Recognizes FastAPI/router verb decorators
/// (`@app.get("/x")`, `@router.post("/x")`) via the shared verb map, and Flask
/// `@<obj>.route("/x", methods=[...])` (verb from the kwarg, `GET` default).
/// Returns `(None, None)` for a non-route decorator (`@staticmethod`, ...).
fn python_route_meta(
    decorator: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    dec_name: &str,
) -> (Option<String>, Option<String>) {
    let call = decorator.children().find(|c| c.kind() == "call");
    let path = call.as_ref().and_then(|c| {
        let p = first_arg_text(c)?;
        (p.starts_with('"') || p.starts_with('\'')).then(|| super::unquote(&p, false))
    });
    let method = match super::http_verb_for_annotation(dec_name) {
        Some(v) => Some(v.to_string()),
        // Flask `@<obj>.route` — the verb lives in the `methods=[...]` kwarg.
        None if dec_name.ends_with(".route") => Some(
            call.as_ref()
                .and_then(methods_kwarg)
                .unwrap_or_else(|| "GET".to_string()),
        ),
        None => None,
    };
    if method.is_none() {
        return (None, None);
    }
    (method, path)
}

/// Flask-style response: a call to one of Flask's response-producing
/// functions -> body_shape is the function name.
fn response_of(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let fn_node = node.field("function")?;
    if fn_node.kind() != "identifier" {
        return None;
    }
    let name = fn_node.text();
    if RESPONSE_FUNCTIONS.contains(&name.as_ref()) {
        Some(name.into_owned())
    } else {
        None
    }
}

/// The local name a single import clause binds — the receiver used at call
/// sites: the alias for `x as y` (-> `y`), else the last dotted segment
/// (`a.b.c` -> `c`, `crud` -> `crud`). Used to populate `Import.owner_type`
/// for receiver-aware call resolution in resolve.rs.
fn python_import_binding(
    name_node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<String> {
    if name_node.kind() == "aliased_import"
        && let Some(alias) = name_node.field("alias")
    {
        return Some(alias.text().into_owned());
    }
    let text = name_node.text();
    let last = text.rsplit('.').next().unwrap_or(&text).trim();
    (!last.is_empty()).then(|| last.to_owned())
}

/// Slash-normalized dotted path from a `dotted_name` (or the `dotted_name`
/// nested in an `aliased_import`'s `name` field for `import x as y`).
fn python_dotted_path(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let dotted = if node.kind() == "aliased_import" {
        node.field("name")?
    } else {
        node.clone()
    };
    Some(dotted.text().replace('.', "/"))
}

/// `from . import x` / `from ..pkg import y` -> a `./`/`../`-prefixed path
/// resolve.rs's relative-import matching already understands (the same
/// mechanism it uses for Rust's `super::`/`self::`). One leading dot is the
/// current package (`./`); each additional dot climbs one more directory
/// (`../`).
fn python_relative_import_path(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let dots = node
        .children()
        .find(|c| c.kind() == "import_prefix")
        .map(|c| c.text().chars().filter(|&ch| ch == '.').count())
        .unwrap_or(0);
    let module = node
        .children()
        .find(|c| c.kind() == "dotted_name")
        .map(|c| c.text().replace('.', "/"))
        .unwrap_or_default();
    if dots == 0 {
        return module;
    }
    let mut prefix = "./".to_string();
    prefix.push_str(&"../".repeat(dots - 1));
    prefix.push_str(&module);
    prefix
}

/// The decorator expression text of a `decorator` node: the callee name for
/// a call-style decorator (`@app.route(...)` -> "app.route"), otherwise the
/// bare expression text (`@staticmethod` -> "staticmethod").
fn python_decorator_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let inner = node.children().find(|c| c.kind() != "@")?;
    if inner.kind() == "call" {
        inner.field("function").map(|f| f.text().into_owned())
    } else {
        Some(inner.text().into_owned())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::parse::parse_source;

    #[test]
    fn decorator_entity_carries_raw_text_and_owner() {
        let src = "@app.route(\"/x\")\ndef handler():\n    pass\n";
        let parsed = parse_source(&SupportLang::Python, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let decorators: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Decorator)
            .collect();
        assert_eq!(decorators.len(), 1, "entities: {entities:?}");
        assert_eq!(decorators[0].name, "app.route");
        assert_eq!(decorators[0].enclosing_function.as_deref(), Some("handler"));
    }

    #[test]
    fn method_in_class_records_owning_type_and_module_function_does_not() {
        let src = "class EventBus:\n    def on(self):\n        pass\n\ndef helper():\n    pass\n";
        let parsed = parse_source(&SupportLang::Python, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let on = entities
            .iter()
            .find(|e| e.kind == EntityKind::Function && e.name == "on")
            .expect("method `on` extracted");
        assert_eq!(
            on.owner_type.as_deref(),
            Some("EventBus"),
            "class method must record its owning type: {entities:?}"
        );

        let helper = entities
            .iter()
            .find(|e| e.kind == EntityKind::Function && e.name == "helper")
            .expect("module function `helper` extracted");
        assert_eq!(
            helper.owner_type, None,
            "module-level function has no owning type: {entities:?}"
        );
    }

    #[test]
    fn lambdas_are_callable_boundaries() {
        let parsed = parse_source(
            &SupportLang::Python,
            "def outer():\n    callback = lambda: remote()\n",
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
    fn complexity_events_cover_python_decisions() {
        let src = r#"
def f(items, ready, fallback):
    values = [item for item in items if item and ready or fallback]
    if ready:
        return values
    elif fallback:
        return []
    else:
        return [None]
    match values:
        case []:
            return []
        case [first, *_]:
            return [first]
"#;
        let parsed = parse_source(&SupportLang::Python, src);
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
        assert!(flows.contains(&"else_branch"), "entities: {entities:?}");
        assert!(
            flows.contains(&"match_expression"),
            "entities: {entities:?}"
        );
        assert_eq!(flows.iter().filter(|name| **name == "match_arm").count(), 2);
        assert_eq!(
            flows
                .iter()
                .filter(|name| **name == "comprehension_for")
                .count(),
            1
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| **name == "comprehension_if")
                .count(),
            1
        );
        assert_eq!(
            flows.iter().filter(|name| **name == "if_statement").count(),
            1
        );
    }

    #[test]
    fn legacy_nesting_spans_the_full_if_alternative_chain() {
        let src = "def branch_depth(outer, flag, first, second, deeper, items):\n    if outer:\n        if flag:\n            pass\n        elif first:\n            if deeper:\n                pass\n        elif second:\n            for item in items:\n                pass\n        else:\n            while outer:\n                pass\n";
        let parsed = parse_source(&SupportLang::Python, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let branch = crate::complexity::function_complexities(&entities)
            .into_iter()
            .find(|metric| metric.name == "branch_depth")
            .expect("branch_depth metrics");
        // Installed pre-change varde: cyclomatic/max_nesting = 8/2.
        assert_eq!((branch.cyclomatic, branch.max_nesting), (8, 2));

        let alternative_markers: Vec<_> = entities
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow
                    && entity.name == "legacy_nesting"
                    && entity.enclosing_function.as_deref() == Some("branch_depth")
                    && src[entity.span.start_byte as usize..].starts_with("elif")
            })
            .collect();
        assert_eq!(alternative_markers.len(), 1);
        assert_eq!(
            &src[alternative_markers[0].span.start_byte as usize
                ..alternative_markers[0].span.end_byte as usize],
            "elif first:\n            if deeper:\n                pass\n        elif second:\n            for item in items:\n                pass\n        else:\n            while outer:\n                pass"
        );
    }

    #[test]
    fn legacy_nesting_preserves_single_flow_if_consequence() {
        let src = "def nested_loop(ready, items):\n    if ready:\n        for item in items:\n            pass\n\ndef nested_if(outer, inner):\n    if outer:\n        if inner:\n            pass\n";
        let parsed = parse_source(&SupportLang::Python, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let metrics = crate::complexity::function_complexities(&entities);
        let nested_loop = metrics
            .iter()
            .find(|metric| metric.name == "nested_loop")
            .expect("nested_loop metrics");
        let nested_if = metrics
            .iter()
            .find(|metric| metric.name == "nested_if")
            .expect("nested_if metrics");
        // Installed pre-change varde: both functions have cyclomatic/max_nesting = 3/1.
        assert_eq!((nested_loop.cyclomatic, nested_loop.max_nesting), (3, 1));
        assert_eq!((nested_if.cyclomatic, nested_if.max_nesting), (3, 1));

        let marker = entities
            .iter()
            .find(|entity| {
                entity.kind == EntityKind::ControlFlow
                    && entity.name == "legacy_nesting"
                    && entity.enclosing_function.as_deref() == Some("nested_loop")
            })
            .expect("legacy if-span marker");
        assert_eq!(
            &src[marker.span.start_byte as usize..marker.span.end_byte as usize],
            "if ready:\n        for item in items:\n            pass"
        );
    }

    #[test]
    fn comprehension_flows_do_not_duplicate_legacy_nesting() {
        let src = "def nested_comprehension(xs):\n    return [x for x in (y for y in xs)]\n";
        let parsed = parse_source(&SupportLang::Python, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let nested = crate::complexity::function_complexities(&entities)
            .into_iter()
            .find(|metric| metric.name == "nested_comprehension")
            .expect("nested_comprehension metrics");
        // Installed pre-change varde: cyclomatic/max_nesting = 3/1.
        assert_eq!((nested.cyclomatic, nested.max_nesting), (3, 1));

        let comp_spans: Vec<_> = entities
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "comprehension_for"
            })
            .map(|entity| entity.span)
            .collect();
        assert_eq!(comp_spans.len(), 2);
        let legacy_markers: Vec<_> = entities
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "legacy_nesting"
            })
            .collect();
        assert!(
            legacy_markers
                .iter()
                .all(|marker| !comp_spans.contains(&marker.span)),
            "comprehension spans must have one legacy event: {entities:?}"
        );
    }
}

/// Match containers add one cognitive point; their arms retain legacy branches.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[
    (
        "match_expression",
        crate::complexity::FlowRole::DecisionContainer,
    ),
    ("comprehension_for", crate::complexity::FlowRole::LegacyOnly),
    ("comprehension_if", crate::complexity::FlowRole::LegacyOnly),
];

/// Collect Python declarations and same-file call references for recursion.
pub fn match_callees(
    root: &super::ParsedNode<'_>,
) -> (
    Vec<crate::extract::recursion::Callable>,
    Vec<crate::extract::recursion::CalleeReference>,
) {
    use crate::extract::recursion::{Callable, CalleeReference, Qualifier};

    let declarations: Vec<_> = root
        .dfs()
        .filter(|node| node.kind() == "function_definition")
        .collect();
    let callables: Vec<_> = declarations
        .iter()
        .filter_map(|node| {
            let name_node = node.field("name")?;
            let name = name_node.text().into_owned();
            let parameters = node.field("parameters");
            let parameter_nodes: Vec<_> = parameters
                .map(|list| {
                    list.children()
                        .filter(|child| is_python_parameter(child.kind().as_ref()))
                        .collect()
                })
                .unwrap_or_default();
            let lexical_parent = node
                .ancestors()
                .find(|ancestor| ancestor.kind() == "function_definition")
                .and_then(|ancestor| ancestor.field("name"))
                .map(|name| name.text().into_owned());
            let owner_type = enclosing_type_name(node);
            let mut callable_parameters = parameter_nodes.as_slice();
            if lexical_parent.is_none()
                && owner_type.is_some()
                && callable_parameters
                    .first()
                    .and_then(python_parameter_name)
                    .is_some_and(|name| matches!(name.as_str(), "self" | "cls"))
            {
                callable_parameters = &callable_parameters[1..];
            }
            let required_args = callable_parameters
                .iter()
                .filter(|parameter| !parameter.kind().as_ref().contains("default"))
                .count();
            let owner = lexical_parent.clone().or_else(|| owner_type.clone());
            Some(Callable {
                owner,
                owner_type,
                unqualified_callable: lexical_parent.is_some() || owner_type_is_none(node),
                name,
                required_args: u16::try_from(required_args).unwrap_or(u16::MAX),
                total_args: u16::try_from(callable_parameters.len()).unwrap_or(u16::MAX),
                file_id: 0,
                span: crate::extract::span_of(node),
                name_span: crate::extract::span_of(&name_node),
            })
        })
        .collect();

    let mut references = Vec::new();
    for call in root.dfs().filter(|node| node.kind() == "call") {
        let Some(caller_node) = call
            .ancestors()
            .find(|ancestor| ancestor.kind() == "function_definition")
        else {
            continue;
        };
        let Some(caller) = callables
            .iter()
            .position(|item| item.span == crate::extract::span_of(&caller_node))
        else {
            continue;
        };
        let Some(function) = call.field("function") else {
            continue;
        };
        let (name, qualifier) = match function.kind().as_ref() {
            "identifier" => (function.text().into_owned(), Qualifier::None),
            "attribute" => {
                let Some(method) = function.field("attribute") else {
                    continue;
                };
                let Some(receiver) = function.field("object") else {
                    continue;
                };
                let qualifier = if matches!(receiver.text().as_ref(), "self" | "cls") {
                    Qualifier::SelfLike
                } else {
                    Qualifier::Other
                };
                (method.text().into_owned(), qualifier)
            }
            _ => continue,
        };
        let argument_count = call
            .field("arguments")
            .map(|arguments| {
                arguments
                    .children()
                    .filter(|argument| argument.is_named() && argument.kind() != "comment")
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

fn is_python_parameter(kind: &str) -> bool {
    matches!(
        kind,
        "identifier"
            | "typed_parameter"
            | "default_parameter"
            | "typed_default_parameter"
            | "list_splat_pattern"
            | "dictionary_splat_pattern"
    )
}

fn python_parameter_name(
    parameter: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<String> {
    if parameter.kind() == "identifier" {
        return Some(parameter.text().into_owned());
    }
    parameter
        .field("name")
        .or_else(|| {
            parameter
                .children()
                .find(|child| child.kind() == "identifier")
        })
        .map(|name| name.text().into_owned())
}

fn owner_type_is_none(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    enclosing_type_name(node).is_none()
}

fn enclosing_type_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.ancestors()
        .find(|ancestor| ancestor.kind() == "class_definition")
        .and_then(|ancestor| ancestor.field("name"))
        .map(|name| name.text().into_owned())
}
