//! Python import resolution: module paths follow the filesystem.
//!
//! The generic matcher guesses from file stems and path suffixes, which for
//! Python can bind an unrelated same-named module anywhere in the repository.
//! Python imports follow package layout instead:
//!
//! - `from . import x` / `from ..pkg import x` resolve against the importing
//!   file's directory to `x.py` or `x/__init__.py`.
//! - `from pkg.sub import x` / `import pkg.sub` resolve the top-level package
//!   `pkg` to the one repository directory named `pkg` that has an
//!   `__init__.py`, then append the remaining path. Namespace packages (no
//!   `__init__.py`) and external packages yield nothing.
//!
//! Mirrors `rust_modules::resolve`: `Some(target)` is authoritative
//! (`Some(None)` means "this is a repository module path with no file in the
//! index"); `None` defers to the generic matcher, which is what an external or
//! ambiguous top-level package gets.

use std::path::Path;

use super::{ImportIndexes, normalize_path, strip_quotes};

pub(super) fn resolve(spec: &str, from_file: &str, idx: &ImportIndexes<'_>) -> Option<Option<u32>> {
    if crate::parse::language_for_path(Path::new(from_file))
        != Some(ast_grep_language::SupportLang::Python)
    {
        return None;
    }
    let raw = strip_quotes(spec).trim();
    if raw.is_empty() {
        return None;
    }
    if raw.starts_with("./") || raw.starts_with("../") {
        let base = super::resolve_relative(raw, from_file)?;
        return Some(unique_module(&base, idx));
    }
    let (first, rest) = raw.split_once('/').unwrap_or((raw, ""));
    if first.is_empty() {
        return None;
    }
    let mut roots = package_roots(first, idx);
    roots.dedup();
    if roots.len() != 1 {
        return None;
    }
    let base = if rest.is_empty() {
        roots[0].clone()
    } else {
        format!("{}/{rest}", roots[0])
    };
    Some(unique_module(&base, idx))
}

/// The one file `base.py`/`base/__init__.py` names, or `None` when the index
/// knows neither (a missing repository module) or both (ambiguous).
fn unique_module(base: &str, idx: &ImportIndexes<'_>) -> Option<u32> {
    let mut found = None;
    for candidate in [format!("{base}.py"), format!("{base}/__init__.py")] {
        let normalized = normalize_path(Path::new(&candidate))
            .to_string_lossy()
            .into_owned();
        let Some(&id) = idx.by_path.get(normalized.as_str()) else {
            continue;
        };
        if found.is_some_and(|seen| seen != id) {
            return None;
        }
        found = Some(id);
    }
    found
}

/// Repository directories whose last path segment is `first` and that carry an
/// `__init__.py` — the candidates for a Python top-level package name.
fn package_roots(first: &str, idx: &ImportIndexes<'_>) -> Vec<String> {
    let mut roots = Vec::new();
    for (id, lang) in idx.package.get(first).into_iter().flatten() {
        if *lang != Some(ast_grep_language::SupportLang::Python) {
            continue;
        }
        let Some(path) = idx.files.get(*id as usize) else {
            continue;
        };
        let Some(parent) = Path::new(path).parent() else {
            continue;
        };
        let root = normalize_path(parent).to_string_lossy().into_owned();
        if !root.is_empty() && !roots.contains(&root) {
            roots.push(root);
        }
    }
    roots
}

#[cfg(test)]
mod tests {
    #[test]
    fn top_level_package_split() {
        for (raw, first, rest) in [("pkg", "pkg", ""), ("pkg/sub/mod", "pkg", "sub/mod")] {
            assert_eq!(raw.split_once('/').unwrap_or((raw, "")), (first, rest));
        }
    }
}
