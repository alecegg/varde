//! C and C++ include dependency facts.
//!
//! Only a quoted `#include "x.h"` outside any conditional compilation is a
//! fact. The including file's directory is the only search root this module
//! trusts: a hit there that is indexed exactly once is certified. A miss is
//! reported as missing only when the spec is explicitly repository-relative
//! (`./` or `../`); a bare `"x.h"` or a subdirectory path may name a toolchain
//! header or a file generated after indexing, so neither certifies a miss.
//! Angle-bracket includes name toolchain or external headers and yield
//! nothing. The index stores `"x.h"` and `<x.h>` alike, so the directives are
//! re-read from the physical source and paired with the import entities in
//! order.

use super::{
    Fact, FactInput, FileRow, ImportRow, certified_fact, indexed_paths, missing_fact,
    physical_targets, resolve_relative_path,
};
use std::collections::{HashMap, HashSet};
use std::path::{Path, PathBuf};

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
    let mut tree_names = TreeNames::default();
    let mut facts = Vec::new();
    for source in input.files {
        if source.is_test || source.is_tooling || !is_c_cpp(source) {
            continue;
        }
        let Some(imports) = imports_by_file.get(&source.id) else {
            continue;
        };
        let Ok(bytes) = std::fs::read(&source.physical) else {
            continue;
        };
        let root = repository_root(source);
        let includes = scan_includes(&String::from_utf8_lossy(&bytes));
        for (import, include) in pair_includes(imports, includes) {
            if !include.quoted || include.conditional || import.type_only {
                continue;
            }
            if let Some(fact) = include_fact(
                &root,
                &by_id,
                &indexed,
                input.files,
                &mut tree_names,
                source,
                import,
            )? {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

fn is_c_cpp(file: &FileRow) -> bool {
    matches!(
        crate::parse::language_for_path(Path::new(&file.path)),
        Some(ast_grep_language::SupportLang::C | ast_grep_language::SupportLang::Cpp)
    )
}

/// The repository root: the source's physical path minus its relative path.
fn repository_root(source: &FileRow) -> PathBuf {
    let mut root = source.physical.clone();
    for _ in Path::new(&source.relative).components() {
        root.pop();
    }
    root
}

fn include_fact(
    root: &Path,
    by_id: &HashMap<i64, &FileRow>,
    indexed: &HashMap<String, Vec<i64>>,
    files: &[FileRow],
    tree_names: &mut TreeNames,
    source: &FileRow,
    import: &ImportRow,
) -> Result<Option<Fact>, String> {
    let spec = import.specifier.as_str();
    if !is_plain_header_path(spec) {
        return Ok(None);
    }
    let Some(base) = resolve_relative_path(&source.relative, spec) else {
        return Ok(None);
    };
    let targets = physical_targets(root, vec![base.clone()])?;
    if targets.paths.len() == 1 {
        return Ok(match indexed.get(&base).map(Vec::as_slice) {
            Some([target_id]) => certified_fact(by_id, source, import, *target_id),
            _ => None,
        });
    }
    if targets.existing_path || !targets.paths.is_empty() {
        return Ok(None);
    }
    if !names_repository_path(spec)
        || include_root_candidate(files, spec)
        || tree_names.mentions(root, spec)
    {
        return Ok(None);
    }
    Ok(Some(missing_fact(source, import)))
}

/// Header paths made only of path characters; anything else (macros,
/// backslashes, absolute paths) is not certified.
fn is_plain_header_path(spec: &str) -> bool {
    !spec.is_empty()
        && !spec.starts_with('/')
        && spec
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || matches!(c, '_' | '.' | '/' | '+' | '-'))
}

/// Whether a missing `spec` is explicitly repository-relative: `./` or `../`.
/// A subdirectory path is not enough: the directory may hold a file generated
/// after indexing, or a header found only through a `-I` root.
fn names_repository_path(spec: &str) -> bool {
    spec.starts_with("./") || spec.starts_with("../")
}

/// An indexed file that a `-I` root could expose under this spec.
fn include_root_candidate(files: &[FileRow], spec: &str) -> bool {
    let spec = spec.trim_start_matches("./");
    let suffix = format!("/{spec}");
    files
        .iter()
        .any(|file| file.relative == spec || file.relative.ends_with(&suffix))
}

/// Lazily collected file names of the whole physical tree, so a header that is
/// ignored by the index or generated from a template (`config.h.in`) is never
/// reported missing.
#[derive(Default)]
struct TreeNames(Option<HashSet<String>>);

impl TreeNames {
    fn mentions(&mut self, root: &Path, spec: &str) -> bool {
        let names = self.0.get_or_insert_with(|| collect_names(root));
        let basename = spec.rsplit('/').next().unwrap_or(spec);
        let prefix = format!("{basename}.");
        names
            .iter()
            .any(|name| name == basename || name.starts_with(&prefix))
    }
}

fn collect_names(root: &Path) -> HashSet<String> {
    let mut names = HashSet::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(dir) = pending.pop() {
        let Ok(entries) = std::fs::read_dir(&dir) else {
            continue;
        };
        for entry in entries.flatten() {
            let name = entry.file_name().to_string_lossy().into_owned();
            match entry.file_type() {
                Ok(kind) if kind.is_dir() => {
                    if name != ".git" {
                        pending.push(entry.path());
                    }
                }
                Ok(_) => {
                    names.insert(name);
                }
                Err(_) => {}
            }
        }
    }
    names
}

#[derive(Debug)]
struct Include {
    spec: String,
    quoted: bool,
    conditional: bool,
}

/// Pair each directive with the next import entity of the same specifier;
/// `using` imports and unparsed directives drop out.
fn pair_includes<'a>(
    imports: &[&'a ImportRow],
    includes: Vec<Include>,
) -> Vec<(&'a ImportRow, Include)> {
    let mut pairs = Vec::new();
    let mut next = 0;
    for include in includes {
        if let Some(offset) = imports[next..]
            .iter()
            .position(|import| import.specifier == include.spec)
        {
            pairs.push((imports[next + offset], include));
            next += offset + 1;
        }
    }
    pairs
}

/// The whole-file include guard: `#ifndef X` then `#define X`, closed by the
/// last directive of the file. Its frame does not make includes conditional.
#[derive(Default)]
struct Guard {
    name: Option<String>,
    defined: bool,
    closed: bool,
    trailing: bool,
    branched: bool,
}

impl Guard {
    fn whole_file(&self) -> bool {
        self.defined && self.closed && !self.trailing && !self.branched
    }
}

fn scan_includes(text: &str) -> Vec<Include> {
    let mut depth = 0usize;
    let mut guard = Guard::default();
    let mut seen = 0;
    let mut found = Vec::new();
    for line in directive_lines(text) {
        let (keyword, args) = split_directive(&line);
        seen += 1;
        if guard.closed {
            guard.trailing = true;
        }
        match keyword {
            "if" | "ifdef" | "ifndef" => {
                if seen == 1 {
                    guard.name = guard_name(keyword, args);
                }
                depth += 1;
            }
            "else" | "elif" | "elifdef" | "elifndef" => {
                if depth == 1 {
                    guard.branched = true;
                }
            }
            "endif" => {
                depth = depth.saturating_sub(1);
                if depth == 0 && guard.name.is_some() {
                    guard.closed = true;
                }
            }
            "define" if seen == 2 => {
                guard.defined = guard
                    .name
                    .as_deref()
                    .is_some_and(|name| args.split_whitespace().next() == Some(name));
            }
            "include" => {
                if let Some((spec, quoted)) = include_target(args) {
                    found.push((
                        Include {
                            spec,
                            quoted,
                            conditional: false,
                        },
                        depth,
                    ));
                }
            }
            _ => {}
        }
    }
    let guard_depth = usize::from(guard.whole_file());
    found
        .into_iter()
        .map(|(mut include, depth)| {
            include.conditional = depth > guard_depth;
            include
        })
        .collect()
}

fn guard_name(keyword: &str, args: &str) -> Option<String> {
    let compact: String = args.split_whitespace().collect();
    let name = match keyword {
        "ifndef" => args.split_whitespace().next()?.to_string(),
        "if" => compact
            .strip_prefix("!defined(")
            .and_then(|rest| rest.strip_suffix(')'))
            .or_else(|| compact.strip_prefix("!defined"))?
            .to_string(),
        _ => return None,
    };
    (!name.is_empty()).then_some(name)
}

fn include_target(args: &str) -> Option<(String, bool)> {
    let args = args.trim();
    let (open, close, quoted) = match args.chars().next()? {
        '"' => ('"', '"', true),
        '<' => ('<', '>', false),
        _ => return None,
    };
    let rest = args.strip_prefix(open)?;
    let end = rest.find(close)?;
    Some((rest[..end].to_string(), quoted))
}

fn split_directive(line: &str) -> (&str, &str) {
    let body = line.trim_start().trim_start_matches('#').trim_start();
    let end = body
        .find(|c: char| !c.is_ascii_alphanumeric() && c != '_')
        .unwrap_or(body.len());
    (&body[..end], &body[end..])
}

/// Preprocessor lines with comments removed and continuations joined.
fn directive_lines(text: &str) -> Vec<String> {
    let text = text.replace("\r\n", "\n").replace("\\\n", "");
    strip_comments(&text)
        .lines()
        .filter(|line| line.trim_start().starts_with('#'))
        .map(str::to_string)
        .collect()
}

fn strip_comments(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    let mut chars = text.chars().peekable();
    let (mut block, mut line_comment, mut quote) = (false, false, None::<char>);
    while let Some(c) = chars.next() {
        if c == '\n' {
            line_comment = false;
            quote = None;
            out.push('\n');
        } else if block {
            if c == '*' && chars.peek() == Some(&'/') {
                chars.next();
                block = false;
                out.push(' ');
            }
        } else if line_comment {
            continue;
        } else if let Some(open) = quote {
            out.push(c);
            if c == '\\' {
                out.extend(chars.next());
            } else if c == open {
                quote = None;
            }
        } else if c == '/' && chars.peek() == Some(&'*') {
            chars.next();
            block = true;
        } else if c == '/' && chars.peek() == Some(&'/') {
            line_comment = true;
        } else {
            if c == '"' || c == '\'' {
                quote = Some(c);
            }
            out.push(c);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flags(text: &str) -> Vec<(String, bool, bool)> {
        scan_includes(text)
            .into_iter()
            .map(|i| (i.spec, i.quoted, i.conditional))
            .collect()
    }

    #[test]
    fn whole_file_guard_is_not_conditional() {
        let text = "#ifndef X_H\n#define X_H\n#include \"a.h\"\n#include <b.h>\n#endif\n";
        assert_eq!(
            flags(text),
            [("a.h".into(), true, false), ("b.h".into(), false, false)]
        );
    }

    #[test]
    fn nested_conditionals_and_non_guards_are_conditional() {
        let guarded = "#ifndef X_H\n#define X_H\n#ifdef Y\n#include \"a.h\"\n#endif\n#endif\n";
        assert_eq!(flags(guarded), [("a.h".into(), true, true)]);
        let trailing = "#ifndef X_H\n#define X_H\n#endif\n#include \"a.h\"\n";
        assert_eq!(flags(trailing), [("a.h".into(), true, false)]);
        let not_guard = "#ifndef X_H\n#include \"a.h\"\n#endif\n";
        assert_eq!(flags(not_guard), [("a.h".into(), true, true)]);
    }

    #[test]
    fn comments_and_continuations_are_handled() {
        let text = "/* #include \"no.h\" */ // #include \"no2.h\"\n#  include \"yes.h\" // c\n#define X \\\n #include \"no3.h\"\n";
        assert_eq!(flags(text), [("yes.h".into(), true, false)]);
    }
}
