//! Elixir entity extraction.
//!
//! GRAMMAR SHAPE (tree-sitter-elixir): almost everything is a `call` node.
//! `defmodule`, `def`, `defp`, `defmacro`, `defprotocol`, `defimpl`,
//! `defstruct`, `import`, `alias`, `require`, `use`, `raise`, `throw`, and the
//! control-flow macros (`if`/`case`/`cond`/`for`/`with`/`receive`/`try`) are
//! all parsed as `call` nodes whose callee lives in the `target` field (an
//! `identifier`, or a `dot` for remote calls like `Enum.map`). The macro's
//! operands live in an `arguments` child. So `visit` matches `kind == "call"`
//! and dispatches on the callee identifier, Ruby-style (early-return per
//! branch), before falling back to a plain Call.
//!
//! SCOPE-STACKING CARVE-OUT: the walker (`crate::extract::walk`) stacks the
//! enclosing-function / owner-type scopes by matching `node.kind()` against
//! `FUNCTION_SCOPES` / `TYPE_SCOPES` and naming the scope via
//! `field_name(node)`. In Elixir `def` and `defmodule` share the single kind
//! `call`, so they CANNOT be distinguished by kind, and a `call` node has no
//! `name` field. Therefore both scope lists are **empty** and the generic
//! stack does not light up for Elixir; `enclosing_function` stays `None`.
//! `owner_type`, however, IS populated for functions: `visit_call` resolves
//! the enclosing `defmodule` by walking ancestors (see `enclosing_module_name`)
//! and stamps it on each `def`/`defp`, so `Foo.Bar.bar` records its owning
//! module even though the kind-keyed stack can't. Every entity kind is still
//! extracted.
//!
//! MAPPING (verified against a grammar dump):
//! - `def` / `defp` / `defmacro` -> Function. The function head is the first
//!   argument: a nested `call` (`bar(x, y)`) whose target identifier is the
//!   name and whose arguments are the Parameters, or a bare `identifier`
//!   (`def f`, no arg list) which is the name with no params.
//! - `defmodule` -> Class. Modules are Elixir's primary structural unit; Class
//!   is the closest kind. Name is the `alias` argument text (`Foo.Bar`).
//! - `defprotocol` -> Interface (a named behavioural contract). `defimpl A,
//!   for: B` -> Implements referencing the protocol `A`.
//! - `defstruct` -> Class (a module-level record definition). Named after the
//!   struct's field list text so it is non-empty and distinct.
//! - module attribute `@x value` (`unary_operator` `@` wrapping a `call`) ->
//!   Variable named `@x`. Covers `@moduledoc`, `@doc`, `@spec`, and plain
//!   module attributes uniformly (no allow-list; a Decorator mapping would
//!   need one and Elixir attributes aren't decorators).
//! - `import` / `alias` / `require` / `use` -> Import; spec is the module-path
//!   argument text (`A.B`). Branch and return early (not also a Call).
//! - local call `bar(x)` -> Call (callee identifier). Remote call `A.b(...)` /
//!   `x.field` (target is a `dot`) -> MemberAccess for the accessed member
//!   (the `dot`'s right identifier) AND a Call named the same.
//! - `=` match (`binary_operator` operator `=`) -> Variable for each
//!   identifier bound on the left pattern (tuple/list/bare).
//! - Parameter: identifiers in a function head's argument list.
//! - Literal: `integer` / `float` / `string` / `atom` / `boolean` / `nil` /
//!   `char` / `charlist`.
//! - `raise` / `throw` calls -> Throw (named after the first argument).
//! - `rescue_block` / `catch_block` (children of a `try` call) -> Catch.
//! - `if`/`unless`/`case`/`cond`/`for`/`with`/`receive`/`try` calls ->
//!   ControlFlow (named after the macro). Detected by callee identifier since
//!   they are `call` nodes, not dedicated kinds.
//! - Route: narrow Phoenix router shape — an HTTP-verb macro call whose first
//!   argument is a string path (`get "/users", Ctrl, :index`) -> Route. Clean
//!   in the grammar (callee identifier + leading `string` arg).
//!
//! CARVE-OUTS:
//! - Export: Elixir has no export statement; visibility is `def` (public) vs
//!   `defp` (private), not a declaration. Carved out.
//! - Response: Phoenix has no single response-DSL macro comparable to
//!   Sinatra's `json`/`erb` helpers (responses are conn-pipeline calls); no
//!   clean narrow shape, so Response is carved out. Route alone is included.

use crate::extract::entity::ExtractCtx;
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Empty: `def`/`defmodule` are both `call` kind and indistinguishable by
/// kind, and a `call` has no `name` field for the walker to stack. See the
/// module-doc scope-stacking carve-out.
pub const FUNCTION_SCOPES: &[&str] = &[];

/// Empty for the same reason as [`FUNCTION_SCOPES`].
pub const TYPE_SCOPES: &[&str] = &[];

