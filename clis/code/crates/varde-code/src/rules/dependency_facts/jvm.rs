//! Java, Kotlin and Scala import dependency facts.
//!
//! These languages import declarations, not files, and one package can span
//! many files, so the unit is the package directory (the declaring file's
//! parent directory), as Go uses package-directory units.  A fact exists only
//! when `import a.b.C` names a declaration that exactly one repository file
//! declares under package `a.b`, in a different unit.  A `missing` fact is
//! emitted only when package `a.b` is a repository package declared in the
//! importing file's source root and no repository file declares the type `C`;
//! external packages, lowercase function or value imports, wildcard, `static`
//! and Scala selector imports, and generated or vendored sources yield
//! nothing.  Source text is read because the indexed specifier (`a/b/C` or
//! `a/b`) cannot distinguish `import a.b.C` from `import a.b.*`.

use super::{Fact, FactInput, FileRow, IMPORT_KIND, ImportRow};
use std::collections::{BTreeMap, BTreeSet, HashMap};
use std::path::Path;

type Declarations<'a> = BTreeMap<(String, String), BTreeMap<String, &'a FileRow>>;

/// What the fact builder knows about the repository's packages and
/// declarations, shared by every import.
#[derive(Default)]
struct RepoIndex<'a> {
    declarations: Declarations<'a>,
    packages: BTreeSet<String>,
    /// Packages whose members are declared in a block this builder does not
    /// read (`package object a.b`, `package a.b { ... }`).
    partial: BTreeSet<String>,
    /// Source roots (`src/main/java`, ...) of the files declaring each package.
    roots: BTreeMap<String, BTreeSet<String>>,
}

/// Certified dependency facts for Java, Kotlin and Scala.
pub(super) fn facts(input: &FactInput<'_>) -> Result<Vec<Fact>, String> {
    let mut imports_by_file: HashMap<i64, Vec<&ImportRow>> = HashMap::new();
    for import in input.imports.iter().filter(|import| !import.type_only) {
        imports_by_file
            .entry(import.file_id)
            .or_default()
            .push(import);
    }

    let mut index = RepoIndex::default();
    let mut sources = Vec::new();
    for file in input.files.iter().filter(|file| is_candidate(file)) {
        let Some(language) = jvm_language(file) else {
            continue;
        };
        let Some(text) = read_source(file)? else {
            continue;
        };
        let parsed = parse_file(&text, language);
        index.partial.extend(parsed.partial.iter().cloned());
        let Some(package) = parsed.package else {
            continue;
        };
        index.packages.insert(package.clone());
        index
            .roots
            .entry(package.clone())
            .or_default()
            .insert(source_root(&file.relative));
        // Test and tooling files may still declare a type, so they keep a
        // name from reading as `missing`; only production files are sources.
        for name in parsed.declared {
            index
                .declarations
                .entry((package.clone(), name))
                .or_default()
                .entry(unit(file))
                .or_insert(file);
        }
        if !file.is_test && !file.is_tooling {
            sources.push(ParsedFile {
                file,
                imports: parsed.imports,
            });
        }
    }

    let mut facts = Vec::new();
    for source in &sources {
        let Some(imports) = imports_by_file.get(&source.file.id) else {
            continue;
        };
        for (import, plain) in pair_imports(imports, &source.imports) {
            if !plain {
                continue;
            }
            if let Some(fact) = import_fact(source.file, import, &index) {
                facts.push(fact);
            }
        }
    }
    Ok(facts)
}

fn jvm_language(file: &FileRow) -> Option<Language> {
    match Path::new(&file.relative)
        .extension()
        .and_then(|extension| extension.to_str())
    {
        Some("java") => Some(Language::Java),
        Some("kt" | "kts") => Some(Language::Kotlin),
        Some("scala") => Some(Language::Scala),
        _ => None,
    }
}

fn is_candidate(file: &FileRow) -> bool {
    jvm_language(file).is_some()
        && !crate::query::noise_filter::is_generated_or_vendored_path(&file.relative)
        && !is_build_tooling(&file.relative)
}

