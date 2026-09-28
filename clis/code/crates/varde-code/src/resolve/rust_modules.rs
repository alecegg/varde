//! Rust module-path resolution: `mod foo;` declarations and
//! `crate::`/`self::`/`super::` `use` paths mapped to the files that define
//! those modules.
//!
//! The generic import matcher guesses from file stems and path suffixes. Rust
//! paths follow fixed filesystem rules instead, so they are resolved here
//! against the importing file's module location:
//!
//! - `mod foo;` in a crate root or `mod.rs` file loads `dir/foo.rs` or
//!   `dir/foo/mod.rs`; in any other file `dir/stem.rs` it loads
//!   `dir/stem/foo.rs` or `dir/stem/foo/mod.rs`.
//! - `#[path = "x.rs"] mod foo;` (outside inline modules) loads `x.rs` relative
//!   to the declaring file's directory.
//! - `crate::a::b::C` walks from the crate root directory to the longest module
//!   prefix that maps to a file; `self::`/`super::` walk from the current
//!   module. A path that names only the module itself (`use super::*`) maps to
//!   that module's own file.
//! - The package's own library crate name (from a binary target) and path or
//!   workspace path dependencies resolve into that crate's `src/` modules.
//!
//! A path whose base cannot be located (no Cargo package, no `lib.rs`/`main.rs`
//! above the file) returns `None`, and the caller falls back to the generic
//! matcher.

use std::path::{Path, PathBuf};

use super::{ImportIndexes, normalize_path, strip_quotes};

/// Resolve a Rust import specifier from `from_file`.
///
/// `Some(target)` is authoritative (`Some(None)` means "this is a module path
/// with no file in the index"); `None` means this resolver does not apply and
/// the generic matcher should run.
pub(super) fn resolve(spec: &str, from_file: &str, idx: &ImportIndexes<'_>) -> Option<Option<u32>> {
    let raw = strip_quotes(spec).trim();
    let from_id = idx.by_path.get(from_file).copied();
    let from = Path::new(from_file);
    let ctx = FileContext::new(from, from_id, idx);

    if let Some((path_attr, module)) = parse_mod_declaration(raw) {
        if let Some(path_attr) = path_attr {
            let target = normalize_path(&from.parent()?.join(path_attr));
            return Some(lookup(&target, idx).filter(|&id| Some(id) != from_id));
        }
        let base = ctx.module_child_dir()?;
        let segments: Vec<&str> = module.split("::").map(str::trim).collect();
        return Some(module_file(&base, &segments, idx).filter(|&id| Some(id) != from_id));
    }

    // A leading `::` names an external crate (2018+ edition).
    if raw.starts_with("::") {
        return Some(None);
    }
    let segments = use_path_segments(raw);
    let (&first, rest) = segments.split_first()?;
    let (base, rest, crate_root) = match first {
        "crate" => (ctx.crate_root_dir()?, rest, ctx.crate_root.clone()),
        "self" | "super" => {
            let mut base = ctx.module_child_dir()?;
            let mut rest: &[&str] = &segments;
            if rest.first() == Some(&"self") {
                rest = &rest[1..];
            }
            while rest.first() == Some(&"super") {
                base = base.parent()?.to_path_buf();
                rest = &rest[1..];
            }
            (base, rest, ctx.crate_root.clone())
        }
        name => {
            if let Some(base) = ctx.named_crate_dir(name, idx) {
                (base.clone(), rest, Some(base))
            } else {
                // 2018 edition: a bare path may name a child of the current
                // module. Only claim it when that child module exists.
                let base = ctx.module_child_dir()?;
                module_file(&base, &[name], idx)?;
                (base, &segments[..], ctx.crate_root.clone())
            }
        }
    };
    Some(
        longest_prefix_file(&base, rest, crate_root.as_deref(), idx)
            .filter(|&id| Some(id) != from_id),
    )
}

/// Parse `mod a::b` / `#[path = "x.rs"] mod b` import names emitted by the
/// Rust extractor for out-of-line module declarations.
fn parse_mod_declaration(raw: &str) -> Option<(Option<&str>, &str)> {
    if let Some(module) = raw.strip_prefix("mod ") {
        return Some((None, module.trim()));
    }
    let rest = raw.strip_prefix("#[path = \"")?;
    let (path, rest) = rest.split_once("\"]")?;
    let module = rest.trim_start().strip_prefix("mod ")?;
    Some((Some(path), module.trim()))
}

/// `crate::a::{b, c}` / `super::*` / `a::B as C` → the plain module-path
/// segments (`["crate", "a"]`, `["super"]`, `["a", "B"]`).
fn use_path_segments(raw: &str) -> Vec<&str> {
    let path = raw.split(" as ").next().unwrap_or(raw);
    path.split("::")
        .map(str::trim)
        .take_while(|segment| !segment.is_empty() && *segment != "*" && !segment.starts_with('{'))
        .collect()
}

/// Where the importing file sits in its crate.
struct FileContext<'a> {
    from: &'a Path,
    package_root: Option<PathBuf>,
    crate_root: Option<PathBuf>,
    is_crate_root_file: bool,
    package: Option<&'a super::RustPackageInfo>,
}