/// Entity kinds the fixtures must produce. Export and Response are carved out
/// (see module docs); Interface via `defprotocol`, Route via Phoenix verbs.
pub const REQUIRED_KINDS: [EntityKind; 12] = [
    EntityKind::Function,
    EntityKind::Class,
    EntityKind::Interface,
    EntityKind::Variable,
    EntityKind::Parameter,
    EntityKind::Call,
    EntityKind::Literal,
    EntityKind::MemberAccess,
    EntityKind::Catch,
    EntityKind::Throw,
    EntityKind::ControlFlow,
    EntityKind::Route,
];

/// Macros that define a named function.
const FUNCTION_DEFS: &[&str] = &[
    "def",
    "defp",
    "defmacro",
    "defmacrop",
    "defguard",
    "defguardp",
];

/// Directive macros that name a module dependency instead of a normal call.
const IMPORT_DIRECTIVES: &[&str] = &["import", "alias", "require", "use"];

/// Control-flow macros (parsed as `call` nodes, dispatched by callee).
const CONTROL_FLOW: &[&str] = &[
    "if", "unless", "case", "cond", "for", "with", "receive", "try",
];

/// Phoenix router HTTP-verb macros: `get "/path", Ctrl, :action` -> Route.
const HTTP_VERBS: &[&str] = &["get", "post", "put", "patch", "delete", "options", "head"];

/// Semantic category for a plain-identifier call target.
enum NamedCallKind {
    FunctionDefinition,
    Module,
    Protocol,
    ProtocolImplementation,
    Struct,
    Import,
    Throw,
    Route,
    ControlFlow,
    Call,
}

/// Emit entities for one node (called for every node in the tree).
pub fn visit(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) {
    if visit_part_1(node, kind, ctx) {
        return;
    }
    let _ = visit_part_2(node, kind, ctx);
}

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        "anonymous_function" => {
            ctx.push_callable_boundary(node);
            if direct_stab_clause_count(node) > 1 {
                ctx.push(EntityKind::ControlFlow, "case".to_string(), node);
            }
        }
        // Every macro/definition/call is a `call` node — dispatch on callee.
        "call" => visit_call(node, ctx),
        // `@x value` module attribute -> Variable named `@x`.
        "unary_operator" => {
            if let Some(name) = module_attribute_name(node) {
                ctx.push(EntityKind::Variable, name, node);
            }
            if matches!(operator_text(node).as_deref(), Some("not" | "!")) {
                ctx.push(EntityKind::ControlFlow, "negation_break".to_string(), node);
            }
        }
        // `a = 1`, `{b, c} = {2, 3}` -> Variable per bound identifier. Other
        // binary operators (`+`, `<-`, `>`, ...) are ignored here.
        "binary_operator" => {
            if is_match_operator(node)
                && let Some(left) = node.field("left")
            {
                for name in pattern_identifiers(&left) {
                    ctx.push(EntityKind::Variable, name, node);
                }
            }
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
            if operator_text(node).as_deref() == Some("when") {
                ctx.push(
                    EntityKind::ControlFlow,
                    "elixir_guard_statement".to_string(),
                    node,
                );
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
        // Rescue/catch clauses are paths. `after` is cleanup only.
        "rescue_block" | "catch_block" if direct_stab_clause_count(node) == 0 => {
            ctx.push(EntityKind::Catch, node.kind().into_owned(), node);
        }
        "stab_clause" => match stab_context(node) {
            StabContext::Catch => {
                ctx.push(EntityKind::Catch, "catch_clause".to_string(), node);
            }
            StabContext::DecisionArm => {
                ctx.push(EntityKind::ControlFlow, "case_item".to_string(), node);
                if enclosing_control_flow(node).as_deref() == Some("cond") {
                    // `cond` is a sequence of guarded alternatives. Keep the
                    // existing case_item for cyclomatic compatibility and add
                    // a cognitive-only hybrid event for each condition.
                    ctx.push(
                        EntityKind::ControlFlow,
                        "cognitive_decision".to_string(),
                        node,
                    );
                    // The pre-change scorer treated case_item as a nesting
                    // parent. Preserve that effect for a nested decision in
                    // this cond alternative without changing legacy counts.
                    ctx.push(EntityKind::ControlFlow, "legacy_nesting".to_string(), node);
                } else if enclosing_control_flow(node).as_deref() == Some("receive") {
                    ctx.push(
                        EntityKind::ControlFlow,
                        "cognitive_decision".to_string(),
                        node,
                    );
                }
            }
            StabContext::Other => {}
        },
        "else_block" => {
            if let Some(control) = enclosing_control_flow(node)
                && matches!(control.as_str(), "if" | "unless" | "with")
                && !else_block_is_elseif(node)
            {
                // `else` is a hybrid branch but does not raise the nesting of
                // its body. The grammar exposes the whole else block, so trim
                // the event span to its four-character keyword.
                ctx.push(EntityKind::ControlFlow, "else_branch".to_string(), node);
                if let Some(flow) = ctx.out.last_mut() {
                    flow.span.end_byte = flow.span.start_byte.saturating_add(4);
                    flow.span.end_col = flow.span.start_col.saturating_add(4);
                }
            }
        }
        "keyword" if node.text().trim_start().starts_with("else:") => {
            if matches!(
                enclosing_control_flow(node).as_deref(),
                Some("if" | "unless")
            ) {
                ctx.push(EntityKind::ControlFlow, "else_branch".to_string(), node);
            }
        }
        // Literals.
        "integer" | "float" | "string" | "atom" | "boolean" | "nil" | "char" | "charlist" => {
            ctx.push(EntityKind::Literal, node.text().into_owned(), node);
        }
        _ => return false,
    }
    true
}

