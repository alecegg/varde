//! Ruby and PHP require dependency facts.
//!
//! Ruby certifies a literal `require_relative` target; PHP certifies a literal
//! `require`/`require_once`/`include`/`include_once` target that names a file
//! relative to the including file. The index keeps only the import specifier,
//! so the directives are re-read from the physical source and paired with the
//! import entities in order. A fact exists only when exactly one physical
//! candidate is also indexed exactly once; an explicitly relative target with
//! no candidate is missing. Dynamic or interpolated specifiers, `@`-suppressed
//! includes, rescued (guarded) requires and `__DIR__` concatenations that the
//! extractor never turns into a plain string import yield no fact.

use super::{
    Fact, FactInput, FileRow, ImportRow, certified_fact, indexed_paths, missing_fact,
    physical_targets, resolve_relative_path,
};
use ast_grep_core::Node;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Ruby require-family methods that name a dependency.
const RUBY_REQUIRE_FUNCTIONS: &[&str] = &["require", "require_relative", "load", "autoload"];

/// PHP require-family node kinds that name a dependency.
const PHP_REQUIRE_KINDS: &[&str] = &[
    "require_expression",
    "require_once_expression",
    "include_expression",
    "include_once_expression",
];

/// Certified dependency facts for Ruby and PHP.
pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let indexed = indexed_paths(input.files);
    let mut imports_by_file: HashMap<i64, Vec<&ImportRow>> = HashMap::new();
    for import in input.imports {
        imports_by_file
            .entry(import.file_id)
            .or_default()
            .push(import);
    }

    let mut facts = Vec::new();
    for source in input.files {
        if source.is_test || source.is_tooling {
            continue;
        }
        let lang = crate::parse::language_for_path(Path::new(&source.path));
        let is_ruby = lang == Some(SupportLang::Ruby);
        let is_php = lang == Some(SupportLang::Php);
        if !is_ruby && !is_php {
            continue;
        }
        let Some(imports) = imports_by_file.get(&source.id) else {
            continue;
        };
        let Ok(bytes) = std::fs::read(&source.physical) else {
            continue;
        };
        let text = String::from_utf8_lossy(&bytes);
        let requires = if is_ruby {
            ruby_requires(&text)
        } else {
            php_requires(&text)
        };
        let root = repository_root(source);
        let mut next = 0;
        for require in &requires {
            let Some(offset) = imports[next..]
                .iter()
                .position(|import| import.specifier == require.spec)
            else {
                continue;
            };
            let import = imports[next + offset];
            next += offset + 1;
            if import.type_only || !require.certifiable {
                continue;
            }
            if let Some(fact) = require_fact(&root, &by_id, &indexed, source, import, require)? {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

/// The repository root: the source's physical path minus its relative path.
fn repository_root(source: &FileRow) -> PathBuf {
    let mut root = source.physical.clone();
    for _ in Path::new(&source.relative).components() {
        root.pop();
    }
    root
}

/// A require-family directive re-read from the source, in source order.
struct Require {
    /// The specifier exactly as the extractor records it (so pairing matches).
    spec: String,
    /// False for dynamic/guarded forms: no fact, but still consumes its import
    /// row so later specifiers pair with the right entity.
    certifiable: bool,
    /// True when a target with no candidate is a genuine missing dependency.
    missing_eligible: bool,
    /// True for `require_relative` (candidates get a `.rb` suffix).
    ruby: bool,
}

fn require_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    source: &FileRow,
    import: &ImportRow,
    require: &Require,
) -> Result<Option<Fact>, String> {
    let Some(base) = resolve_relative_path(&source.relative, &require.spec) else {
        return Ok(None);
    };
    let candidates = candidate_paths(&base, require);
    let targets = physical_targets(root, candidates)?;
    let mut indexed_targets: Vec<i64> = Vec::new();
    for (path, _) in &targets.paths {
        if let Some(ids) = indexed.get(path) {
            indexed_targets.extend(ids.iter().copied());
        }
    }
    if targets.paths.len() == 1 && indexed_targets.len() == 1 {
        return Ok(certified_fact(by_id, source, import, indexed_targets[0]));
    }
    if targets.paths.is_empty() && !targets.existing_path && require.missing_eligible {
        return Ok(Some(missing_fact(source, import)));
    }
    Ok(None)
}

fn candidate_paths(base: &str, require: &Require) -> Vec<String> {
    if !require.ruby {
        return vec![base.to_string()];
    }
    match Path::new(base).extension().and_then(|value| value.to_str()) {
        Some(extension) if extension.eq_ignore_ascii_case("rb") => vec![base.to_string()],
        Some(_) => vec![base.to_string(), format!("{base}.rb")],
        None => vec![format!("{base}.rb")],
    }
}

// ---- Ruby ----

fn ruby_requires(text: &str) -> Vec<Require> {
    let parsed = crate::parse::parse_source(&SupportLang::Ruby, text);
    let mut requires = Vec::new();
    for node in parsed.root.root().dfs() {
        if node.kind().as_ref() != "call" {
            continue;
        }
        let Some(method) = node.field("method") else {
            continue;
        };
        let method = method.text();
        if !RUBY_REQUIRE_FUNCTIONS.contains(&method.as_ref()) {
            continue;
        }
        let Some(argument) = first_argument(&node) else {
            continue;
        };
        let Some(spec) = ruby_string_content(&argument) else {
            continue;
        };
        if spec.is_empty() {
            continue;
        }
        let relative = method.as_ref() == "require_relative";
        let guarded = ruby_guarded(&node);
        let dynamic = has_kind(&argument, "interpolation");
        let certifiable = relative && !guarded && !dynamic;
        requires.push(Require {
            spec,
            certifiable,
            missing_eligible: certifiable,
            ruby: true,
        });
    }
    requires
}

fn first_argument<'t>(
    node: &Node<'t, StrDoc<SupportLang>>,
) -> Option<Node<'t, StrDoc<SupportLang>>> {
    let args = node.children().find(|c| c.kind() == "argument_list")?;
    args.children()
        .find(|c| !matches!(c.kind().as_ref(), "(" | "," | ")"))
}

