//! Ruby entity extraction.
//!
//! Ruby-specific mapping notes (fixture-driven, superset-safe):
//! - `def` / `def self.` -> Function (`method` / `singleton_method`, name via
//!   field "name").
//! - `class` -> Class; a `superclass` (`< Base`) -> Extends.
//! - `module` -> Interface. Ruby has no interface keyword; modules are the
//!   mixin/shared-contract mechanism (`include`d into classes), so they map to
//!   the closest kind — Interface — rather than being conflated with Class.
//!   `include`/`prepend`/`extend M` -> Implements referencing the module.
//! - Variable: `assignment` whose `left` is an identifier / instance /
//!   class / global variable or a constant (`x = 1`, `@x = 1`, `CONST = 1`),
//!   plus each target of a multiple assignment.
//! - Parameter: names inside `method_parameters` / `block_parameters`
//!   (plain, optional/keyword `name` field, splat/block wrappers).
//! - Export: carved out — Ruby has no export statement (visibility is
//!   `private`/`public`, a runtime call, not a declaration).
//! - Call: `call` node; callee is the `method` field. A call with a `receiver`
//!   additionally emits MemberAccess (`msg.upcase` -> MemberAccess "upcase").
//! - Import: `require` / `require_relative` / `load` / `autoload` calls, spec
//!   taken from the string-literal argument (require_relative paths resolve
//!   against sibling files via resolve.rs's shared stem matching).
//! - Literal: integer/float/string/true/false/nil (Ruby has no type context to
//!   exclude).
//! - Catch/Throw: `rescue` (named after the exception variable) and
//!   `raise`/`fail` calls (named after the raised expression).
//! - ControlFlow: decisions, boolean sequences, case arms, statement
//!   modifiers, transfers, and the ternary.
//! - Route/Response: narrow Sinatra shape — an HTTP-verb call with a string
//!   path and a block (`get "/x" do … end`) -> Route; calls to Sinatra's
//!   response helpers (`json`, `erb`, `redirect`, `halt`, …) -> Response with
//!   body_shape set to the helper name.

use crate::extract::entity::ExtractCtx;
use crate::extract::field_name;
use crate::model::{Entity, EntityKind};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;

/// Node kinds that introduce a named function scope.
pub const FUNCTION_SCOPES: &[&str] = &["method", "singleton_method"];

/// Node kinds that introduce a named class/module type scope (for
/// `Entity::owner_type` linkage on methods).
pub const TYPE_SCOPES: &[&str] = &["class", "module", "singleton_class"];

/// Entity kinds the fixtures must produce. Export is carved out (see module
/// docs); Interface is expressed via `module`, Route/Response via Sinatra.
pub const REQUIRED_KINDS: [EntityKind; 13] = [
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
    EntityKind::Response,
];

/// HTTP-verb DSL methods that introduce a Sinatra route.
const HTTP_VERBS: &[&str] = &[
    "get", "post", "put", "patch", "delete", "options", "head", "link", "unlink",
];

/// Sinatra response-producing helpers -> body_shape is the helper name.
const RESPONSE_FUNCTIONS: &[&str] = &[
    "json",
    "erb",
    "haml",
    "slim",
    "erubis",
    "redirect",
    "halt",
    "send_file",
    "body",
];

/// Require-family methods that name a dependency instead of a normal call.
const REQUIRE_FUNCTIONS: &[&str] = &["require", "require_relative", "load", "autoload"];

/// Mixin methods that pull a module's behavior into the enclosing type.
const MIXIN_FUNCTIONS: &[&str] = &["include", "prepend", "extend"];

/// Attribute-macro calls that declare accessor methods over instance state.
const ATTR_FUNCTIONS: &[&str] = &["attr_accessor", "attr_reader", "attr_writer", "attr"];

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
    let _ = visit_part_4(node, kind, ctx);
}

