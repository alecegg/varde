//! Elixir and Haskell dependency facts.
//!
//! Neither language imports files, so a fact needs a module name the
//! repository itself defines.  Elixir modules come from `defmodule`
//! declarations (nested modules are qualified by indentation); Haskell
//! modules come from `module M where` declarations and from the
//! `<SourceRoot>/M.hs` path convention.  A fact exists only when the imported
//! module maps to exactly one indexed file; a module with several candidate
//! files is ambiguous.  A module no file defines yields no fact unless the
//! repository owns it: a local package manifest lists it, or (with no
//! manifest) its declared parent module exists.  Dependency-package modules
//! that share a namespace with the repository (`Text.Pandoc.Definition` from
//! `pandoc-types`) are therefore never certified.  Cabal's generated
//! `Paths_` modules and macro-generated modules are not defined by any file
//! either.  `#if`-guarded Haskell imports,
//! test/tooling sources and type-only imports are excluded.  Source text is
//! read from disk because the index keeps only the import specifier.

use super::{Fact, FactInput, FileRow, ImportRow, certified_fact, missing_fact};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::{Path, PathBuf};

/// Certified dependency facts for Elixir and Haskell.
pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let mut facts = elixir_facts(input)?;
    facts.extend(haskell_facts(input)?);
    Ok(facts)
}

fn language(file: &FileRow) -> Option<ast_grep_language::SupportLang> {
    crate::parse::language_for_path(Path::new(&file.path))
}

/// A shipped source file in one language; test and tooling files stay out of
/// the fact sources but still count as module targets (via `certified_fact`,
/// which refuses them, so a module defined only in a test file is never
/// certified missing).
fn is_source(file: &FileRow, lang: ast_grep_language::SupportLang) -> bool {
    !file.is_test && !file.is_tooling && language(file) == Some(lang)
}

fn read_source(file: &FileRow) -> Result<Option<String>, String> {
    match std::fs::read(&file.physical) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("read {}: {error}", file.relative)),
    }
}

/// Whether a dotted or slash-separated name is a plain module path.
fn is_module_path(name: &str, separator: char) -> bool {
    !name.is_empty()
        && name.split(separator).all(|part| {
            part.chars()
                .next()
                .is_some_and(|first| first.is_uppercase())
                && part.chars().all(|c| c.is_alphanumeric() || c == '_')
        })
}

/// The distinct files that define each module, keyed by module name.
type ModuleMap<'a> = BTreeMap<String, BTreeMap<String, &'a FileRow>>;

enum Target<'a> {
    One(&'a FileRow),
    Ambiguous,
    None,
}

fn target<'a>(map: &ModuleMap<'a>, spec: &str) -> Target<'a> {
    let Some(files) = map.get(spec) else {
        return Target::None;
    };
    let mut files = files.values();
    match (files.next(), files.next()) {
        (Some(only), None) => Target::One(only),
        _ => Target::Ambiguous,
    }
}

/// Whether the repository declares the exact parent module of a
/// three-or-more-segment spec.  Only that shape is certified missing:
/// Elixir and Haskell apps share their top-level namespace with dependencies
/// (`Phoenix.PubSub`, `Plug.Conn`, `Mix.Task`, `Data.Text`), so a shorter
/// path or a top-level parent cannot be told apart from a package module.
fn missing_parent_declared(map: &ModuleMap<'_>, spec: &str, separator: char) -> bool {
    let Some((parent, _)) = spec.rsplit_once(separator) else {
        return false;
    };
    parent.contains(separator) && map.contains_key(parent)
}

// ---- Elixir ----

fn elixir_facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let elixir_files: Vec<&FileRow> = input
        .files
        .iter()
        .filter(|file| language(file) == Some(ast_grep_language::SupportLang::Elixir))
        .collect();
    let mut modules: ModuleMap<'_> = ModuleMap::new();
    for file in &elixir_files {
        let Some(text) = read_source(file)? else {
            continue;
        };
        for name in elixir_modules(&text) {
            modules
                .entry(name)
                .or_default()
                .entry(file.relative.clone())
                .or_insert(file);
        }
    }
    let mut facts = Vec::new();
    for file in elixir_files
        .iter()
        .filter(|file| is_source(file, ast_grep_language::SupportLang::Elixir))
    {
        for import in input
            .imports
            .iter()
            .filter(|import| import.file_id == file.id && !import.type_only)
        {
            let spec = import.specifier.as_str();
            if !is_module_path(spec, '.') {
                continue;
            }
            match target(&modules, spec) {
                Target::One(target) => {
                    if let Some(fact) = certified_fact(&by_id, file, import, target.id) {
                        facts.push(fact);
                    }
                }
                Target::None if missing_parent_declared(&modules, spec, '.') => {
                    facts.push(missing_fact(file, import));
                }
                Target::Ambiguous | Target::None => {}
            }
        }
    }
    Ok(facts)
}