impl<'a> FileContext<'a> {
    fn new(from: &'a Path, from_id: Option<u32>, idx: &'a ImportIndexes<'_>) -> Self {
        let package = from_id
            .and_then(|id| idx.rust_packages.get(id as usize))
            .and_then(Option::as_ref)
            .map(AsRef::as_ref);
        let package_root = package.map(|package| package.root.clone());
        let (crate_root, is_crate_root_file) = crate_root(from, package_root.as_deref(), idx);
        FileContext {
            from,
            package_root,
            crate_root,
            is_crate_root_file,
            package,
        }
    }

    /// Directory holding the child-module files of the importing file.
    fn module_child_dir(&self) -> Option<PathBuf> {
        let parent = self.from.parent()?;
        let name = self.from.file_name()?.to_str()?;
        if self.is_crate_root_file || matches!(name, "lib.rs" | "main.rs" | "mod.rs") {
            Some(parent.to_path_buf())
        } else {
            Some(parent.join(self.from.file_stem()?))
        }
    }

    fn crate_root_dir(&self) -> Option<PathBuf> {
        self.crate_root.clone()
    }

    /// `src/` of a named local crate: the package's own library (used from a
    /// binary target) or a path/workspace-path dependency.
    fn named_crate_dir(&self, name: &str, idx: &ImportIndexes<'_>) -> Option<PathBuf> {
        let package = self.package?;
        let root = if package.lib_name.as_deref() == Some(name) {
            self.package_root.clone()?
        } else {
            package.path_dependency_crates.get(name)?.clone()
        };
        let src = root.join("src");
        lookup(&src.join("lib.rs"), idx).map(|_| src)
    }
}

/// The crate root directory for `from`, and whether `from` is itself a crate
/// root file (whose child modules live beside it, like `lib.rs`).
fn crate_root(
    from: &Path,
    package_root: Option<&Path>,
    idx: &ImportIndexes<'_>,
) -> (Option<PathBuf>, bool) {
    if let Some(root) = package_root
        && let Ok(relative) = from.strip_prefix(root)
    {
        let parts: Vec<&str> = relative.iter().filter_map(|part| part.to_str()).collect();
        match parts.as_slice() {
            ["build.rs"] => return (Some(root.to_path_buf()), true),
            ["src", "bin", _file] => return (Some(root.join("src/bin")), true),
            ["src", "bin", dir, ..] => {
                return (target_dir_root(&root.join("src/bin"), dir, idx), false);
            }
            ["src", ..] => return (Some(root.join("src")), false),
            [kind @ ("tests" | "benches" | "examples"), _file] => {
                return (Some(root.join(kind)), true);
            }
            [kind @ ("tests" | "benches" | "examples"), dir, ..] => {
                return (target_dir_root(&root.join(kind), dir, idx), false);
            }
            _ => {}
        }
    }
    // No Cargo layout to go by: the nearest directory holding a crate root file.
    let root = from.ancestors().skip(1).find(|dir| {
        lookup(&dir.join("lib.rs"), idx).is_some() || lookup(&dir.join("main.rs"), idx).is_some()
    });
    (root.map(Path::to_path_buf), false)
}

/// `tests/foo/main.rs` is its own crate rooted at `tests/foo`; any other
/// `tests/dir/..` file is a module of a `tests/*.rs` crate rooted at `tests`.
fn target_dir_root(kind_dir: &Path, dir: &str, idx: &ImportIndexes<'_>) -> Option<PathBuf> {
    let candidate = kind_dir.join(dir);
    if lookup(&candidate.join("main.rs"), idx).is_some() {
        Some(candidate)
    } else {
        Some(kind_dir.to_path_buf())
    }
}

/// File defining module `segments` under `base`: `base/a/b.rs` or
/// `base/a/b/mod.rs`.
fn module_file(base: &Path, segments: &[&str], idx: &ImportIndexes<'_>) -> Option<u32> {
    let mut dir = base.to_path_buf();
    let (last, parents) = segments.split_last()?;
    for segment in parents {
        dir.push(segment);
    }
    lookup(&dir.join(format!("{last}.rs")), idx)
        .or_else(|| lookup(&dir.join(last).join("mod.rs"), idx))
}

/// Longest prefix of `segments` that names a module file under `base`; with
/// no matching prefix, the file of the module `base` itself.
fn longest_prefix_file(
    base: &Path,
    segments: &[&str],
    crate_root: Option<&Path>,
    idx: &ImportIndexes<'_>,
) -> Option<u32> {
    (1..=segments.len())
        .rev()
        .find_map(|len| module_file(base, &segments[..len], idx))
        .or_else(|| own_module_file(base, crate_root, idx))
}

/// The file that defines the module whose children live in `dir`.
fn own_module_file(dir: &Path, crate_root: Option<&Path>, idx: &ImportIndexes<'_>) -> Option<u32> {
    if crate_root == Some(dir) {
        return lookup(&dir.join("lib.rs"), idx).or_else(|| lookup(&dir.join("main.rs"), idx));
    }
    lookup(&dir.join("mod.rs"), idx).or_else(|| lookup(&dir.with_extension("rs"), idx))
}

fn lookup(path: &Path, idx: &ImportIndexes<'_>) -> Option<u32> {
    idx.by_path.get(path.to_str()?).copied()
}