fn visit_part_1(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    kind: &str,
    ctx: &mut ExtractCtx,
) -> bool {
    match kind {
        // ---- structural ----
        "method" | "singleton_method" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Function, name, node);
            if preserves_legacy_method_nesting(node) {
                ctx.push(EntityKind::ControlFlow, "legacy_nesting".to_string(), node);
            }
            if let Some(rescue) = first_implicit_rescue(node) {
                push_legacy_catch_marker(&rescue, ctx);
            }
        }
        "block" | "do_block" => ctx.push_callable_boundary(node),
        "class" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Class, name.clone(), node);
            // `class Sub < Base` -> one Extends entity for the superclass.
            if let Some(superclass) = node.field("superclass")
                && let Some(base) = superclass
                    .children()
                    .find(|c| matches!(c.kind().as_ref(), "constant" | "scope_resolution"))
            {
                push_owned(
                    ctx,
                    EntityKind::Extends,
                    base.text().into_owned(),
                    &name,
                    &base,
                );
            }
        }
        "module" => {
            let name = field_name(node).unwrap_or_default();
            ctx.push(EntityKind::Interface, name, node);
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
        // ---- variables ----
        "assignment" | "operator_assignment" => {
            if let Some(left) = node.field("left") {
                for name in assignment_target_names(&left) {
                    ctx.push(EntityKind::Variable, name, node);
                }
            }
        }
        // ---- parameters ----
        "method_parameters" | "block_parameters" | "lambda_parameters" => {
            for name in parameter_names(node) {
                ctx.push(EntityKind::Parameter, name, node);
            }
        }
        // ---- calls (imports / mixins / routes / raises / responses) ----
        "call" => visit_call(node, ctx),
        // ---- literals ----
        "integer" | "float" | "string" | "true" | "false" | "nil" => {
            ctx.push(EntityKind::Literal, node.text().into_owned(), node);
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
        // ---- control-flow / error ----
        "rescue" if node.get_inner_node().is_named() => {
            ctx.push(EntityKind::Catch, rescue_var(node), node);
        }
        "binary" => {
            if let Some(name) = boolean_operator_name(node) {
                ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            }
        }
        "elsif" => {
            if node.get_inner_node().is_named() {
                ctx.push(
                    EntityKind::ControlFlow,
                    "elseif_statement".to_string(),
                    node,
                );
                // The `elsif` hybrid contributes its own point and raises
                // nesting for its condition, but its consequence stays at
                // the root `if` branch depth (plan decision OQ5).
                if let (Some(condition), Some(event)) =
                    (node.field("condition"), ctx.out.last_mut())
                {
                    let span = crate::extract::span_of(&condition);
                    event.span.end_byte = span.end_byte;
                    event.span.end_line = span.end_line;
                    event.span.end_col = span.end_col;
                }
            }
        }
        "else"
            if node.ancestors().next().is_some_and(|parent| {
                matches!(parent.kind().as_ref(), "if" | "elsif" | "unless")
            }) =>
        {
            ctx.push(EntityKind::ControlFlow, "else_branch".to_string(), node);
            // Keep a hybrid `else` event on the keyword so the branch body
            // remains one level under its root `if`, as in the spec example.
            if let Some(event) = ctx.out.last_mut() {
                event.span.end_byte = event.span.start_byte + 4;
                event.span.end_col = event.span.start_col + 4;
            }
        }
        "when" => {
            if node.get_inner_node().is_named() {
                ctx.push(EntityKind::ControlFlow, "case_statement".to_string(), node);
            }
        }
        "begin" if node.get_inner_node().is_named() => {
            let name = if node
                .dfs()
                .any(|child| child.kind() == "rescue" && child.get_inner_node().is_named())
            {
                // Preserve the pre-change cyclomatic branch on rescue-bearing
                // begin constructs without assigning cognitive points to begin.
                "rescue_begin"
            } else {
                "begin"
            };
            ctx.push(EntityKind::ControlFlow, name.to_string(), node);
            if name == "rescue_begin" {
                let rescues: Vec<_> = node
                    .dfs()
                    .filter(|child| child.kind() == "rescue" && child.get_inner_node().is_named())
                    .collect();
                if rescues.len() > 1
                    && let Some(rescue) = rescues.first()
                {
                    push_legacy_catch_marker(&rescue, ctx);
                }
            }
        }
        "unary"
            if node
                .field("operator")
                .is_some_and(|operator| matches!(operator.text().as_ref(), "!" | "not")) =>
        {
            ctx.push(EntityKind::ControlFlow, "negation_break".to_string(), node);
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
        "if" | "unless" | "while" | "until" | "for" | "case" | "return" | "break" | "next"
        | "redo" | "retry" | "yield" | "if_modifier" | "unless_modifier" | "while_modifier"
        | "until_modifier" | "rescue_modifier" | "conditional"
            if node.get_inner_node().is_named() =>
        {
            ctx.push(EntityKind::ControlFlow, node.kind().into_owned(), node);
        }
        _ => return false,
    }
    true
}

fn boolean_operator_name(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) -> Option<&'static str> {
    match node.field("operator")?.text().as_ref() {
        "&&" | "and" => Some("logical_and"),
        "||" | "or" => Some("logical_or"),
        _ => None,
    }
}

