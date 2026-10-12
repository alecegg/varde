//! Circular dependency rule evidence for every indexed source language.

use std::path::PathBuf;

use ast_grep_language::SupportLang;
use tempfile::tempdir;
use varde_code::db;
use varde_code::extract;
use varde_code::model::{ExtractOutput, FileMeta};
use varde_code::parse::parse_source;
use varde_code::persist;
use varde_code::resolve;
use varde_code::rules::finding::Finding;
use varde_code::rules::{builtin_rules, Rule};

fn run_pair(
    language: SupportLang,
    extension: &str,
    left: &str,
    right: &str,
    cycle: bool,
) -> Vec<Finding> {
    let root = tempdir().unwrap();
    let src = root.path().join("src");
    std::fs::create_dir_all(&src).unwrap();
    let files = [
        src.join(format!("left.{extension}")),
        src.join(format!("right.{extension}")),
    ];
    std::fs::write(&files[0], left).unwrap();
    std::fs::write(&files[1], right).unwrap();

    let paths: Vec<String> = files
        .iter()
        .map(|path| path.to_string_lossy().into_owned())
        .collect();
    let sources = [left, right];
    let mut entities = Vec::new();
    for (id, source) in sources.iter().enumerate() {
        let parsed = parse_source(&language, source);
        entities.extend(extract::extract(&parsed, id as u32).entities);
    }
    let output = ExtractOutput {
        entities,
        symbols: Vec::new(),
        diagnostics: Vec::new(),
        files: paths,
        file_meta: sources
            .iter()
            .map(|source| FileMeta {
                mtime: 0,
                size: source.len() as i64,
                content_hash: "0".into(),
            })
            .collect(),
    };
    let graph = resolve::resolve(&output.entities, &output.symbols, &output.files).unwrap();
    let db_path: PathBuf = root.path().join("index.db");
    persist::persist(&db_path, &[output], &graph, root.path()).unwrap();
    let conn = db::open_read_only(&db_path).unwrap();
    let rule: Rule = builtin_rules()
        .into_iter()
        .find(|rule| rule.id == "circular-import")
        .unwrap();
    let (findings, diagnostics) =
        varde_code::rules::sql::run_sql_rules_in_repo(&[rule], &conn, root.path()).unwrap();
    assert!(diagnostics.is_empty(), "{diagnostics:?}");
    if cycle {
        assert_eq!(findings.len(), 1, "expected a certified two-file cycle");
    } else {
        assert!(findings.is_empty(), "unexpected cycle: {findings:?}");
    }
    drop(conn);
    drop(root);
    findings
}

macro_rules! case {
    ($name:ident, $lang:ident, $ext:literal, $left:literal, $right:literal, $cycle:expr) => {
        #[test]
        fn $name() {
            run_pair(SupportLang::$lang, $ext, $left, $right, $cycle);
            if $cycle {
                run_pair(SupportLang::$lang, $ext, "", "", false);
            }
        }
    };
}

// The relative-path certifier supports these module systems. Each cycle uses
// explicit relative paths so the SQL rule only sees exact indexed targets.
case!(
    javascript_cycle_and_clean_pair,
    JavaScript,
    "js",
    "import './right.js';",
    "import './left.js';",
    true
);
case!(
    typescript_cycle_and_clean_pair,
    TypeScript,
    "ts",
    "import './right.ts';",
    "import './left.ts';",
    true
);
case!(
    tsx_cycle_and_clean_pair,
    Tsx,
    "tsx",
    "import './right.tsx';",
    "import './left.tsx';",
    true
);
case!(
    dart_expected_absent_without_package_path,
    Dart,
    "dart",
    "import 'right.dart';",
    "import 'left.dart';",
    false
);
case!(
    solidity_expected_absent_without_relative_path,
    Solidity,
    "sol",
    "import 'right.sol';",
    "import 'left.sol';",
    false
);

// Rust dependency units are Cargo package directories. These files are in one
// package and cannot form a certified inter-package cycle.
case!(
    rust_expected_absent_within_one_package,
    Rust,
    "rs",
    "use crate::right;",
    "use crate::left;",
    false
);

// Package/module fact builders need declarations/manifests beyond this small
// pair. These expected-absent cases ensure incomplete evidence abstains.
case!(
    c_expected_absent_without_relative_include,
    C,
    "c",
    "#include \"./right.h\"",
    "#include \"./left.h\"",
    false
);
case!(
    cpp_expected_absent_without_relative_include,
    Cpp,
    "cpp",
    "#include \"./right.hpp\"",
    "#include \"./left.hpp\"",
    false
);
case!(
    csharp_expected_absent_without_project_units,
    CSharp,
    "cs",
    "using Right;",
    "using Left;",
    false
);
case!(
    elixir_expected_absent_without_module_declarations,
    Elixir,
    "ex",
    "import Right",
    "import Left",
    false
);
case!(
    go_expected_absent_without_package_metadata,
    Go,
    "go",
    "package left\nimport \"example/right\"",
    "package right\nimport \"example/left\"",
    false
);
case!(
    haskell_cycle_and_clean_pair,
    Haskell,
    "hs",
    "module Left where\nimport Right",
    "module Right where\nimport Left",
    true
);
case!(
    java_expected_absent_without_type_declarations,
    Java,
    "java",
    "package left; import right.Right;",
    "package right; import left.Left;",
    false
);
case!(
    kotlin_expected_absent_without_type_declarations,
    Kotlin,
    "kt",
    "package left\nimport right.Right",
    "package right\nimport left.Left",
    false
);
case!(
    scala_expected_absent_without_type_declarations,
    Scala,
    "scala",
    "package left\nimport right.Right",
    "package right\nimport left.Left",
    false
);
case!(
    lua_cycle_and_clean_pair,
    Lua,
    "lua",
    "require('right')",
    "require('left')",
    true
);
case!(
    bash_cycle_and_clean_pair,
    Bash,
    "sh",
    "source ./right.sh",
    "source ./left.sh",
    true
);
case!(
    python_expected_absent_without_package_targets,
    Python,
    "py",
    "import right",
    "import left",
    false
);
case!(
    ruby_expected_absent_without_load_path_targets,
    Ruby,
    "rb",
    "require 'right'",
    "require 'left'",
    false
);
case!(
    php_cycle_and_clean_pair,
    Php,
    "php",
    "<?php require 'right.php';",
    "<?php require 'left.php';",
    true
);
case!(
    swift_expected_absent_without_package_manifest,
    Swift,
    "swift",
    "import Right",
    "import Left",
    false
);
