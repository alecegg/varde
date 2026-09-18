//! Tree-sitter parsing via `ast-grep-language`.
//!
//! Grammar loading/registration is delegated to `ast-grep-language` (per the
//! plan: direct dependency, no reimplementation). Parsing is an unconditional
//! full-tree walk — `ast-grep-core`'s pattern engine is deliberately not used
//! for this hot path.

use anyhow::{Context, Result};
use ast_grep_core::AstGrep;
use ast_grep_core::language::Language;
use ast_grep_core::tree_sitter::LanguageExt;
use ast_grep_core::tree_sitter::StrDoc;
use ast_grep_language::SupportLang;
use std::path::Path;

/// The single registry of indexable file extensions and the ast-grep language
/// each one parses as. Lowercase, matched case-insensitively.
///
/// Every downstream classifier — parsing, entrypoint role-tag rules,
/// call-based route detection, process-`main` naming — resolves through this
/// table via [`language_for_path`] instead of re-listing extensions. Those
/// switches had drifted from it: `.mts`/`.cts` parsed as TypeScript but were
/// invisible to route detection, and `.c++`/`.hxx`/`.h++` parsed as C++ but
/// could never surface a `main`. Adding an extension here is the only edit a
/// new file type needs.
pub const EXTENSION_LANGUAGES: &[(&str, SupportLang)] = &[
    ("ts", SupportLang::TypeScript),
    ("mts", SupportLang::TypeScript),
    ("cts", SupportLang::TypeScript),
    ("tsx", SupportLang::Tsx),
    ("js", SupportLang::JavaScript),
    ("jsx", SupportLang::JavaScript),
    ("mjs", SupportLang::JavaScript),
    ("cjs", SupportLang::JavaScript),
    // `.h` starts as C. `parse_source_for_path` retries cleanly parseable
    // C++ headers after a C syntax error.
    ("c", SupportLang::C),
    ("h", SupportLang::C),
    ("cpp", SupportLang::Cpp),
    ("cc", SupportLang::Cpp),
    ("cxx", SupportLang::Cpp),
    ("c++", SupportLang::Cpp),
    ("hpp", SupportLang::Cpp),
    ("hh", SupportLang::Cpp),
    ("hxx", SupportLang::Cpp),
    ("h++", SupportLang::Cpp),
    ("go", SupportLang::Go),
    ("java", SupportLang::Java),
    ("cs", SupportLang::CSharp),
    ("kt", SupportLang::Kotlin),
    ("kts", SupportLang::Kotlin),
    ("swift", SupportLang::Swift),
    ("py", SupportLang::Python),
    ("rb", SupportLang::Ruby),
    ("php", SupportLang::Php),
    ("lua", SupportLang::Lua),
    ("scala", SupportLang::Scala),
    ("sc", SupportLang::Scala),
    ("sbt", SupportLang::Scala),
    ("dart", SupportLang::Dart),
    ("ex", SupportLang::Elixir),
    ("exs", SupportLang::Elixir),
    ("sol", SupportLang::Solidity),
    ("hs", SupportLang::Haskell),
    // Shell scripts (bash/sh/zsh/ksh/bats) all parse against the
    // tree-sitter-bash grammar; ast-grep's own extension list groups them
    // the same way.
    ("sh", SupportLang::Bash),
    ("bash", SupportLang::Bash),
    ("zsh", SupportLang::Bash),
    ("ksh", SupportLang::Bash),
    ("bats", SupportLang::Bash),
    ("rs", SupportLang::Rust),
];

/// Map a file extension to its ast-grep language via [`EXTENSION_LANGUAGES`].
/// `None` for unsupported extensions (binary, unknown, etc.).
pub fn language_for_path(path: &Path) -> Option<SupportLang> {
    // Match the raw extension bytes case-insensitively (no lowercase String
    // allocation per file).
    let ext = path.extension()?.to_str()?;
    language_for_extension(ext)
}

/// [`language_for_path`] for a bare extension (no leading dot).
pub fn language_for_extension(ext: &str) -> Option<SupportLang> {
    EXTENSION_LANGUAGES
        .iter()
        .find(|(candidate, _)| ext.eq_ignore_ascii_case(candidate))
        .map(|(_, lang)| *lang)
}

