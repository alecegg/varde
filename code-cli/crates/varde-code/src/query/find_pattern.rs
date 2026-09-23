//! find_pattern mode: hand-rolled AST meta-variable pattern matcher.
//!
//! Not ast-grep-core's matcher — a standalone structural matcher over the
//! parsed tree (parsing reuses the project's existing `parse_source`).
//!
//! Syntax (this phase's scope):
//! - `$VAR`  — single-node capture: matches exactly one node of any kind.
//! - `$VAR:kind` — single-node capture constrained to a given tree-sitter
//!   node kind (e.g. `$FN:function_item`); fails to match otherwise.
//! - `$$$VAR` — variadic capture: matches zero or more sibling nodes.
//! - `$$$VAR:kind` — variadic capture where every captured node must have
//!   the given kind.
//!
//! Relational operators — top-level `inside`/`has`/`precedes`/`follows`
//! input fields, each `{"kind": "..."}` — filter matches by ancestor,
//! descendant, or sibling kind:
//! - `inside`: some ancestor of the match has the given kind.
//! - `has`: some descendant of the match has the given kind.
//! - `precedes`/`follows`: some later/earlier *sibling* (same parent) has
//!   the given kind — this is ast-grep's default "neighbor" `stopBy`, not a
//!   full-document-order search.
//!
//! Scoped to kind-only constraints; a nested sub-pattern for these fields
//! (ast-grep's full relational rules) is out of scope for this phase.
//!
//! The pattern is parsed in the target language after rewriting `$VAR`/`$$$VAR`
//! tokens to marker identifiers, then matched structurally: same node kind,
//! leaf text equality, children matched pairwise with variadic backtracking.
//! Trivia — unnamed/anonymous tokens (`;`, `,`, brackets) — is stripped from
//! both sides before comparison (`strip_trivia`), matching ast-grep's
//! default "Smart" match strictness.

use anyhow::Result;
use std::collections::HashMap;

use super::{ApiError, req_str};

/// Marker prefixes injected by preprocessing (kept unlikely to collide with
/// real identifiers).
const SINGLE_PREFIX: &str = "__varde_meta_s_";
const VARIADIC_PREFIX: &str = "__varde_meta_v_";
const SUFFIX: &str = "__";
const MATCH_LIMIT: usize = 100;

#[derive(Clone, Copy, Debug)]
struct MatchOptions {
    full: bool,
    limit: usize,
    offset: usize,
}

#[derive(Clone, Copy, Debug)]
struct MatchOutputOptions {
    compact: bool,
    window: MatchOptions,
}

fn match_options(input: &serde_json::Value) -> Result<MatchOptions, ApiError> {
    let full = match input.get("fullMatches") {
        None => false,
        Some(value) => value
            .as_bool()
            .ok_or_else(|| ApiError::new("invalid_input", "fullMatches must be a boolean"))?,
    };
    let number = |name: &str| -> Result<Option<usize>, ApiError> {
        let Some(value) = input.get(name) else {
            return Ok(None);
        };
        let number = value.as_u64().ok_or_else(|| {
            ApiError::new(
                "invalid_input",
                format!("{name} must be a nonnegative integer"),
            )
        })?;
        usize::try_from(number).map(Some).map_err(|_| {
            ApiError::new(
                "invalid_input",
                format!("{name} is too large for this platform"),
            )
        })
    };
    let limit = number("matchesLimit")?.unwrap_or(MATCH_LIMIT);
    if limit == 0 {
        return Err(ApiError::new(
            "invalid_input",
            "matchesLimit must be greater than zero",
        ));
    }
    Ok(MatchOptions {
        full,
        limit,
        offset: number("matchesOffset")?.unwrap_or(0),
    })
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum MetaKind {
    /// `$NAME` — matches any single node.
    Single(String),
    /// `$$$NAME` — matches zero or more sibling nodes.
    Variadic(String),
}

type PatternMeta = HashMap<usize, MetaKind>;

/// Rewrite `$VAR` / `$$$VAR` tokens in a pattern into parseable marker
/// identifiers.
fn preprocess(pattern: &str) -> String {
    let mut out = pattern.to_string();
    // Variadic first ($$$ before $).
    out = replace_meta(&out, "$$$", VARIADIC_PREFIX);
    out = replace_meta(&out, "$", SINGLE_PREFIX);
    out
}

/// Strip `:kind` suffixes off `$VAR:kind` / `$$$VAR:kind` tokens before
/// they reach [`preprocess`], recording each name's required kind in a side
/// map. The identifier that ends up parsed (and later matched via
/// [`meta_of`]) never contains the kind — `:` isn't valid inside most
/// languages' identifier tokens, so the constraint has to live out-of-band
/// rather than embedded in the marker text.
fn split_kind_constraints(pattern: &str) -> (String, HashMap<String, String>) {
    let mut out = String::with_capacity(pattern.len());
    let mut constraints = HashMap::new();
    let bytes = pattern.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if let Some(token) = kind_constraint_token(&pattern[i..]) {
            out.push_str(token.sigil);
            out.push_str(token.name);
            if let Some(kind) = token.kind {
                constraints.insert(token.name.to_string(), kind.to_string());
            }
            i += token.consumed;
            continue;
        }
        let ch_len = pattern[i..].chars().next().map(char::len_utf8).unwrap_or(1);
        out.push_str(&pattern[i..i + ch_len]);
        i += ch_len;
    }
    (out, constraints)
}

struct KindConstraintToken<'a> {
    sigil: &'static str,
    name: &'a str,
    kind: Option<&'a str>,
    consumed: usize,
}

fn kind_constraint_token(input: &str) -> Option<KindConstraintToken<'_>> {
    let sigil = if input.starts_with("$$$") {
        "$$$"
    } else if input.starts_with('$') {
        "$"
    } else {
        return None;
    };
    let rest = &input[sigil.len()..];
    let name_end = identifier_end(rest);
    let name = &rest[..name_end];
    if name.is_empty() {
        return None;
    }
    let after_name = &rest[name_end..];
    let kind = after_name.strip_prefix(':').and_then(|remaining| {
        let end = identifier_end(remaining);
        (end > 0).then_some(&remaining[..end])
    });
    let consumed = sigil.len() + name_end + kind.map_or(0, |kind| kind.len() + 1);
    Some(KindConstraintToken {
        sigil,
        name,
        kind,
        consumed,
    })
}

fn identifier_end(text: &str) -> usize {
    text.find(|character: char| !(character.is_ascii_alphanumeric() || character == '_'))
        .unwrap_or(text.len())
}

fn replace_meta(pattern: &str, sigil: &str, prefix: &str) -> String {
    // Token syntax contract shared with rules/rewrite.rs::template_tokens
    // and rules/pattern.rs::capture_names (see rewrite.rs's TemplateToken
    // doc): `$$$` before `$`, `[A-Za-z0-9_]` name run, empty name → literal.
    // This byte loop deliberately stays here rather than consolidating into
    // the shared tokenizer: it rewrites tokens into marker identifiers for
    // parsing (not name extraction), and it is the matcher's hot path —
    // consolidating would change find_pattern's behavior and its perf
    // budget. Keep the boundary rules above in sync with template_tokens.
    let mut result = String::with_capacity(pattern.len());
    let bytes = pattern.as_bytes();
    let mut i = 0;
    while i < bytes.len() {
        if pattern[i..].starts_with(sigil) {
            // Parse the following identifier.
            let rest = &pattern[i + sigil.len()..];
            let name_end = rest
                .find(|c: char| !(c.is_ascii_alphanumeric() || c == '_'))
                .unwrap_or(rest.len());
            let name = &rest[..name_end];
            if !name.is_empty() {
                result.push_str(prefix);
                result.push_str(name);
                result.push_str(SUFFIX);
                i += sigil.len() + name_end;
                continue;
            }
        }
        result.push(bytes[i] as char);
        i += 1;
    }
    result
}

/// Soft cap on backtracking steps for the variadic (`$$$VAR`) matcher, shared
/// by `match_sequence`/`bind_sequence`. Pathological patterns (e.g. many
/// `$$$VAR` markers against a long sibling list) can otherwise blow up
/// combinatorially; this bounds worst-case latency with a generous ceiling
/// that no real-world pattern should approach.
const MAX_BACKTRACK_STEPS: usize = 100_000;

thread_local! {
    /// Remaining backtracking steps for the in-flight `find_pattern` call.
    /// Reset at the start of each call; decremented by `tick_budget`.
    static BACKTRACK_BUDGET: std::cell::Cell<usize> =
        const { std::cell::Cell::new(MAX_BACKTRACK_STEPS) };
}

/// Consume one unit of backtracking budget. Returns `false` once the budget
/// is exhausted, signalling callers to stop recursing.
fn tick_budget() -> bool {
    BACKTRACK_BUDGET.with(|budget| {
        let remaining = budget.get();
        if remaining == 0 {
            return false;
        }
        budget.set(remaining - 1);
        true
    })
}

