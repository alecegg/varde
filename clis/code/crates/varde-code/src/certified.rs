use ast_grep_language::SupportLang;

/// Languages covered by the cognitive-complexity conformance gate.
pub const CERTIFIED_COMPLEXITY_LANGUAGES: [SupportLang; 21] = [
    SupportLang::Bash,
    SupportLang::C,
    SupportLang::Cpp,
    SupportLang::CSharp,
    SupportLang::Dart,
    SupportLang::Elixir,
    SupportLang::Go,
    SupportLang::Haskell,
    SupportLang::Java,
    SupportLang::JavaScript,
    SupportLang::Kotlin,
    SupportLang::Lua,
    SupportLang::Php,
    SupportLang::Python,
    SupportLang::Ruby,
    SupportLang::Rust,
    SupportLang::Scala,
    SupportLang::Solidity,
    SupportLang::Swift,
    SupportLang::Tsx,
    SupportLang::TypeScript,
];
