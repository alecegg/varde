//! Rust module dependency facts.
//!
//! A unit is the module file path, as for the relative-import languages. Rust
//! allows intra-crate module cycles and its module tree makes them structural:
//! the parent declares the child (`mod child;`) and the child references the
//! parent (`use super::…`), and siblings commonly `use` each other. Only
//! cross-Cargo-package imports are certified, the compiled-dependency
//! granularity Rust shares with Go's package and C#'s project, so the
//! module-tree references inside one crate yield no fact. Certified edges are
//! the persisted module-aware resolutions from `resolve/rust_modules.rs` (the Go
//! builder's equivalent for Rust) and every target is checked to exist on disk
//! so physical and indexed views agree. An out-of-line `mod name;` declaration
//! whose candidate file is absent from both the index and the filesystem is a
//! `missing` fact, unless it is nested in an inline module or carries a
//! `#[path]` or `#[cfg]` attribute. Test and
//! tooling targets are excluded through the index's test-path flags,
//! `#[cfg]`-guarded imports are excluded because they exist only in some
//! builds, and external-crate paths never resolve to a local file.

use super::{Fact, FactInput, FileRow, IMPORT_KIND, ImportRow, metadata_if_exists, missing_fact};
use ast_grep_core::Node;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;
use std::collections::{HashMap, HashSet};
use std::path::Path;

pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let import_by_id: HashMap<i64, &ImportRow> = input
        .imports
        .iter()
        .map(|import| (import.id, import))
        .collect();
    let guarded = cfg_guarded_imports(input)?;
    let repo_root = repository_root(input.files);
    let mut facts = certified_facts(input, &by_id, &import_by_id, &guarded, repo_root.as_deref())?;
    facts.extend(missing_facts(input, &by_id, &guarded)?);
    Ok(facts)
}

/// The repository root: a file's physical path minus its relative path.
fn repository_root(files: &[FileRow]) -> Option<std::path::PathBuf> {
    let file = files.first()?;
    let mut root = file.physical.clone();
    for _ in Path::new(&file.relative).components() {
        root.pop();
    }
    Some(root)
}

/// Certified facts from the persisted module-aware edges.
fn certified_facts(
    input: &FactInput<'_>,
    by_id: &HashMap<i64, &FileRow>,
    import_by_id: &HashMap<i64, &ImportRow>,
    guarded: &HashMap<i64, HashSet<String>>,
    repo_root: Option<&Path>,
) -> Result<Vec<Fact>, String> {
    let mut units = HashMap::new();
    let mut facts = Vec::new();
    for edge in input.edges {
        if !edge.resolved {
            continue;
        }
        let Some(source) = by_id.get(&edge.from_file_id) else {
            continue;
        };
        if source.is_test || source.is_tooling || !is_rust(source) {
            continue;
        }
        let Some(entity_id) = edge.from_entity_id else {
            continue;
        };
        let Some(import) = import_by_id.get(&entity_id) else {
            continue;
        };
        if import.type_only || is_guarded(guarded, source.id, &import.specifier) {
            continue;
        }
        // A `mod child;` declaration is the module tree, not a dependency: the
        // parent→child edge it adds would pair with any `use` back to the
        // parent and report a structural cycle on virtually every Rust
        // directory module. Declaration edges still drive `missing` facts.
        if is_mod_declaration(&import.specifier) {
            continue;
        }
        let Some(target_id) = edge.to_file_id else {
            continue;
        };
        let Some(target) = by_id.get(&target_id) else {
            continue;
        };
        if !is_rust(target) || !physical_is_file(&target.physical)? {
            continue;
        }
        let from_unit = package_unit(source, repo_root, &mut units);
        let to_unit = package_unit(target, repo_root, &mut units);
        if from_unit == to_unit {
            continue;
        }
        facts.push(Fact {
            from_file_id: source.id,
            from_unit: source.relative.clone(),
            to_file_id: Some(target_id),
            to_unit: Some(target.relative.clone()),
            kind: IMPORT_KIND,
            certainty: "certified",
            source_entity_id: entity_id,
            specifier: import.specifier.clone(),
        });
    }
    Ok(facts)
}

/// The nearest ancestor directory with a `[package]` Cargo manifest, or the
/// file's own directory when the file is not inside a Cargo package. Compared
/// to decide whether an edge is cross-crate; cached by directory because one
/// crate holds hundreds of files.
fn package_unit(
    source: &FileRow,
    repo_root: Option<&Path>,
    cache: &mut HashMap<std::path::PathBuf, String>,
) -> String {
    let relative = Path::new(&source.relative);
    let parent = relative
        .parent()
        .unwrap_or_else(|| Path::new(""))
        .to_path_buf();
    if let Some(unit) = cache.get(&parent) {
        return unit.clone();
    }
    let unit = discover_package_unit(&parent, repo_root);
    cache.insert(parent, unit.clone());
    unit
}