#[derive(Clone, Copy)]
enum StabContext {
    Catch,
    DecisionArm,
    Other,
}

fn stab_context(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> StabContext {
    for ancestor in node.ancestors() {
        match ancestor.kind().as_ref() {
            "rescue_block" | "catch_block" => return StabContext::Catch,
            "else_block" => return StabContext::DecisionArm,
            "anonymous_function" => {
                return if direct_stab_clause_count(&ancestor) > 1 {
                    StabContext::DecisionArm
                } else {
                    StabContext::Other
                };
            }
            "call" => {
                let target = ancestor.field("target").map(|target| target.text());
                return match target.as_deref() {
                    Some("case" | "cond" | "receive") => StabContext::DecisionArm,
                    _ => StabContext::Other,
                };
            }
            _ => {}
        }
    }
    StabContext::Other
}

fn direct_stab_clause_count(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> usize {
    node.children()
        .filter(|child| child.kind() == "stab_clause")
        .count()
}

fn enclosing_control_flow(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.ancestors()
        .find(|ancestor| ancestor.kind() == "call")
        .and_then(|call| {
            call.field("target")
                .map(|target| target.text().into_owned())
        })
}

/// Whether this `else` belongs to an `if`/`unless` whose only body expression
/// is another conditional. Such a nested conditional is an `else if` branch.
fn else_block_is_elseif(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let Some(parent_call) = node
        .parent()
        .filter(|parent| parent.kind() == "do_block")
        .and_then(|block| block.parent())
        .filter(|parent| parent.kind() == "call")
    else {
        return false;
    };
    let Some(target) = parent_call.field("target") else {
        return false;
    };
    if !matches!(target.text().as_ref(), "if" | "unless") {
        return false;
    }
    node.children()
        .find(|child| child.is_named())
        .filter(|first| first.kind() == "call")
        .and_then(|first| first.field("target"))
        .is_some_and(|target| matches!(target.text().as_ref(), "if" | "unless"))
}

fn is_elseif_call(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    if node.kind() != "call"
        || !node
            .field("target")
            .is_some_and(|target| matches!(target.text().as_ref(), "if" | "unless"))
    {
        return false;
    }
    node.ancestors().any(|ancestor| {
        ancestor.kind() == "else_block"
            && else_block_is_elseif(&ancestor)
            && ancestor
                .children()
                .any(|child| crate::extract::span_of(&child) == crate::extract::span_of(node))
    })
}

fn operator_text(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.field("operator")
        .map(|operator| operator.text().into_owned())
}

fn boolean_operator_name(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<&'static str> {
    match operator_text(node)?.as_str() {
        "&&" | "and" => Some("logical_and"),
        "||" | "or" => Some("logical_or"),
        _ => None,
    }
}

/// Handle a `call` node: definitions, imports, control-flow, raises, routes,
/// member access, and the plain call itself.
fn visit_call(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    let Some(target) = node.field("target") else {
        return;
    };

    // Remote call / field access: `Enum.map(...)`, `x.field` — target is a
    // `dot`. Handle member access + Call, then done.
    if target.kind() == "dot" {
        visit_remote_call(node, ctx, &target);
        return;
    }

    let callee = target.text().into_owned();
    visit_named_call(node, ctx, callee);
}

/// Emit member access and call entities for a remote target.
fn visit_remote_call(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    target: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) {
    if let Some(member) = dot_member(target) {
        ctx.push(EntityKind::MemberAccess, member.clone(), node);
        ctx.push(EntityKind::Call, member, node);
    }
}

/// Classify a plain call before extracting its entities.
fn named_call_kind(callee: &str) -> NamedCallKind {
    match callee {
        name if FUNCTION_DEFS.contains(&name) => NamedCallKind::FunctionDefinition,
        "defmodule" => NamedCallKind::Module,
        "defprotocol" => NamedCallKind::Protocol,
        "defimpl" => NamedCallKind::ProtocolImplementation,
        "defstruct" => NamedCallKind::Struct,
        name if IMPORT_DIRECTIVES.contains(&name) => NamedCallKind::Import,
        "raise" | "throw" => NamedCallKind::Throw,
        name if HTTP_VERBS.contains(&name) => NamedCallKind::Route,
        name if CONTROL_FLOW.contains(&name) => NamedCallKind::ControlFlow,
        _ => NamedCallKind::Call,
    }
}

/// Emit entities for a call whose target is a plain identifier.
fn visit_named_call(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    callee: String,
) {
    match named_call_kind(&callee) {
        NamedCallKind::FunctionDefinition => push_function_definition(node, ctx),
        NamedCallKind::Module => push_first_arg(ctx, EntityKind::Class, node),
        NamedCallKind::Protocol => push_first_arg(ctx, EntityKind::Interface, node),
        NamedCallKind::ProtocolImplementation => {
            push_owned(ctx, EntityKind::Implements, first_arg_or_empty(node), node);
        }
        NamedCallKind::Struct => {
            let name = first_arg_text(node).unwrap_or_else(|| "defstruct".to_string());
            ctx.push(EntityKind::Class, name, node);
        }
        NamedCallKind::Import => {
            if let Some(spec) = first_arg_text(node) {
                ctx.push(EntityKind::Import, spec, node);
            }
        }
        NamedCallKind::Throw => ctx.push(EntityKind::Throw, first_arg_or_empty(node), node),
        NamedCallKind::Route => push_route_or_call(node, ctx, callee),
        NamedCallKind::ControlFlow => {
            let is_elseif = is_elseif_call(node);
            let name = if is_elseif {
                "elseif_statement".to_string()
            } else {
                match callee.as_str() {
                    "cond" => "elixir_cond".to_string(),
                    "for" => "elixir_comprehension".to_string(),
                    "receive" => "elixir_receive".to_string(),
                    _ => callee,
                }
            };
            ctx.push(EntityKind::ControlFlow, name, node);
            if is_elseif {
                ctx.push(EntityKind::ControlFlow, "legacy_nesting".to_string(), node);
            }
        }
        NamedCallKind::Call => ctx.push(EntityKind::Call, callee, node),
    }
}

/// Emit a function and its parameters from a definition macro.
fn push_function_definition(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    let Some((name, head)) = function_head(node) else {
        return;
    };
    ctx.push(EntityKind::Function, name.clone(), node);

    // Generic scope stacking cannot distinguish `def` from `defmodule`.
    if let Some(owner) = enclosing_module_name(node)
        && let Some(function) = ctx.out.last_mut()
    {
        function.owner_type = Some(owner);
    }

    if has_sibling_function_clause(node, &name) {
        ctx.push(
            EntityKind::ControlFlow,
            "elixir_unknown_multi_clause_grouping".to_string(),
            node,
        );
    }

    if let Some(head) = head {
        for name in head_parameter_names(&head) {
            ctx.push(EntityKind::Parameter, name, node);
        }
    }
}

fn has_sibling_function_clause(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    name: &str,
) -> bool {
    node.parent().is_some_and(|parent| {
        parent
            .children()
            .filter(|sibling| sibling.kind() == "call")
            .filter(|sibling| {
                sibling
                    .field("target")
                    .is_some_and(|target| FUNCTION_DEFS.contains(&target.text().as_ref()))
            })
            .filter_map(|sibling| function_head(&sibling).map(|(sibling_name, _)| sibling_name))
            .filter(|sibling_name| sibling_name == name)
            .nth(1)
            .is_some()
    })
}

/// Emit an entity named by the call's first argument.
fn push_first_arg(
    ctx: &mut ExtractCtx,
    kind: EntityKind,
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) {
    ctx.push(kind, first_arg_or_empty(node), node);
}

/// Return the first argument text, or an empty fallback.
fn first_arg_or_empty(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    first_arg_text(node).unwrap_or_default()
}

/// Emit a Phoenix route, falling back to a normal call.
fn push_route_or_call(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    callee: String,
) {
    if let Some(path) = first_string_arg(node) {
        ctx.out.push(Entity {
            kind: EntityKind::Route,
            name: callee.clone(),
            file_id: ctx.file_id,
            span: crate::extract::span_of(node),
            enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
            method: Some(callee.to_uppercase()),
            path: Some(path),
            status: None,
            body_shape: None,
            body_minhash: None,
            is_async: None,
            is_test: false,
            owner_type: ctx.type_scope.map(|s| s.to_owned()),
        });
    } else {
        ctx.push(EntityKind::Call, callee, node);
    }
}

/// Push a type-reference entity (`Implements`) — Elixir has no owner-type
/// scope (see the module-doc carve-out), so `enclosing_function` is left None.
fn push_owned(
    ctx: &mut ExtractCtx,
    kind: EntityKind,
    name: String,
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) {
    ctx.out.push(Entity {
        kind,
        name,
        file_id: ctx.file_id,
        span: crate::extract::span_of(node),
        enclosing_function: None,
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

/// Name of the nearest enclosing `defmodule` (`Foo.Bar`) for a `def`/`defp`
/// node, or None at file top level. Elixir nests function definitions inside a
/// module's `do` block, so the owning module is an ancestor `call` whose
/// callee (`target`) is the `defmodule` macro; its first argument is the
/// module alias.
fn enclosing_module_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    node.ancestors()
        .filter(|a| a.kind() == "call")
        .find(|a| {
            a.field("target")
                .map(|t| t.text() == "defmodule")
                .unwrap_or(false)
        })
        .and_then(|m| first_arg_text(&m))
}

/// The `arguments` child of a `call` (`(x, y)` or a comma list), if present.
fn arguments<'t>(
    node: &ast_grep_core::Node<'t, StrDoc<SupportLang>>,
) -> Option<ast_grep_core::Node<'t, StrDoc<SupportLang>>> {
    node.children().find(|c| c.kind() == "arguments")
}

/// First positional argument node of a call (skipping `(` `,` `)` tokens).
fn first_arg<'t>(
    node: &ast_grep_core::Node<'t, StrDoc<SupportLang>>,
) -> Option<ast_grep_core::Node<'t, StrDoc<SupportLang>>> {
    arguments(node)?
        .children()
        .find(|c| !matches!(c.kind().as_ref(), "(" | "," | ")"))
}