/// Handle a `call` node: imports, mixins, routes, raises, response helpers,
/// member access, and the plain call itself.
fn visit_call(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>, ctx: &mut ExtractCtx) {
    let callee = call_name(node);
    if visit_special_call(node, ctx, &callee) {
        return;
    }
    visit_mixin(node, ctx, &callee);
    if node.field("receiver").is_some() {
        ctx.push(EntityKind::MemberAccess, callee.clone(), node);
    }
    if RESPONSE_FUNCTIONS.contains(&callee.as_str()) {
        push_response(node, ctx, &callee);
    }
    ctx.push(EntityKind::Call, callee, node);
}

/// Handle call forms which replace the ordinary Call entity.
fn visit_special_call(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    callee: &str,
) -> bool {
    // `require "json"` / `require_relative "helper"` -> Import (not a Call).
    if REQUIRE_FUNCTIONS.contains(&callee) {
        if let Some(spec) = first_string_arg(node) {
            ctx.push(EntityKind::Import, spec, node);
        }
        return true;
    }
    if ATTR_FUNCTIONS.contains(&callee) {
        for name in symbol_arg_names(node) {
            ctx.push(EntityKind::Variable, name, node);
        }
        return true;
    }
    if callee == "raise" || callee == "fail" {
        let name = first_arg(node)
            .map(|a| a.text().into_owned())
            .unwrap_or_default();
        ctx.push(EntityKind::Throw, name, node);
        return true;
    }
    if let Some((method, path)) = sinatra_route(node, callee) {
        ctx.out.push(Entity {
            kind: EntityKind::Route,
            name: callee.to_string(),
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
            owner_type: ctx.type_scope.map(|s| s.to_owned()),
        });
        return true;
    }
    false
}

/// Emit Ruby mixin relationships for class-scoped calls.
fn visit_mixin(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    callee: &str,
) {
    // `include Comparable` / `prepend M` / `extend M` -> Implements.
    if MIXIN_FUNCTIONS.contains(&callee)
        && let Some(arg) = first_arg(node)
        && matches!(arg.kind().as_ref(), "constant" | "scope_resolution")
        && let Some(owner) = ctx.type_scope
    {
        let owner = owner.to_owned();
        push_owned(
            ctx,
            EntityKind::Implements,
            arg.text().into_owned(),
            &owner,
            &arg,
        );
    }
}

/// Emit one response helper call with its shape metadata.
fn push_response(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
    callee: &str,
) {
    ctx.out.push(Entity {
        kind: EntityKind::Response,
        name: callee.to_string(),
        file_id: ctx.file_id,
        span: crate::extract::span_of(node),
        enclosing_function: ctx.enclosing.map(|s| s.to_owned()),
        method: None,
        path: None,
        status: None,
        body_shape: Some(callee.to_string()),
        body_minhash: None,
        is_async: None,
        is_test: false,
        owner_type: ctx.type_scope.map(|s| s.to_owned()),
    });
}