/// Map a path to a language across the *full* `ast-grep` grammar set, not just
/// the extraction-supported subset in [`language_for_path`]. Structural
/// `find_pattern` search only needs a grammar to parse against — no hand-written
/// entity extractor — so it recognizes every language `ast-grep-language` links
/// (e.g. C/C++, PHP, HCL/Terraform), while the indexing pipeline stays
/// restricted to [`SUPPORTED_LANGUAGES`]. Kept as a distinct function so the two
/// mappings can diverge on purpose.
pub(crate) fn any_language_for_path(path: &Path) -> Option<SupportLang> {
    SupportLang::from_path(path)
}

/// Every language the extractor/parser supports, in a stable order. Used by
/// the pattern-rule pipeline's language-agnostic default ("run against every
/// file whose parse succeeds"). A slice (not a fixed-size array) so adding a
/// language is a one-line append with no size bump.
pub const SUPPORTED_LANGUAGES: &[SupportLang] = &[
    SupportLang::TypeScript,
    SupportLang::Tsx,
    SupportLang::JavaScript,
    SupportLang::C,
    SupportLang::Cpp,
    SupportLang::Go,
    SupportLang::Java,
    SupportLang::CSharp,
    SupportLang::Kotlin,
    SupportLang::Swift,
    SupportLang::Python,
    SupportLang::Ruby,
    SupportLang::Php,
    SupportLang::Scala,
    SupportLang::Dart,
    SupportLang::Lua,
    SupportLang::Elixir,
    SupportLang::Solidity,
    SupportLang::Haskell,
    SupportLang::Bash,
    SupportLang::Rust,
];

/// Resolve a rule/CLI language name to its `SupportLang`. Accepts the
/// canonical names plus common aliases (`ts`, `js`, `py`, `cs`).
pub fn language_from_name(name: &str) -> Option<SupportLang> {
    use SupportLang::*;
    Some(match name {
        "rust" => Rust,
        "typescript" | "ts" => TypeScript,
        "tsx" => Tsx,
        "javascript" | "js" => JavaScript,
        "c" => C,
        "cpp" | "c++" | "cxx" => Cpp,
        "go" | "golang" => Go,
        "java" => Java,
        "csharp" | "cs" => CSharp,
        "kotlin" | "kt" => Kotlin,
        "swift" => Swift,
        "python" | "py" => Python,
        "ruby" | "rb" => Ruby,
        "php" => Php,
        "lua" => Lua,
        "scala" => Scala,
        "dart" => Dart,
        "elixir" | "ex" => Elixir,
        "solidity" | "sol" => Solidity,
        "haskell" | "hs" => Haskell,
        "bash" | "sh" | "shell" => Bash,
        _ => return None,
    })
}

/// Canonical name accepted by ast-grep for an extraction-supported language.
pub fn language_name(lang: &SupportLang) -> &'static str {
    use SupportLang::*;
    match lang {
        TypeScript => "typescript",
        Tsx => "tsx",
        JavaScript => "javascript",
        C => "c",
        Cpp => "cpp",
        Go => "go",
        Java => "java",
        CSharp => "csharp",
        Kotlin => "kotlin",
        Swift => "swift",
        Python => "python",
        Ruby => "ruby",
        Php => "php",
        Lua => "lua",
        Scala => "scala",
        Dart => "dart",
        Elixir => "elixir",
        Solidity => "solidity",
        Haskell => "haskell",
        Bash => "bash",
        Rust => "rust",
        // Rules resolve only `SUPPORTED_LANGUAGES`. Keep this exhaustive so
        // a new supported language requires an explicit canonical name.
        Css | Hcl | Html | Json | Markdown | Nix | Yaml => {
            unreachable!("non-rule language cannot reach the pattern rule pipeline")
        }
    }
}

/// A parsed source file: the ast-grep root plus a syntax-error flag.
pub struct ParsedFile {
    pub lang: SupportLang,
    pub root: AstGrep<StrDoc<SupportLang>>,
}