/// Text of the first positional argument (`import Enum` -> "Enum").
fn first_arg_text(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    first_arg(node).map(|a| a.text().into_owned())
}

/// Inner text of the first string-literal argument (`get "/x"` -> "/x"),
/// joining `quoted_content` runs. `None` when the first arg is not a string.
fn first_string_arg(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let arg = first_arg(node)?;
    if arg.kind() != "string" {
        return None;
    }
    let mut out = String::new();
    for child in arg.children() {
        if child.kind() == "quoted_content" {
            out.push_str(child.text().as_ref());
        }
    }
    Some(out)
}

/// The right-hand member of a `dot` node (`Enum.map` -> "map", `x.field` ->
/// "field"): the `dot`'s `right` field, or the trailing identifier child.
fn dot_member(dot: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    if let Some(right) = dot.field("right") {
        return Some(right.text().into_owned());
    }
    dot.children()
        .filter(|c| matches!(c.kind().as_ref(), "identifier" | "alias"))
        .last()
        .map(|c| c.text().into_owned())
}

/// Function name + head node from a `def`/`defp`/... call. The first argument
/// is either a nested `call` (`bar(x, y)`) whose target identifier is the name
/// and whose arguments hold the parameters, or a bare `identifier` (`def f`)
/// which is the name with no head. Returns `(name, Some(head_call))` or
/// `(name, None)`.
#[allow(clippy::type_complexity)]
fn function_head<'t>(
    node: &ast_grep_core::Node<'t, StrDoc<SupportLang>>,
) -> Option<(String, Option<ast_grep_core::Node<'t, StrDoc<SupportLang>>>)> {
    let head = first_arg(node)?;
    match head.kind().as_ref() {
        "call" => {
            // `bar(x, y)` — name is the head call's target identifier.
            let name = head.field("target")?.text().into_owned();
            Some((name, Some(head)))
        }
        // `def f` — bare identifier name, no parameters. A guard head
        // (`def f(x) when ...`) is a `binary_operator`; fall through to its
        // left side (the actual call) if present.
        "identifier" => Some((head.text().into_owned(), None)),
        "binary_operator" => {
            let left = head.field("left")?;
            if left.kind() == "call" {
                let name = left.field("target")?.text().into_owned();
                Some((name, Some(left)))
            } else if left.kind() == "identifier" {
                Some((left.text().into_owned(), None))
            } else {
                None
            }
        }
        _ => None,
    }
}

