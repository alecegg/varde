//! Process entrypoint and generated-source evidence for C, C++, C#, Go, Java,
//! Kotlin, Scala, Swift, Dart, and Rust.

use varde_code::query::{entrypoints, run_mode};

fn project(language: &str, filename: &str, source: &str) -> Vec<entrypoints::Entrypoint> {
    let root = tempfile::tempdir().expect("temporary nav project");
    let root_path = root.path();
    std::fs::create_dir_all(root_path.join("src")).expect("create source directory");
    std::fs::write(root_path.join("src").join(filename), source).expect("write entrypoint source");
    std::fs::create_dir_all(root_path.join("dist")).expect("create generated directory");
    std::fs::write(root_path.join("dist/app.min.js"), "function bundled(){return 1}function minified(){return bundled()}\n").expect("write generated source");

    varde_code::build::run_with_force(root_path.to_str().expect("UTF-8 temp path"), true)
        .expect("index fixture project");
    let db = varde_code::db::path::repo_db_path(root_path);
    let conn = rusqlite::Connection::open(&db).expect("open fixture index");
    let found = entrypoints::detect_process_mains(&conn).expect("detect process entrypoints");
    let nav: serde_json::Value = serde_json::from_str(&run_mode("nav_map", &serde_json::json!({"dbPath": db, "repoRoot": root_path, "maxTokensEstimate": 18446744073709551615_u64}).to_string())).expect("nav map JSON");
    assert_eq!(nav["ok"], true, "{language}: nav_map failed: {nav}");
    assert!(!nav.to_string().contains("dist/app.min.js"), "{language}: generated file leaked into nav_map: {nav}");
    found
}

macro_rules! entrypoint_case {
    ($name:ident, $language:literal, $file:literal, $source:literal, $symbol:literal) => {
        #[test]
        fn $name() {
            let found = project($language, $file, $source);
            assert!(
                found.iter().any(|entry| entry.symbol == $symbol),
                "{} entrypoint missing: {found:?}",
                $language
            );
        }
    };
}

macro_rules! ignored_entrypoint_case {
    ($name:ident, $language:literal, $file:literal, $source:literal, $symbol:literal, $reason:literal) => {
        #[test]
        #[ignore = $reason]
        fn $name() {
            let found = project($language, $file, $source);
            assert!(
                found.iter().any(|entry| entry.symbol == $symbol),
                "{} entrypoint missing: {found:?}",
                $language
            );
        }
    };
}

entrypoint_case!(
    c_main_is_navigation_entrypoint,
    "c",
    "main.c",
    "int main(void) { return 0; }",
    "main"
);
entrypoint_case!(
    cpp_main_is_navigation_entrypoint,
    "cpp",
    "main.cpp",
    "int main() { return 0; }",
    "main"
);
ignored_entrypoint_case!(
    csharp_main_is_navigation_entrypoint,
    "cs",
    "Program.cs",
    "class Program { static void Main(string[] args) {} }",
    "Main",
    "process-main detection does not currently emit C# Main methods"
);
entrypoint_case!(
    go_main_is_navigation_entrypoint,
    "go",
    "main.go",
    "package main\nfunc main() {}",
    "main"
);
ignored_entrypoint_case!(
    java_main_is_navigation_entrypoint,
    "java",
    "Main.java",
    "class Main { public static void main(String[] args) {} }",
    "main",
    "process-main detection does not currently emit Java main methods"
);
entrypoint_case!(
    kotlin_main_is_navigation_entrypoint,
    "kotlin",
    "Main.kt",
    "fun main(args: Array<String>) {}",
    "main"
);
ignored_entrypoint_case!(
    scala_main_is_navigation_entrypoint,
    "scala",
    "Main.scala",
    "object Main { def main(args: Array[String]): Unit = {} }",
    "main",
    "process-main detection does not currently emit Scala main methods"
);
ignored_entrypoint_case!(
    swift_main_is_navigation_entrypoint,
    "swift",
    "main.swift",
    "func main() {}",
    "main",
    "process-main detection does not currently emit Swift top-level main functions"
);
ignored_entrypoint_case!(
    dart_main_is_navigation_entrypoint,
    "dart",
    "main.dart",
    "void main() {}",
    "main",
    "process-main detection does not currently emit Dart main functions"
);
entrypoint_case!(
    rust_main_is_navigation_entrypoint,
    "rust",
    "main.rs",
    "fn main() {}",
    "main"
);
