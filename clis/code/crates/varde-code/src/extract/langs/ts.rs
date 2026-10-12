//! TypeScript entity extraction (the reference implementation for the
//! coverage-parity checklist; JS/TSX share most of these node kinds).

use crate::extract::entity::{EntityMeta, ExtractCtx, entity};
use crate::extract::field_name;
use crate::extract::langs::{
    boolean_operator_name, chain_status, decorator_name, first_arg_text, push_type_ref,
    strip_generic_args, visit_do_statement,
};
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const TYPE_SCOPES: &[&str] = &["class_declaration", "interface_declaration"];

pub const FUNCTION_SCOPES: &[&str] = &[
    "function_declaration",
    "function_expression",
    "arrow_function",
    "generator_function",
    "method_definition",
    "generator_function_declaration",
];

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
    if visit_part_8(node, kind, ctx) {
        return;
    }
    if visit_part_9(node, kind, ctx) {
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
            let name = field_name(node).unwrap_or_default();
            push_named(node, EntityKind::Class, ctx);
            // `class Foo extends Base implements IFoo, IBar` — the grammar
            // gives `extends`/`implements` their own clauses under a
            // `class_heritage` wrapper, so no first-entry heuristic is
            // needed here (unlike C#/Swift).
            if let Some(heritage) = node.children().find(|c| c.kind() == "class_heritage") {
                if let Some(extends) = heritage.children().find(|c| c.kind() == "extends_clause")
                    && let Some(value) = extends.field("value")
                {
                    push_type_ref(
                        ctx,
                        EntityKind::Extends,
                        value.text().into_owned(),
                        &name,
                        &extends,
                    );
                }
                if let Some(implements) = heritage
                    .children()
                    .find(|c| c.kind() == "implements_clause")
                {
                    for ty in implements.children().filter(|c| c.is_named()) {
                        push_type_ref(
                            ctx,
                            EntityKind::Implements,
                            strip_generic_args(&ty.text()),
                            &name,
                            &implements,
                        );
                    }
                }
            }
            // `@Component class Foo {}` — decorator(s) attach as direct
            // children of class_declaration, preceding the `class` keyword.
            // `name` is the decorator expression text (callee for a call-style
            // decorator factory, otherwise the bare expression).
            ts_emit_decorators(node, &name, ctx);
            // `@Controller('x') export class Foo {}` — when the class is
            // exported, the grammar hangs the decorator off the wrapping
            // `export_statement`, not the `class_declaration`. Sweep the parent
            // too so an exported NestJS controller's decorators aren't dropped.
            if let Some(parent) = node.parent().filter(|p| p.kind() == "export_statement") {
                ts_emit_decorators(&parent, &name, ctx);
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
        "interface_declaration" => push_named(node, EntityKind::Interface, ctx),
        // `type X = ...` — a first-class TS type declaration (alias, union,
        // mapped type). Mapped to Interface (the closest structural type kind)
        // so it is queryable via `symbols_in_file`/`get_symbol`; previously
        // dropped entirely (audit S3: all 17 aliases in one file were missing).
        "type_alias_declaration" => push_named(node, EntityKind::Interface, ctx),
        // `enum X { ... }` / `const enum X { ... }` — a runtime object of named
        // members; mapped to Class so it surfaces as a declaration rather than
        // being dropped.
        "enum_declaration" => push_named(node, EntityKind::Class, ctx),
        // Class/interface methods — previously invisible to extraction (only
        // top-level `function_declaration` emitted a Function entity), so
        // class-membership queries (SOLID interface-coverage/fat-interface
        // rules) had no method to count. `owner_type` (set from `ctx.type_scope`
        // inside `entity()`/`push_named`) links each method back to its class.
        "method_definition" => {
            push_named(node, EntityKind::Function, ctx);
            // Method-level decorators (`@Get(':id')`, `@Post()`) — the NestJS
            // route verbs. Unlike class decorators these are *siblings* in the
            // `class_body` immediately preceding the `method_definition`, not
            // children, so walk the contiguous preceding `decorator` run.
            // Owner is the method's own name so `entrypoints` role-tags the
            // action and picks up its verb+path.
            if let Some(name) = field_name(node) {
                for decorator in node.prev_all().take_while(|c| c.kind() == "decorator") {
                    ts_emit_decorator(&decorator, &name, ctx);
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
    match kind {
        // Interface method member (`method_signature`, e.g. `foo(): void;`
        // inside `interface Foo { ... }`) — same class-membership need as
        // `method_definition`, just for the interface side of a
        // coverage/ISP comparison.
        "method_signature" => push_named(node, EntityKind::Function, ctx),
        // Class field/property (`email: string;`, `@Column() id: number;`) and
        // its interface counterpart (`property_signature`). Previously dropped,
        // so `symbols_in_file` showed no data model for a TS entity/DTO (audit:
        // TS class fields missing, unlike C#/Python). Emit a Variable — the
        // same kind C# fields use — so it surfaces as a declared member;
        // `ctx.push` stamps `owner_type` from the enclosing class scope.
        "public_field_definition" | "property_signature" => {
            let name = node
                .field("name")
                .or_else(|| node.children().find(|c| c.kind() == "property_identifier"))
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            if !name.is_empty() {
                ctx.push(EntityKind::Variable, name, node);
            }
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
        // ---- imports ----
        // `import ... from "spec"` -> one Import entity named after the
        // (unquoted) module specifier.
        "import_statement" => {
            let spec = node
                .field("source")
                .map(|n| super::unquote(n.text().as_ref(), true))
                .unwrap_or_default();
            let mut imp = entity(
                EntityKind::Import,
                spec,
                ctx.file_id,
                node,
                EntityMeta::default(),
            );
            // `import type { Foo } from "./bar"` (and `import type Foo from
            // ...`) is erased entirely at compile time — no runtime module
            // reference exists, so it can't produce a real load-order cycle.
            // `body_shape` is otherwise unused on Import entities (reused
            // here, not a new column); `circular_import.toml` excludes edges
            // tagged this way from the runtime import graph.
            if is_ts_type_only_import(node) {
                imp.body_shape = Some("type_only".to_string());
            }
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

fn visit_part_6(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    visit_part_6_a(node, kind, ctx) || visit_part_6_b(node, kind, ctx)
}

fn visit_part_6_a(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // Function/method parameters carry their identifier in the `pattern`
        // field (required_parameter / optional_parameter).
        "required_parameter" | "optional_parameter" => {
            let name = node
                .field("pattern")
                .map(|n| n.text().into_owned())
                .unwrap_or_default();
            ctx.push(EntityKind::Parameter, name, node);
        }
        _ => return false,
    }
    true
}

fn visit_part_6_b(
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

fn visit_part_7(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- expression-level kinds ----
        // Calls: callee text as name. Also the anchor for domain-specific
        // route/response detection.
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

fn visit_part_8(
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
        // Fixture-driven scoping decision: literals inside type annotations
        // (`predefined_type`) are not matched; literal *types* (`literal_type`)
        // do collide with expression literals and are currently included.
        "number" | "string" | "true" | "false" | "null" | "undefined" | "template_string"
        | "regex" => {
            // Literals inside type annotations (predefined_type, literal_type,
            // generic type args, ...) are types, not expression literals.
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
        // throw <expr> -> Throw, named after the thrown expression. The JS/TS
        // grammar gives throw_statement no field for the expression (it is a
        // bare seq('throw', $._expressions, ';')), so take the text after the
        // 'throw' keyword.
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

fn visit_part_9(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // Control flow: name = tree-sitter node kind (superset-safe minimal
        // shape per the plan: kind + span + enclosing linkage).
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
            is_async: (kind == EntityKind::Function)
                .then(|| super::super::langs::node_is_async(node)),
            owner_type: (kind == EntityKind::Function)
                .then_some(ctx.type_scope)
                .flatten()
                .map(|s| s.to_owned()),
            ..Default::default()
        },
    ));
}

/// Emit a `Decorator` entity for each `@decorator` child of `node`, owned by
/// `owner` (the decorated class or method name). Route decorators
/// (`@Controller('x')`, `@Get(':id')`) additionally carry the HTTP verb+path
/// so `entrypoints::detect` can surface the NestJS handler as a route.
fn ts_emit_decorators(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    owner: &str,
    ctx: &mut ExtractCtx,
) {
    for decorator in node.children().filter(|c| c.kind() == "decorator") {
        ts_emit_decorator(&decorator, owner, ctx);
    }
}

/// Emit one `Decorator` entity for a `decorator` node, owned by `owner`.
fn ts_emit_decorator(
    decorator: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    owner: &str,
    ctx: &mut ExtractCtx,
) {
    if let Some(dec_name) = decorator_name(decorator) {
        let (method, path) = ts_route_meta(decorator, &dec_name);
        ctx.out.push(Entity {
            kind: EntityKind::Decorator,
            name: dec_name,
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
}

/// Route `(method, path)` carried by a NestJS decorator, for stamping onto its
/// `Decorator` entity. Verb from the decorator name (`@Get` -> GET); a prefix
/// decorator (`@Controller('cats')`) contributes only its base path.
/// `(None, None)` for a non-route decorator (`@Injectable()`, ...).
fn ts_route_meta(
    decorator: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    dec_name: &str,
) -> (Option<String>, Option<String>) {
    let verb = super::http_verb_for_annotation(dec_name);
    if verb.is_none() && !super::is_route_prefix_annotation(dec_name) {
        return (None, None);
    }
    (
        verb.map(|v| v.to_string()),
        ts_decorator_first_string(decorator),
    )
}

/// First string-literal argument of a call-style decorator
/// (`@Get(':id')` -> `:id`), or `None` for a bare decorator / non-string arg.
fn ts_decorator_first_string(
    decorator: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<String> {
    let call = decorator
        .children()
        .find(|c| c.kind() == "call_expression")?;
    let arg = first_arg_text(&call)?;
    (arg.starts_with('"') || arg.starts_with('\'') || arg.starts_with('`'))
        .then(|| super::unquote(&arg, true))
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

// ---- domain-specific detection (Express-style call shapes) ----

const ROUTE_METHODS: &[&str] = &[
    "get", "post", "put", "patch", "delete", "options", "head", "all", "use",
];
const ROUTE_OBJECTS: &[&str] = &["app", "router"];
const RESPONSE_OBJECTS: &[&str] = &["res"];
const RESPONSE_VERBS: &[&str] = &["send", "json", "end", "render", "redirect", "sendFile"];

/// Express-style route registration: `app.get("/path", handler)` →
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
/// `res.status(200).json(...)` / `res.sendStatus(404)` →
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

/// Strip surrounding quotes/backticks from a string literal's text.
/// True for a top-level type-only import: `import type Foo from "..."` or
/// `import type { Foo } from "..."`. Named-specifier-level `import { type
/// Foo, bar } from "..."` (a mixed import) is intentionally NOT matched
/// here — that statement still has a real runtime module reference via
/// `bar`, so it can legitimately participate in a load-bearing cycle.
fn is_ts_type_only_import(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.children()
        .take_while(|c| c.kind().as_ref() != "import_clause")
        .any(|c| c.text().as_ref() == "type")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::parse::parse_source;

    #[test]
    fn extends_implements_entities_carry_raw_name_and_owner() {
        let src = "class Foo extends Base implements IFoo, IBar { }";
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
    fn generic_implements_supertype_names_are_stripped_to_bare_identifier() {
        // CORRECTNESS-002: `implements Comparable<Foo>` must yield
        // "Comparable", matching the `extends` branch's existing behavior
        // (which already excludes type_arguments via the grammar's `value`
        // field).
        let src = "class Foo implements Comparable<Foo> { }";
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let implements: Vec<&Entity> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Implements)
            .collect();
        assert_eq!(implements.len(), 1, "entities: {entities:?}");
        assert_eq!(implements[0].name, "Comparable");
    }

    #[test]
    fn generator_declarations_and_closures_have_callable_entities() {
        let src = r#"
            function* entries(): Iterable<string> { yield load(); }
            function outer() {
                const callback = () => remote();
                queue(function () { deferred(); });
                queue(function* () { yield later(); });
            }
        "#;
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
    fn complexity_events_cover_typescript_decisions() {
        let src = r#"
            function f(a: boolean, b: boolean, value: number): number {
                if (a && b || a) {} else if (b) {}
                switch (value) { case 1: break; default: break; }
                do {} while (a);
                return a ? 1 : 0;
            }
        "#;
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        let flows: Vec<&str> = entities
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        for expected in [
            "logical_and",
            "logical_or",
            "elseif_statement",
            "do_while_statement",
        ] {
            assert!(
                flows.contains(&expected),
                "missing {expected}: {entities:?}"
            );
        }
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
    fn type_aliases_and_enums_are_captured_as_declarations() {
        // Audit S3: `type X = ...` and `enum X {}` were dropped entirely, so
        // they never appeared in symbols_in_file/get_symbol. Aliases map to
        // Interface (type-level), enums to Class (runtime object of members).
        let src = "export type JsonValue = string | number;\ntype Mode = \"a\" | \"b\";\nexport enum Color { Red, Green }\n";
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let interfaces: Vec<&str> = entities
            .iter()
            .filter(|e| e.kind == EntityKind::Interface)
            .map(|e| e.name.as_str())
            .collect();
        assert!(
            interfaces.contains(&"JsonValue") && interfaces.contains(&"Mode"),
            "type aliases must be captured as Interface: {entities:?}"
        );
        assert!(
            entities
                .iter()
                .any(|e| e.kind == EntityKind::Class && e.name == "Color"),
            "enum must be captured as Class: {entities:?}"
        );
    }

    #[test]
    fn decorator_entity_carries_expression_text_and_owner() {
        let src = "@Component\nclass Foo {}";
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
    fn express_routes_accept_single_quoted_paths() {
        let src = "app.get('/users', listUsers);";
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        assert!(
            entities.iter().any(|entity| {
                entity.kind == EntityKind::Route
                    && entity.method.as_deref() == Some("get")
                    && entity.path.as_deref() == Some("/users")
                    && entity.owner_type.as_deref() == Some("listUsers")
            }),
            "single-quoted route missing: {entities:?}"
        );
    }

    /// Class fields (`public_field_definition`) and interface properties
    /// (`property_signature`) must be captured as `Variable` entities owned by
    /// their type — previously dropped, so a TS entity/DTO's data model was
    /// invisible to `symbols_in_file` (unlike C#/Python).
    #[test]
    fn ts_class_fields_and_interface_properties_captured() {
        let src = "export class User {\n  @Column()\n  email: string;\n  bio: string = \"\";\n}\ninterface Dto {\n  id: number;\n}\n";
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let field = |name: &str, owner: &str| {
            assert!(
                entities.iter().any(|e| e.kind == EntityKind::Variable
                    && e.name == name
                    && e.owner_type.as_deref() == Some(owner)),
                "field {name} of {owner} must be a Variable: {entities:?}"
            );
        };
        field("email", "User");
        field("bio", "User");
        field("id", "Dto");
    }

    /// NestJS: a decorator on an *exported* class hangs off the wrapping
    /// `export_statement` (not the `class_declaration`), and a *method*
    /// decorator is a preceding sibling in the class body (not a child). Both
    /// must be captured, and route decorators must carry verb+path.
    #[test]
    fn nestjs_exported_class_and_method_decorators_captured() {
        let src = "@Controller('cats')\nexport class CatsController {\n  @Get(':id')\n  findOne(id: string): string { return id; }\n}\n";
        let parsed = parse_source(&SupportLang::TypeScript, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;

        let dec = |name: &str| -> &Entity {
            entities
                .iter()
                .find(|e| e.kind == EntityKind::Decorator && e.name == name)
                .unwrap_or_else(|| panic!("decorator {name} missing: {entities:?}"))
        };
        let controller = dec("Controller");
        assert_eq!(
            controller.enclosing_function.as_deref(),
            Some("CatsController")
        );
        assert_eq!(controller.path.as_deref(), Some("cats"));
        let get = dec("Get");
        assert_eq!(get.enclosing_function.as_deref(), Some("findOne"));
        assert_eq!(get.method.as_deref(), Some("GET"));
        assert_eq!(get.path.as_deref(), Some(":id"));
    }

    #[test]
    fn complexity_metadata_covers_else_jumps_negation_and_compensation() {
        let src = r#"
            function events(a: boolean, b: boolean, c: boolean) {
                if (a) {} else {}
                outer: while (a) { break outer; }
                return a && !(b && c);
            }
            function declarative() { function child(a: boolean) { if (a) {} } }
            function assigned() { assigned.child = function (a: boolean) { if (a) {} }; }
            function callback(xs: boolean[]) { xs.forEach(x => { if (x) {} }); }
        "#;
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
        assert_eq!(markers.len(), 2, "{flows:?}");
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
            function direct(n: number) { return direct(n - 1); }
            function closure(n: number) { const next = () => closure(n - 1); return next(); }
            function cycle_a(n: number) { return cycle_b(n - 1); }
            function cycle_b(n: number) { return cycle_a(n - 1); }
            class SelfCall { method(n: number) { return this.method(n - 1); } }
            class OtherCall {
                method(other: {method: (n: number) => number}, n: number) {
                    return other.method(n - 1);
                }
            }
        "#;
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
        let src = "function f(a: boolean, b: boolean, c: boolean) { if (a) { if (b) { } } else if (b) { if (c) { } } else { if (a) { } } }";
        let parsed = parse_source(&SupportLang::TypeScript, src);
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
    match_callees_for_lang(root)
}

pub(super) fn match_callees_for_lang(
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
                                "required_parameter" | "optional_parameter" | "rest_pattern"
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
                        parameter.kind() != "optional_parameter"
                            && parameter.kind() != "rest_pattern"
                            && !parameter.text().contains('=')
                            && !parameter.text().contains('?')
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