/// Reset the backtracking budget before a fresh `find_pattern` run.
fn reset_budget() {
    BACKTRACK_BUDGET.with(|budget| budget.set(MAX_BACKTRACK_STEPS));
}

/// Whether the backtracking budget was exhausted during the last run.
fn budget_exhausted() -> bool {
    BACKTRACK_BUDGET.with(|budget| budget.get() == 0)
}

type PNode<'a> =
    ast_grep_core::Node<'a, ast_grep_core::tree_sitter::StrDoc<ast_grep_language::SupportLang>>;

/// Cache of a pattern node's (trivia-stripped) children, keyed by
/// `Node::node_id()`. The pattern tree is small, static and shared across
/// every candidate node `find_matches`/`match_node` visit in a file — most
/// candidates fail to match, but each failed attempt still re-collects the
/// *same* pattern children over and over via `pattern.children().collect()`.
/// This cache turns that into one `TreeCursor` walk per distinct pattern
/// node per file, plus cheap `Vec<Node>` clones (`Node` is a small
/// ref+id handle, not a subtree copy) for every subsequent visit.
///
/// A full `TreeCursor`-based rewrite of `match_node`/`match_sequence` was
/// attempted first but abandoned: `match_sequence`'s memoized backtracking
/// (`rec`, keyed by `(pi, si)`) needs random-access indexing into *both*
/// sides' child sequences (`p[pi]`, arbitrary `s[si + consume]` jumps for
/// `$$$VAR`), which a `TreeCursor` — a single-position walk with only
/// next-sibling/parent/first-child moves — cannot provide without
/// rebuilding an index on first use anyway. So this fallback (pattern-side
/// caching only) is what's implemented; see the task's Progress notes.
type PatternChildCache<'p> = std::cell::RefCell<HashMap<usize, Vec<PNode<'p>>>>;

struct PatternMatchContext<'a, 'p> {
    cache: &'a PatternChildCache<'p>,
    meta: &'a PatternMeta,
    constraints: &'a HashMap<String, String>,
}

fn cached_pattern_children<'p>(cache: &PatternChildCache<'p>, node: &PNode<'p>) -> Vec<PNode<'p>> {
    let id = node.node_id();
    if let Some(children) = cache.borrow().get(&id) {
        return children.clone();
    }
    let children = strip_trivia(node.children().collect());
    cache.borrow_mut().insert(id, children.clone());
    children
}

/// If `node` is a single-level grammar wrapper whose sole named child is a
/// *variadic* marker, return that marker. Some grammars wrap each element of a
/// list in an extra node — e.g. C# wraps every call/constructor argument in an
/// `argument` node, so the pattern `foo($$$A)` parses its argument list as
/// `argument_list → argument → identifier("__varde_meta_v_A__")`. Buried under
/// that lone `argument`, the variadic is never seen at the `argument_list`
/// sequence level, so it fails to match empty or multi-element argument lists.
///
/// This only *detects* a liftable wrapper; the caller
/// ([`match_node_capture`]) decides whether to apply it, using the source
/// side to tell a per-element wrapper (lift) from a singleton list container
/// (keep). Only variadic markers are considered: single markers already match
/// through ordinary recursive descent, and lifting them would change which node
/// their capture binds.
fn lift_variadic_marker<'p>(node: &PNode<'p>, meta: &PatternMeta) -> Option<PNode<'p>> {
    // A node that is itself a bare marker has no wrapper to lift.
    if meta_of(meta, node).is_some() {
        return None;
    }
    let named: Vec<PNode<'p>> = node.children().filter(|c| c.is_named()).collect();
    let [only] = named.as_slice() else {
        return None;
    };
    matches!(meta_of(meta, only), Some(MetaKind::Variadic(_))).then(|| only.clone())
}

/// Detect whether a node is a meta-variable marker.
///
/// Markers are single identifier tokens, so only leaf nodes (no children)
/// can be markers. Without the leaf guard, a compound node whose text
/// happens to start *and* end with the marker delimiters — e.g. the root
/// of `$KEY = $VAL`, whose text is `__varde_meta_s_KEY__ =
/// __varde_meta_s_VAL__` — is misdetected as one giant meta variable named
/// `KEY__ = __varde_meta_s_VAL`, which then matches any node and binds the
/// whole program as a single capture.
fn parse_meta(node: &PNode<'_>) -> Option<MetaKind> {
    if node.children().count() != 0 {
        return None;
    }
    let text = node.text();
    if let Some(rest) = text.strip_prefix(SINGLE_PREFIX)
        && let Some(name) = rest.strip_suffix(SUFFIX)
    {
        return Some(MetaKind::Single(name.to_string()));
    }
    if let Some(rest) = text.strip_prefix(VARIADIC_PREFIX)
        && let Some(name) = rest.strip_suffix(SUFFIX)
    {
        return Some(MetaKind::Variadic(name.to_string()));
    }
    None
}

fn compile_pattern_meta(root: &PNode<'_>) -> PatternMeta {
    root.dfs()
        .filter_map(|node| parse_meta(&node).map(|meta| (node.node_id(), meta)))
        .collect()
}

fn meta_of<'a>(meta: &'a PatternMeta, node: &PNode<'_>) -> Option<&'a MetaKind> {
    meta.get(&node.node_id())
}

#[cfg(test)]
mod tests {
    use super::*;

    static NEXT_TEST_DIR: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

    fn run_pattern(pattern: &str, source: &str) -> serde_json::Value {
        run_pattern_ex(pattern, source, serde_json::json!({}))
    }

    fn match_rows(output: &serde_json::Value) -> &[serde_json::Value] {
        output["matches"].as_array().expect("matches array")
    }

    fn run_pattern_ex(pattern: &str, source: &str, extra: serde_json::Value) -> serde_json::Value {
        let dir = std::env::temp_dir().join(format!(
            "fp-meta-test-{}-{}-{}-{}",
            std::process::id(),
            pattern.len(),
            source.len(),
            NEXT_TEST_DIR.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        let file = dir.join("sample.ts");
        std::fs::write(&file, source).expect("fixture writes");
        let mut input = serde_json::json!({
            "filePath": file.display().to_string(),
            "pattern": pattern,
        });
        if let Some(obj) = extra.as_object() {
            for (k, v) in obj {
                input[k] = v.clone();
            }
        }
        let out = find_pattern(&input).expect("pattern runs");
        let _ = std::fs::remove_dir_all(&dir);
        out
    }

    #[test]
    fn two_meta_variables_in_one_statement_bind_separately() {
        // Regression for the credential rule shape: `$KEY = $VAL`. The
        // assignment root's text is `__varde_meta_s_KEY__ =
        // __varde_meta_s_VAL__`, which starts and ends with the marker
        // delimiters — meta_of used to misdetect the whole root as one
        // giant meta variable (matching every node and binding the entire
        // program under the bogus name `KEY__ = __varde_meta_s_VAL`).
        let out = run_pattern(
            "$KEY = $VAL",
            "const x = 1;\napi_key = \"sk-abc\";\nlet z;\n",
        );
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 1, "only the real assignment matches: {out}");
        assert_eq!(matches[0]["text"], "api_key = \"sk-abc\"");
        let caps = matches[0]["captures"].as_object().expect("captures object");
        assert_eq!(caps["KEY"]["text"], "api_key", "{out}");
        assert_eq!(caps["VAL"]["text"], "\"sk-abc\"", "{out}");
        assert!(
            caps.keys().all(|k| k == "KEY" || k == "VAL"),
            "no bogus capture names: {out}"
        );
    }

    #[test]
    fn kind_constraint_filters_single_capture() {
        let out = run_pattern("$KEY = $VAL:number", "x = 1;\ny = \"s\";\n");
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 1, "only the numeric RHS matches: {out}");
        assert_eq!(matches[0]["text"], "x = 1");
    }