/// Gradle build logic and build scripts are build tooling: they neither
/// declare application types nor import certifiable ones. The index's tooling
/// flag does not cover these paths.
fn is_build_tooling(relative: &str) -> bool {
    let path = Path::new(relative);
    if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
        if name.ends_with(".gradle.kts") || name == "build.gradle" || name == "settings.gradle" {
            return true;
        }
    }
    path.components().any(|component| {
        matches!(
            component.as_os_str().to_str(),
            Some("build-logic" | "buildSrc" | "build-settings-logic")
        )
    })
}

fn read_source(file: &FileRow) -> Result<Option<String>, String> {
    match std::fs::read(&file.physical) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!("read {}: {error}", file.relative)),
    }
}

/// The unit of a declaration is its package directory, like Go.
fn unit(file: &FileRow) -> String {
    let parent = Path::new(&file.relative)
        .parent()
        .unwrap_or_else(|| Path::new(""));
    let unit = parent.to_string_lossy().replace('\\', "/");
    if unit.is_empty() {
        ".".to_string()
    } else {
        unit
    }
}

/// The source root a file sits under (`src/main/java`, `src/commonMain/kotlin`,
/// ...). Files outside a `src/<config>/<lang>` layout use their directory.
fn source_root(relative: &str) -> String {
    let components: Vec<&str> = relative.split('/').collect();
    for index in 0..components.len().saturating_sub(2) {
        if components[index] == "src" {
            return components[..=index + 2].join("/");
        }
    }
    Path::new(relative)
        .parent()
        .map(|parent| parent.to_string_lossy().replace('\\', "/"))
        .unwrap_or_default()
}

/// One repository file that an import can certify.
fn import_fact(source: &FileRow, import: &ImportRow, index: &RepoIndex<'_>) -> Option<Fact> {
    let (package, name) = split_specifier(&import.specifier)?;
    let package = package.replace('/', ".");
    if index.packages.contains(&format!("{package}.{name}")) {
        // The whole import path is also a repository package: which one is
        // meant cannot be certified.
        return None;
    }
    let from_unit = unit(source);
    // Java code imports a Scala object's module class as `Foo$`; the
    // declaration is `object Foo` (or a companion) in a Scala file.
    let (lookup, module_class) = match name.strip_suffix('$') {
        Some(base) if !base.is_empty() => (base, true),
        _ => (name, false),
    };
    if let Some(units) = index
        .declarations
        .get(&(package.clone(), lookup.to_string()))
    {
        let mut found = units.iter();
        let (Some((to_unit, target)), None) = (found.next(), found.next()) else {
            return None;
        };
        if target.is_test
            || target.is_tooling
            || (module_class && jvm_language(target) != Some(Language::Scala))
            || *to_unit == from_unit
            || target.id == source.id
        {
            return None;
        }
        return Some(Fact {
            from_file_id: source.id,
            from_unit,
            to_file_id: Some(target.id),
            to_unit: Some(to_unit.clone()),
            kind: IMPORT_KIND,
            certainty: "certified",
            source_entity_id: import.id,
            specifier: import.specifier.clone(),
        });
    }
    if module_class {
        // A synthetic module class whose base is not declared here: the real
        // declaration may be generated or external, so this is not `missing`.
        return None;
    }
    // `missing` is a missing *type*. Functions and values are lowercase,
    // SCREAMING_SNAKE_CASE names are constants, and a package declared only in
    // another source root is an external or sibling artifact, so none of them
    // can be certified absent.
    let constant = name.contains('_') && !name.chars().any(char::is_lowercase);
    let looks_like_type = name.chars().next().is_some_and(char::is_uppercase) && !constant;
    let root = source_root(&source.relative);
    let missing = index.packages.contains(&package)
        && !index.partial.contains(&package)
        && looks_like_type
        && index
            .roots
            .get(&package)
            .is_some_and(|roots| roots.contains(&root));
    missing.then(|| Fact {
        from_file_id: source.id,
        from_unit,
        to_file_id: None,
        to_unit: None,
        kind: IMPORT_KIND,
        certainty: "missing",
        source_entity_id: import.id,
        specifier: import.specifier.clone(),
    })
}

/// A slash-separated import path with at least a package and a name, both
/// plain identifiers.
fn split_specifier(specifier: &str) -> Option<(&str, &str)> {
    let (package, name) = specifier.rsplit_once('/')?;
    (!package.is_empty() && package.split('/').all(is_identifier) && is_identifier(name))
        .then_some((package, name))
}