/// Parameter identifier names inside a function head's `arguments` list.
/// Elixir params are patterns; collect the identifier leaves (skipping `_`).
fn head_parameter_names(head: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let Some(args) = arguments(head) else {
        return Vec::new();
    };
    let mut names = Vec::new();
    for child in args.children() {
        collect_pattern_idents(&child, &mut names);
    }
    names
}

/// Identifiers bound by a match's left pattern (`a`, or `b`/`c` in `{b, c}`).
fn pattern_identifiers(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names = Vec::new();
    collect_pattern_idents(node, &mut names);
    names
}

/// Recursively collect identifier leaves of a pattern, skipping the wildcard
/// `_` and pinned/typed decorations that aren't bindings. Bounded to a small
/// pattern subtree.
fn collect_pattern_idents(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    out: &mut Vec<String>,
) {
    match node.kind().as_ref() {
        "identifier" => {
            let t = node.text().into_owned();
            if t != "_" && !t.starts_with('_') {
                out.push(t);
            }
        }
        // Delimiters / keyword syntax — recurse into structural children.
        "(" | ")" | "," | "{" | "}" | "[" | "]" | "keyword" => {}
        _ => {
            for child in node.children() {
                collect_pattern_idents(&child, out);
            }
        }
    }
}

/// Name of a module attribute `unary_operator` (`@x value` -> "@x", `@moduledoc`
/// -> "@moduledoc"). Returns `None` for non-`@` unary operators (`-x`, `&f`).
fn module_attribute_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let op = node.field("operator")?;
    if op.text() != "@" {
        return None;
    }
    // The operand is a `call` whose target identifier is the attribute name,
    // or a bare identifier (`@x` with no value).
    let operand = node
        .children()
        .find(|c| matches!(c.kind().as_ref(), "call" | "identifier"))?;
    let name = if operand.kind() == "call" {
        operand.field("target")?.text().into_owned()
    } else {
        operand.text().into_owned()
    };
    Some(format!("@{name}"))
}