    #[test]
    fn kind_constraint_on_variadic_requires_every_element() {
        // $$$ARGS:number should only bind when every captured argument is a
        // number literal — mixed-kind argument lists must not match.
        let out = run_pattern("foo($$$ARGS:number)", "foo(1, 2, 3);\nfoo(1, \"x\");\n");
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 1, "only the all-numeric call matches: {out}");
        assert_eq!(matches[0]["text"], "foo(1, 2, 3)");
    }

    #[test]
    fn csharp_catch_fragment_wrapper_locates_catch_clause() {
        let rewritten = preprocess("catch ($TYPE $ERR) { }");
        let wrapped = wrap_for_lang(&ast_grep_language::SupportLang::CSharp, &rewritten);
        assert!(wrapped.contains("try {} catch"), "{wrapped}");
        let raw = crate::parse::parse_source(&ast_grep_language::SupportLang::CSharp, &rewritten);
        let wrapped_parsed =
            crate::parse::parse_source(&ast_grep_language::SupportLang::CSharp, &wrapped);
        assert!(
            !wrapped_parsed.has_error(),
            "wrapped catch parses: {wrapped}"
        );
        let root = locate_pattern_root(&raw, &wrapped_parsed, &rewritten)
            .expect("catch fragment root resolves");
        assert_eq!(root.kind().as_ref(), "catch_clause");
    }

    #[test]
    fn csharp_identifier_starting_with_catch_uses_statement_wrapper() {
        let matches = run_pattern_cs("catcher($ARG)", "class C { void M() { catcher(value); } }");
        assert_eq!(
            matches.len(),
            1,
            "ordinary catcher call matches: {matches:?}"
        );
        assert_eq!(matches[0]["kind"], "invocation_expression");
    }

    /// Run a pattern over a C# source fixture (`sample.cs`), returning the match
    /// array directly. C# wraps each argument in an `argument` node, so this
    /// exercises the buried-variadic lift that the TS fixtures cannot.
    fn run_pattern_cs(pattern: &str, source: &str) -> Vec<serde_json::Value> {
        let dir = std::env::temp_dir().join(format!(
            "fp-cs-test-{}-{}",
            std::process::id(),
            pattern.len()
        ));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        let file = dir.join("sample.cs");
        std::fs::write(&file, source).expect("fixture writes");
        let out = find_pattern(&serde_json::json!({
            "filePath": file.display().to_string(),
            "pattern": pattern,
            "language": "csharp",
        }))
        .expect("pattern runs");
        let _ = std::fs::remove_dir_all(&dir);
        match_rows(&out).to_vec()
    }

    #[test]
    fn variadic_matches_empty_and_multi_arg_through_csharp_wrapper() {
        // Regression: in C# `$$$A` sits under an `argument` wrapper inside
        // `argument_list`. Before the lift, the variadic could only match a
        // single-argument call (varde 6 vs ast-grep 7 on real code); empty and
        // multi-argument calls were missed. `$$$A` must match 0, 1, and N args.
        let src = "class C { void M() {\n\
            Foo();\n\
            Foo(1);\n\
            Foo(1, 2, 3);\n\
            var a = new Thing();\n\
            var b = new Thing(x, y);\n\
        } }\n";

        let calls = run_pattern_cs("Foo($$$A)", src);
        let texts: Vec<&str> = calls.iter().map(|m| m["text"].as_str().unwrap()).collect();
        assert!(
            texts.contains(&"Foo()"),
            "empty-arg call matched: {texts:?}"
        );
        assert!(
            texts.contains(&"Foo(1)"),
            "single-arg call matched: {texts:?}"
        );
        assert!(
            texts.contains(&"Foo(1, 2, 3)"),
            "multi-arg call matched: {texts:?}"
        );
        assert_eq!(calls.len(), 3, "exactly the three Foo calls: {texts:?}");

        let news = run_pattern_cs("new Thing($$$A)", src);
        assert_eq!(
            news.len(),
            2,
            "both empty and multi-arg constructor calls match: {news:?}"
        );
    }

    #[test]
    fn expression_form_throw_pattern_locates_statement_root() {
        // Regression: `throw new $E($$$A)` with no trailing `;` used to fail
        // with "cannot locate pattern root in wrapper". C# has no throw
        // *expression*, so the fragment only parses inside the wrapper, which
        // appends a `;` — the located node is the `throw_statement`. The pattern
        // must resolve and match statement-form throws (parity with ast-grep,
        // which matches the no-`;` form).
        let src = "class C { void M() {\n\
            throw new System.Exception();\n\
            throw new System.Exception(\"msg\");\n\
        } }\n";
        let matches = run_pattern_cs("throw new $E($$$A)", src);
        assert_eq!(
            matches.len(),
            2,
            "no-semicolon throw pattern matches both throw statements: {matches:?}"
        );
        assert!(
            matches.iter().all(|m| m["kind"] == "throw_statement"),
            "located root is the throw statement: {matches:?}"
        );
    }

    #[test]
    fn inside_relation_filters_by_ancestor_kind() {
        let out = run_pattern_ex(
            "helper()",
            "function outer() { helper(); }\nhelper();\n",
            serde_json::json!({"inside": {"kind": "function_declaration"}}),
        );
        let matches = match_rows(&out);
        assert_eq!(
            matches.len(),
            1,
            "only the call inside outer() matches: {out}"
        );
    }

    #[test]
    fn has_relation_filters_by_descendant_kind() {
        let out = run_pattern_ex(
            "function $NAME() { $$$BODY }",
            "function withCall() { helper(); }\nfunction empty() {}\n",
            serde_json::json!({"has": {"kind": "call_expression"}}),
        );
        let matches = match_rows(&out);
        assert_eq!(
            matches.len(),
            1,
            "only the function containing a call matches: {out}"
        );
        let caps = matches[0]["captures"].as_object().expect("captures object");
        assert_eq!(caps["NAME"]["text"], "withCall", "{out}");
    }

    #[test]
    fn follows_relation_requires_a_preceding_sibling_kind() {
        let out = run_pattern_ex(
            "let $A = $B;",
            "let a = 1;\nlet b = 2;\n",
            serde_json::json!({"follows": {"kind": "lexical_declaration"}}),
        );
        let matches = match_rows(&out);
        assert_eq!(
            matches.len(),
            1,
            "only the second declaration follows one: {out}"
        );
        assert_eq!(matches[0]["text"], "let b = 2;");
    }

    #[test]
    fn precedes_relation_requires_a_following_sibling_kind() {
        let out = run_pattern_ex(
            "let $A = $B;",
            "let a = 1;\nlet b = 2;\n",
            serde_json::json!({"precedes": {"kind": "lexical_declaration"}}),
        );
        let matches = match_rows(&out);
        assert_eq!(
            matches.len(),
            1,
            "only the first declaration precedes one: {out}"
        );
        assert_eq!(matches[0]["text"], "let a = 1;");
    }

    // --- literal-atom prefilter ---

    #[test]
    fn mandatory_atoms_extracts_literal_identifiers() {
        // The two literal leaves of `console.log($MSG)` must appear verbatim
        // in any matching file; `$MSG` is a meta-var and contributes nothing.
        assert_eq!(mandatory_atoms("console.log($MSG)"), vec!["console", "log"]);
    }

    #[test]
    fn mandatory_atoms_skips_meta_vars_and_kind_constraints() {
        // Pure meta-vars + punctuation ⇒ no atoms ⇒ prefilter disabled.
        assert!(mandatory_atoms("$KEY = $VAL").is_empty());
        // A `:kind` suffix is a node-kind constraint, not source text.
        assert!(mandatory_atoms("$VAL:number").is_empty());
        // Variadic markers (`$$$`) are likewise not literals.
        assert_eq!(mandatory_atoms("foo($$$ARGS:number)"), vec!["foo"]);
    }

    #[test]
    fn mandatory_atoms_includes_string_and_number_literals() {
        // A string literal's inner identifier and a numeric literal both must
        // appear verbatim (returned sorted+deduped).
        assert_eq!(
            mandatory_atoms("require(\"react\")"),
            vec!["react", "require"]
        );
        assert_eq!(mandatory_atoms("foo(42)"), vec!["42", "foo"]);
        // Dedup: a repeated atom appears once.
        assert_eq!(mandatory_atoms("log($X); log($Y)"), vec!["log"]);
    }

    /// Run a directory search over an in-memory set of `(filename, source)`
    /// fixtures — the code path the prefilter actually gates.
    fn run_pattern_dir(tag: &str, pattern: &str, files: &[(&str, &str)]) -> serde_json::Value {
        let dir = std::env::temp_dir().join(format!("fp-dir-{}-{tag}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        for (name, src) in files {
            std::fs::write(dir.join(name), src).expect("fixture writes");
        }
        let input = serde_json::json!({
            "path": dir.display().to_string(),
            "pattern": pattern,
            "language": "typescript",
        });
        let out = find_pattern(&input).expect("pattern runs");
        let _ = std::fs::remove_dir_all(&dir);
        out
    }

    #[test]
    fn prefilter_changes_timing_not_results() {
        // Three files: one real match; one that contains both atoms
        // (`console`, `log`) but does not structurally match (prefilter lets it
        // through, the matcher rejects it); one that lacks an atom entirely
        // (prefilter skips it without parsing). Only the real match survives —
        // proving the prefilter never drops a match and defers the final
        // decision to the matcher.
        let out = run_pattern_dir(
            "prefilter",
            "console.log($MSG)",
            &[
                ("match.ts", "console.log(\"hi\");\n"),
                ("atom_no_match.ts", "const log = console;\n"),
                ("no_atom.ts", "let x = 1;\n"),
            ],
        );
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 1, "only the real console.log matches: {out}");
        assert_eq!(matches[0]["captures"]["MSG"]["text"], "\"hi\"", "{out}");
    }

    #[test]
    fn atomless_pattern_still_searches_whole_tree() {
        // `$A = $B` has no literal atom, so the prefilter is disabled and every
        // file is parsed — the assignment is still found.
        // Bare assignments (`assignment_expression`), which `$A = $B` matches —
        // a `let`-bound `variable_declarator` is a different shape.
        let out = run_pattern_dir(
            "atomless",
            "$A = $B",
            &[("a.ts", "x = 1;\n"), ("b.ts", "y = 2;\n")],
        );
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 2, "both assignments found: {out}");
    }

    #[test]
    fn bounded_results_keep_exact_total_and_first_matches() {
        let source = (0..150)
            .map(|index| format!("value{index} = {index};"))
            .collect::<Vec<_>>()
            .join("\n");
        let out = run_pattern("$A = $B", &source);
        let matches = match_rows(&out);
        assert_eq!(matches.len(), MATCH_LIMIT);
        assert_eq!(out["guide"]["truncated"]["matches"]["shown"], 100);
        assert_eq!(out["guide"]["truncated"]["matches"]["total"], 150);
        assert_eq!(matches[0]["captures"]["A"]["text"], "value0");
        assert_eq!(matches[99]["captures"]["A"]["text"], "value99");
    }

    #[test]
    fn bounded_results_support_offset_and_explicit_limit() {
        let source = (0..8)
            .map(|index| format!("value{index} = {index};"))
            .collect::<Vec<_>>()
            .join("\n");
        let out = run_pattern_ex(
            "$A = $B",
            &source,
            serde_json::json!({"matchesLimit": 3, "matchesOffset": 2}),
        );
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 3, "window size: {out}");
        assert_eq!(out["guide"]["truncated"]["matches"]["shown"], 3);
        assert_eq!(out["guide"]["truncated"]["matches"]["total"], 8);
        assert_eq!(out["guide"]["truncated"]["matches"]["offset"], 2);
        assert_eq!(out["guide"]["truncated"]["matches"]["next_offset"], 5);
        assert_eq!(matches[0]["captures"]["A"]["text"], "value2");
        assert_eq!(matches[2]["captures"]["A"]["text"], "value4");
    }

    #[test]
    fn full_matches_recovers_results_after_a_bounded_default() {
        let source = (0..8)
            .map(|index| format!("value{index} = {index};"))
            .collect::<Vec<_>>()
            .join("\n");
        let out = run_pattern_ex(
            "$A = $B",
            &source,
            serde_json::json!({"fullMatches": true, "matchesOffset": 6}),
        );
        let matches = match_rows(&out);
        assert_eq!(matches.len(), 2, "tail window: {out}");
        assert_eq!(out["guide"]["truncated"]["matches"]["total"], 8);
        assert_eq!(matches[0]["captures"]["A"]["text"], "value6");
    }

    #[test]
    fn batched_patterns_preserve_per_pattern_results() {
        let dir = std::env::temp_dir().join(format!("fp-batch-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        std::fs::write(dir.join("a.ts"), "console.log('a');\nwarn('a');\n").expect("a.ts writes");
        std::fs::write(dir.join("b.ts"), "console.log('b');\n").expect("b.ts writes");

        let patterns = ["console.log($MSG)", "warn($MSG)"];
        let results =
            find_patterns_unbounded(&dir, &ast_grep_language::SupportLang::TypeScript, &patterns);
        assert_eq!(
            results[0].as_ref().expect("first pattern succeeds").len(),
            2
        );
        assert_eq!(
            results[1].as_ref().expect("second pattern succeeds").len(),
            1
        );

        let _ = std::fs::remove_dir_all(dir);
    }
}

/// Drop trivia — unnamed (anonymous) tokens, e.g. `;`, `,`, `(`, `)` — from a
/// child sequence before structural comparison. Mirrors ast-grep's default
/// "Smart" match strictness: named nodes carry the pattern's meaning, while
/// punctuation-only tokens are formatting/optional-syntax noise (a trailing
/// comma before `)`, an ASI-omitted `;`) that shouldn't defeat matching an
/// unformatted pattern against differently-formatted source. Stripped from
/// both sides symmetrically, so a pattern that happens to spell out a token
/// the source omits (or vice versa) still aligns.
fn strip_trivia<'a>(children: Vec<PNode<'a>>) -> Vec<PNode<'a>> {
    // Most node kinds are all-named children (e.g. argument lists without
    // punctuation nodes at this level); skip the scan/rebuild entirely for
    // them rather than allocating a same-length copy on every match_node
    // call.
    if children.iter().all(|c| c.is_named()) {
        return children;
    }
    children
        .into_iter()
        .filter(|c| c.is_named() || is_semantic_operator(c.text().as_ref()))
        .collect()
}