/// Module names a file defines; nested `defmodule`s are qualified by
/// indentation.  `defprotocol` declares a module too (Livebook's
/// `Livebook.FileSystem` is a protocol).  A dynamic name
/// (`defmodule unquote(name)`) is not a module name and yields nothing, so
/// macro-generated modules are never certified.
fn elixir_modules(text: &str) -> Vec<String> {
    let mut stack: Vec<(usize, String)> = Vec::new();
    let mut modules = Vec::new();
    for line in text.lines() {
        let code = strip_elixir_comment(line);
        let indent = code.len() - code.trim_start().len();
        let trimmed = code.trim_start();
        let Some(rest) = ["defmodule", "defprotocol"]
            .iter()
            .find_map(|keyword| trimmed.strip_prefix(keyword))
        else {
            continue;
        };
        if !rest.starts_with([' ', '\t', '(']) {
            continue;
        }
        let name = rest
            .trim_start_matches([' ', '\t', '('])
            .split(|c: char| !(c.is_alphanumeric() || c == '_' || c == '.'))
            .next()
            .unwrap_or("");
        if !is_module_path(name, '.') {
            continue;
        }
        while stack.last().is_some_and(|(depth, _)| *depth >= indent) {
            stack.pop();
        }
        let full = match stack.last() {
            Some((_, parent)) => format!("{parent}.{name}"),
            None => name.to_string(),
        };
        stack.push((indent, full.clone()));
        modules.push(full);
    }
    modules
}

fn strip_elixir_comment(line: &str) -> &str {
    match line.find('#') {
        Some(index) => &line[..index],
        None => line,
    }
}

// ---- Haskell ----

fn haskell_facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let by_id: HashMap<i64, &FileRow> = input.files.iter().map(|file| (file.id, file)).collect();
    let haskell_files: Vec<&FileRow> = input
        .files
        .iter()
        .filter(|file| language(file) == Some(ast_grep_language::SupportLang::Haskell))
        .collect();
    let mut declared: ModuleMap<'_> = ModuleMap::new();
    let mut declared_by_file: HashMap<String, String> = HashMap::new();
    let mut by_path: Vec<&FileRow> = Vec::new();
    for file in &haskell_files {
        if file.relative.strip_suffix(".hs").is_some() {
            by_path.push(file);
        }
        let Some(text) = read_source(file)? else {
            continue;
        };
        if let Some(name) = haskell_module(&text) {
            let module = name.replace('.', "/");
            declared
                .entry(module.clone())
                .or_default()
                .entry(file.relative.clone())
                .or_insert(file);
            declared_by_file.insert(file.relative.clone(), module);
        }
    }
    let mut facts = Vec::new();
    let mut tree = TreeNames::default();
    let mut manifests = Manifests::default();
    let root = input.files.first().map(repository_root);
    for file in haskell_files
        .iter()
        .filter(|file| is_source(file, ast_grep_language::SupportLang::Haskell))
    {
        let imports: Vec<&ImportRow> = input
            .imports
            .iter()
            .filter(|import| import.file_id == file.id)
            .collect();
        let Some(text) = read_source(file)? else {
            continue;
        };
        let scanned = scan_haskell_imports(&text);
        for (import, guarded) in pair_imports(&imports, &scanned) {
            if guarded || import.type_only {
                continue;
            }
            let spec = import.specifier.as_str();
            if !is_module_path(spec, '/') {
                continue;
            }
            match haskell_target(&declared, &by_path, &declared_by_file, spec) {
                Target::One(target) => {
                    if let Some(fact) = certified_fact(&by_id, file, import, target.id) {
                        facts.push(fact);
                    }
                }
                Target::None
                    if !is_generated_module(spec)
                        && manifests
                            .owns(root.as_deref(), file, spec)
                            .unwrap_or_else(|| missing_parent_declared(&declared, spec, '/'))
                        && root.as_ref().is_none_or(|root| {
                            let name = spec.rsplit('/').next().unwrap_or(spec);
                            !tree.mentions(root, name)
                        }) =>
                {
                    facts.push(missing_fact(file, import));
                }
                Target::Ambiguous | Target::None => {}
            }
        }
    }
    Ok(facts)
}