/// The literal runs of a Ruby `string` node, matching the extractor's spec.
fn ruby_string_content(node: &Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    if node.kind().as_ref() != "string" {
        return None;
    }
    Some(join_string_content(node))
}

/// A `require_relative` under `rescue` (or a `rescue` modifier) is guarded:
/// it may legitimately fail, so it certifies nothing.
fn ruby_guarded(node: &Node<'_, StrDoc<SupportLang>>) -> bool {
    node.ancestors().any(|ancestor| {
        ancestor.kind().as_ref() == "rescue_modifier" || has_kind(&ancestor, "rescue")
    })
}

// ---- PHP ----

fn php_requires(text: &str) -> Vec<Require> {
    let parsed = crate::parse::parse_source(&SupportLang::Php, text);
    let mut requires = Vec::new();
    for node in parsed.root.root().dfs() {
        if !PHP_REQUIRE_KINDS.contains(&node.kind().as_ref()) {
            continue;
        }
        let Some((argument, spec)) = first_string_child(&node) else {
            continue;
        };
        let spec = normalize_namespace(&spec);
        if spec.is_empty() {
            continue;
        }
        let guarded = php_suppressed(&node);
        let certifiable = !guarded && !php_dynamic(&argument);
        let missing_eligible = certifiable && is_explicitly_relative(&spec);
        requires.push(Require {
            spec,
            certifiable,
            missing_eligible,
            ruby: false,
        });
    }
    requires
}

/// The first direct string/encapsed-string child, as the extractor reads it.
fn first_string_child<'t>(
    node: &Node<'t, StrDoc<SupportLang>>,
) -> Option<(Node<'t, StrDoc<SupportLang>>, String)> {
    node.children()
        .find(|child| matches!(child.kind().as_ref(), "string" | "encapsed_string"))
        .map(|child| {
            let content = join_string_content(&child);
            (child, content)
        })
}

fn normalize_namespace(spec: &str) -> String {
    spec.trim_start_matches('\\').replace('\\', "/")
}

fn php_suppressed(node: &Node<'_, StrDoc<SupportLang>>) -> bool {
    node.ancestors()
        .any(|ancestor| ancestor.kind().as_ref() == "error_suppression_expression")
}

fn php_dynamic(node: &Node<'_, StrDoc<SupportLang>>) -> bool {
    node.children().any(|child| {
        matches!(
            child.kind().as_ref(),
            "variable_name"
                | "dynamic_variable_name"
                | "member_access_expression"
                | "subscript_expression"
                | "function_call_expression"
        )
    })
}

fn is_explicitly_relative(spec: &str) -> bool {
    spec.starts_with("./") || spec.starts_with("../")
}

// ---- shared ----

fn has_kind(node: &Node<'_, StrDoc<SupportLang>>, kind: &str) -> bool {
    node.children().any(|child| child.kind().as_ref() == kind)
}

fn join_string_content(node: &Node<'_, StrDoc<SupportLang>>) -> String {
    let mut out = String::new();
    for child in node.children() {
        if child.kind().as_ref() == "string_content" {
            out.push_str(child.text().as_ref());
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn ruby(text: &str) -> Vec<(String, bool, bool)> {
        ruby_requires(text)
            .into_iter()
            .map(|require| (require.spec, require.certifiable, require.missing_eligible))
            .collect()
    }

    fn php(text: &str) -> Vec<(String, bool, bool)> {
        php_requires(text)
            .into_iter()
            .map(|require| (require.spec, require.certifiable, require.missing_eligible))
            .collect()
    }

    #[test]
    fn ruby_certifies_only_plain_require_relative() {
        assert_eq!(
            ruby("require_relative 'b'\nrequire 'json'\nrequire_relative '../lib/util'\n"),
            [
                ("b".to_string(), true, true),
                ("json".to_string(), false, false),
                ("../lib/util".to_string(), true, true),
            ]
        );
    }

    #[test]
    fn ruby_guard_and_interpolation_certify_nothing() {
        assert_eq!(
            ruby("begin\n  require_relative 'gone'\nrescue LoadError\nend\n"),
            [("gone".to_string(), false, false)]
        );
        assert_eq!(
            ruby("require_relative \"#{dir}/gone\"\n"),
            [("/gone".to_string(), false, false)]
        );
    }

    #[test]
    fn php_certifies_literal_require_forms() {
        assert_eq!(
            php(
                "<?php\nrequire_once 'b.php';\nrequire './gone.php';\nrequire __DIR__ . '/x.php';\n"
            ),
            [
                ("b.php".to_string(), true, false),
                ("./gone.php".to_string(), true, true),
            ]
        );
    }

    #[test]
    fn php_suppressed_and_dynamic_include_certify_nothing() {
        assert_eq!(
            php(
                "<?php\n@include './x.php';\n$f = './y.php';\ninclude $f;\ninclude \"$dir/z.php\";\n"
            ),
            [
                ("./x.php".to_string(), false, false),
                ("/z.php".to_string(), false, false),
            ]
        );
    }
}