fn is_identifier(part: &str) -> bool {
    let mut chars = part.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    (first.is_alphabetic() || first == '_' || first == '$')
        && chars.all(|c| c.is_alphanumeric() || c == '_' || c == '$')
}

// ---- source parsing ----

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Language {
    Java,
    Kotlin,
    Scala,
}

/// One import directive in source order.
struct RawImport {
    specifier: String,
    /// Whether this exact directive names a single declaration.
    plain: bool,
}

struct ParsedFile<'a> {
    file: &'a FileRow,
    imports: Vec<RawImport>,
}

struct ParsedSource {
    package: Option<String>,
    declared: Vec<String>,
    imports: Vec<RawImport>,
    /// Packages whose members are declared in a block this builder does not
    /// read (`package object a.b`, `package a.b { ... }`), so `a.b` must not
    /// produce `missing` facts.
    partial: Vec<String>,
}

/// Pair each indexed import row, in order, with the next source directive of
/// the same specifier, so a wildcard or `static` directive is never certified.
fn pair_imports<'a>(
    imports: &[&'a ImportRow],
    directives: &[RawImport],
) -> Vec<(&'a ImportRow, bool)> {
    let mut pairs = Vec::new();
    let mut next = 0;
    for directive in directives {
        if let Some(offset) = imports[next..]
            .iter()
            .position(|import| import.specifier == directive.specifier)
        {
            pairs.push((imports[next + offset], directive.plain));
            next += offset + 1;
        }
    }
    pairs
}

fn parse_file(text: &str, language: Language) -> ParsedSource {
    let mut package_parts: Vec<String> = Vec::new();
    let mut partial = Vec::new();
    let mut block = false;
    let mut declared = Vec::new();
    let mut imports = Vec::new();
    // Annotations may precede the package clause (`@file:JvmName`), so the
    // header ends at the first import or declaration, not the first line.
    let mut body_seen = false;
    for line in code_lines(text) {
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if let Some(rest) = trimmed.strip_prefix("package ") {
            match package_clause(rest) {
                PackageClause::Plain(parts) => {
                    // A plain clause is a header statement; after code it is not
                    // a package declaration this builder can trust.
                    if !body_seen {
                        package_parts.extend(parts);
                    }
                }
                PackageClause::Block(name) => {
                    block = true;
                    partial.push(join_package(&package_parts, &name));
                }
                PackageClause::Unknown => block = true,
            }
            continue;
        }
        if let Some(import) = import_clause(trimmed, language) {
            body_seen = true;
            imports.push(import);
        } else if !line.starts_with(char::is_whitespace)
            && let Some(name) = declaration_name(trimmed, language)
        {
            body_seen = true;
            declared.push(name);
        }
    }
    if block {
        declared.clear();
        imports.clear();
    }
    let package = (!package_parts.is_empty() && !block).then(|| package_parts.join("."));
    ParsedSource {
        package,
        declared,
        imports,
        partial,
    }
}

enum PackageClause {
    /// A plain `package a.b` clause.
    Plain(Vec<String>),
    /// A block form (`package a.b {`, `package object a.b`, `package a.b:`)
    /// that owns the named package; this builder does not read its members.
    Block(String),
    /// Unrecognized, so the file is not certified.
    Unknown,
}

/// Parse one `package` clause.
fn package_clause(rest: &str) -> PackageClause {
    let rest = rest.trim();
    if let Some(after) = rest.strip_prefix("object ") {
        // `package object data extends Base {` may carry an extends clause.
        let name = after
            .split(|c: char| c.is_whitespace() || c == '{')
            .next()
            .unwrap_or(after)
            .trim();
        return if !name.is_empty() && name.split('.').all(is_identifier) {
            PackageClause::Block(name.to_string())
        } else {
            PackageClause::Unknown
        };
    }
    if rest.contains('{') || rest.ends_with(':') {
        let name = rest.trim_end_matches('{').trim_end_matches(':').trim();
        return if !name.is_empty() && name.split('.').all(is_identifier) {
            PackageClause::Block(name.to_string())
        } else {
            PackageClause::Unknown
        };
    }
    let name = rest.trim_end_matches(';').trim();
    if name.is_empty() || !name.split('.').all(is_identifier) {
        return PackageClause::Unknown;
    }
    PackageClause::Plain(name.split('.').map(str::to_string).collect())
}