/// True when a `binary_operator` is a match (`=`) binding.
fn is_match_operator(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.field("operator").is_some_and(|o| o.text() == "=")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::model::Entity;
    use crate::parse::parse_source;

    fn entities(src: &str) -> Vec<Entity> {
        let parsed = parse_source(&SupportLang::Elixir, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        extract::extract(&parsed, 0).entities
    }

    fn find<'a>(es: &'a [Entity], kind: EntityKind, name: &str) -> Option<&'a Entity> {
        es.iter().find(|e| e.kind == kind && e.name == name)
    }

    #[test]
    fn defmodule_is_class_and_def_is_function_with_params() {
        let es = entities("defmodule Foo.Bar do\n  def bar(x, y) do\n    x + y\n  end\nend\n");
        assert!(find(&es, EntityKind::Class, "Foo.Bar").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Function, "bar").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Parameter, "x").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Parameter, "y").is_some(), "{es:?}");
    }

    #[test]
    fn function_records_enclosing_module_as_owner_type() {
        // A `def`/`defp` inside `defmodule Foo.Bar` records that module as its
        // `owner_type`. Elixir's `def`/`defmodule` are both `call` kind, so the
        // generic type-scope stack can't supply this — it's resolved by walking
        // ancestors to the enclosing `defmodule`.
        let es =
            entities("defmodule Foo.Bar do\n  def bar(x), do: x\n  defp helper(z), do: z\nend\n");
        assert_eq!(
            find(&es, EntityKind::Function, "bar")
                .expect("bar present")
                .owner_type
                .as_deref(),
            Some("Foo.Bar"),
            "def must carry its enclosing module: {es:?}"
        );
        assert_eq!(
            find(&es, EntityKind::Function, "helper")
                .expect("helper present")
                .owner_type
                .as_deref(),
            Some("Foo.Bar"),
            "defp must carry its enclosing module: {es:?}"
        );
    }

    #[test]
    fn defp_and_no_arg_def_extract() {
        let es = entities("defmodule M do\n  defp helper(z), do: z\n  def f, do: 1\nend\n");
        assert!(
            find(&es, EntityKind::Function, "helper").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Parameter, "z").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Function, "f").is_some(), "{es:?}");
    }

    #[test]
    fn import_directives_become_imports_not_calls() {
        let es = entities(
            "defmodule M do\n  import Enum\n  alias A.B\n  require Logger\n  use GenServer\nend\n",
        );
        assert!(find(&es, EntityKind::Import, "Enum").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Import, "A.B").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Import, "Logger").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Import, "GenServer").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Call, "import").is_none(), "{es:?}");
    }

    #[test]
    fn remote_call_emits_member_access_and_call() {
        let es = entities("defmodule M do\n  def f(x) do\n    Enum.map(x, x)\n  end\nend\n");
        assert!(
            find(&es, EntityKind::MemberAccess, "map").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Call, "map").is_some(), "{es:?}");
    }

    #[test]
    fn match_binding_and_literals() {
        let es = entities(
            "defmodule M do\n  def f do\n    a = 1\n    {b, c} = {2, 3}\n    s = \"hi\"\n    at = :ok\n  end\nend\n",
        );
        assert!(find(&es, EntityKind::Variable, "a").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "b").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Variable, "c").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Literal, "1").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Literal, ":ok").is_some(), "{es:?}");
    }

    #[test]
    fn module_attribute_is_variable() {
        let es = entities("defmodule M do\n  @answer 42\n  @moduledoc \"docs\"\nend\n");
        assert!(
            find(&es, EntityKind::Variable, "@answer").is_some(),
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::Variable, "@moduledoc").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn control_flow_and_throw_and_catch() {
        let es = entities(
            "defmodule M do\n  def f(x) do\n    if x, do: 1\n    case x do\n      _ -> :ok\n    end\n    try do\n      raise \"boom\"\n    rescue\n      e -> e\n    end\n  end\nend\n",
        );
        assert!(find(&es, EntityKind::ControlFlow, "if").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::ControlFlow, "case").is_some(),
            "{es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "try").is_some(),
            "{es:?}"
        );
        assert!(
            es.iter().any(|e| e.kind == EntityKind::Throw),
            "expected a Throw: {es:?}"
        );
        assert!(
            es.iter().any(|e| e.kind == EntityKind::Catch),
            "expected a Catch: {es:?}"
        );
    }

    #[test]
    fn protocol_impl_and_phoenix_route() {
        let es = entities(
            "defprotocol Size do\n  def size(data)\nend\ndefimpl Size, for: BitString do\n  def size(s), do: 1\nend\ndefmodule R do\n  get \"/users\", UserController, :index\nend\n",
        );
        assert!(find(&es, EntityKind::Interface, "Size").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Implements, "Size").is_some(),
            "{es:?}"
        );
        let route = es
            .iter()
            .find(|e| e.kind == EntityKind::Route)
            .expect("route entity");
        assert_eq!(route.method.as_deref(), Some("GET"));
        assert_eq!(route.path.as_deref(), Some("/users"));
    }

    #[test]
    fn anonymous_functions_are_callable_boundaries() {
        let es = entities(
            "defmodule M do\n  def outer do\n    callback = fn -> remote() end\n  end\nend\n",
        );
        assert_eq!(
            es.iter()
                .filter(|e| e.kind == EntityKind::CallableBoundary)
                .count(),
            1,
            "{es:?}"
        );
    }

    #[test]
    fn complexity_events_cover_booleans_arms_guards_catches_and_lambdas() {
        let es = entities(
            "defmodule M do\n  def classify(x) when x > 0 do\n    case x do\n      0 -> :zero\n      n when n > 1 -> :many\n      _ -> :other\n    end\n    cond do\n      x < 0 -> :negative\n      true -> :positive\n    end\n    try do\n      work()\n    rescue\n      RuntimeError -> :runtime\n      _ -> :other\n    catch\n      :throw, reason -> reason\n    after\n      cleanup()\n    end\n    callback = fn\n      value -> value\n      value when value > 0 -> value\n    end\n    x && ready or fallback\n  end\nend\n",
        );
        let flow_names: Vec<&str> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert!(flow_names.contains(&"logical_and"), "events: {es:?}");
        assert!(flow_names.contains(&"logical_or"), "events: {es:?}");
        assert_eq!(
            flow_names
                .iter()
                .filter(|name| **name == "case_item")
                .count(),
            7,
            "events: {es:?}"
        );
        assert_eq!(
            flow_names
                .iter()
                .filter(|name| **name == "elixir_guard_statement")
                .count(),
            3,
            "events: {es:?}"
        );
        assert_eq!(
            es.iter()
                .filter(|entity| entity.kind == EntityKind::Catch)
                .count(),
            3,
            "events: {es:?}"
        );
        assert_eq!(
            es.iter()
                .filter(|entity| entity.kind == EntityKind::CallableBoundary)
                .count(),
            1,
            "events: {es:?}"
        );
    }

    #[test]
    fn plain_else_and_else_if_are_distinct_hybrid_events() {
        let es = entities(
            "defmodule M do\n  def f(a, b) do\n    if a do\n      :a\n    else\n      if b do\n        :b\n      else\n        :other\n      end\n    end\n  end\nend\n",
        );
        let names: Vec<_> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();
        assert_eq!(names.iter().filter(|name| **name == "if").count(), 1);
        assert_eq!(
            names
                .iter()
                .filter(|name| **name == "elseif_statement")
                .count(),
            1
        );
        assert_eq!(
            names.iter().filter(|name| **name == "else_branch").count(),
            1
        );
        let elseif = es
            .iter()
            .find(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "elseif_statement"
            })
            .unwrap();
        let legacy_nesting = es
            .iter()
            .find(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "legacy_nesting"
            })
            .unwrap();
        assert_eq!(legacy_nesting.span, elseif.span);
        let metric = crate::complexity::function_complexities(&es)
            .into_iter()
            .find(|metric| metric.name == "f")
            .unwrap();
        assert_eq!(metric.cognitive, 3);
        assert_eq!(metric.max_nesting, 1);
    }

    #[test]
    fn cond_alternative_preserves_legacy_nesting_for_nested_if() {
        let es = entities(
            "defmodule M do\n  def f(value) do\n    cond do\n      value == :first -> :one\n      value == :second -> if(value, do: :nested)\n      true -> :other\n    end\n  end\nend\n",
        );
        let metric = crate::complexity::function_complexities(&es)
            .into_iter()
            .find(|metric| metric.name == "f")
            .unwrap();

        assert_eq!(metric.max_nesting, 1);
        assert!(es.iter().any(|entity| {
            entity.kind == EntityKind::ControlFlow
                && entity.name == "legacy_nesting"
                && entity.span.start_line == 5
        }));
    }

    #[test]
    fn legacy_guard_keeps_prechange_nesting_but_scores_no_cognitive_point() {
        let es = entities(
            "defmodule M do\n  def f(flag, value) do\n    if flag do\n      case value do\n        n when n > 0 -> n\n        _ -> 0\n      end\n    end\n  end\nend\n",
        );
        let metric = crate::complexity::function_complexities(&es)
            .into_iter()
            .find(|metric| metric.name == "f")
            .unwrap();
        assert_eq!(metric.cognitive, 3);
        assert_eq!(metric.max_nesting, 2);
        assert_eq!(
            crate::complexity::control_flow_role("elixir_guard_statement"),
            crate::complexity::FlowRole::LegacyOnly
        );
    }

    #[test]
    fn each_recursive_function_clause_gets_its_own_marker() {
        let es = entities(
            "defmodule M do\n  def choose(0), do: choose(1)\n  def choose(value), do: choose(value - 1)\nend\n",
        );
        let metrics: Vec<_> = crate::complexity::function_complexities(&es)
            .into_iter()
            .filter(|metric| metric.name == "choose")
            .collect();

        assert_eq!(metrics.len(), 2, "metrics: {metrics:?}");
        assert!(metrics.iter().all(|metric| {
            metric.confidence == crate::complexity::ComplexityConfidence::High
                && metric.cognitive == 1
        }));
        assert_eq!(
            es.iter()
                .filter(|entity| entity.kind == EntityKind::ControlFlow
                    && entity.name == "recursive_call")
                .count(),
            2,
            "each clause receives its own recursion marker: {es:?}"
        );
    }

    #[test]
    fn multi_clause_legacy_rows_are_ignored_without_losing_file_complexity() {
        let es = entities(
            "defmodule M do\n  def choose(0), do: :zero\n  def choose(value), do: value\nend\n",
        );
        let legacy_rows: Vec<_> = es
            .iter()
            .filter(|entity| {
                entity.kind == EntityKind::ControlFlow
                    && entity.name == "elixir_unknown_multi_clause_grouping"
            })
            .collect();

        assert_eq!(legacy_rows.len(), 2, "entities: {es:?}");
        assert!(legacy_rows.iter().all(|entity| {
            crate::complexity::control_flow_role(&entity.name)
                == crate::complexity::FlowRole::Ignored
                && crate::complexity::counts_toward_file_complexity(entity)
        }));
    }
}

