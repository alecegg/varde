//! Per-language query evidence for C, C++, C#, Go, Java, Kotlin, Scala,
//! Swift, Dart, and Rust.

use std::path::{Path, PathBuf};
use super::index_and_persist;

fn index_fixture(language: &str, filename: &str, tag: &str) -> super::IndexedFixture {
    let source_path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests/fixtures")
        .join(language)
        .join(filename);
    let content = std::fs::read_to_string(&source_path).expect("fixture source exists");
    let fixture = index_and_persist(language, tag, vec![(filename.to_string(), content)]);
    fixture
}

fn data(root: &Path, db: &Path, mode: &str, fields: serde_json::Value) -> serde_json::Value {
    let mut input = fields;
    input["repoRoot"] = serde_json::json!(root);
    input["dbPath"] = serde_json::json!(db);
    let _lock = crate::ENV_LOCK.lock().unwrap_or_else(std::sync::PoisonError::into_inner);
    let output = varde_code::query::run_mode(mode, &input.to_string());
    let envelope: serde_json::Value = serde_json::from_str(&output).expect("query returns JSON");
    assert_eq!(envelope["ok"], true, "{mode}: {envelope}");
    envelope["data"].clone()
}

macro_rules! language_case {
    ($module:ident, $language:literal, $file:literal, $symbol:literal, $parent:literal) => {
        mod $module {
            use super::*;

            #[test]
            fn simple_symbol_and_import_queries() {
                let fixture = index_fixture($language, $file, stringify!($module));
                let file = fixture.files[0].clone();
                let symbols = data(&fixture.root, &fixture.db, "symbols_in_file", serde_json::json!({"filePath": file}));
                assert!(symbols.as_array().unwrap().iter().any(|item| item["name"] == $symbol), "{symbols}");

                let symbol = data(&fixture.root, &fixture.db, "get_symbol", serde_json::json!({"name": $symbol, "filePath": file}));
                assert_eq!(symbol["name"], $symbol);

                let filtered = data(&fixture.root, &fixture.db, "filter_symbols", serde_json::json!({"file": $file}));
                assert!(filtered.as_array().unwrap().iter().any(|item| item["name"] == $symbol), "{filtered}");

                let imports = data(&fixture.root, &fixture.db, "find_imports", serde_json::json!({"filePath": file}));
                assert!(imports.as_array().is_some(), "{imports}");
                assert!(imports.as_array().unwrap().iter().all(|item| item["resolved"] == false && item["to"] == ""), "single-file fixture imports are unresolved: {imports}");
                let tests = data(&fixture.root, &fixture.db, "tests_for_file", serde_json::json!({"filePath": file}));
                assert_eq!(tests, serde_json::json!([]), "standalone source fixture has no associated test file");

                if !$parent.is_empty() {
                    let hierarchy_name = if stringify!($module) == "swift" { "GreeterImpl" } else { $symbol };
                    let hierarchy = data(&fixture.root, &fixture.db, "type_hierarchy", serde_json::json!({"name": hierarchy_name}));
                    assert_eq!(hierarchy["symbol"]["name"], hierarchy_name, "{hierarchy}");
                    assert!(hierarchy["supertypes"].as_array().unwrap().iter().any(|item| item["name"] == $parent), "expected parent {}: {hierarchy}", $parent);
                }
            }
        }
    };
}

language_case!(c, "c", "structural.c", "add", "");
language_case!(cpp, "cpp", "structural.cpp", "Widget", "Base");
language_case!(cs, "cs", "Program.cs", "Program", "");
language_case!(go, "go", "fixture.go", "Add", "");
language_case!(java, "java", "Controller.java", "TodoController", "");
language_case!(kotlin, "kotlin", "fixture.kt", "add", "");
language_case!(scala, "scala", "structural.scala", "UserService", "BaseService");
language_case!(swift, "swift", "fixture.swift", "add", "Greeter");
language_case!(dart, "dart", "structural.dart", "Animal", "Base");
language_case!(rust, "rust", "structural.rs", "greet", "");

macro_rules! import_target_na {
    ($test:ident, $lang:literal) => {
        #[test]
        fn $test() {
            let fixture = index_fixture($lang, match $lang { "c" => "structural.c", "cpp" => "structural.cpp", "cs" => "Program.cs", "go" => "fixture.go", "java" => "Controller.java", "kotlin" => "fixture.kt", "scala" => "structural.scala", "swift" => "fixture.swift", "dart" => "structural.dart", _ => "structural.rs" }, stringify!($test));
            assert_eq!(fixture.files.len(), 1, "N/A find_imports target for {}: single-file fixture has no indexed target", $lang);
        }
    };
}
import_target_na!(c_import_target_na, "c");
import_target_na!(cpp_import_target_na, "cpp");
import_target_na!(csharp_import_target_na, "cs");
import_target_na!(go_import_target_na, "go");
import_target_na!(java_import_target_na, "java");
import_target_na!(kotlin_import_target_na, "kotlin");
import_target_na!(scala_import_target_na, "scala");
import_target_na!(swift_import_target_na, "swift");
import_target_na!(dart_import_target_na, "dart");
import_target_na!(rust_import_target_na, "rust");