/// The full package a block clause owns: its name is relative to the package
/// clauses already seen (`package cats` then `package object data`).
fn join_package(parts: &[String], name: &str) -> String {
    if parts.is_empty() {
        name.to_string()
    } else {
        format!("{}.{name}", parts.join("."))
    }
}

fn import_clause(line: &str, language: Language) -> Option<RawImport> {
    let rest = line.strip_prefix("import")?;
    if !rest.starts_with(char::is_whitespace) {
        return None;
    }
    let rest = rest.trim();
    let (path, plain) = match language {
        Language::Java => {
            let static_import = rest == "static" || rest.starts_with("static ");
            let path = rest
                .strip_prefix("static")
                .map(str::trim_start)
                .unwrap_or(rest);
            let path = path.trim_end_matches(';').trim();
            let wildcard = path.ends_with(".*");
            (
                path.strip_suffix(".*").unwrap_or(path),
                !static_import && !wildcard,
            )
        }
        Language::Kotlin => {
            let path = rest.split(" as ").next().unwrap_or(rest).trim();
            let wildcard = path.ends_with(".*");
            (path.strip_suffix(".*").unwrap_or(path), !wildcard)
        }
        Language::Scala => {
            let selector = rest.contains('{');
            let base = match rest.find('{') {
                Some(index) => rest[..index].trim_end_matches('.').trim(),
                None => rest,
            };
            let wildcard = base.ends_with("._") || base.ends_with(".*");
            (
                base.trim_end_matches("._").trim_end_matches(".*").trim(),
                !selector && !wildcard,
            )
        }
    };
    if path.is_empty() || path.contains('*') {
        return None;
    }
    Some(RawImport {
        specifier: path.replace('.', "/"),
        plain,
    })
}

fn declaration_name(line: &str, language: Language) -> Option<String> {
    let text = strip_annotations(line);
    let (mut word, mut rest) = first_word(text)?;
    for _ in 0..12 {
        if word == "@interface" {
            return identifier(rest);
        }
        if !is_modifier(base_word(word), language) {
            break;
        }
        if matches!(word, "enum" | "fun") {
            // `enum`/`fun` are modifiers only before another declaration
            // keyword (`enum class Foo`, `fun interface Foo`).
            let (next, _) = first_word(rest)?;
            if !is_declaration_keyword(base_word(next), language) {
                break;
            }
        }
        (word, rest) = first_word(rest)?;
    }
    if word == "@interface" {
        return identifier(rest);
    }
    if !is_declaration_keyword(base_word(word), language) {
        return None;
    }
    if matches!(word, "fun" | "def" | "val" | "var" | "type") {
        callable_name(rest)
    } else {
        identifier(rest)
    }
}

/// Scala access modifiers carry a scope (`private[foo]`, `protected[this]`).
fn base_word(word: &str) -> &str {
    word.split('[').next().unwrap_or(word)
}

fn is_declaration_keyword(word: &str, language: Language) -> bool {
    match language {
        Language::Java => matches!(word, "class" | "interface" | "enum" | "record"),
        Language::Kotlin => matches!(
            word,
            "class" | "interface" | "object" | "typealias" | "fun" | "val" | "var"
        ),
        Language::Scala => matches!(
            word,
            "class" | "trait" | "object" | "type" | "given" | "def" | "val" | "var" | "enum"
        ),
    }
}

fn is_modifier(word: &str, language: Language) -> bool {
    match language {
        Language::Java => matches!(
            word,
            "public"
                | "protected"
                | "private"
                | "abstract"
                | "final"
                | "static"
                | "sealed"
                | "non-sealed"
                | "strictfp"
                | "default"
                | "synchronized"
                | "native"
                | "transient"
                | "volatile"
        ),
        Language::Kotlin => matches!(
            word,
            "public"
                | "private"
                | "protected"
                | "internal"
                | "open"
                | "abstract"
                | "sealed"
                | "data"
                | "value"
                | "inline"
                | "fun"
                | "annotation"
                | "enum"
                | "companion"
                | "expect"
                | "actual"
                | "external"
                | "lateinit"
                | "operator"
                | "infix"
                | "suspend"
                | "tailrec"
                | "const"
                | "crossinline"
                | "noinline"
                | "vararg"
                | "override"
        ),
        Language::Scala => matches!(
            word,
            "case"
                | "abstract"
                | "final"
                | "sealed"
                | "implicit"
                | "lazy"
                | "override"
                | "private"
                | "protected"
                | "erased"
                | "inline"
                | "opaque"
                | "open"
                | "transparent"
                | "infix"
                | "extension"
        ),
    }
}