/// Language-specific flow-role overrides, extended by language tasks.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[
    ("elixir_cond", crate::complexity::FlowRole::Ignored),
    (
        "elixir_comprehension",
        crate::complexity::FlowRole::LegacyOnly,
    ),
    (
        "elixir_guard_statement",
        crate::complexity::FlowRole::LegacyOnly,
    ),
    ("elixir_receive", crate::complexity::FlowRole::Else),
    (
        "elixir_unknown_multi_clause_grouping",
        crate::complexity::FlowRole::Ignored,
    ),
];

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
        .filter(|node| {
            node.kind() == "call"
                && node
                    .field("target")
                    .is_some_and(|target| FUNCTION_DEFS.contains(&target.text().as_ref()))
        })
        .collect();
    let callables: Vec<_> = declarations
        .iter()
        .filter_map(|node| {
            let (name, head) = function_head(node)?;
            let owner_type = enclosing_module_name(node);
            let parameters: Vec<_> = head
                .as_ref()
                .and_then(arguments)
                .map(|args| args.children().filter(|child| child.is_named()).collect())
                .unwrap_or_default();
            let total_args = u16::try_from(parameters.len()).unwrap_or(u16::MAX);
            let required_args = u16::try_from(
                parameters
                    .iter()
                    .filter(|parameter| {
                        !parameter
                            .field("operator")
                            .is_some_and(|operator| operator.text() == "\\\\")
                            && !parameter.text().contains("\\\\")
                    })
                    .count(),
            )
            .unwrap_or(u16::MAX);
            let name_node = head
                .as_ref()
                .and_then(|head| head.field("target"))
                .or_else(|| first_arg(node))?;
            Some(Callable {
                owner: owner_type.clone(),
                owner_type,
                unqualified_callable: true,
                name,
                required_args,
                total_args,
                file_id: 0,
                span: crate::extract::span_of(node),
                name_span: crate::extract::span_of(&name_node),
            })
        })
        .collect();

    let mut references = Vec::new();
    for call in root.dfs().filter(|node| node.kind() == "call") {
        let Some(caller_node) = call.ancestors().find(|ancestor| {
            ancestor.kind() == "call"
                && ancestor
                    .field("target")
                    .is_some_and(|target| FUNCTION_DEFS.contains(&target.text().as_ref()))
        }) else {
            continue;
        };
        let caller_span = crate::extract::span_of(&caller_node);
        let Some(caller) = callables.iter().position(|item| item.span == caller_span) else {
            continue;
        };
        let Some(target) = call.field("target") else {
            continue;
        };
        let head_span = function_head(&caller_node)
            .and_then(|(_, head)| head)
            .map(|head| crate::extract::span_of(&head));
        if head_span.is_some_and(|span| {
            span.start_byte <= crate::extract::span_of(&call).start_byte
                && crate::extract::span_of(&call).end_byte <= span.end_byte
        }) {
            continue;
        }
        let (name, qualifier, qualifier_name) = if target.kind() == "dot" {
            let Some(name) = dot_member(&target) else {
                continue;
            };
            let qualifier = target
                .field("left")
                .map(|left| left.text().into_owned())
                .unwrap_or_default();
            if matches!(qualifier.as_str(), "__MODULE__")
                || callables[caller].owner_type.as_deref() == Some(&qualifier)
            {
                (name, Qualifier::SelfLike, None)
            } else {
                (name, Qualifier::Other, None)
            }
        } else if target.kind() == "identifier" {
            (target.text().into_owned(), Qualifier::None, None)
        } else {
            continue;
        };
        let argument_count = arguments(&call)
            .map(|args| args.children().filter(|child| child.is_named()).count())
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