/// The unique file a Haskell module resolves to: a file whose path (minus
/// `.hs`) equals or ends with the module path, or a file whose `module`
/// declaration names it.  A path match must agree with the file's module
/// header when it has one, so the external `Citeproc` package never resolves
/// to `Text/Pandoc/Citeproc.hs`.  Several candidates are ambiguous.
fn haskell_target<'a>(
    declared: &ModuleMap<'a>,
    by_path: &[&'a FileRow],
    declared_by_file: &HashMap<String, String>,
    spec: &str,
) -> Target<'a> {
    let mut found: BTreeMap<String, &FileRow> = BTreeMap::new();
    if let Some(files) = declared.get(spec) {
        for (relative, file) in files {
            found.insert(relative.clone(), file);
        }
    }
    let suffix = format!("/{spec}");
    for file in by_path {
        let Some(base) = file.relative.strip_suffix(".hs") else {
            continue;
        };
        if (base == spec || base.ends_with(&suffix))
            && declared_by_file
                .get(&file.relative)
                .is_none_or(|name| name == spec)
        {
            found.insert(file.relative.clone(), file);
        }
    }
    let mut found = found.into_values();
    match (found.next(), found.next()) {
        (Some(only), None) => Target::One(only),
        (None, None) => Target::None,
        _ => Target::Ambiguous,
    }
}

/// Cabal generates a `Paths_<package>` module for every package, so a
/// `Paths_` spec is never a missing source file.
fn is_generated_module(spec: &str) -> bool {
    spec.rsplit('/')
        .next()
        .is_some_and(|name| name.starts_with("Paths_"))
}

/// Module names the local package manifest declares, keyed by manifest
/// directory.  A manifest covering the importing file decides ownership: a
/// listed module is repository-owned even when no file defines it, and a
/// module absent from the manifest belongs to a dependency package that
/// shares the namespace.  Files with no covering manifest fall back to the
/// declared-parent test.
#[derive(Default)]
struct Manifests {
    cache: HashMap<PathBuf, Option<HashSet<String>>>,
}

impl Manifests {
    /// Whether the manifest covering `source` owns `spec`; `None` when no
    /// manifest covers it.
    fn owns(&mut self, root: Option<&Path>, source: &FileRow, spec: &str) -> Option<bool> {
        let spec = spec.replace('/', ".");
        let mut dir = source.physical.parent()?.to_path_buf();
        loop {
            if let Some(modules) = self.modules(&dir) {
                return Some(modules.contains(&spec));
            }
            if root.is_some_and(|root| root == dir.as_path()) {
                return None;
            }
            dir = dir.parent()?.to_path_buf();
        }
    }

    fn modules(&mut self, dir: &Path) -> Option<&HashSet<String>> {
        if !self.cache.contains_key(dir) {
            self.cache
                .insert(dir.to_path_buf(), read_manifest_modules(dir));
        }
        self.cache.get(dir).and_then(Option::as_ref)
    }
}

/// The module names in the first `*.cabal` or `package.yaml` beside the
/// source, or `None` when the directory holds no manifest.
fn read_manifest_modules(dir: &Path) -> Option<HashSet<String>> {
    let entries = std::fs::read_dir(dir).ok()?;
    let mut modules = HashSet::new();
    let mut found = false;
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        if !(name.ends_with(".cabal") || name == "package.yaml") {
            continue;
        }
        found = true;
        if let Ok(text) = std::fs::read_to_string(entry.path()) {
            collect_manifest_modules(&text, &mut modules);
        }
    }
    found.then_some(modules)
}

const MANIFEST_MODULE_FIELDS: [&str; 5] = [
    "exposed-modules",
    "other-modules",
    "reexported-modules",
    "signatures",
    "virtual-modules",
];

/// Module names from a cabal or hpack module field, including continuation
/// lines.  Comments (`--`) and other fields are ignored.
fn collect_manifest_modules(text: &str, out: &mut HashSet<String>) {
    let mut collecting = false;
    for raw in text.lines() {
        let line = raw.split("--").next().unwrap_or("");
        let trimmed = line.trim();
        if trimmed.is_empty() {
            collecting = false;
            continue;
        }
        if let Some((field, rest)) = trimmed.split_once(':') {
            collecting =
                MANIFEST_MODULE_FIELDS.contains(&field.trim().to_ascii_lowercase().as_str());
            if collecting {
                add_module_names(rest, out);
            }
            continue;
        }
        if collecting && line.starts_with([' ', '\t']) {
            add_module_names(trimmed, out);
        }
    }
}

