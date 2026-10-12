//! Lua and Bash dependency facts.
//!
//! Lua `require "a.b"` is a module path, not a file path. The extractor turns
//! the dots into slashes, so the fact builder looks for exactly one indexed
//! source file whose repository-relative path is `a/b.lua` or `a/b/init.lua`
//! (the conventional `lua/` prefix included). Two candidates are ambiguous and
//! a candidate the index does not know is not certified; `require(x)` and
//! concatenated arguments never become an import entity at all.
//!
//! Bash `source` / `.` is certified only for an explicitly relative literal
//! path (`./x.sh`, `../lib/x.sh`): `$VAR` expansions, command substitution,
//! globs, bare names and absolute paths are not repository-owned and yield no
//! fact. A `missing` fact is emitted only when the literal target has no
//! candidate at all. The unit is the file for both languages, and the physical
//! and indexed targets must agree exactly.

use super::{
    Fact, FactInput, FileRow, ImportRow, certified_fact, indexed_paths, metadata_if_exists,
    missing_fact, physical_targets, resolve_relative_path,
};
use std::collections::HashMap;
use std::path::{Path, PathBuf};

/// Certified dependency facts for Lua and Bash.
pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let indexed = indexed_paths(input.files);
    let mut facts = lua_facts(input, &by_id, &indexed)?;
    facts.extend(bash_facts(input, &by_id, &indexed)?);
    Ok(facts)
}

fn is_language(file: &FileRow, language: ast_grep_language::SupportLang) -> bool {
    crate::parse::language_for_path(Path::new(&file.path)) == Some(language)
}

/// The source's physical path minus its repository-relative path.
fn repository_root(source: &FileRow) -> PathBuf {
    let mut root = source.physical.clone();
    for _ in Path::new(&source.relative).components() {
        root.pop();
    }
    root
}

// ---- Lua ----

