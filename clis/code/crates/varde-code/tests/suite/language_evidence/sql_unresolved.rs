//! Per-language evidence for the unresolved-local-import SQL rule.

use ast_grep_language::SupportLang;
use tempfile::{TempDir, tempdir};
use varde_code::db;
use varde_code::extract;
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::parse_source;
use varde_code::persist;
use varde_code::resolve;
use varde_code::rules::finding::Finding;
use varde_code::rules::sql::run_sql_rules_in_repo;
use varde_code::rules::{Rule, builtin_rules};

struct Fixture {
    _root: TempDir,
    findings: Vec<Finding>,
}

fn run_case(
    extension: &str,
    language: SupportLang,
    source: &str,
    companion: Option<(&str, SupportLang, &str)>,
) -> Fixture {
    let root = tempdir().unwrap();
    let source_path = if extension == "py" {
        "src/pkg/main.py".to_string()
    } else {
        format!("src/main.{extension}")
    };
    let mut sources = vec![(source_path.as_str(), language, source)];
    if extension == "py" {
        sources.push(("src/pkg/__init__.py", language, ""));
    }
    if extension == "hs" {
        sources.push((
            "src/MyApp/Parent.hs",
            language,
            "module MyApp.Parent where\n",
        ));
    }
    if let Some((path, language, text)) = companion {
        sources.push((path, language, text));
    }

    for (path, _, text) in &sources {
        let physical = root.path().join(path);
        std::fs::create_dir_all(physical.parent().unwrap()).unwrap();
        std::fs::write(physical, text).unwrap();
    }

    let mut entities = Vec::new();
    let mut symbols = Vec::new();
    for (file_id, (_, language, text)) in sources.iter().enumerate() {
        let parsed = parse_source(language, text);
        assert!(
            !parsed.has_error(),
            "could not parse {language:?} fixture: {text}"
        );
        let extracted = extract::extract(&parsed, file_id as u32);
        entities.extend(extracted.entities);
        symbols.extend(extracted.symbols);
    }
    let files: Vec<String> = sources
        .iter()
        .map(|(path, _, _)| (*path).to_string())
        .collect();
    let metadata = sources
        .iter()
        .map(|(_, _, text)| FileMeta {
            mtime: 0,
            size: text.len() as i64,
            content_hash: "fixture".into(),
        })
        .collect();
    let output = ExtractOutput {
        entities,
        symbols,
        diagnostics: Vec::new(),
        files,
        file_meta: metadata,
    };
    let graph = resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
    let db_path = root.path().join("index.db");
    persist::persist(&db_path, &[output], &graph, root.path()).unwrap();

    let conn = db::open_read_only(&db_path).unwrap();
    let rules: Vec<Rule> = builtin_rules()
        .into_iter()
        .filter(|rule| rule.id == "unresolved-local-import")
        .collect();
    let (findings, diagnostics) = run_sql_rules_in_repo(&rules, &conn, root.path()).unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    drop(conn);
    Fixture {
        _root: root,
        findings,
    }
}

fn assert_result(fixture: Fixture, expected_missing: Option<&str>) {
    match expected_missing {
        Some(specifier) => {
            assert_eq!(fixture.findings.len(), 1, "{:?}", fixture.findings);
            assert_eq!(fixture.findings[0].evidence["specifier"], specifier);
        }
        None => assert!(fixture.findings.is_empty(), "{:?}", fixture.findings),
    }
}

#[test]
fn typescript_relative_import_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "ts",
            SupportLang::TypeScript,
            "import './missing.ts'; import './present.ts';",
            Some((
                "src/present.ts",
                SupportLang::TypeScript,
                "export const present = true;",
            )),
        ),
        Some("./missing.ts"),
    );
}

#[test]
fn tsx_relative_import_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "tsx",
            SupportLang::Tsx,
            "import './missing.tsx'; import './present.tsx';",
            Some((
                "src/present.tsx",
                SupportLang::Tsx,
                "export const Present = () => null;",
            )),
        ),
        Some("./missing.tsx"),
    );
}

#[test]
fn javascript_relative_import_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "js",
            SupportLang::JavaScript,
            "import './missing.js'; import './present.js';",
            Some((
                "src/present.js",
                SupportLang::JavaScript,
                "export const present = true;",
            )),
        ),
        Some("./missing.js"),
    );
}

#[test]
fn python_missing_relative_module_is_reported_with_clean_sibling() {
    assert_result(
        run_case(
            "py",
            SupportLang::Python,
            "from .missing import value\nfrom .present import value\n",
            Some(("src/pkg/present.py", SupportLang::Python, "value = 1\n")),
        ),
        Some("./missing"),
    );
}

#[test]
fn ruby_relative_require_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "rb",
            SupportLang::Ruby,
            "require_relative './missing'\nrequire_relative './present'\n",
            Some(("src/present.rb", SupportLang::Ruby, "VALUE = 1\n")),
        ),
        Some("./missing"),
    );
}

#[test]
fn php_relative_require_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "php",
            SupportLang::Php,
            "<?php require './missing.php'; require './present.php';",
            Some((
                "src/present.php",
                SupportLang::Php,
                "<?php $present = true;",
            )),
        ),
        Some("./missing.php"),
    );
}