fn is_semantic_operator(text: &str) -> bool {
    !text.is_empty()
        && text.chars().all(|ch| {
            matches!(
                ch,
                '=' | '+' | '-' | '*' | '/' | '%' | '!' | '<' | '>' | '&' | '|' | '^' | '~' | '?'
            )
        })
}

fn merge_captures(
    mut left: serde_json::Map<String, serde_json::Value>,
    right: serde_json::Map<String, serde_json::Value>,
) -> Option<serde_json::Map<String, serde_json::Value>> {
    for (name, value) in right {
        if let Some(existing) = left.get(&name) {
            if existing != &value {
                return None;
            }
        } else {
            left.insert(name, value);
        }
    }
    Some(left)
}

/// Does the pattern node match the source node, and if so, what captures
/// does that alignment bind? Merges what used to be two separate
/// structural walks — `match_node` (locate) followed by `collect_captures`
/// (bind, re-deriving the same pattern/source alignment from scratch) — into
/// one: alignment is computed once and captures are collected along the way,
/// discarded automatically on any backtracked-away branch (an `Option`
/// return, not a side-effecting `&mut` accumulator, so a failed branch's
/// partial captures never leak into the result).
fn match_node_capture<'p>(
    pattern: &PNode<'p>,
    source: &PNode<'_>,
    context: &PatternMatchContext<'_, 'p>,
) -> Option<serde_json::Map<String, serde_json::Value>> {
    if let Some(marker) = meta_of(context.meta, pattern) {
        return capture_meta_node(marker, source, context.constraints);
    }
    if pattern.kind() != source.kind() {
        return None;
    }
    let pchildren = cached_pattern_children(context.cache, pattern);
    if pchildren.is_empty() {
        // Keep the common leaf path cheap and exact.
        if pattern.text() == source.text() {
            return Some(serde_json::Map::new());
        }
        // Empty punctuation containers such as `{}` have unnamed children
        // which `strip_trivia` removes. Compare those children directly so
        // layout whitespace does not matter, while literal tokens, operators,
        // and comments still require exact kind and text equality.
        let raw_pattern_children: Vec<PNode<'p>> = pattern.children().collect();
        if raw_pattern_children.is_empty() {
            return None;
        }
        let raw_source_children: Vec<PNode<'_>> = source.children().collect();
        if raw_pattern_children.len() != raw_source_children.len()
            || !raw_pattern_children
                .iter()
                .zip(raw_source_children.iter())
                .all(|(expected, actual)| {
                    expected.kind() == actual.kind() && expected.text() == actual.text()
                })
        {
            return None;
        }
        return Some(serde_json::Map::new());
    }
    let schildren: Vec<PNode<'_>> = strip_trivia(source.children().collect());
    // Lift per-element wrappers that bury a variadic marker (e.g. C#'s
    // `argument` node) up to this sequence level, but only when the wrapper's
    // kind is a *per-element* wrapper here — i.e. the source has some number
    // other than exactly one child of that kind. A singleton list container
    // (`arguments` in TS/JS holds the marker directly and appears once) has
    // exactly one same-kind source child and is left intact for ordinary
    // recursive descent, which handles the variadic one level down. Without the
    // count gate, that container would be collapsed and the variadic would
    // wrongly swallow sibling slots. Most patterns have no liftable child, so
    // the common path returns the cached `pchildren` untouched.
    let plifted = lift_pattern_variadics(pchildren, &schildren, context.meta);
    match_sequence_capture(&plifted, &schildren, context)
}

fn capture_meta_node(
    marker: &MetaKind,
    source: &PNode<'_>,
    constraints: &HashMap<String, String>,
) -> Option<serde_json::Map<String, serde_json::Value>> {
    let name = match marker {
        MetaKind::Single(name) | MetaKind::Variadic(name) => name,
    };
    if constraints
        .get(name.as_str())
        .is_some_and(|kind| source.kind().as_ref() != kind)
    {
        return None;
    }
    let value = match marker {
        MetaKind::Single(_) => node_json(source),
        MetaKind::Variadic(_) => serde_json::json!([node_json(source)]),
    };
    let mut captures = serde_json::Map::new();
    captures.insert(name.to_string(), value);
    Some(captures)
}