fn discover_package_unit(dir: &Path, repo_root: Option<&Path>) -> String {
    let mut cursor = dir.to_path_buf();
    loop {
        if let Some(root) = repo_root
            && has_package_manifest(&root.join(&cursor))
        {
            return unit_path(&cursor);
        }
        match cursor.parent() {
            Some(parent) => cursor = parent.to_path_buf(),
            None => break,
        }
    }
    unit_path(dir)
}

fn has_package_manifest(dir: &Path) -> bool {
    let Ok(contents) = std::fs::read_to_string(dir.join("Cargo.toml")) else {
        return false;
    };
    contents.lines().any(|line| {
        let line = line.trim();
        line == "[package]" || line.starts_with("[package.")
    })
}

fn unit_path(dir: &Path) -> String {
    if dir.as_os_str().is_empty() {
        return ".".to_string();
    }
    dir.to_string_lossy()
        .replace(std::path::MAIN_SEPARATOR, "/")
}

/// `missing` facts for out-of-line module declarations with no candidate file.
fn missing_facts(
    input: &FactInput<'_>,
    by_id: &HashMap<i64, &FileRow>,
    guarded: &HashMap<i64, HashSet<String>>,
) -> Result<Vec<Fact>, String> {
    let mut facts = Vec::new();
    for import in input.imports {
        let Some(source) = by_id.get(&import.file_id) else {
            continue;
        };
        if source.is_test || source.is_tooling || !is_rust(source) || import.type_only {
            continue;
        }
        let Some(segments) = mod_segments(&import.specifier) else {
            continue;
        };
        // A declaration nested in an inline module reaches us as
        // `mod outer::inner`, but the extractor drops any `#[path]` attribute
        // on nested declarations. With the attribute invisible here, an absent
        // candidate file cannot be told from a renamed one, so never certify
        // `missing` for a nested declaration.
        if segments.len() > 1 {
            continue;
        }
        if is_guarded(guarded, source.id, &import.specifier) {
            continue;
        }
        if module_candidate_exists(source, &segments)? {
            continue;
        }
        facts.push(missing_fact(source, import));
    }
    Ok(facts)
}

fn is_guarded(guarded: &HashMap<i64, HashSet<String>>, file_id: i64, specifier: &str) -> bool {
    guarded
        .get(&file_id)
        .is_some_and(|specs| specs.contains(specifier))
}

fn is_rust(file: &FileRow) -> bool {
    crate::parse::language_for_path(Path::new(&file.path)) == Some(SupportLang::Rust)
}

fn physical_is_file(path: &Path) -> Result<bool, String> {
    Ok(metadata_if_exists(path)?.is_some_and(|metadata| metadata.is_file()))
}

/// The candidate files the resolver would load for `mod a::b`, relative to the
/// declaring file. Both crate-root and non-root bases are checked so a file the
/// index skipped can never be reported missing.
fn module_candidate_exists(source: &FileRow, segments: &[&str]) -> Result<bool, String> {
    let relative = Path::new(&source.relative);
    let stem = relative
        .file_stem()
        .and_then(|value| value.to_str())
        .unwrap_or_default();
    let Some(physical_parent) = source.physical.parent() else {
        return Ok(true);
    };
    let mut bases = vec![physical_parent.to_path_buf()];
    if !stem.is_empty() {
        bases.push(physical_parent.join(stem));
    }
    let Some((last, parents)) = segments.split_last() else {
        return Ok(true);
    };
    for base in bases {
        let mut dir = base;
        for segment in parents {
            dir.push(segment);
        }
        let candidates = [
            dir.join(format!("{last}.rs")),
            dir.join(last).join("mod.rs"),
        ];
        for candidate in candidates {
            if physical_is_file(&candidate)? {
                return Ok(true);
            }
        }
    }
    Ok(false)
}

/// `mod a::b` -> `["a", "b"]`; `#[path = "x.rs"] mod b` and `use` paths -> None.
fn mod_segments(specifier: &str) -> Option<Vec<&str>> {
    let module = specifier.strip_prefix("mod ")?;
    let segments: Vec<&str> = module
        .split("::")
        .map(str::trim)
        .filter(|segment| !segment.is_empty())
        .collect();
    (!segments.is_empty()).then_some(segments)
}

fn is_mod_declaration(specifier: &str) -> bool {
    specifier.starts_with("mod ") || specifier.starts_with("#[path")
}