/// Push a type-reference entity (`Extends`/`Implements`) owned by `owner`.
fn push_owned(
    ctx: &mut ExtractCtx,
    kind: EntityKind,
    name: String,
    owner: &str,
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
) {
    ctx.out.push(Entity {
        kind,
        name,
        file_id: ctx.file_id,
        span: crate::extract::span_of(node),
        enclosing_function: Some(owner.to_string()),
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

/// Callee name of a `call`: the `method` field (present for both `foo(...)`
/// and `recv.foo`), falling back to the first identifier/constant child.
fn call_name(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    if let Some(m) = node.field("method") {
        return m.text().into_owned();
    }
    node.children()
        .find(|c| matches!(c.kind().as_ref(), "identifier" | "constant"))
        .map(|c| c.text().into_owned())
        .unwrap_or_default()
}

/// Names of the symbol arguments of a call (`attr_accessor :a, :b` -> `["a",
/// "b"]`), stripping the leading `:`. Non-symbol arguments (e.g. a string) are
/// skipped. Handles both `simple_symbol` (`:a`) and the rare `hash_key_symbol`.
fn symbol_arg_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let Some(args) = node.children().find(|c| c.kind() == "argument_list") else {
        return Vec::new();
    };
    args.children()
        .filter(|c| matches!(c.kind().as_ref(), "simple_symbol" | "hash_key_symbol"))
        .map(|c| c.text().trim_start_matches(':').to_string())
        .filter(|s| !s.is_empty())
        .collect()
}

/// First positional argument node of a call (skipping `(` `,` `)` tokens).
fn first_arg<'t>(
    node: &ast_grep_core::Node<'t, StrDoc<SupportLang>>,
) -> Option<ast_grep_core::Node<'t, StrDoc<SupportLang>>> {
    let args = node.children().find(|c| c.kind() == "argument_list")?;
    args.children()
        .find(|c| !matches!(c.kind().as_ref(), "(" | "," | ")"))
}

/// Content of the first string-literal argument of a call (`require "json"`
/// -> "json"). `None` when the first argument is not a string.
fn first_string_arg(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    string_content(&first_arg(node)?)
}

/// Inner text of a `string` node (`"json"` -> "json"), joining the literal
/// `string_content` runs and ignoring interpolations.
fn string_content(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    if node.kind() != "string" {
        return None;
    }
    let mut out = String::new();
    for child in node.children() {
        if child.kind() == "string_content" {
            out.push_str(child.text().as_ref());
        }
    }
    Some(out)
}