fn lift_pattern_variadics<'p>(
    children: Vec<PNode<'p>>,
    source_children: &[PNode<'_>],
    meta: &PatternMeta,
) -> Vec<PNode<'p>> {
    if !children
        .iter()
        .any(|child| lift_variadic_marker(child, meta).is_some())
    {
        return children;
    }
    children
        .iter()
        .map(|child| match lift_variadic_marker(child, meta) {
            Some(marker)
                if source_children
                    .iter()
                    .filter(|source| source.kind() == child.kind())
                    .count()
                    != 1 =>
            {
                marker
            }
            _ => child.clone(),
        })
        .collect()
}

/// Match a pattern-child sequence against a source-child sequence, allowing
/// variadic markers to consume zero or more source children (backtracking),
/// binding captures along the accepted path in the same recursion that
/// decides the match. Memoized like the old bool-only `match_sequence`
/// (`(pi, si) -> Option<Map>`): a `None`/`Some` outcome — and, for `Some`,
/// its bound captures — is deterministic per `(pi, si)` suffix, since
/// backtracking always resolves to the same first-successful alignment.
fn match_sequence_capture<'p>(
    p: &[PNode<'p>],
    s: &[PNode<'_>],
    context: &PatternMatchContext<'_, 'p>,
) -> Option<serde_json::Map<String, serde_json::Value>> {
    match_sequence_suffix(p, s, 0, 0, &mut HashMap::new(), context)
}

type CaptureMap = serde_json::Map<String, serde_json::Value>;
type SequenceMemo = HashMap<(usize, usize), Option<CaptureMap>>;

fn match_sequence_suffix<'p>(
    pattern: &[PNode<'p>],
    source: &[PNode<'_>],
    pattern_index: usize,
    source_index: usize,
    memo: &mut SequenceMemo,
    context: &PatternMatchContext<'_, 'p>,
) -> Option<CaptureMap> {
    if let Some(result) = memo.get(&(pattern_index, source_index)) {
        return result.clone();
    }
    if !tick_budget() {
        return None;
    }
    let result = if pattern_index == pattern.len() {
        (source_index == source.len()).then(serde_json::Map::new)
    } else if let Some(MetaKind::Variadic(name)) = meta_of(context.meta, &pattern[pattern_index]) {
        match_variadic_suffix(
            pattern,
            source,
            pattern_index,
            source_index,
            name.as_str(),
            memo,
            context,
        )
    } else if source_index >= source.len() {
        None
    } else {
        match_node_capture(&pattern[pattern_index], &source[source_index], context).and_then(
            |node_captures| {
                match_sequence_suffix(
                    pattern,
                    source,
                    pattern_index + 1,
                    source_index + 1,
                    memo,
                    context,
                )
                .and_then(|rest| merge_captures(node_captures, rest))
            },
        )
    };
    memo.insert((pattern_index, source_index), result.clone());
    result
}

fn match_variadic_suffix<'p>(
    pattern: &[PNode<'p>],
    source: &[PNode<'_>],
    pattern_index: usize,
    source_index: usize,
    name: &str,
    memo: &mut SequenceMemo,
    context: &PatternMatchContext<'_, 'p>,
) -> Option<CaptureMap> {
    for consume in 0..=(source.len() - source_index) {
        let consumed = &source[source_index..source_index + consume];
        let compatible = context
            .constraints
            .get(name)
            .is_none_or(|kind| consumed.iter().all(|node| node.kind().as_ref() == kind));
        if !compatible {
            continue;
        }
        let Some(rest) = match_sequence_suffix(
            pattern,
            source,
            pattern_index + 1,
            source_index + consume,
            memo,
            context,
        ) else {
            continue;
        };
        let mut captures = serde_json::Map::new();
        let bound: Vec<_> = consumed.iter().map(node_json).collect();
        captures.insert(name.to_string(), serde_json::json!(bound));
        if let Some(merged) = merge_captures(captures, rest) {
            return Some(merged);
        }
    }
    None
}

/// Find every node in `source` (root included) matching the pattern root,
/// binding its captures inline as part of the same structural walk instead
/// of a second re-walk over each matched subtree afterwards (see
/// `match_node_capture`/`match_sequence_capture`, which check-and-bind in
/// one recursive pass).
///
/// Kind-filtered before attempting the expensive structural
/// `match_node_capture` call: a plain (non-meta-var) pattern root can only
/// ever match nodes of its own kind, so skip straight to recursing into
/// children otherwise instead of walking the pattern/source child sequences
/// just to fail on the kind check inside `match_node_capture`.
fn find_matches<'p, 's>(
    pattern: &PNode<'p>,
    node: &PNode<'s>,
    out: &mut MatchOutput,
    context: &PatternMatchContext<'_, 'p>,
    relations: &Relations,
    limit: Option<usize>,
) {
    let plain_kind_mismatch =
        meta_of(context.meta, pattern).is_none() && pattern.kind() != node.kind();
    if !plain_kind_mismatch
        && let Some(captures) = match_node_capture(pattern, node, context)
        && (relations.is_empty() || relations.matches(node))
    {
        out.total += 1;
        if limit.is_none_or(|limit| out.matches.len() < limit) {
            out.matches.push(serde_json::json!({
                "kind": node.kind().as_ref(),
                "text": node.text().as_ref(),
                "span": node_json(node)["span"],
                "captures": serde_json::Value::Object(captures),
            }));
        }
    }
    // Still recurse into every child regardless of whether `node` matched —
    // a matched node's descendants (or its siblings) can independently
    // contain further matches elsewhere in the tree. This recursion locates
    // further matches only; it does not re-derive the alignment of a
    // subtree that already matched above (that alignment, and its
    // captures, were already computed by `match_node_capture` in this same
    // call).
    for child in node.children() {
        find_matches(pattern, &child, out, context, relations, limit);
    }
}

/// Top-level relational filters — `inside`/`has`/`precedes`/`follows` —
/// applied to a match's node after structural matching, kind-only (see
/// module docs for scope). All present fields are ANDed together.
#[derive(Default)]
struct Relations {
    inside: Option<String>,
    has: Option<String>,
    precedes: Option<String>,
    follows: Option<String>,
}

impl Relations {
    fn is_empty(&self) -> bool {
        self.inside.is_none()
            && self.has.is_none()
            && self.precedes.is_none()
            && self.follows.is_none()
    }

    /// Does `node` satisfy every relational constraint set on this
    /// `Relations`? `ancestors()`/`dfs()`/`next_all()`/`prev_all()` are
    /// ast-grep-core's own traversal primitives — `dfs()` includes `node`
    /// itself first, so `has` skips one to only consider descendants.
    fn matches(&self, node: &PNode<'_>) -> bool {
        if let Some(k) = &self.inside
            && !node.ancestors().any(|a| a.kind().as_ref() == k.as_str())
        {
            return false;
        }
        if let Some(k) = &self.has
            && !node.dfs().skip(1).any(|d| d.kind().as_ref() == k.as_str())
        {
            return false;
        }
        if let Some(k) = &self.precedes
            && !node.next_all().any(|s| s.kind().as_ref() == k.as_str())
        {
            return false;
        }
        if let Some(k) = &self.follows
            && !node.prev_all().any(|s| s.kind().as_ref() == k.as_str())
        {
            return false;
        }
        true
    }
}

/// Parse a `{"kind": "..."}` relational constraint from an optional
/// top-level input field.
fn parse_relation_kind(input: &serde_json::Value, key: &str) -> Result<Option<String>, ApiError> {
    match input.get(key) {
        None | Some(serde_json::Value::Null) => Ok(None),
        Some(v) => {
            let kind = v.get("kind").and_then(|k| k.as_str()).ok_or_else(|| {
                ApiError::new(
                    "invalid_input",
                    format!("{key:?} requires a string \"kind\" field"),
                )
            })?;
            Ok(Some(kind.to_string()))
        }
    }
}

fn node_json(node: &PNode<'_>) -> serde_json::Value {
    let pos = node.start_pos();
    let end = node.end_pos();
    serde_json::json!({
        "kind": node.kind().as_ref(),
        "text": node.text().as_ref(),
        "span": {
            "start_byte": node.range().start,
            "end_byte": node.range().end,
            "start_line": pos.line() + 1,
            "start_col": pos.column(node),
            "end_line": end.line() + 1,
            "end_col": end.column(node),
        },
    })
}

/// Depth-first search for the first node whose text matches `target`.
/// Post-order: children are checked before `node` itself, so when a wrapper
/// node's text happens to equal its single child's text exactly (e.g. a
/// whole-file pattern with one top-level statement), the more specific
/// (deepest) matching node wins instead of the outer wrapper.
fn find_text_node<'a>(node: &PNode<'a>, target: &str) -> Option<PNode<'a>> {
    for child in node.children() {
        if let Some(found) = find_text_node(&child, target) {
            return Some(found);
        }
    }
    if node.text().trim() == target {
        return Some(node.clone());
    }
    None
}

/// Resolve the language for a pattern-matching call: explicit `language`
/// input wins, otherwise infer from a single target file's extension.
/// Directory targets require an explicit `language` since the tree walk
/// covers mixed extensions.
///
/// Both paths span the full `ast-grep` grammar set (every language
/// `ast-grep-language` links), not just the extraction-supported subset:
/// structural search needs only a grammar to parse against. Explicit names
/// accept `ast-grep`'s own aliases (e.g. `ts`, `py`, `c++`).
fn resolve_lang(
    input: &serde_json::Value,
    file_hint: Option<&std::path::Path>,
) -> Result<ast_grep_language::SupportLang, ApiError> {
    use ast_grep_language::SupportLang;
    use std::str::FromStr;
    match input.get("language").and_then(|v| v.as_str()) {
        Some(l) => SupportLang::from_str(l)
            .map_err(|_| ApiError::new("invalid_input", format!("unsupported language {l:?}"))),
        None => {
            let path = file_hint.ok_or_else(|| {
                ApiError::new(
                    "invalid_input",
                    "language is required when searching a directory",
                )
            })?;
            crate::parse::any_language_for_path(path).ok_or_else(|| {
                ApiError::new(
                    "invalid_input",
                    format!("unsupported file type {}", path.display()),
                )
            })
        }
    }
}

/// Match a parsed pattern against one file's source. Returns match JSON
/// objects (without a `file` field — the caller attaches it).
/// Wrap a pattern fragment in a minimal function body so statement/expression
/// fragments that aren't valid top-level syntax (e.g. a bare method call)
/// still parse. Wrapper syntax is language-specific — a Rust-only `fn ... {}`
/// wrapper doesn't parse in TS/JS/Go/Python.
fn wrap_for_lang(lang: &ast_grep_language::SupportLang, rewritten: &str) -> String {
    use ast_grep_language::SupportLang;
    match lang {
        SupportLang::Rust => format!("fn __varde_wrapper__() {{ {rewritten} }}"),
        SupportLang::TypeScript | SupportLang::Tsx | SupportLang::JavaScript => {
            format!("function __varde_wrapper__() {{ {rewritten} }}")
        }
        SupportLang::Go | SupportLang::Swift => {
            format!("func __varde_wrapper__() {{ {rewritten} }}")
        }
        SupportLang::Python => format!("def __varde_wrapper__():\n    {rewritten}\n"),
        // C-family: a plain function body carries statement/expression
        // fragments. These languages need a statement terminator, so append a
        // `;` — a fragment that already ends in one just yields a harmless
        // trailing empty statement.
        SupportLang::C | SupportLang::Cpp | SupportLang::Dart => {
            format!("void __varde_wrapper__() {{ {rewritten}; }}")
        }
        // Java requires the method to live inside a type declaration.
        SupportLang::Java => {
            format!("class __VardeWrapper__ {{ void __varde_wrapper__() {{ {rewritten}; }} }}")
        }
        // A bare C# catch clause is only valid after a try statement. Keep
        // the fragment exact so locate_pattern_root selects `catch_clause`.
        SupportLang::CSharp if is_csharp_catch_fragment(rewritten) => {
            format!(
                "class __VardeWrapper__ {{ void __varde_wrapper__() {{ try {{}} {rewritten} }} }}"
            )
        }
        // Other C# fragments need the ordinary statement wrapper.
        SupportLang::CSharp => {
            format!("class __VardeWrapper__ {{ void __varde_wrapper__() {{ {rewritten}; }} }}")
        }
        SupportLang::Kotlin => format!("fun __varde_wrapper__() {{ {rewritten} }}"),
        SupportLang::Php => format!("<?php function __varde_wrapper__() {{ {rewritten}; }}"),
        SupportLang::Scala => {
            format!("object __VardeWrapper__ {{ def __varde_wrapper__() = {{ {rewritten} }} }}")
        }
        SupportLang::Solidity => format!(
            "contract __VardeWrapper__ {{ function __varde_wrapper__() public {{ {rewritten}; }} }}"
        ),
        SupportLang::Ruby => format!("def __varde_wrapper__\n{rewritten}\nend"),
        SupportLang::Lua => format!("function __varde_wrapper__() {rewritten} end"),
        // Shell statements are already valid at top level; other languages
        // (Bash, config/markup grammars, etc.) have no universal single-function
        // wrapper, so fall back to the bare fragment — `locate_pattern_root`
        // still prefers the raw parse whenever the fragment parses on its own.
        _ => rewritten.to_string(),
    }
}

fn is_csharp_catch_fragment(rewritten: &str) -> bool {
    let trimmed = rewritten.trim_start();
    let Some(rest) = trimmed.strip_prefix("catch") else {
        return false;
    };
    matches!(rest.chars().next(), Some(c) if c.is_whitespace() || c == '(' || c == '{')
}

/// Locate the pattern's root node for matching. Always prefers an exact
/// text-match lookup over blindly trusting the parse root: a pattern that
/// happens to be valid top-level syntax on its own (e.g. `throw new
/// Error($MSG)` is a complete program) would otherwise resolve to the whole
/// `program`/`source_file` node, which never matches anything since that
/// kind never appears as an inner node.
fn locate_pattern_root<'a>(
    raw_parsed: &'a crate::parse::ParsedFile,
    wrapped_parsed: &'a crate::parse::ParsedFile,
    rewritten: &str,
) -> Result<PNode<'a>, ApiError> {
    let trimmed = rewritten.trim();
    if !raw_parsed.has_error() {
        let root = raw_parsed.root.root();
        if let Some(found) = find_text_node(&root, trimmed) {
            return Ok(found);
        }
        return Ok(root);
    }
    if wrapped_parsed.has_error() {
        return Err(ApiError::new(
            "invalid_pattern",
            "pattern does not parse in the target language",
        ));
    }
    let root = wrapped_parsed.root.root();
    // Try the pattern text verbatim first. If that fails, retry with a trailing
    // `;`: several wrappers (C/C++/Dart/Java/C#/PHP/Solidity — see
    // `wrap_for_lang`) append a statement terminator, so an *expression*-form
    // fragment like `throw new $E($$$A)` (no `;`) becomes a `throw_statement`
    // whose text carries the appended `;` and never equals the semicolon-less
    // pattern. Retrying with the terminator locates that statement node — giving
    // parity with `ast-grep run`, which matches the no-`;` form fine. A fragment
    // that already ended in `;` matched on the first attempt.
    find_text_node(&root, trimmed)
        .or_else(|| find_text_node(&root, &format!("{trimmed};")))
        .ok_or_else(|| ApiError::new("invalid_pattern", "cannot locate pattern root in wrapper"))
}