/// The declared name after a callable or property keyword: an extension
/// declaration (`fun String.foo()`, `val String.bar`) declares the last
/// segment, not the receiver, whose type parameters may contain spaces.
fn callable_name(rest: &str) -> Option<String> {
    let rest = rest.trim_start();
    let rest = if rest.starts_with('<') {
        after_angle(rest)?
    } else {
        rest
    };
    let rest = rest.trim_start();
    let end = delimiter_index(rest);
    let candidate = &rest[..end];
    identifier(candidate.rsplit('.').next().unwrap_or(candidate))
}

/// The first delimiter outside `<...>`: a parameter list, expression body or
/// type annotation.
fn delimiter_index(text: &str) -> usize {
    let mut depth = 0usize;
    for (index, c) in text.char_indices() {
        match c {
            '<' => depth += 1,
            '>' => depth = depth.saturating_sub(1),
            '(' | '=' | '[' | ':' | '{' if depth == 0 => return index,
            c if c.is_whitespace() && depth == 0 => return index,
            _ => {}
        }
    }
    text.len()
}

fn identifier(text: &str) -> Option<String> {
    let trimmed = text.trim_start();
    let end = trimmed
        .find(|c: char| !(c.is_alphanumeric() || matches!(c, '_' | '$')))
        .unwrap_or(trimmed.len());
    is_identifier(&trimmed[..end]).then(|| trimmed[..end].to_string())
}

fn first_word(text: &str) -> Option<(&str, &str)> {
    let trimmed = text.trim_start();
    if trimmed.is_empty() {
        return None;
    }
    match trimmed.find(char::is_whitespace) {
        Some(index) => Some((&trimmed[..index], &trimmed[index..])),
        None => Some((trimmed, &trimmed[trimmed.len()..])),
    }
}

fn strip_annotations(mut text: &str) -> &str {
    loop {
        let trimmed = text.trim_start();
        if !trimmed.starts_with('@') || trimmed.starts_with("@interface") {
            return trimmed;
        }
        let after = &trimmed[1..];
        let end = after
            .find(|c: char| !(c.is_alphanumeric() || matches!(c, '_' | '$' | '.')))
            .unwrap_or(after.len());
        let rest = after[end..].trim_start();
        text = match rest.strip_prefix('(') {
            Some(inside) => after_parens(inside).unwrap_or(""),
            None => rest,
        };
    }
}

/// `text` follows an already consumed `(`, so the group starts at depth 1.
fn after_parens(text: &str) -> Option<&str> {
    let mut depth = 1usize;
    for (index, c) in text.char_indices() {
        match c {
            '(' => depth += 1,
            ')' => {
                depth -= 1;
                if depth == 0 {
                    return Some(&text[index + 1..]);
                }
            }
            _ => {}
        }
    }
    None
}

fn after_angle(text: &str) -> Option<&str> {
    let mut depth = 0usize;
    for (index, c) in text.char_indices() {
        match c {
            '<' => depth += 1,
            '>' => {
                depth -= 1;
                if depth == 0 {
                    return Some(&text[index + 1..]);
                }
            }
            _ => {}
        }
    }
    None
}

/// Whether the next two characters are quotes (the tail of a `"""`).
fn next_two_are_quotes(chars: &std::iter::Peekable<std::str::Chars<'_>>) -> bool {
    let mut lookahead = chars.clone();
    lookahead.next() == Some('"') && lookahead.next() == Some('"')
}

