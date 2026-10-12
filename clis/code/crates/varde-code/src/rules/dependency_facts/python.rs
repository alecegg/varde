//! Python import dependency facts.
//!
//! A Python import names a module, not a file path. Facts are certified only
//! when the module resolves to exactly one indexed file:
//!
//! - a relative import (`from . import x`, `from ..pkg import x`) resolves
//!   against the importing file's package directory to `x.py` or
//!   `x/__init__.py`;
//! - an absolute import (`import pkg.sub`, `from pkg.sub import x`) resolves
//!   the top-level package name to the one repository directory with an
//!   `__init__.py`, then appends the remaining path.
//!
//! Imports inside a `TYPE_CHECKING` block or a `try`/`except ImportError`
//! guard are not runtime dependencies and yield nothing. Namespace packages
//! (no `__init__.py`), external packages and ambiguous targets yield nothing.
//! A `missing` fact is emitted only when the importing directory is itself a
//! package and the relative module names neither `a.py` nor an `a/` directory;
//! the bare `from . import name` form may be an `__init__.py` attribute, so it
//! stays ambiguous and is never reported missing. The extractor drops the
//! imported names from the specifier, so the directives are re-read from the
//! physical source and paired with the import entities in order.

use super::{
    Fact, FactInput, FileRow, ImportRow, certified_fact, indexed_paths, missing_fact,
    physical_targets, resolve_relative_path,
};
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;
use std::collections::HashMap;
use std::path::{Path, PathBuf};

pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let indexed = indexed_paths(input.files);
    let package_roots = package_roots(input.files);
    let mut facts = Vec::new();
    for source in input.files {
        if source.is_test || source.is_tooling || !is_python(source) {
            continue;
        }
        let imports = imports_of(input, source);
        if imports.is_empty() {
            continue;
        }
        let Ok(bytes) = std::fs::read(&source.physical) else {
            continue;
        };
        let root = repository_root(source);
        for (import, record) in
            pair_imports(&imports, scan_imports(&String::from_utf8_lossy(&bytes)))
        {
            if import.type_only || record.guarded {
                continue;
            }
            if let Some(fact) = python_fact(
                &root,
                &by_id,
                &indexed,
                &package_roots,
                source,
                import,
                record.attribute_form,
            )? {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

fn is_python(file: &FileRow) -> bool {
    crate::parse::language_for_path(Path::new(&file.path)) == Some(SupportLang::Python)
}

/// The source's physical path minus its repository-relative path.
fn repository_root(source: &FileRow) -> PathBuf {
    let mut root = source.physical.clone();
    for _ in Path::new(&source.relative).components() {
        root.pop();
    }
    root
}

fn imports_of<'a>(input: &'a FactInput<'_>, source: &FileRow) -> Vec<&'a ImportRow> {
    input
        .imports
        .iter()
        .filter(|import| import.file_id == source.id)
        .collect()
}

/// Directories that carry an `__init__.py` and sit at a source root, keyed by
/// their last path segment: the candidate roots for a Python top-level package
/// name. A directory nested below a source root (`plugins/platforms/email`) is
/// not importable as the top-level package `email`, so a standard-library or
/// third-party name it shadows stays external and yields no fact.
fn package_roots(files: &[FileRow]) -> HashMap<String, Vec<String>> {
    let mut roots: HashMap<String, Vec<String>> = HashMap::new();
    for file in files {
        let path = Path::new(&file.relative);
        if path.file_name().and_then(|name| name.to_str()) != Some("__init__.py") {
            continue;
        }
        let Some(parent) = path.parent() else {
            continue;
        };
        let dir = parent
            .to_string_lossy()
            .replace(std::path::MAIN_SEPARATOR, "/");
        if dir.is_empty() {
            continue;
        }
        let grandparent = Path::new(&dir)
            .parent()
            .map(|parent| {
                parent
                    .to_string_lossy()
                    .replace(std::path::MAIN_SEPARATOR, "/")
            })
            .unwrap_or_default();
        if !is_source_root(&grandparent) {
            continue;
        }
        let name = dir.rsplit('/').next().unwrap_or_default().to_string();
        let entries = roots.entry(name).or_default();
        if !entries.contains(&dir) {
            entries.push(dir);
        }
    }
    roots
}

/// The repository root and `src`/`*/src` directories are the standard places a
/// Python top-level package can live.
fn is_source_root(dir: &str) -> bool {
    dir.is_empty() || dir == "src" || dir.ends_with("/src")
}

/// `base.py` and `base/__init__.py`, the two files a Python module path names.
fn module_candidates(base: &str) -> Vec<String> {
    vec![format!("{base}.py"), format!("{base}/__init__.py")]
}

fn python_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    package_roots: &HashMap<String, Vec<String>>,
    source: &FileRow,
    import: &ImportRow,
    attribute_form: bool,
) -> Result<Option<Fact>, String> {
    let spec = import.specifier.as_str();
    if spec.starts_with("./") || spec.starts_with("../") {
        if !source_is_package(source, indexed) {
            return Ok(None);
        }
        let Some(base) = resolve_relative_path(&source.relative, spec) else {
            return Ok(None);
        };
        return relative_fact(root, by_id, indexed, source, import, &base, attribute_form);
    }
    if !is_module_path(spec) {
        return Ok(None);
    }
    let (first, rest) = spec.split_once('/').unwrap_or((spec, ""));
    let Some(roots) = package_roots.get(first) else {
        return Ok(None);
    };
    let mut roots = roots.iter();
    let Some(root_dir) = roots.next() else {
        return Ok(None);
    };
    if roots.next().is_some() {
        return Ok(None);
    }
    let base = if rest.is_empty() {
        root_dir.clone()
    } else {
        format!("{root_dir}/{rest}")
    };
    Ok(certified_target(
        root, by_id, indexed, source, import, &base,
    )?)
}

fn relative_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    source: &FileRow,
    import: &ImportRow,
    base: &str,
    attribute_form: bool,
) -> Result<Option<Fact>, String> {
    let targets = physical_targets(root, module_candidates(base))?;
    if targets.paths.len() == 1 {
        return Ok(match indexed.get(&targets.paths[0].0).map(Vec::as_slice) {
            Some([target_id]) => certified_fact(by_id, source, import, *target_id),
            _ => None,
        });
    }
    if !targets.paths.is_empty() || targets.existing_path {
        return Ok(None);
    }
    if attribute_form || has_sibling_with_stem(root, base) {
        return Ok(None);
    }
    Ok(Some(missing_fact(source, import)))
}

/// The single indexed file `base` names, or no fact when the index knows
/// neither candidate or more than one.
fn certified_target(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    source: &FileRow,
    import: &ImportRow,
    base: &str,
) -> Result<Option<Fact>, String> {
    let targets = physical_targets(root, module_candidates(base))?;
    if targets.paths.len() != 1 {
        return Ok(None);
    }
    Ok(match indexed.get(&targets.paths[0].0).map(Vec::as_slice) {
        Some([target_id]) => certified_fact(by_id, source, import, *target_id),
        _ => None,
    })
}

/// Whether the importing file's own directory has an `__init__.py`. Python
/// relative imports are only valid inside a package, and this also excludes
/// PEP 420 namespace packages.
fn source_is_package(source: &FileRow, indexed: &HashMap<String, Vec<i64>>) -> bool {
    let path = Path::new(&source.relative);
    let Some(parent) = path.parent() else {
        return false;
    };
    let dir = parent
        .to_string_lossy()
        .replace(std::path::MAIN_SEPARATOR, "/");
    let init = if dir.is_empty() {
        "__init__.py".to_string()
    } else {
        format!("{dir}/__init__.py")
    };
    indexed.contains_key(&init)
}

/// Whether a physical file beside the module path already uses that name with
/// any extension (a C extension, a stub, a generated file), so a module that
/// the index does not carry is not reported missing.
fn has_sibling_with_stem(root: &Path, base: &str) -> bool {
    let path = Path::new(base);
    let Some(name) = path.file_name() else {
        return false;
    };
    let parent = path.parent().unwrap_or_else(|| Path::new(""));
    let dir = root.join(
        parent
            .to_string_lossy()
            .replace('/', std::path::MAIN_SEPARATOR_STR),
    );
    let Ok(entries) = std::fs::read_dir(&dir) else {
        return false;
    };
    let name = name.to_string_lossy();
    entries.flatten().any(|entry| {
        entry
            .path()
            .file_stem()
            .is_some_and(|stem| stem.to_string_lossy().as_ref() == name.as_ref())
    })
}

/// A dotted module path as the extractor emits it: slash-separated identifier
/// segments. Anything else (macros, `*`, absolute paths) is not certified.
fn is_module_path(spec: &str) -> bool {
    !spec.is_empty()
        && !spec.starts_with('/')
        && spec.split('/').all(|segment| {
            segment
                .chars()
                .next()
                .is_some_and(|first| first.is_ascii_alphabetic() || first == '_')
                && segment
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '_')
        })
}