/// The exact import specifiers under a `#[cfg]`-guarded declaration or
/// module, keyed by file id. `use` paths inside a `#[cfg(test)] mod tests`
/// block are the dominant Rust test idiom, and a cfg-gated dependency exists
/// only in some builds, so neither may certify. Only files that carry imports
/// and mention `cfg` are parsed.
fn cfg_guarded_imports(input: &FactInput<'_>) -> Result<HashMap<i64, HashSet<String>>, String> {
    let imported_files: HashSet<i64> = input.imports.iter().map(|import| import.file_id).collect();
    let mut guarded = HashMap::new();
    for file in input.files {
        if !imported_files.contains(&file.id) || file.is_test || file.is_tooling || !is_rust(file) {
            continue;
        }
        // Skip a file that cannot be read instead of failing every dependency
        // rule: a removed or non-UTF-8 source is not a certification error.
        let Ok(bytes) = std::fs::read(&file.physical) else {
            continue;
        };
        let source = String::from_utf8_lossy(&bytes);
        if !source.contains("cfg") {
            continue;
        }
        let parsed = crate::parse::parse_source(&SupportLang::Rust, &source);
        let mut ranges = Vec::new();
        collect_cfg_ranges(&parsed.root.root(), &mut ranges);
        if ranges.is_empty() {
            continue;
        }
        let specs = guarded_import_specs(&parsed, &ranges);
        if !specs.is_empty() {
            guarded.insert(file.id, specs);
        }
    }
    Ok(guarded)
}

/// Byte ranges of every `#[cfg]`-attributed node. The walk stops at a guarded
/// node because its whole subtree is conditional.
fn collect_cfg_ranges(node: &Node<'_, StrDoc<SupportLang>>, ranges: &mut Vec<(u32, u32)>) {
    if has_cfg_attribute(node) {
        let span = crate::extract::span_of(node);
        ranges.push((span.start_byte, span.end_byte));
        return;
    }
    for child in node.children() {
        collect_cfg_ranges(&child, ranges);
    }
}

/// The specifiers the extractor emitted for imports whose span falls inside a
/// guarded range.
fn guarded_import_specs(
    parsed: &crate::parse::ParsedFile,
    ranges: &[(u32, u32)],
) -> HashSet<String> {
    crate::extract::extract(parsed, 0)
        .entities
        .into_iter()
        .filter(|entity| entity.kind == crate::model::EntityKind::Import)
        .filter(|entity| {
            ranges.iter().any(|&(start, end)| {
                entity.span.start_byte >= start && entity.span.start_byte < end
            })
        })
        .map(|entity| entity.name)
        .collect()
}

/// `#[cfg(...)]` among the attributes directly above the declaration.
fn has_cfg_attribute(node: &Node<'_, StrDoc<SupportLang>>) -> bool {
    for sibling in node.prev_all() {
        match sibling.kind().as_ref() {
            "attribute_item" => {
                let text = sibling.text();
                if attribute_inner(&text).is_some_and(|attr| {
                    attr == "cfg" || attr.starts_with("cfg(") || attr.starts_with("cfg_attr(")
                }) {
                    return true;
                }
            }
            "line_comment" | "block_comment" => {}
            _ => return false,
        }
    }
    false
}

fn attribute_inner(text: &str) -> Option<&str> {
    text.trim()
        .strip_prefix("#[")
        .and_then(|rest| rest.strip_suffix(']'))
        .map(str::trim)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn guarded_specs(source: &str) -> HashSet<String> {
        let parsed = crate::parse::parse_source(&SupportLang::Rust, source);
        let mut ranges = Vec::new();
        collect_cfg_ranges(&parsed.root.root(), &mut ranges);
        guarded_import_specs(&parsed, &ranges)
    }

    #[test]
    fn cfg_guarded_modules_and_uses_are_collected() {
        let source = "\
#[cfg(test)]
mod tests {
    use crate::extract;
}

#[cfg(feature = \"extra\")]
#[path = \"custom.rs\"]
mod custom;

mod plain;
use crate::other;
";
        let specs = guarded_specs(source);
        assert!(specs.contains("crate::extract"), "{specs:?}");
        assert!(
            specs.contains("#[path = \"custom.rs\"] mod custom"),
            "{specs:?}"
        );
        assert!(!specs.contains("crate::other"), "{specs:?}");
    }

    #[test]
    fn direct_cfg_attribute_on_a_use_is_collected() {
        let source = "#[cfg(unix)]\nuse crate::unix_only::Thing;\nuse crate::always::Thing;\n";
        let specs = guarded_specs(source);
        assert!(specs.contains("crate::unix_only::Thing"), "{specs:?}");
        assert!(!specs.contains("crate::always::Thing"), "{specs:?}");
    }

    #[test]
    fn mod_segments_only_accepts_module_declarations() {
        assert_eq!(mod_segments("mod a::b"), Some(vec!["a", "b"]));
        assert_eq!(mod_segments("#[path = \"x.rs\"] mod a"), None);
        assert_eq!(mod_segments("crate::a::B"), None);
    }
}