/// Source lines with comments removed. String and backtick literals are
/// skipped, so a `/*` inside one (`s"a/*b"`, `` `*/*` ``) is not a comment.
fn code_lines(text: &str) -> Vec<String> {
    let mut lines = Vec::new();
    let mut in_block = false;
    let mut quote: Option<char> = None;
    let mut triple = false;
    for raw in text.lines() {
        let mut code = String::new();
        let mut chars = raw.chars().peekable();
        let mut escaped = false;
        while let Some(c) = chars.next() {
            if in_block {
                if c == '*' && chars.peek() == Some(&'/') {
                    chars.next();
                    in_block = false;
                }
                continue;
            }
            if let Some(q) = quote {
                code.push(c);
                if escaped {
                    escaped = false;
                } else if c == '\\' {
                    escaped = true;
                } else if c == q {
                    if triple && next_two_are_quotes(&chars) {
                        chars.next();
                        chars.next();
                        code.push_str("\"\"");
                        quote = None;
                        triple = false;
                    } else if !triple {
                        quote = None;
                    }
                }
                continue;
            }
            match c {
                '"' => {
                    quote = Some('"');
                    if next_two_are_quotes(&chars) {
                        chars.next();
                        chars.next();
                        code.push_str("\"\"\"");
                        triple = true;
                    } else {
                        code.push('"');
                    }
                }
                '`' => {
                    quote = Some('`');
                    code.push('`');
                }
                '/' if chars.peek() == Some(&'*') => {
                    chars.next();
                    in_block = true;
                }
                '/' if chars.peek() == Some(&'/') => break,
                _ => code.push(c),
            }
        }
        lines.push(code);
    }
    lines
}

#[cfg(test)]
mod tests {
    use super::*;

    fn parse(text: &str, language: Language) -> ParsedSource {
        parse_file(text, language)
    }

    #[test]
    fn java_declarations_and_imports_are_parsed() {
        let source = "package com.example.alpha;\n\n\
             import com.example.beta.Beta;\n\
             import static com.example.beta.Beta.VALUE;\n\
             import com.example.beta.*;\n\n\
             /** doc */\n\
             public final class Alpha extends Base implements Iface {\n\
             \x20   static class Nested {}\n\
             }\n\
             interface Helper {}\n";
        let parsed = parse(source, Language::Java);
        assert_eq!(parsed.package.as_deref(), Some("com.example.alpha"));
        assert_eq!(parsed.declared, ["Alpha", "Helper"]);
        let specs: Vec<(&str, bool)> = parsed
            .imports
            .iter()
            .map(|import| (import.specifier.as_str(), import.plain))
            .collect();
        assert_eq!(
            specs,
            [
                ("com/example/beta/Beta", true),
                ("com/example/beta/Beta/VALUE", false),
                ("com/example/beta", false),
            ]
        );
    }

    #[test]
    fn kotlin_declarations_and_import_forms_are_parsed() {
        let source = "package com.example.alpha\n\n\
             import com.example.beta.Beta\n\
             import com.example.beta.Beta as B\n\
             import com.example.beta.*\n\n\
             data class Alpha(val x: Int)\n\
             fun String.extension() = this\n\
             fun topLevel() = 1\n\
             val answer = 42\n\
             object Registry\n";
        let parsed = parse(source, Language::Kotlin);
        assert_eq!(
            parsed.declared,
            ["Alpha", "extension", "topLevel", "answer", "Registry"]
        );
        assert_eq!(
            parsed.imports.iter().map(|i| i.plain).collect::<Vec<_>>(),
            [true, true, false]
        );
    }

    #[test]
    fn scala_declarations_and_import_forms_are_parsed() {
        let source = "package com.example.alpha\n\n\
             import com.example.beta.Beta\n\
             import com.example.beta._\n\
             import com.example.beta.{Beta, Other}\n\n\
             case class Alpha(n: Int)\n\
             sealed trait Trait\n\
             object Registry\n\
             type Alias = Int\n\
             def helper(): Unit = ()\n";
        let parsed = parse(source, Language::Scala);
        assert_eq!(
            parsed.declared,
            ["Alpha", "Trait", "Registry", "Alias", "helper"]
        );
        assert_eq!(
            parsed.imports.iter().map(|i| i.plain).collect::<Vec<_>>(),
            [true, false, false]
        );
    }

    #[test]
    fn comments_and_block_packages_are_ignored() {
        let commented = parse(
            "package com.example.alpha\n// import com.example.gone.Gone\n/* import com.example.gone2.Gone2 */\nclass Alpha\n",
            Language::Java,
        );
        assert!(commented.imports.is_empty());
        let block = parse("package com.example {\nclass Alpha\n}\n", Language::Java);
        assert_eq!(block.package, None);
        assert!(block.declared.is_empty());
    }