/// Literal identifier/keyword/number atoms a pattern requires verbatim in any
/// source it can match — the prefilter's key. Every non-meta-var leaf in the
/// pattern must match a source leaf by exact text (`match_node_capture`), so
/// each maximal `[A-Za-z0-9_]` run in the pattern (excluding meta-var names
/// and `:kind` constraints) must appear as a byte substring of any matching
/// file. AND-ing them is therefore *conservative*: a file missing any atom
/// cannot match and can be skipped without parsing, but the filter never
/// skips a file that could match (it only ever over-selects). Punctuation
/// (`.`/`(`/`=`) is intentionally not an atom — it is trivia the "Smart"
/// matcher strips and appears in nearly every file, so it would not narrow.
/// A pattern with no literal atoms (e.g. `$A = $B`) yields an empty set and
/// the prefilter is skipped (parse everything), which is correct.
fn mandatory_atoms(pattern: &str) -> Vec<String> {
    let bytes = pattern.as_bytes();
    let mut atoms = Vec::new();
    let mut i = 0;
    while i < bytes.len() {
        if bytes[i] == b'$' {
            i = metavariable_end(bytes, i);
            continue;
        }
        if is_identifier_byte(bytes[i]) {
            let start = i;
            i = identifier_byte_end(bytes, i);
            atoms.push(pattern[start..i].to_string());
            continue;
        }
        i += 1;
    }
    atoms.sort();
    atoms.dedup();
    atoms
}

fn metavariable_end(bytes: &[u8], start: usize) -> usize {
    let mut end = start;
    while end < bytes.len() && bytes[end] == b'$' {
        end += 1;
    }
    end = identifier_byte_end(bytes, end);
    if end < bytes.len() && bytes[end] == b':' {
        return identifier_byte_end(bytes, end + 1);
    }
    end
}