impl ParsedFile {
    /// True when the tree contains ERROR/MISSING nodes (syntax error).
    ///
    /// Lazily walks the tree, so the build path never pays for it — the merged
    /// extract walk folds `has_error` detection into its single traversal. Only
    /// the query path (`find_pattern`, which parses without extracting) calls
    /// this.
    pub fn has_error(&self) -> bool {
        self.root.root().get_inner_node().has_error()
    }
}

/// Parse a source string with the given language. `ast-grep-language` grammar
/// loading cannot fail at runtime; syntax errors surface as ERROR nodes in the
/// tree, which we surface via `has_error` instead of panicking.
pub fn parse_source(lang: &SupportLang, source: &str) -> ParsedFile {
    // tree-sitter's lexer reserves byte 0x00 as an internal end-of-input
    // sentinel, so a literal NUL inside otherwise-valid source (e.g. in a
    // string/template literal) produces a spurious ERROR node. Replace with
    // a same-length placeholder to preserve byte offsets.
    let source = if source.as_bytes().contains(&0) {
        std::borrow::Cow::Owned(source.replace('\0', " "))
    } else {
        std::borrow::Cow::Borrowed(source)
    };
    let root = lang.ast_grep(source.as_ref());
    ParsedFile { lang: *lang, root }
}

/// Parse source using its selected language.
///
/// Ambiguous `.h` headers start as C. If that parse has errors, retry C++ and
/// retain the C++ tree only when it parses cleanly. Malformed C headers retain
/// their original partial C tree for error recovery.
pub fn parse_source_for_path(lang: &SupportLang, path: &Path, source: &str) -> ParsedFile {
    let parsed = parse_source(lang, source);
    let is_ambiguous_header = *lang == SupportLang::C
        && path
            .extension()
            .is_some_and(|ext| ext.eq_ignore_ascii_case("h"));
    if !is_ambiguous_header || !parsed.has_error() {
        return parsed;
    }

    let cpp = parse_source(&SupportLang::Cpp, source);
    if cpp.has_error() { parsed } else { cpp }
}

/// Parse a file on disk. Returns `Ok(None)` for unsupported extensions.
pub fn parse_file(path: &Path) -> Result<Option<ParsedFile>> {
    let Some(lang) = language_for_path(path) else {
        return Ok(None);
    };
    let source = std::fs::read_to_string(path)
        .with_context(|| format!("failed to read {}", path.display()))?;
    Ok(Some(parse_source_for_path(&lang, path, &source)))
}

#[cfg(test)]
mod tests {
    use super::{language_for_path, parse_source_for_path};
    use crate::extract;
    use crate::model::EntityKind;
    use ast_grep_language::SupportLang;
    use std::path::Path;

    #[test]
    fn cpp_header_retries_after_c_syntax_error() {
        let path = Path::new("include/repository.h");
        let source = "template <typename T> class Repository { public: void find() {} };";
        let parsed = parse_source_for_path(
            &language_for_path(path).expect(".h is supported"),
            path,
            source,
        );

        assert_eq!(parsed.lang, SupportLang::Cpp);
        assert!(!parsed.has_error(), "C++ header must parse cleanly");
        let entities = extract::extract(&parsed, 0).entities;
        assert!(
            entities
                .iter()
                .any(|entity| entity.kind == EntityKind::Class && entity.name == "Repository"),
            "class missing: {entities:?}"
        );
        assert!(
            entities
                .iter()
                .any(|entity| entity.kind == EntityKind::Function && entity.name == "find"),
            "method missing: {entities:?}"
        );
    }

    #[test]
    fn plain_c_header_keeps_c_grammar() {
        let path = Path::new("include/api.h");
        let parsed = parse_source_for_path(
            &language_for_path(path).expect(".h is supported"),
            path,
            "int add(int left, int right);",
        );

        assert_eq!(parsed.lang, SupportLang::C);
        assert!(!parsed.has_error(), "C header must parse cleanly");
    }

    #[test]
    fn malformed_header_keeps_partial_c_tree() {
        let path = Path::new("include/broken.h");
        let parsed = parse_source_for_path(
            &language_for_path(path).expect(".h is supported"),
            path,
            "template <typename T> class Repository {",
        );

        assert_eq!(parsed.lang, SupportLang::C);
        assert!(
            parsed.has_error(),
            "malformed header must remain diagnostic"
        );
    }
}