// ---- source scan: guard flags and specifiers, extractor-aligned ----

struct PyImport {
    spec: String,
    guarded: bool,
    attribute_form: bool,
}

fn scan_imports(text: &str) -> Vec<PyImport> {
    let parsed = crate::parse::parse_source(&SupportLang::Python, text);
    let mut out = Vec::new();
    for node in parsed.root.root().dfs() {
        match node.kind().as_ref() {
            "import_statement" => {
                let guarded = is_guarded(&node);
                for name in node.field_children("name") {
                    if let Some(spec) = python_dotted_path(&name) {
                        out.push(PyImport {
                            spec,
                            guarded,
                            attribute_form: false,
                        });
                    }
                }
            }
            "import_from_statement" => {
                let Some(module) = node.field("module_name") else {
                    continue;
                };
                let guarded = is_guarded(&node);
                let mut spec = python_import_module(&module);
                let mut attribute_form = false;
                if spec.ends_with('/') || spec.is_empty() {
                    attribute_form = true;
                    if let Some(name) = node
                        .field_children("name")
                        .next()
                        .and_then(|name| python_dotted_path(&name))
                    {
                        spec.push_str(&name);
                    }
                }
                if spec.is_empty() {
                    continue;
                }
                out.push(PyImport {
                    spec,
                    guarded,
                    attribute_form,
                });
            }
            _ => {}
        }
    }
    out
}

/// A `if TYPE_CHECKING:` block or a `try` with an `except` that catches
/// `ImportError` (or a supertype) makes the import optional at runtime.
fn is_guarded(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    node.ancestors()
        .skip(1)
        .any(|ancestor| match ancestor.kind().as_ref() {
            "if_statement" => ancestor
                .field("condition")
                .is_some_and(|condition| condition.text().contains("TYPE_CHECKING")),
            "try_statement" => ancestor.children().any(|child| {
                child.kind().as_ref() == "except_clause" && except_catches_import_error(&child)
            }),
            _ => false,
        })
}