fn add_module_names(text: &str, out: &mut HashSet<String>) {
    for token in text.split(|c: char| c == ',' || c.is_whitespace()) {
        if is_module_path(token, '.') {
            out.insert(token.to_string());
        }
    }
}

/// The module an `module M where` header declares, if any.
fn haskell_module(text: &str) -> Option<String> {
    for line in text.lines() {
        let line = line.trim();
        let Some(rest) = line.strip_prefix("module ") else {
            continue;
        };
        let name = rest
            .split(|c: char| c.is_whitespace() || c == '(')
            .next()
            .unwrap_or("");
        if is_module_path(name, '.') {
            return Some(name.to_string());
        }
    }
    None
}

/// The repository root: a source's physical path minus its relative path.
fn repository_root(source: &FileRow) -> PathBuf {
    let mut root = source.physical.clone();
    for _ in Path::new(&source.relative).components() {
        root.pop();
    }
    root
}

/// File names anywhere in the physical tree, so a module generated from a C
/// preprocessor source (`Hasql/LibPq14/Mappings.hsc` -> `.hs`) is never
/// reported missing.
#[derive(Default)]
struct TreeNames(Option<HashSet<String>>);

impl TreeNames {
    fn mentions(&mut self, root: &Path, name: &str) -> bool {
        let names = self.0.get_or_insert_with(|| collect_names(root));
        let prefix = format!("{name}.");
        names
            .iter()
            .any(|candidate| candidate == name || candidate.starts_with(&prefix))
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

struct ScannedImport {
    spec: String,
    guarded: bool,
}

/// `import` lines with their CPP guard state.  `{-# ... #-}` pragmas are
/// blanked so a `SOURCE` pragma is not mistaken for a module.
fn scan_haskell_imports(text: &str) -> Vec<ScannedImport> {
    let mut depth = 0usize;
    let mut in_block_comment = false;
    let mut out = Vec::new();
    for raw in text.lines() {
        let line = strip_haskell_block_comment(raw, &mut in_block_comment);
        let trimmed = line.trim();
        if let Some(rest) = trimmed.strip_prefix('#') {
            match cpp_keyword(rest) {
                "if" | "ifdef" | "ifndef" => depth += 1,
                "endif" => depth = depth.saturating_sub(1),
                _ => {}
            }
            continue;
        }
        let line = blank_pragmas(trimmed);
        let Some(spec) = haskell_import_spec(&line) else {
            continue;
        };
        out.push(ScannedImport {
            spec,
            guarded: depth > 0,
        });
    }
    out
}

fn cpp_keyword(rest: &str) -> &str {
    let rest = rest.trim_start();
    let end = rest
        .find(|c: char| !c.is_ascii_alphanumeric())
        .unwrap_or(rest.len());
    &rest[..end]
}

fn blank_pragmas(line: &str) -> String {
    let mut out = String::with_capacity(line.len());
    let mut rest = line;
    while let Some(start) = rest.find("{-#") {
        out.push_str(&rest[..start]);
        match rest[start..].find("#-}") {
            Some(end) => {
                out.push(' ');
                rest = &rest[start + end + 3..];
            }
            None => {
                rest = "";
                break;
            }
        }
    }
    out.push_str(rest);
    out
}

/// The module token of an `import` line in slash form.
fn haskell_import_spec(line: &str) -> Option<String> {
    let mut tokens = line.split_whitespace();
    if tokens.next()? != "import" {
        return None;
    }
    tokens
        .filter(|token| token.chars().next().is_some_and(char::is_uppercase))
        .find(|token| is_module_path(token, '.'))
        .map(|name| name.replace('.', "/"))
}

fn strip_haskell_block_comment(line: &str, in_block_comment: &mut bool) -> String {
    if *in_block_comment {
        match line.find("-}") {
            Some(end) => {
                *in_block_comment = false;
                return line[end + 2..].to_string();
            }
            None => return String::new(),
        }
    }
    match line.find("{-") {
        Some(start) => {
            let tail = &line[start + 2..];
            match tail.find("-}") {
                Some(end) => format!("{}{}", &line[..start], &tail[end + 2..]),
                None => {
                    *in_block_comment = true;
                    line[..start].to_string()
                }
            }
        }
        None => line.to_string(),
    }
}

/// Pair each scanned directive with the next matching import entity, mirroring
/// the C/C++ include pairing: the index keeps no position, so order is the
/// only link between them.
fn pair_imports<'a>(
    imports: &[&'a ImportRow],
    scanned: &[ScannedImport],
) -> Vec<(&'a ImportRow, bool)> {
    let mut pairs = Vec::new();
    let mut next = 0;
    for scanned in scanned {
        if let Some(offset) = imports[next..]
            .iter()
            .position(|import| import.specifier == scanned.spec)
        {
            pairs.push((imports[next + offset], scanned.guarded));
            next += offset + 1;
        }
    }
    pairs
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn elixir_modules_qualify_nested_declarations() {
        let text = "defmodule MyApp do\n  defmodule Foo do\n  end\nend\ndefmodule Other do\nend\n";
        assert_eq!(elixir_modules(text), ["MyApp", "MyApp.Foo", "Other"]);
    }

    #[test]
    fn dynamic_elixir_module_names_are_ignored() {
        let text = "defmodule unquote(name) do\nend\ndefmodule #{inspect(owner)} do\nend\n";
        assert!(elixir_modules(text).is_empty());
    }

    #[test]
    fn elixir_protocols_are_modules() {
        let text = "defprotocol Livebook.FileSystem do\nend\n";
        assert_eq!(elixir_modules(text), ["Livebook.FileSystem"]);
    }

    #[test]
    fn haskell_module_headers_are_parsed() {
        assert_eq!(
            haskell_module("module Data.List (sort) where\n"),
            Some("Data.List".to_string())
        );
        assert_eq!(haskell_module("main = pure ()\n"), None);
    }

    #[test]
    fn haskell_imports_track_cpp_guards() {
        let text = "#ifdef X\nimport Guarded\n#endif\nimport Plain\n";
        let scanned = scan_haskell_imports(text);
        assert_eq!(scanned.len(), 2);
        assert!(scanned[0].guarded);
        assert_eq!(scanned[0].spec, "Guarded");
        assert!(!scanned[1].guarded);
    }

    #[test]
    fn haskell_source_pragma_is_not_a_module() {
        let scanned = scan_haskell_imports("import {-# SOURCE #-} App.Real\n");
        assert_eq!(scanned.len(), 1);
        assert_eq!(scanned[0].spec, "App/Real");
    }

    #[test]
    fn haskell_path_match_must_agree_with_the_module_header() {
        let file = FileRow {
            id: 1,
            path: "src/Text/Pandoc/Citeproc.hs".to_string(),
            relative: "src/Text/Pandoc/Citeproc.hs".to_string(),
            physical: PathBuf::from("/repo/src/Text/Pandoc/Citeproc.hs"),
            is_test: false,
            is_tooling: false,
        };
        let files = vec![&file];
        let mut declared: ModuleMap<'_> = ModuleMap::new();
        declared
            .entry("Text/Pandoc/Citeproc".to_string())
            .or_default()
            .insert(file.relative.clone(), &file);
        let mut declared_by_file = HashMap::new();
        declared_by_file.insert(file.relative.clone(), "Text/Pandoc/Citeproc".to_string());
        assert!(matches!(
            haskell_target(&declared, &files, &declared_by_file, "Citeproc"),
            Target::None
        ));
        assert!(matches!(
            haskell_target(&declared, &files, &declared_by_file, "Text/Pandoc/Citeproc"),
            Target::One(_)
        ));
    }

    #[test]
    fn generated_paths_modules_are_not_missing_sources() {
        assert!(is_generated_module("Paths_pandoc"));
        assert!(is_generated_module("Foo/Paths_bar"));
        assert!(!is_generated_module("Paths"));
        assert!(!is_generated_module("App/Core/Gone"));
    }

    #[test]
    fn manifest_module_fields_are_collected() {
        let cabal = "library\n  hs-source-dirs: src\n  exposed-modules: Text.Pandoc,\n                   Text.Pandoc.App,\n                   Text.Pandoc.XML.Light.Types\n  build-depends: base >= 4.14\n  other-modules: Paths_pandoc\n";
        let mut modules = HashSet::new();
        collect_manifest_modules(cabal, &mut modules);
        assert!(modules.contains("Text.Pandoc"));
        assert!(modules.contains("Text.Pandoc.App"));
        assert!(modules.contains("Text.Pandoc.XML.Light.Types"));
        assert!(modules.contains("Paths_pandoc"));
        assert!(!modules.contains("base"));
    }
}