fn identifier_byte_end(bytes: &[u8], start: usize) -> usize {
    let mut end = start;
    while end < bytes.len() && is_identifier_byte(bytes[end]) {
        end += 1;
    }
    end
}

fn is_identifier_byte(byte: u8) -> bool {
    byte.is_ascii_alphanumeric() || byte == b'_'
}

#[derive(Default)]
struct MatchOutput {
    matches: Vec<serde_json::Value>,
    total: usize,
}

fn match_source(
    pattern_root: &PNode<'_>,
    meta: &PatternMeta,
    lang: &ast_grep_language::SupportLang,
    source: &str,
    constraints: &HashMap<String, String>,
    relations: &Relations,
    limit: Option<usize>,
) -> Result<MatchOutput, ApiError> {
    // Match on tree-sitter's error-recovered tree rather than rejecting the
    // whole file on the first syntax error. A single unparseable construct
    // (often just modern-syntax the pinned grammar version doesn't know)
    // otherwise discards *every* match in the file — a large recall loss and a
    // parity gap vs. `ast-grep run`, which matches recovered trees. ERROR and
    // MISSING nodes carry their own kinds, so they never match a real pattern's
    // node kind; tolerating them only recovers the well-formed regions and
    // never invents spurious matches.
    let source_parsed = crate::parse::parse_source(lang, source);
    let source_root = source_parsed.root.root();

    match_parsed_source(
        pattern_root,
        meta,
        &source_root,
        constraints,
        relations,
        limit,
    )
}

fn match_parsed_source(
    pattern_root: &PNode<'_>,
    meta: &PatternMeta,
    source_root: &PNode<'_>,
    constraints: &HashMap<String, String>,
    relations: &Relations,
    limit: Option<usize>,
) -> Result<MatchOutput, ApiError> {
    reset_budget();
    let cache: PatternChildCache<'_> = std::cell::RefCell::new(HashMap::new());
    let context = PatternMatchContext {
        cache: &cache,
        meta,
        constraints,
    };
    // Locate and bind captures in one structural walk per match: `find_matches`
    // now calls `match_node_capture`, which checks alignment and collects
    // captures together, instead of the old two-phase locate-then-rewalk
    // (`find_matches` followed by a per-match `collect_captures` call).
    let mut matched = MatchOutput::default();
    find_matches(
        pattern_root,
        source_root,
        &mut matched,
        &context,
        relations,
        limit,
    );
    if budget_exhausted() {
        return Err(ApiError::new(
            "pattern_too_complex",
            "pattern matching exceeded the backtracking step budget; \
             simplify the pattern (fewer $$$VAR markers or a narrower search)",
        ));
    }
    Ok(matched)
}

struct BatchPattern<'a> {
    root: PNode<'a>,
    meta: PatternMeta,
    constraints: HashMap<String, String>,
    atoms: Vec<String>,
    matches: std::sync::Mutex<Vec<serde_json::Value>>,
}

enum BatchSlot<'a> {
    Ready(BatchPattern<'a>),
    Failed(ApiError),
}

/// Search many patterns through one language-specific repository traversal.
///
/// Every candidate file is read and parsed once. Its syntax tree is then
/// matched against all viable patterns for that language.
pub(crate) fn find_patterns_unbounded(
    repo_root: &std::path::Path,
    lang: &ast_grep_language::SupportLang,
    patterns: &[&str],
) -> Vec<Result<Vec<serde_json::Value>, ApiError>> {
    let parsed: Vec<_> = patterns
        .iter()
        .map(|pattern| {
            let (stripped, constraints) = split_kind_constraints(pattern);
            let rewritten = preprocess(&stripped);
            let wrapped = wrap_for_lang(lang, &rewritten);
            let raw = crate::parse::parse_source(lang, &rewritten);
            let wrapped_parsed = crate::parse::parse_source(lang, &wrapped);
            (rewritten, constraints, raw, wrapped_parsed)
        })
        .collect();
    let slots: Vec<_> = parsed
        .iter()
        .zip(patterns)
        .map(|((rewritten, constraints, raw, wrapped), pattern)| {
            match locate_pattern_root(raw, wrapped, rewritten) {
                Ok(root) => BatchSlot::Ready(BatchPattern {
                    meta: compile_pattern_meta(&root),
                    root,
                    constraints: constraints.clone(),
                    atoms: mandatory_atoms(pattern),
                    matches: std::sync::Mutex::new(Vec::new()),
                }),
                Err(error) => BatchSlot::Failed(error),
            }
        })
        .collect();
    if !slots.iter().any(|slot| matches!(slot, BatchSlot::Ready(_))) {
        return slots
            .into_iter()
            .map(|slot| match slot {
                BatchSlot::Failed(error) => Err(error),
                BatchSlot::Ready(_) => unreachable!(),
            })
            .collect();
    }
    walk_batch_patterns(repo_root, lang, &slots);
    slots
        .into_iter()
        .map(|slot| match slot {
            BatchSlot::Failed(error) => Err(error),
            BatchSlot::Ready(pattern) => {
                let mut matches = pattern.matches.into_inner().unwrap();
                sort_matches(&mut matches);
                Ok(matches)
            }
        })
        .collect()
}