fn except_catches_import_error(clause: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> bool {
    let text = clause.text();
    let after = text
        .split_once("except")
        .map(|(_, rest)| rest)
        .unwrap_or(text.as_ref());
    let after = after.trim().trim_end_matches(':').trim();
    after.is_empty()
        || [
            "ImportError",
            "ModuleNotFoundError",
            "Exception",
            "BaseException",
        ]
        .iter()
        .any(|name| after.contains(name))
}

fn python_import_module(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    if node.kind().as_ref() == "relative_import" {
        python_relative_import_path(node)
    } else {
        python_dotted_path(node).unwrap_or_default()
    }
}

/// Slash-normalized dotted path from a `dotted_name` (or the `dotted_name`
/// nested in an `aliased_import`'s `name` field for `import x as y`).
fn python_dotted_path(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> Option<String> {
    let dotted = if node.kind().as_ref() == "aliased_import" {
        node.field("name")?
    } else {
        node.clone()
    };
    Some(dotted.text().replace('.', "/"))
}

/// `from . import x` / `from ..pkg import y` -> a `./`/`../`-prefixed path.
fn python_relative_import_path(node: &ast_grep_core::Node<'_, StrDoc<SupportLang>>) -> String {
    let dots = node
        .children()
        .find(|c| c.kind().as_ref() == "import_prefix")
        .map(|c| c.text().chars().filter(|&ch| ch == '.').count())
        .unwrap_or(0);
    let module = node
        .children()
        .find(|c| c.kind().as_ref() == "dotted_name")
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

/// Pair each re-read directive with the next import entity of the same
/// specifier; imports the extractor did not emit drop out.
fn pair_imports<'a>(
    imports: &[&'a ImportRow],
    scanned: Vec<PyImport>,
) -> Vec<(&'a ImportRow, PyImport)> {
    let mut pairs = Vec::new();
    let mut next = 0;
    for record in scanned {
        if let Some(offset) = imports[next..]
            .iter()
            .position(|import| import.specifier == record.spec)
        {
            pairs.push((imports[next + offset], record));
            next += offset + 1;
        }
    }
    pairs
}

#[cfg(test)]
mod tests {
    use super::*;

    fn specs(text: &str) -> Vec<(String, bool, bool)> {
        scan_imports(text)
            .into_iter()
            .map(|import| (import.spec, import.guarded, import.attribute_form))
            .collect()
    }

    #[test]
    fn import_forms_match_the_extractor_specifiers() {
        let text = "\
from . import attrname
from . import sub
from .sub import thing
from ..pkg.sub import thing as t2
import os.path
import pkg.sub, other as o
from pkg import thing
";
        let got: Vec<String> = specs(text).into_iter().map(|(spec, _, _)| spec).collect();
        assert_eq!(
            got,
            [
                "./attrname",
                "./sub",
                "./sub",
                "./../pkg/sub",
                "os/path",
                "pkg/sub",
                "other",
                "pkg"
            ]
        );
    }

    #[test]
    fn attribute_form_only_for_name_appended_relative_forms() {
        let got = specs("from . import x\nfrom .mod import y\nfrom pkg import z\n");
        assert_eq!(got[0], ("./x".into(), false, true));
        assert_eq!(got[1], ("./mod".into(), false, false));
        assert_eq!(got[2], ("pkg".into(), false, false));
    }

    #[test]
    fn types_only_and_import_error_guards_are_flagged() {
        let text = "\
if TYPE_CHECKING:
    from . import typed
try:
    from . import optional
except ImportError:
    from . import fallback
try:
    from . import required
except ValueError:
    pass
";
        let flags: Vec<bool> = specs(text)
            .into_iter()
            .map(|(_, guarded, _)| guarded)
            .collect();
        assert_eq!(flags, [true, true, true, false]);
    }

    #[test]
    fn module_paths_are_identifier_segments() {
        for valid in ["pkg", "pkg/sub", "a_b/c1"] {
            assert!(is_module_path(valid), "{valid}");
        }
        for invalid in ["", "/pkg", "pkg/", "pkg//sub", "a-b", "pkg/x.py", "a.b"] {
            assert!(!is_module_path(invalid), "{invalid}");
        }
    }

    #[test]
    fn module_candidates_cover_module_and_package_files() {
        assert_eq!(
            module_candidates("pkg/sub"),
            ["pkg/sub.py", "pkg/sub/__init__.py"]
        );
    }

    #[test]
    fn source_roots_are_repo_root_and_src_dirs() {
        for valid in ["", "src", "lib/crewai/src"] {
            assert!(is_source_root(valid), "{valid}");
        }
        for invalid in ["plugins/platforms", "libs/langgraph", "srcx", "mysrc"] {
            assert!(!is_source_root(invalid), "{invalid}");
        }
    }
}