fn lua_facts(
    input: &FactInput<'_>,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
) -> Result<Vec<Fact>, String> {
    let candidates: Vec<&FileRow> = input
        .files
        .iter()
        .filter(|file| {
            !file.is_test
                && !file.is_tooling
                && is_language(file, ast_grep_language::SupportLang::Lua)
        })
        .collect();
    let mut facts = Vec::new();
    for source in input.files {
        if source.is_test
            || source.is_tooling
            || !is_language(source, ast_grep_language::SupportLang::Lua)
        {
            continue;
        }
        let root = repository_root(source);
        for import in imports_of(input, source) {
            if let Some(fact) = lua_fact(&root, by_id, indexed, &candidates, source, import)? {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

fn lua_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    candidates: &[&FileRow],
    source: &FileRow,
    import: &ImportRow,
) -> Result<Option<Fact>, String> {
    let module = import.specifier.as_str();
    if !is_lua_module(module) {
        return Ok(None);
    }
    let matches = lua_candidates(candidates, module);
    if matches.len() > 1 {
        return Ok(None);
    }
    if let Some(candidate) = matches.first() {
        let physical = root.join(candidate.replace('/', std::path::MAIN_SEPARATOR_STR));
        if !metadata_if_exists(&physical)?.is_some_and(|metadata| metadata.is_file()) {
            return Ok(None);
        }
        return Ok(match indexed.get(candidate).map(Vec::as_slice) {
            Some([target_id]) => certified_fact(by_id, source, import, *target_id),
            _ => None,
        });
    }
    if lua_module_is_repository_owned(candidates, module) {
        return Ok(Some(missing_fact(source, import)));
    }
    Ok(None)
}

/// Whether the literal names a dotted module (each segment an identifier).
fn is_lua_module(module: &str) -> bool {
    !module.is_empty()
        && !module.starts_with('/')
        && !module.ends_with('/')
        && module.split('/').all(|segment| {
            segment
                .chars()
                .next()
                .is_some_and(|first| first.is_ascii_alphabetic() || first == '_')
                && segment
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-'))
        })
}

/// Repository-relative paths of the `module.lua` and `module/init.lua`
/// candidates, deduplicated and sorted.
fn lua_candidates(candidates: &[&FileRow], module: &str) -> Vec<String> {
    let file = format!("{module}.lua");
    let init = format!("{module}/init.lua");
    let mut matches: Vec<String> = candidates
        .iter()
        .map(|candidate| candidate.relative.as_str())
        .filter(|relative| {
            *relative == file
                || *relative == init
                || relative.ends_with(&format!("/{file}"))
                || relative.ends_with(&format!("/{init}"))
        })
        .map(str::to_string)
        .collect();
    matches.sort();
    matches.dedup();
    matches
}

/// Whether a candidate-less module is repository-owned: its parent directory
/// exists directly at a Lua module root, which is the repository root
/// (`kong/deprecation.lua` for `require "kong.deprecation"`) or the repository
/// `lua/` directory Neovim plugins use (`lua/telescope/util.lua` for
/// `require "telescope.util"`). A dependency that OpenResty or a plugin
/// manager supplies from `package.path` never qualifies, even when an
/// unrelated namespace nests a same-named directory elsewhere (`kong/resty/`
/// does not own `require "resty.dns.resolver"`), so the parent prefix is
/// matched, never searched for anywhere in the path.
fn lua_module_is_repository_owned(candidates: &[&FileRow], module: &str) -> bool {
    let Some((parent, _leaf)) = module.rsplit_once('/') else {
        return false;
    };
    let at_root = format!("{parent}/");
    let under_lua = format!("lua/{parent}/");
    candidates
        .iter()
        .any(|file| file.relative.starts_with(&at_root) || file.relative.starts_with(&under_lua))
}

// ---- Bash ----

fn bash_facts(
    input: &FactInput<'_>,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
) -> Result<Vec<Fact>, String> {
    let mut facts = Vec::new();
    for source in input.files {
        if source.is_test
            || source.is_tooling
            || !is_language(source, ast_grep_language::SupportLang::Bash)
        {
            continue;
        }
        let root = repository_root(source);
        for import in imports_of(input, source) {
            if let Some(fact) = bash_fact(&root, by_id, indexed, source, import)? {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

fn bash_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    source: &FileRow,
    import: &ImportRow,
) -> Result<Option<Fact>, String> {
    let specifier = import.specifier.as_str();
    if !is_literal_relative_path(specifier) {
        return Ok(None);
    }
    let Some(base) = resolve_relative_path(&source.relative, specifier) else {
        return Ok(None);
    };
    let targets = physical_targets(root, vec![base.clone()])?;
    if targets.paths.len() == 1 {
        return Ok(match indexed.get(&base).map(Vec::as_slice) {
            Some([target_id]) => certified_fact(by_id, source, import, *target_id),
            _ => None,
        });
    }
    if targets.paths.is_empty() && !targets.existing_path {
        return Ok(Some(missing_fact(source, import)));
    }
    Ok(None)
}

/// An explicitly relative path made only of literal path characters. Bare
/// names depend on the caller's working directory, and `$VAR`, backtick,
/// command substitution, globs and absolute paths are not repository-owned.
fn is_literal_relative_path(specifier: &str) -> bool {
    if !(specifier.starts_with("./") || specifier.starts_with("../")) {
        return false;
    }
    if specifier.ends_with('/') || specifier.contains("//") {
        return false;
    }
    specifier
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '-' | '.' | '/' | '+'))
}

fn imports_of<'a>(input: &'a FactInput<'_>, source: &FileRow) -> Vec<&'a ImportRow> {
    input
        .imports
        .iter()
        .filter(|import| import.file_id == source.id && !import.type_only)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn lua_module_names_are_segment_identifiers() {
        for valid in ["a", "a/b", "kong/tools/utils", "a-b_c"] {
            assert!(is_lua_module(valid), "{valid}");
        }
        for invalid in ["", "/a", "a/", "a//b", "a b", "a?b", "$a", "a/b.c"] {
            assert!(!is_lua_module(invalid), "{invalid}");
        }
    }

    #[test]
    fn bash_literal_relative_paths_only() {
        for valid in ["./x.sh", "../lib/x.sh", "./a/b.bash", "./a_b-c+d.sh"] {
            assert!(is_literal_relative_path(valid), "{valid}");
        }
        for invalid in [
            "x.sh",
            "/etc/os-release",
            "$DIR/x.sh",
            "${DIR}/x.sh",
            "$(dirname \"$0\")/x.sh",
            "./x*.sh",
            "\"./x y.sh\"",
            "./x/",
            "./x//y.sh",
            "~/.x.sh",
            "./x.sh;rm",
        ] {
            assert!(!is_literal_relative_path(invalid), "{invalid}");
        }
    }
}