fn walk_batch_patterns(
    repo_root: &std::path::Path,
    lang: &ast_grep_language::SupportLang,
    slots: &[BatchSlot<'_>],
) {
    let relations = Relations::default();
    ignore::WalkBuilder::new(repo_root)
        .hidden(false)
        .filter_entry(|entry| !crate::scan::is_vcs_internal(entry))
        .build_parallel()
        .run(|| {
            Box::new(|entry| {
                use ignore::WalkState;
                let Ok(entry) = entry else {
                    return WalkState::Continue;
                };
                visit_batch_path(entry.path(), lang, slots, &relations);
                WalkState::Continue
            })
        });
}

fn visit_batch_path(
    path: &std::path::Path,
    lang: &ast_grep_language::SupportLang,
    slots: &[BatchSlot<'_>],
    relations: &Relations,
) {
    if !path.is_file() || crate::parse::any_language_for_path(path).as_ref() != Some(lang) {
        return;
    }
    let Ok(source) = std::fs::read_to_string(path) else {
        return;
    };
    let viable =
        |pattern: &BatchPattern<'_>| pattern.atoms.iter().all(|atom| source.contains(atom));
    if !slots
        .iter()
        .any(|slot| matches!(slot, BatchSlot::Ready(pattern) if viable(pattern)))
    {
        return;
    }
    let parsed_source = crate::parse::parse_source(lang, &source);
    let source_root = parsed_source.root.root();
    for slot in slots {
        let BatchSlot::Ready(pattern) = slot else {
            continue;
        };
        if !viable(pattern) {
            continue;
        }
        let Ok(matched) = match_parsed_source(
            &pattern.root,
            &pattern.meta,
            &source_root,
            &pattern.constraints,
            relations,
            None,
        ) else {
            continue;
        };
        if matched.matches.is_empty() {
            continue;
        }
        let file = path.display().to_string();
        pattern
            .matches
            .lock()
            .unwrap()
            .extend(matched.matches.into_iter().map(|mut row| {
                row["file"] = serde_json::json!(file);
                row
            }));
    }
}

/// find_pattern — find AST nodes matching a `$VAR`/`$$$VAR` pattern.
///
/// Inputs: `pattern` (required); either `filePath`/`file` (search one file)
/// or `path` (search a directory tree — requires `language` since a tree may
/// mix extensions). Files with syntax errors are matched on tree-sitter's
/// error-recovered tree (matching `ast-grep run`), not skipped. A
/// `pattern_too_complex` error still fails a single-file call; in a directory
/// search it drops that one file rather than failing the whole call.
///
/// Output: `{ matches, guide? }`; each match is `{kind, text, span, captures,
/// file}` where
/// `captures` maps each meta-variable name to its matched node(s) — a single
/// node object for `$VAR`, an array for `$$$VAR`. `guide.truncated.matches`
/// reports shown and total counts when the bounded result omits matches.
pub fn find_pattern(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    find_pattern_with_compaction(input, true)
}

fn find_pattern_with_compaction(
    input: &serde_json::Value,
    compact: bool,
) -> Result<serde_json::Value, ApiError> {
    let options = match_options(input)?;
    let output = MatchOutputOptions {
        compact,
        window: options,
    };
    let pattern_text = req_str(input, "pattern")?;
    let target_path = pattern_target(input)?;
    let is_dir = target_path.is_dir();
    let lang = resolve_lang(input, (!is_dir).then_some(target_path))?;
    let (stripped, constraints) = split_kind_constraints(pattern_text);
    let rewritten = preprocess(&stripped);
    let relations = pattern_relations(input)?;
    let raw_parsed = crate::parse::parse_source(&lang, &rewritten);
    let wrapped = wrap_for_lang(&lang, &rewritten);
    let wrapped_parsed = crate::parse::parse_source(&lang, &wrapped);
    let pattern_root = locate_pattern_root(&raw_parsed, &wrapped_parsed, &rewritten)?;
    let pattern_root = &pattern_root;
    let pattern_meta = compile_pattern_meta(pattern_root);

    let atoms = mandatory_atoms(pattern_text);
    if !is_dir {
        return match_single_file(
            target_path,
            pattern_root,
            &pattern_meta,
            &lang,
            &constraints,
            &relations,
            output,
        );
    }
    let search = DirectoryPatternSearch::new(
        pattern_root,
        &pattern_meta,
        &lang,
        &constraints,
        &relations,
        &atoms,
        output,
    );
    finish_directory_search(search, target_path, output)
}

fn pattern_target(input: &serde_json::Value) -> Result<&std::path::Path, ApiError> {
    let target = input
        .get("filePath")
        .and_then(|value| value.as_str())
        .or_else(|| input.get("file").and_then(|value| value.as_str()))
        .or_else(|| input.get("path").and_then(|value| value.as_str()))
        .ok_or_else(|| {
            ApiError::new(
                "invalid_input",
                "missing filePath (or path for a directory search)",
            )
        })?;
    Ok(std::path::Path::new(target))
}

fn pattern_relations(input: &serde_json::Value) -> Result<Relations, ApiError> {
    Ok(Relations {
        inside: parse_relation_kind(input, "inside")?,
        has: parse_relation_kind(input, "has")?,
        precedes: parse_relation_kind(input, "precedes")?,
        follows: parse_relation_kind(input, "follows")?,
    })
}

fn finish_directory_search(
    search: DirectoryPatternSearch<'_, '_>,
    target_path: &std::path::Path,
    output: MatchOutputOptions,
) -> Result<serde_json::Value, ApiError> {
    let started = std::time::Instant::now();
    search.walk(target_path);
    search.report_profile(started.elapsed());
    let results = search.results.into_inner().unwrap();
    let total = results.total;
    let mut out = results.matches;
    sort_matches(&mut out);
    Ok(compact_matches(out, total, output.compact, output.window))
}

fn match_single_file(
    path: &std::path::Path,
    pattern_root: &PNode<'_>,
    pattern_meta: &PatternMeta,
    lang: &ast_grep_language::SupportLang,
    constraints: &HashMap<String, String>,
    relations: &Relations,
    output: MatchOutputOptions,
) -> Result<serde_json::Value, ApiError> {
    let source = std::fs::read_to_string(path)
        .map_err(|error| ApiError::new("file_error", format!("{}: {error}", path.display())))?;
    let matched = match_source(
        pattern_root,
        pattern_meta,
        lang,
        &source,
        constraints,
        relations,
        (output.compact && !output.window.full && output.window.offset == 0)
            .then_some(output.window.limit),
    )?;
    let out = matched
        .matches
        .into_iter()
        .map(|mut row| {
            row["file"] = serde_json::json!(path.display().to_string());
            row
        })
        .collect();
    Ok(compact_matches(
        out,
        matched.total,
        output.compact,
        output.window,
    ))
}

struct DirectoryPatternSearch<'a, 'p> {
    pattern_root: &'a PNode<'p>,
    pattern_meta: &'a PatternMeta,
    lang: &'a ast_grep_language::SupportLang,
    constraints: &'a HashMap<String, String>,
    relations: &'a Relations,
    atoms: &'a [String],
    output: MatchOutputOptions,
    results: std::sync::Mutex<MatchOutput>,
    scanned: std::sync::atomic::AtomicUsize,
    parsed: std::sync::atomic::AtomicUsize,
}

impl<'a, 'p> DirectoryPatternSearch<'a, 'p> {
    fn new(
        pattern_root: &'a PNode<'p>,
        pattern_meta: &'a PatternMeta,
        lang: &'a ast_grep_language::SupportLang,
        constraints: &'a HashMap<String, String>,
        relations: &'a Relations,
        atoms: &'a [String],
        output: MatchOutputOptions,
    ) -> Self {
        Self {
            pattern_root,
            pattern_meta,
            lang,
            constraints,
            relations,
            atoms,
            output,
            results: std::sync::Mutex::new(MatchOutput::default()),
            scanned: std::sync::atomic::AtomicUsize::new(0),
            parsed: std::sync::atomic::AtomicUsize::new(0),
        }
    }

    fn walk(&self, root: &std::path::Path) {
        ignore::WalkBuilder::new(root)
            .hidden(false)
            .filter_entry(|entry| !crate::scan::is_vcs_internal(entry))
            .build_parallel()
            .run(|| Box::new(|entry| self.visit(entry)))
    }

    fn visit(&self, entry: Result<ignore::DirEntry, ignore::Error>) -> ignore::WalkState {
        use std::sync::atomic::Ordering;
        let Ok(entry) = entry else {
            return ignore::WalkState::Continue;
        };
        let path = entry.path();
        if !path.is_file() || crate::parse::any_language_for_path(path).as_ref() != Some(self.lang)
        {
            return ignore::WalkState::Continue;
        }
        self.scanned.fetch_add(1, Ordering::Relaxed);
        let Ok(source) = std::fs::read_to_string(path) else {
            return ignore::WalkState::Continue;
        };
        if !self.atoms.iter().all(|atom| source.contains(atom)) {
            return ignore::WalkState::Continue;
        }
        self.parsed.fetch_add(1, Ordering::Relaxed);
        if let Ok(matched) = match_source(
            self.pattern_root,
            self.pattern_meta,
            self.lang,
            &source,
            self.constraints,
            self.relations,
            (self.output.compact && !self.output.window.full && self.output.window.offset == 0)
                .then_some(self.output.window.limit),
        ) {
            self.store(path, matched);
        }
        ignore::WalkState::Continue
    }

    fn store(&self, path: &std::path::Path, matched: MatchOutput) {
        let file = path.display().to_string();
        let mut local: Vec<_> = matched
            .matches
            .into_iter()
            .map(|mut row| {
                row["file"] = serde_json::json!(file);
                row
            })
            .collect();
        let mut results = self.results.lock().unwrap();
        results.total += matched.total;
        results.matches.append(&mut local);
        if self.output.compact
            && !self.output.window.full
            && self.output.window.offset == 0
            && results.matches.len() > self.output.window.limit
        {
            sort_matches(&mut results.matches);
            results.matches.truncate(self.output.window.limit);
        }
    }

    fn report_profile(&self, elapsed: std::time::Duration) {
        use std::sync::atomic::Ordering;
        if std::env::var_os("VARDE_PROFILE").is_none() {
            return;
        }
        let scanned = self.scanned.load(Ordering::Relaxed);
        let parsed = self.parsed.load(Ordering::Relaxed);
        let skipped_percent = if scanned > 0 {
            100.0 * (scanned - parsed) as f64 / scanned as f64
        } else {
            0.0
        };
        eprintln!(
            "VARDE_PROFILE find_pattern: walk+match={elapsed:?} matches={} atoms={:?} \
             scanned={scanned} parsed={parsed} skipped_by_prefilter={} ({skipped_percent:.0}%)",
            self.results.lock().unwrap().total,
            self.atoms,
            scanned - parsed,
        );
    }
}

fn sort_matches(matches: &mut [serde_json::Value]) {
    matches.sort_by(|a, b| {
        let fa = a["file"].as_str().unwrap_or("");
        let fb = b["file"].as_str().unwrap_or("");
        fa.cmp(fb).then_with(|| {
            let sa = a["span"]["start_byte"].as_u64().unwrap_or(0);
            let sb = b["span"]["start_byte"].as_u64().unwrap_or(0);
            sa.cmp(&sb)
        })
    });
}

fn compact_matches(
    mut matches: Vec<serde_json::Value>,
    total: usize,
    compact: bool,
    options: MatchOptions,
) -> serde_json::Value {
    if !compact {
        return serde_json::json!({ "matches": matches });
    }
    let start = options.offset.min(total);
    let end = if options.full {
        total
    } else {
        start.saturating_add(options.limit).min(total)
    };
    let truncated = start > 0 || end < total;
    if !truncated {
        return serde_json::json!({ "matches": matches });
    }
    matches = matches[start.min(matches.len())..end.min(matches.len())].to_vec();
    serde_json::json!({
        "matches": matches,
        "guide": { "truncated": { "matches": {
            "shown": end.saturating_sub(start),
            "total": total,
            "offset": start,
            "limit": if options.full { serde_json::Value::Null } else { serde_json::json!(options.limit) },
            "next_offset": if end < total { serde_json::json!(end) } else { serde_json::Value::Null },
            "request": if end < total {
                "set matchesOffset to next_offset, or set fullMatches to true"
            } else {
                "set fullMatches to true for all matches"
            }
        } } },
    })
}