    #[test]
    fn comment_markers_inside_literals_do_not_hide_declarations() {
        let source = "package com.example.alpha\n\n\
             class Alpha {\n\
             \x20 val s = s\"a/*b\"\n\
             \x20 val t = `*/*`\n\
             \x20 val u = \"\"\"raw /* text\"\"\"\n\
             }\n\
             sealed class Beta\n";
        let parsed = parse(source, Language::Scala);
        assert_eq!(parsed.declared, ["Alpha", "Beta"]);
    }

    #[test]
    fn package_clauses_accumulate_like_scala() {
        let parsed = parse(
            "package com.example\npackage alpha\nclass Alpha\n",
            Language::Scala,
        );
        assert_eq!(parsed.package.as_deref(), Some("com.example.alpha"));
    }

    #[test]
    fn annotated_and_scoped_declarations_are_parsed() {
        let java = r#"package com.example.alpha;
public @interface Marker {}
@interface Plain {}
"#;
        let parsed = parse(java, Language::Java);
        assert_eq!(parsed.declared, ["Marker", "Plain"]);

        let scala = r#"package com.example.alpha
private[alpha] class Hidden
protected[this] trait Guarded
"#;
        let parsed = parse(scala, Language::Scala);
        assert_eq!(parsed.declared, ["Hidden", "Guarded"]);
    }

    #[test]
    fn file_annotations_before_the_package_clause_are_parsed() {
        let source = "@file:JvmName(\"Util\")\n\
             @file:Suppress(\"ktlint:standard:filename\")\n\n\
             package com.example.alpha\n\n\
             import com.example.beta.Beta\n\n\
             internal val name = 1\n";
        let parsed = parse(source, Language::Kotlin);
        assert_eq!(parsed.package.as_deref(), Some("com.example.alpha"));
        assert_eq!(parsed.declared, ["name"]);
        assert_eq!(parsed.imports.len(), 1);
    }

    #[test]
    fn type_parameter_extension_functions_declare_the_extension_name() {
        let source = "package com.example.alpha\n\n\
             internal inline fun <T> List<T>.unmodifiable(): List<T> = this\n\
             infix fun <T> Expression<T>.eq(other: T) = other\n";
        let parsed = parse(source, Language::Kotlin);
        assert_eq!(parsed.declared, ["unmodifiable", "eq"]);
    }

    #[test]
    fn generic_receiver_functions_declare_the_extension_name() {
        let source = "package com.example.alpha\n\n\
             fun <T : Any, S : T?> ExpressionWithColumnType<in S>.min(): Min<T, S> = Min(this)\n\
             internal fun Map<String, String>.commonToHeaders(): Headers = Headers()\n";
        let parsed = parse(source, Language::Kotlin);
        assert_eq!(parsed.declared, ["min", "commonToHeaders"]);
    }

    #[test]
    fn extension_properties_declare_the_property_name() {
        let kotlin = "package com.example.alpha\n\n\
             internal val Project.libs: Libraries = Libraries()\n\
             val answer = 42\n";
        let parsed = parse(kotlin, Language::Kotlin);
        assert_eq!(parsed.declared, ["libs", "answer"]);

        let scala = "package com.example.alpha\n\ntype Alias = Int\n";
        let parsed = parse(scala, Language::Scala);
        assert_eq!(parsed.declared, ["Alias"]);
    }

    #[test]
    fn package_objects_and_blocks_are_marked_partial() {
        let scala = "package object cats {\n  type Id[A] = A\n}\n";
        let parsed = parse(scala, Language::Scala);
        assert_eq!(parsed.package, None);
        assert_eq!(parsed.partial, ["cats"]);

        let nested = parse(
            "package cats\npackage object data extends Base {\n  type State[S, A] = StateT[S, A]\n}\n",
            Language::Scala,
        );
        assert_eq!(nested.partial, ["cats.data"]);

        let block = parse("package com.example {\nclass Alpha\n}\n", Language::Java);
        assert_eq!(block.partial, ["com.example"]);
    }

    #[test]
    fn annotation_arguments_with_nested_parens_do_not_underflow() {
        assert_eq!(strip_annotations("@Foo(a(b)) class X"), "class X");
        assert_eq!(strip_annotations("@Foo() class X"), "class X");
    }
}
