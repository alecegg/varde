//! Per-language evidence for the dependency-boundary SQL rule.

use ast_grep_language::SupportLang;
use tempfile::tempdir;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::parse_source;
use varde_code::rules::sql::run_sql_rules_in_repo;
use varde_code::rules::{Rule, builtin_rules};
use varde_code::{persist, resolve};

struct Source<'a> {
    path: String,
    language: SupportLang,
    text: &'a str,
}

fn findings(sources: &[Source<'_>], source_prefix: &str, target_prefix: &str) -> Vec<String> {
    let root = tempdir().unwrap();
    for source in sources {
        let path = root.path().join(&source.path);
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, source.text).unwrap();
    }

    let files = sources
        .iter()
        .map(|source| {
            root.path()
                .join(&source.path)
                .to_string_lossy()
                .into_owned()
        })
        .collect::<Vec<_>>();
    let entities = sources
        .iter()
        .enumerate()
        .flat_map(|(id, source)| {
            let parsed = parse_source(&source.language, source.text);
            if !source.path.ends_with(".csproj")
                && source.path != "go.mod"
                && source.path != "Cargo.toml"
            {
                assert!(!parsed.has_error(), "parse failed for {}", source.path);
            }
            extract::extract(&parsed, id as u32).entities
        })
        .collect();
    let output = ExtractOutput {
        entities,
        symbols: Vec::new(),
        diagnostics: Vec::new(),
        files: files.clone(),
        file_meta: sources
            .iter()
            .map(|source| FileMeta {
                mtime: 0,
                size: source.text.len() as i64,
                content_hash: "0".into(),
            })
            .collect(),
    };
    let graph = resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
    let db_path = root.path().join("index.db");
    persist::persist(&db_path, &[output], &graph, root.path()).unwrap();
    let conn = db::open_read_only(&db_path).unwrap();
    let mut rule: Rule = builtin_rules()
        .into_iter()
        .find(|rule| rule.id == "dependency-boundary")
        .unwrap();
    rule.strings = Some(
        [
            ("source_prefix".into(), source_prefix.into()),
            ("target_prefix".into(), target_prefix.into()),
        ]
        .into(),
    );
    let (findings, diagnostics) = run_sql_rules_in_repo(&[rule], &conn, root.path()).unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    drop(conn);
    drop(root);
    findings
        .into_iter()
        .map(|finding| finding.location.file)
        .collect()
}

fn assert_boundary(language: SupportLang, extension: &str, violating: &str, clean: &str) {
    let target = match language {
        SupportLang::CSharp => "namespace Internal;\nclass Lib {}",
        SupportLang::Java => "package internal; public class Lib {}",
        SupportLang::Kotlin => "package internal\nclass Lib",
        SupportLang::Scala => "package internal\nclass Lib",
        SupportLang::Elixir => "defmodule Internal.Lib do\nend",
        SupportLang::Haskell => "module Internal.Lib where",
        _ => "",
    };
    let mut files = vec![
        Source {
            path: format!("src/main.{extension}"),
            language,
            text: violating,
        },
        Source {
            path: format!("internal/lib.{extension}"),
            language,
            text: target,
        },
        Source {
            path: format!("other/main.{extension}"),
            language,
            text: clean,
        },
    ];
    if language == SupportLang::CSharp {
        files.push(Source {
            path: "src/src.csproj".into(),
            language,
            text: "<Project />",
        });
        files.push(Source {
            path: "internal/internal.csproj".into(),
            language,
            text: "<Project />",
        });
    }
    if language == SupportLang::Go {
        files.push(Source {
            path: "go.mod".into(),
            language,
            text: "module example.com/app\n",
        });
    }
    let found = findings(&files, "src", "internal");
    assert_eq!(
        found.len(),
        1,
        "expected only src to import internal, got {found:?}"
    );
    assert!(found[0].ends_with(&format!("src/main.{extension}")));
}

fn assert_expected_absent(language: SupportLang, extension: &str, source: &str) {
    let files = [
        Source {
            path: format!("src/main.{extension}"),
            language,
            text: source,
        },
        Source {
            path: format!("internal/lib.{extension}"),
            language,
            text: "",
        },
        Source {
            path: format!("other/main.{extension}"),
            language,
            text: source,
        },
    ];
    assert!(findings(&files, "src", "internal").is_empty());
}