/// Names bound by an assignment's `left`: a single variable/constant target
/// or each element of a multiple-assignment list. Underscore is skipped.
fn assignment_target_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    fn is_target(kind: &str) -> bool {
        matches!(
            kind,
            "identifier" | "instance_variable" | "class_variable" | "global_variable" | "constant"
        )
    }
    let mut names = Vec::new();
    match node.kind().as_ref() {
        k if is_target(k) => {
            let t = node.text().into_owned();
            if t != "_" {
                names.push(t);
            }
        }
        "left_assignment_list" | "destructured_left_assignment" => {
            for child in node.children() {
                if is_target(child.kind().as_ref()) {
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

/// Parameter names inside a `method_parameters` / `block_parameters` node.
fn parameter_names(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Vec<String> {
    let mut names = Vec::new();
    for child in node.children() {
        let name = match child.kind().as_ref() {
            "identifier" => Some(child.text().into_owned()),
            "optional_parameter" | "keyword_parameter" => field_name(&child),
            "splat_parameter"
            | "hash_splat_parameter"
            | "block_parameter"
            | "forward_parameter" => child
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

/// Legacy Ruby metrics treat yielded blocks and method-level rescue bodies as
/// one nesting level below the method. The marker restores that parent depth
/// without changing cognitive scoring or file complexity.
fn preserves_legacy_method_nesting(method: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    method.dfs().any(|node| node.kind() == "yield") || first_implicit_rescue(method).is_some()
}

fn first_implicit_rescue<'a>(
    method: &ast_grep_core::Node<'a, StrDoc<SupportLang>>,
) -> Option<ast_grep_core::Node<'a, StrDoc<SupportLang>>> {
    method
        .dfs()
        .find(|rescue| rescue.get_inner_node().is_named() && is_implicit_rescue(rescue))
}

fn is_implicit_rescue(rescue: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    rescue.kind() == "rescue"
        && !rescue.ancestors().any(|ancestor| {
            ancestor.kind() == "rescue_modifier"
                || ancestor.kind() == "begin" && ancestor.text().trim_start().starts_with("begin")
        })
}

/// The exception variable of a `rescue` clause (`rescue E => err` -> "err"),
/// falling back to the rescued exception type, then "".
fn rescue_var(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    if let Some(var) = node
        .children()
        .find(|child| child.kind() == "exception_variable")
        && let Some(identifier) = var.children().find(|child| child.kind() == "identifier")
    {
        return identifier.text().into_owned();
    }
    node.children()
        .find(|child| child.kind() == "exceptions")
        .map(|child| child.text().into_owned())
        .unwrap_or_default()
}

fn push_legacy_catch_marker(
    rescue: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    ctx: &mut ExtractCtx,
) {
    ctx.push(EntityKind::Catch, "legacy_catch_clause".to_string(), rescue);
}

/// Sinatra route shape: an HTTP-verb call with a string path and a block
/// (`get "/users" do … end`). Returns (uppercased method, path).
fn sinatra_route(
    node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>,
    callee: &str,
) -> Option<(String, String)> {
    if !HTTP_VERBS.contains(&callee) {
        return None;
    }
    let has_block = node
        .children()
        .any(|c| matches!(c.kind().as_ref(), "do_block" | "block"));
    if !has_block {
        return None;
    }
    let path = string_content(&first_arg(node)?)?;
    Some((callee.to_uppercase(), path))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::extract;
    use crate::parse::parse_source;

    fn entities(src: &str) -> Vec<Entity> {
        let parsed = parse_source(&SupportLang::Ruby, src);
        assert!(!parsed.has_error(), "fixture must parse cleanly");
        extract::extract(&parsed, 0).entities
    }

    fn find<'a>(es: &'a [Entity], kind: EntityKind, name: &str) -> Option<&'a Entity> {
        es.iter().find(|e| e.kind == kind && e.name == name)
    }

    #[test]
    fn attr_macros_capture_one_variable_per_symbol_with_owner() {
        // Audit S3: attr_accessor/reader/writer were never captured.
        let es = entities(
            "class C\n  attr_accessor :params\n  attr_reader :entry, :name\n  attr_writer :content_type\nend\n",
        );
        for attr in ["params", "entry", "name", "content_type"] {
            let v = find(&es, EntityKind::Variable, attr)
                .unwrap_or_else(|| panic!("attr {attr} not captured: {es:?}"));
            assert_eq!(v.owner_type.as_deref(), Some("C"), "attr {attr} owner");
        }
        // The macro call itself must not also leak as a plain Call.
        assert!(
            find(&es, EntityKind::Call, "attr_accessor").is_none(),
            "{es:?}"
        );
    }

    #[test]
    fn module_maps_to_interface_and_include_to_implements() {
        let es = entities("module M\nend\nclass C\n  include M\nend\n");
        assert!(find(&es, EntityKind::Interface, "M").is_some(), "{es:?}");
        assert!(find(&es, EntityKind::Class, "C").is_some(), "{es:?}");
        let impl_m = find(&es, EntityKind::Implements, "M").expect("Implements M");
        assert_eq!(impl_m.enclosing_function.as_deref(), Some("C"));
    }

    #[test]
    fn superclass_maps_to_extends() {
        let es = entities("class Sub < Base\nend\n");
        let ext = find(&es, EntityKind::Extends, "Base").expect("Extends Base");
        assert_eq!(ext.enclosing_function.as_deref(), Some("Sub"));
    }

    #[test]
    fn require_relative_becomes_an_import_not_a_call() {
        let es = entities("require_relative \"helper\"\n");
        assert!(find(&es, EntityKind::Import, "helper").is_some(), "{es:?}");
        assert!(
            find(&es, EntityKind::Call, "require_relative").is_none(),
            "require should not also emit a Call: {es:?}"
        );
    }

    #[test]
    fn method_call_with_receiver_emits_member_access() {
        let es = entities("def f(x)\n  x.upcase\nend\n");
        assert!(
            find(&es, EntityKind::MemberAccess, "upcase").is_some(),
            "{es:?}"
        );
        assert!(find(&es, EntityKind::Call, "upcase").is_some(), "{es:?}");
    }

    #[test]
    fn raise_becomes_throw() {
        let es = entities("def f\n  raise ArgumentError, \"boom\"\nend\n");
        assert!(
            find(&es, EntityKind::Throw, "ArgumentError").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn sinatra_route_carries_method_and_path() {
        let es = entities("get \"/users\" do\n  json([])\nend\n");
        let route = es
            .iter()
            .find(|e| e.kind == EntityKind::Route)
            .expect("route entity");
        assert_eq!(route.method.as_deref(), Some("GET"));
        assert_eq!(route.path.as_deref(), Some("/users"));
        let resp = es
            .iter()
            .find(|e| e.kind == EntityKind::Response)
            .expect("response entity");
        assert_eq!(resp.body_shape.as_deref(), Some("json"));
    }

    #[test]
    fn blocks_are_callable_boundaries() {
        let es = entities("def outer\n  each { remote }\n  each do\n    remote\n  end\nend\n");
        assert_eq!(
            es.iter()
                .filter(|e| e.kind == EntityKind::CallableBoundary)
                .count(),
            2,
            "{es:?}"
        );
    }

    #[test]
    fn complexity_events_cover_ruby_decisions() {
        let es = entities(
            "def f(a, b, value)\n  if a && !(b || a)\n    1\n  elsif b\n    2\n  else\n    3\n  end\n  case value\n  when 1 then 1\n  when 2 then 2\n  else 0\n  end\nend\n",
        );
        let word_negation = entities("def f(a, b)\n  not (a && b)\nend\n");
        let flows: Vec<&str> = es
            .iter()
            .filter(|entity| entity.kind == EntityKind::ControlFlow)
            .map(|entity| entity.name.as_str())
            .collect();

        assert!(flows.contains(&"logical_and"), "entities: {es:?}");
        assert!(flows.contains(&"logical_or"), "entities: {es:?}");
        assert!(flows.contains(&"elseif_statement"), "entities: {es:?}");
        assert!(flows.contains(&"else_branch"), "entities: {es:?}");
        assert!(flows.contains(&"negation_break"), "entities: {es:?}");
        assert!(
            word_negation.iter().any(|entity| {
                entity.kind == EntityKind::ControlFlow && entity.name == "negation_break"
            }),
            "entities: {word_negation:?}"
        );
        assert_eq!(
            flows
                .iter()
                .filter(|name| **name == "case_statement")
                .count(),
            2,
            "entities: {es:?}"
        );
    }

    #[test]
    fn one_ruby_rescue_clause_emits_one_catch() {
        let es = entities(
            "def f\n  begin\n    work\n  rescue IOError, SystemCallError\n    recover\n    retry\n  ensure\n    cleanup\n  end\nend\n",
        );
        assert_eq!(
            es.iter()
                .filter(|entity| {
                    entity.kind == EntityKind::Catch && entity.name == "legacy_catch_clause"
                })
                .count(),
            0,
            "a semantic Catch already preserves this rescue's legacy branch: {es:?}"
        );
        assert!(
            es.iter().any(|entity| {
                entity.kind == EntityKind::Catch && entity.name != "legacy_catch_clause"
            }),
            "rescue clause retains its cognitive Catch event: {es:?}"
        );
        assert_eq!(
            crate::complexity::function_complexities(&es)[0].cognitive,
            1,
            "legacy event must not change rescue cognitive score: {es:?}"
        );
        assert!(
            find(&es, EntityKind::ControlFlow, "rescue_begin").is_some(),
            "{es:?}"
        );
    }

    #[test]
    fn legacy_yield_and_rescue_events_preserve_legacy_metrics() {
        let src = "def calls_zoo\n  done? ? cleanup_now : 0\n  helper unless finished?\n  compute rescue nil\n  yield\nend\n\ndef risky_io(path)\n  begin\n    File.read(path)\n  rescue ArgumentError => e\n    puts e\n  rescue TypeError\n    puts \"type\"\n  ensure\n    puts \"done\"\n  end\nend\n\ndef implicit_rescue\n  compute\nrescue StandardError\n  nil\nend\n";
        let es = entities(src);
        let metrics = crate::complexity::function_complexities(&es);
        let metric = |name| {
            metrics
                .iter()
                .find(|metric| metric.name == name)
                .unwrap_or_else(|| panic!("{name} metrics: {metrics:?}"))
        };

        // Installed pre-change varde: calls_zoo 5/1, risky_io 5/1,
        // implicit_rescue 3/1 (cyclomatic/max_nesting).
        assert_eq!(
            (
                metric("calls_zoo").cyclomatic,
                metric("calls_zoo").max_nesting
            ),
            (5, 1),
            "events: {es:?}"
        );
        assert_eq!(
            (
                metric("risky_io").cyclomatic,
                metric("risky_io").max_nesting,
            ),
            (5, 1)
        );
        assert_eq!(
            (
                metric("implicit_rescue").cyclomatic,
                metric("implicit_rescue").max_nesting,
            ),
            (3, 1)
        );
        assert_eq!(
            crate::complexity::control_flow_role("yield"),
            crate::complexity::FlowRole::LegacyOnly
        );
        assert_eq!(
            es.iter()
                .filter(|entity| {
                    entity.kind == EntityKind::Catch && entity.name == "legacy_catch_clause"
                })
                .count(),
            2,
            "one legacy event for each explicit rescue group and method-level rescue: {es:?}"
        );
        assert_eq!(
            es.iter()
                .filter(|entity| {
                    entity.kind == EntityKind::ControlFlow && entity.name == "legacy_nesting"
                })
                .count(),
            2,
            "yield and implicit rescue need method-level legacy parents: {es:?}"
        );
    }
}

/// Language-specific flow-role overrides, extended by language tasks.
pub const FLOW_NAME_ROLES: &[(&str, crate::complexity::FlowRole)] = &[
    ("negation_break", crate::complexity::FlowRole::Ignored),
    ("rescue_begin", crate::complexity::FlowRole::LegacyOnly),
    ("yield", crate::complexity::FlowRole::LegacyOnly),
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
        .filter(|node| FUNCTION_SCOPES.contains(&node.kind().as_ref()))
        .collect();
    let callables: Vec<_> = declarations
        .iter()
        .filter_map(|node| {
            let name_node = node.field("name")?;
            let params = node.field("parameters");
            let parameters: Vec<_> = params
                .map(|list| list.children().filter(|child| child.is_named()).collect())
                .unwrap_or_default();
            let variadic = parameters.iter().any(|parameter| {
                matches!(
                    parameter.kind().as_ref(),
                    "splat_parameter" | "hash_splat_parameter"
                )
            });
            let total_args = if variadic {
                u16::MAX
            } else {
                u16::try_from(
                    parameters
                        .iter()
                        .filter(|parameter| parameter.kind() != "block_parameter")
                        .count(),
                )
                .unwrap_or(u16::MAX)
            };
            let required_args = u16::try_from(
                parameters
                    .iter()
                    .filter(|parameter| match parameter.kind().as_ref() {
                        "optional_parameter"
                        | "splat_parameter"
                        | "hash_splat_parameter"
                        | "block_parameter" => false,
                        "keyword_parameter" => parameter.field("value").is_none(),
                        _ => true,
                    })
                    .count(),
            )
            .unwrap_or(u16::MAX);
            let owner_type = node
                .ancestors()
                .find(|ancestor| TYPE_SCOPES.contains(&ancestor.kind().as_ref()))
                .and_then(|ancestor| field_name(&ancestor));
            let lexical_owner = node
                .ancestors()
                .find(|ancestor| FUNCTION_SCOPES.contains(&ancestor.kind().as_ref()))
                .and_then(|ancestor| field_name(&ancestor));
            let owner = lexical_owner.or_else(|| owner_type.clone());
            Some(Callable {
                owner,
                owner_type,
                unqualified_callable: true,
                name: name_node.text().into_owned(),
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
        let Some(method) = call.field("method") else {
            continue;
        };
        let (qualifier, qualifier_name) = match call.field("receiver") {
            None => (Qualifier::None, None),
            Some(receiver) if receiver.text().as_ref() == "self" => (Qualifier::SelfLike, None),
            Some(receiver)
                if callables[caller].owner_type.as_deref() == Some(receiver.text().as_ref()) =>
            {
                (Qualifier::NamedType, Some(receiver.text().into_owned()))
            }
            Some(_) => (Qualifier::Other, None),
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
            name: method.text().into_owned(),
            argument_count: u16::try_from(argument_count).unwrap_or(u16::MAX),
            qualifier,
            qualifier_name,
        });
    }
    (callables, references)
}
