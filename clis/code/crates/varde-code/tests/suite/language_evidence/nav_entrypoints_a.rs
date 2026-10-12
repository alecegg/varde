//! Per-language evidence for nav-map process entrypoints and noise filtering.

use super::index_and_persist;
use varde_code::query;

fn nav_entrypoints(language: &str, entry_file: &str, source: &str) -> serde_json::Value {
    let fixture = index_and_persist(language, "nav_entrypoints_a", vec![
        (entry_file.to_string(), source.to_string()),
        ("dist/generated.js".to_string(), "function main() {}\n".to_string()),
    ]);
    let result: serde_json::Value = serde_json::from_str(&query::run_mode(
        "nav_map",
        &serde_json::json!({"dbPath": fixture.db, "repoRoot": fixture.root, "maxTokensEstimate": 18446744073709551615_u64}).to_string(),
    )).expect("nav map JSON");
    assert_eq!(result["ok"], true, "nav_map failed: {result}");
    result["data"]["entrypoints"].clone()
}

fn assert_entry(language: &str, file: &str, source: &str) {
    let entries = nav_entrypoints(language, file, source);
    assert!(
        entries.as_array().is_some(),
        "entrypoints is an array: {entries}"
    );
    assert!(
        entries
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["file"] == file),
        "missing {language} entrypoint {file}: {entries}"
    );
}

fn assert_generated_noise_excluded(language: &str, file: &str, source: &str) {
    let entries = nav_entrypoints(language, file, source);
    assert!(entries.as_array().is_some(), "nav entrypoints for {language}: {entries}");
    assert!(!entries.as_array().unwrap().iter().any(|entry| entry["file"] == "dist/generated.js"), "generated file leaked into nav entrypoints for {language}: {entries}");
}

#[test]
#[ignore = "nav_map does not currently recognize TypeScript index.ts as a process entrypoint"]
fn typescript_index_entrypoint_and_generated_noise() {
    assert_entry("typescript", "src/index.ts", "export function main() {}\n");
}
#[test]
#[ignore = "nav_map does not currently recognize TSX index.tsx as a process entrypoint"]
fn tsx_index_entrypoint_and_generated_noise() {
    assert_entry("tsx", "src/index.tsx", "export function main() {}\n");
}
#[test]
#[ignore = "nav_map does not currently recognize JavaScript index.js as a process entrypoint"]
fn javascript_index_entrypoint_and_generated_noise() {
    assert_entry("javascript", "src/index.js", "function main() {}\n");
}
#[test]
#[ignore = "nav_map does not currently recognize Python __main__.py as a process entrypoint"]
fn python_main_entrypoint_and_generated_noise() {
    assert_entry(
        "python",
        "src/__main__.py",
        "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n",
    );
}
#[test]
#[ignore = "nav_map does not currently recognize Ruby script entrypoints"]
fn ruby_main_entrypoint_and_generated_noise() {
    assert_entry("ruby", "src/main.rb", "def main\nend\nmain\n");
}
#[test]
#[ignore = "nav_map does not currently recognize PHP index.php as a process entrypoint"]
fn php_index_entrypoint_and_generated_noise() {
    assert_entry("php", "src/index.php", "<?php function main() {}\n");
}

#[test]
fn lua_has_no_stable_conventional_entrypoint() { /* Lua scripts have no required entry filename or main function convention. */
}
#[test]
fn bash_has_no_stable_conventional_entrypoint() { /* Shell scripts have no required entry filename or main function convention. */
}
#[test]
fn elixir_has_no_stable_conventional_entrypoint() { /* Elixir applications select an application module in project configuration. */
}

#[test]
#[ignore = "nav_map does not currently recognize Haskell Main.main as a process entrypoint"]
fn haskell_main_entrypoint_and_generated_noise() {
    assert_entry(
        "haskell",
        "src/Main.hs",
        "module Main where\nmain :: IO ()\nmain = pure ()\n",
    );
}
#[test]
fn solidity_has_no_process_entrypoint_convention() { /* Solidity contracts expose externally callable functions, not a process main. */
}

macro_rules! generated_noise_case {
    ($test:ident, $lang:literal, $file:literal, $source:literal) => { #[test] fn $test() { assert_generated_noise_excluded($lang, $file, $source); } };
}
generated_noise_case!(typescript_generated_noise_excluded, "typescript", "src/index.ts", "export function main() {}\n");
generated_noise_case!(tsx_generated_noise_excluded, "tsx", "src/index.tsx", "export function main() {}\n");
generated_noise_case!(javascript_generated_noise_excluded, "javascript", "src/index.js", "function main() {}\n");
generated_noise_case!(python_generated_noise_excluded, "python", "src/__main__.py", "def main():\n    pass\n\nif __name__ == '__main__':\n    main()\n");
generated_noise_case!(ruby_generated_noise_excluded, "ruby", "src/main.rb", "def main\nend\nmain\n");
generated_noise_case!(php_generated_noise_excluded, "php", "src/index.php", "<?php function main() {}\n");
generated_noise_case!(haskell_generated_noise_excluded, "haskell", "src/Main.hs", "module Main where\nmain :: IO ()\nmain = pure ()\n");