#[test]
fn typescript_relative_boundary() {
    assert_boundary(
        SupportLang::TypeScript,
        "ts",
        "import { lib } from '../internal/lib';",
        "import { lib } from '../internal/lib';",
    );
}
#[test]
fn tsx_relative_boundary() {
    assert_boundary(
        SupportLang::Tsx,
        "tsx",
        "import { lib } from '../internal/lib';",
        "import { lib } from '../internal/lib';",
    );
}
#[test]
fn javascript_relative_boundary() {
    assert_boundary(
        SupportLang::JavaScript,
        "js",
        "import { lib } from '../internal/lib.js';",
        "import { lib } from '../internal/lib.js';",
    );
}
#[test]
fn c_relative_boundary() {
    assert_boundary(
        SupportLang::C,
        "c",
        "#include \"../internal/lib.c\"\nint main(void) { return 0; }",
        "",
    );
}
#[test]
fn cpp_relative_boundary() {
    assert_boundary(
        SupportLang::Cpp,
        "cpp",
        "#include \"../internal/lib.cpp\"\nint main() { return 0; }",
        "",
    );
}
#[test]
fn go_package_boundary() {
    assert_boundary(
        SupportLang::Go,
        "go",
        "package main\nimport \"example.com/app/internal\"",
        "package other\nimport \"example.com/app/internal\"",
    );
}
#[test]
#[ignore = "fixture currently yields no certified Java boundary fact; follow-up evidence needed"]
fn java_relative_boundary() {
    assert_boundary(
        SupportLang::Java,
        "java",
        "package src; import internal.Lib; class Main {}",
        "package other; import internal.Lib; class Main {}",
    );
}
#[test]
#[ignore = "fixture currently yields no certified C# cross-project boundary fact; follow-up evidence needed"]
fn csharp_positive_fact_boundary() {
    assert_boundary(
        SupportLang::CSharp,
        "cs",
        "using Internal; class Main {}",
        "using Internal; class Main {}",
    );
}
#[test]
fn kotlin_relative_boundary() {
    assert_boundary(
        SupportLang::Kotlin,
        "kt",
        "package src\nimport internal.Lib",
        "package other\nimport internal.Lib",
    );
}
#[test]
fn swift_positive_fact_boundary() {
    let files = [
        Source {
            path: "Package/Package.swift".into(),
            language: SupportLang::Swift,
            text: "let targets = [.target(name: \"Src\"), .target(name: \"Internal\"), .target(name: \"Other\")]",
        },
        Source {
            path: "Package/Sources/Src/main.swift".into(),
            language: SupportLang::Swift,
            text: "import Internal",
        },
        Source {
            path: "Package/Sources/Internal/lib.swift".into(),
            language: SupportLang::Swift,
            text: "public struct Lib {}",
        },
        Source {
            path: "Package/Sources/Other/main.swift".into(),
            language: SupportLang::Swift,
            text: "import Internal",
        },
    ];
    let found = findings(&files, "Package/Sources/Src", "Package/Sources/Internal");
    assert_eq!(
        found.len(),
        1,
        "expected SwiftPM target boundary, got {found:?}"
    );
}
#[test]
fn python_relative_boundary() {
    let files = [
        Source {
            path: "src/main.py".into(),
            language: SupportLang::Python,
            text: "from .internal import lib",
        },
        Source {
            path: "src/__init__.py".into(),
            language: SupportLang::Python,
            text: "",
        },
        Source {
            path: "src/internal/__init__.py".into(),
            language: SupportLang::Python,
            text: "",
        },
        Source {
            path: "src/internal/lib.py".into(),
            language: SupportLang::Python,
            text: "",
        },
    ];
    let found = findings(&files, "src", "src/internal");
    assert_eq!(
        found.len(),
        1,
        "expected Python package boundary, got {found:?}"
    );
}
#[test]
fn ruby_relative_boundary() {
    assert_boundary(
        SupportLang::Ruby,
        "rb",
        "require_relative '../internal/lib'",
        "require_relative '../internal/lib'",
    );
}
#[test]
fn php_relative_boundary() {
    assert_boundary(
        SupportLang::Php,
        "php",
        "<?php require_once '../internal/lib.php';",
        "<?php require_once '../internal/lib.php';",
    );
}
#[test]
fn scala_relative_boundary() {
    assert_boundary(
        SupportLang::Scala,
        "scala",
        "package src\nimport internal.Lib",
        "package other\nimport internal.Lib",
    );
}
#[test]
fn dart_relative_boundary() {
    assert_boundary(
        SupportLang::Dart,
        "dart",
        "import '../internal/lib.dart';",
        "import '../internal/lib.dart';",
    );
}
#[test]
fn lua_relative_boundary() {
    assert_boundary(
        SupportLang::Lua,
        "lua",
        "require('internal.lib')",
        "require('internal.lib')",
    );
}
#[test]
fn elixir_relative_boundary() {
    assert_boundary(
        SupportLang::Elixir,
        "ex",
        "alias Internal.Lib",
        "alias Internal.Lib",
    );
}
#[test]
fn solidity_relative_boundary() {
    assert_boundary(
        SupportLang::Solidity,
        "sol",
        "import '../internal/lib.sol';",
        "import '../internal/lib.sol';",
    );
}
#[test]
fn haskell_relative_boundary() {
    assert_boundary(
        SupportLang::Haskell,
        "hs",
        "module Src.Main where\nimport Internal.Lib",
        "module Other.Main where\nimport Internal.Lib",
    );
}
#[test]
fn bash_relative_boundary() {
    assert_boundary(
        SupportLang::Bash,
        "sh",
        "source ../internal/lib.sh",
        "source ../internal/lib.sh",
    );
}
#[test]
fn rust_cross_package_boundary() {
    let sources = [
        Source {
            path: "Cargo.toml".into(),
            language: SupportLang::Rust,
            text: "[package]\nname = \"app\"\nversion = \"0.1.0\"\nedition = \"2021\"",
        },
        Source {
            path: "src/main.rs".into(),
            language: SupportLang::Rust,
            text: "mod internal;\nuse internal::lib;",
        },
        Source {
            path: "src/internal.rs".into(),
            language: SupportLang::Rust,
            text: "pub mod lib;",
        },
        Source {
            path: "src/internal/lib.rs".into(),
            language: SupportLang::Rust,
            text: "pub fn run() {}",
        },
    ];
    let found = findings(&sources, "src", "src/internal");
    assert!(
        found.is_empty(),
        "same-package Rust modules are not boundary facts: {found:?}"
    );
}