#[test]
fn lua_module_require_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "lua",
            SupportLang::Lua,
            "local missing = require 'app.missing'\nlocal present = require 'app.present'\n",
            Some(("app/present.lua", SupportLang::Lua, "return {}\n")),
        ),
        Some("app/missing"),
    );
}

#[test]
fn bash_relative_source_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "sh",
            SupportLang::Bash,
            ". ./missing.sh\n. ./present.sh\n",
            Some(("src/present.sh", SupportLang::Bash, "present=1\n")),
        ),
        Some("./missing.sh"),
    );
}

#[test]
#[ignore = "dependency facts do not certify a missing Java type for this locally declared package fixture"]
fn java_reports_missing_type_in_a_repository_package() {
    assert_result(
        run_case(
            "java",
            SupportLang::Java,
            "package app; import app.Missing; import app.Present; class Main {}",
            Some((
                "src/Present.java",
                SupportLang::Java,
                "package app; class Present {}",
            )),
        ),
        Some("app/Missing"),
    );
}

#[test]
fn csharp_namespace_imports_are_expected_absent_without_project_facts() {
    let fixture = run_case(
        "cs",
        SupportLang::CSharp,
        "using app.Missing; using app.Present; class Main {}",
        Some((
            "src/Present.cs",
            SupportLang::CSharp,
            "namespace app { class Present {} }",
        )),
    );
    assert_result(fixture, None);
}

#[test]
fn kotlin_reports_missing_type_in_a_repository_package() {
    assert_result(
        run_case(
            "kt",
            SupportLang::Kotlin,
            "package app\nimport app.Missing\nimport app.Present\nclass Main",
            Some((
                "src/Present.kt",
                SupportLang::Kotlin,
                "package app\nclass Present",
            )),
        ),
        Some("app/Missing"),
    );
}

#[test]
fn swift_module_imports_are_expected_absent_without_target_facts() {
    let fixture = run_case(
        "swift",
        SupportLang::Swift,
        "import Missing\nimport Present\n",
        Some((
            "src/Present.swift",
            SupportLang::Swift,
            "public struct Present {}",
        )),
    );
    assert_result(fixture, None);
}

#[test]
fn scala_reports_missing_type_in_a_repository_package() {
    assert_result(
        run_case(
            "scala",
            SupportLang::Scala,
            "package app\nimport app.Missing\nimport app.Present\nobject Main",
            Some((
                "src/Present.scala",
                SupportLang::Scala,
                "package app\nobject Present",
            )),
        ),
        Some("app/Missing"),
    );
}

#[test]
fn dart_relative_import_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "dart",
            SupportLang::Dart,
            "import './missing.dart'; import './present.dart';",
            Some(("src/present.dart", SupportLang::Dart, "class Present {}")),
        ),
        Some("./missing.dart"),
    );
}

#[test]
fn c_relative_header_include_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "c",
            SupportLang::C,
            "#include \"./missing.h\"\n#include \"./present.h\"\n",
            Some(("src/present.h", SupportLang::C, "#pragma once\n")),
        ),
        Some("./missing.h"),
    );
}

#[test]
fn cpp_relative_header_include_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "cpp",
            SupportLang::Cpp,
            "#include \"./missing.hpp\"\n#include \"./present.hpp\"\n",
            Some(("src/present.hpp", SupportLang::Cpp, "#pragma once\n")),
        ),
        Some("./missing.hpp"),
    );
}

#[test]
fn go_unresolved_import_is_expected_absent_without_local_file_certification() {
    let fixture = run_case(
        "go",
        SupportLang::Go,
        "package app\nimport _ \"example.com/repo/missing\"\n",
        Some(("src/present.go", SupportLang::Go, "package app\n")),
    );
    assert_result(fixture, None);
}

#[test]
fn elixir_missing_child_of_local_module_is_reported() {
    assert_result(
        run_case(
            "ex",
            SupportLang::Elixir,
            "defmodule MyApp.Parent do\nend\nalias MyApp.Parent.Missing\nalias MyApp.Parent.Present\n",
            Some((
                "src/present.ex",
                SupportLang::Elixir,
                "defmodule MyApp.Parent.Present do\nend\n",
            )),
        ),
        Some("MyApp.Parent.Missing"),
    );
}

#[test]
fn haskell_missing_child_of_local_module_is_reported() {
    assert_result(
        run_case(
            "hs",
            SupportLang::Haskell,
            "module Main where\nimport MyApp.Parent.Missing\nimport MyApp.Parent.Present\n",
            Some((
                "src/MyApp/Parent/Present.hs",
                SupportLang::Haskell,
                "module MyApp.Parent.Present where\n",
            )),
        ),
        Some("MyApp/Parent/Missing"),
    );
}

#[test]
fn solidity_relative_import_reports_missing_and_ignores_existing() {
    assert_result(
        run_case(
            "sol",
            SupportLang::Solidity,
            "import './missing.sol'; import './present.sol'; contract Main {}",
            Some((
                "src/present.sol",
                SupportLang::Solidity,
                "contract Present {}",
            )),
        ),
        Some("./missing.sol"),
    );
}

#[test]
fn rust_missing_module_declaration_is_reported() {
    assert_result(
        run_case(
            "rs",
            SupportLang::Rust,
            "mod missing;\nmod present;\n",
            Some(("src/present.rs", SupportLang::Rust, "pub fn value() {}\n")),
        ),
        Some("mod missing"),
    );
}
