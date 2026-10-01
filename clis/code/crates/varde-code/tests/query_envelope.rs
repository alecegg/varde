//! CLI envelope contract tests: the uniform `{"ok", "data", "meta"}` JSON shape across
//! all query subcommands, and the `--help` registration of query modes.

use std::process::Command;

const BIN: &str = env!("CARGO_BIN_EXE_varde-code");

/// All 17 query-mode subcommand names, exactly as registered in `--help`.
const MODES: [&str; 17] = [
    "symbols_in_file",
    "get_symbol",
    "dependencies",
    "dependents",
    "tests_for_file",
    "hotspots",
    "map_file",
    "map_symbol",
    "map_path",
    "explore",
    "blast_radius",
    "symbol_blast_radius",
    "detect_changes",
    "find_imports",
    "type_hierarchy",
    "filter_symbols",
    "find_pattern",
];

fn run(args: &[&str]) -> String {
    let out = Command::new(BIN).args(args).output().expect("binary runs");
    assert!(
        out.status.success(),
        "command {args:?} exited {:?}: {}",
        out.status.code(),
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).trim().to_string()
}

#[test]
fn help_lists_all_17_mode_subcommands() {
    let help = run(&["--help"]);
    assert!(help.contains("read-only fresh-index query"), "{help}");
    assert!(!help.contains("required before query/scan"), "{help}");
    for mode in MODES {
        assert!(
            help.contains(mode),
            "--help must list the {mode:?} subcommand; got:\n{help}"
        );
    }
}

#[test]
fn context_pack_help_documents_budget_controls_and_defaults() {
    let help = run(&["context_pack", "--help"]);

    for setting in [
        "maxTokensEstimate",
        "4000",
        "includeReadingOrder",
        "true",
        "fullResults",
    ] {
        assert!(
            help.contains(setting),
            "context_pack --help must document {setting:?}; got:\n{help}"
        );
    }
}

#[test]
fn context_pack_cli_budgets_standalone_and_batch_child_envelopes() {
    let root =
        std::env::temp_dir().join(format!("varde-qenv-context-budget-{}", std::process::id()));
    let home = root.with_extension("home");
    let source = root.join("src");
    let _ = std::fs::remove_dir_all(&root);
    let _ = std::fs::remove_dir_all(&home);
    std::fs::create_dir_all(&source).expect("fixture source directory creates");
    for index in 0..30 {
        std::fs::write(
            source.join(format!(
                "needle_module_{index:02}_with_a_long_path_segment.rs"
            )),
            format!("pub fn needle_symbol_{index}() {{}}\n"),
        )
        .expect("fixture source writes");
    }
    std::fs::create_dir_all(&home).expect("isolated home creates");

    let built = Command::new(BIN)
        .args(["build", "--repo-root", root.to_str().unwrap()])
        .env("HOME", &home)
        .env("VARDE_CODE_TOZ", "0")
        .output()
        .expect("fixture index builds");
    assert!(
        built.status.success(),
        "build failed: {}",
        String::from_utf8_lossy(&built.stdout)
    );

    let budget = 250;
    let repo_root = root.to_str().unwrap();
    let standalone_input = serde_json::json!({
        "repoRoot": repo_root,
        "query": "needle",
        "maxTokensEstimate": budget
    })
    .to_string();
    let standalone = Command::new(BIN)
        .args(["context_pack", "--json", &standalone_input])
        .env("HOME", &home)
        .env("VARDE_CODE_TOZ", "0")
        .output()
        .expect("standalone context_pack runs");
    assert!(
        standalone.status.success(),
        "standalone failed: {}",
        String::from_utf8_lossy(&standalone.stderr)
    );
    let standalone: serde_json::Value =
        serde_json::from_slice(&standalone.stdout).expect("standalone output is JSON");

    let batch_input = serde_json::json!({
        "repoRoot": repo_root,
        "calls": [{
            "mode": "context_pack",
            "query": "needle",
            "maxTokensEstimate": budget
        }]
    })
    .to_string();
    let batch = Command::new(BIN)
        .args(["batch", "--json", &batch_input])
        .env("HOME", &home)
        .env("VARDE_CODE_TOZ", "0")
        .output()
        .expect("batch context_pack runs");
    assert!(
        batch.status.success(),
        "batch failed: {}",
        String::from_utf8_lossy(&batch.stderr)
    );
    let batch: serde_json::Value =
        serde_json::from_slice(&batch.stdout).expect("batch output is JSON");
    let child = &batch["data"][0];

    for (label, envelope) in [("standalone", &standalone), ("batch child", child)] {
        assert_eq!(envelope["ok"], true, "{label}: {envelope}");
        assert!(envelope["data"]["files"].as_array().is_some());
        assert!(
            serde_json::to_vec(envelope).unwrap().len() / 4 <= budget,
            "{label} exceeds budget {budget}: {envelope}"
        );
    }
    assert_eq!(child["mode"], "context_pack");

    let _ = std::fs::remove_dir_all(&root);
    let _ = std::fs::remove_dir_all(&home);
}

#[test]
fn success_has_the_complete_machine_envelope() {
    // Build with the same CLI binary that will query the fixture; the index
    // build fingerprint intentionally differs between test and CLI binaries.
    let db_dir = std::env::temp_dir().join(format!("varde-qenv-ok-{}", std::process::id()));
    std::fs::create_dir_all(&db_dir).expect("temp dir creates");
    let home = db_dir.with_extension("home");
    let fixture = format!(
        "{}/resolve_fixtures/rust/graph/a.rs",
        env!("CARGO_MANIFEST_DIR")
    );
    std::fs::copy(fixture, db_dir.join("a.rs")).expect("fixture source copied");
    let built = Command::new(BIN)
        .args(["build", "--repo-root", db_dir.to_str().unwrap()])
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stdout)
    );

    let json = format!(r#"{{"repoRoot":"{}","filePath":"a.rs"}}"#, db_dir.display());
    let queried = Command::new(BIN)
        .args(["symbols_in_file", "--json", &json])
        .env("HOME", &home)
        .output()
        .expect("query runs");
    let stdout = String::from_utf8_lossy(&queried.stdout);
    let value: serde_json::Value = serde_json::from_str(&stdout).expect("stdout is JSON");
    assert_eq!(value["ok"], true, "stdout: {stdout}");
    assert_eq!(value["schema_version"], 1, "stdout: {stdout}");
    assert_eq!(value["outcome"], "success", "stdout: {stdout}");
    assert!(value.get("data").is_some(), "data key present: {stdout}");
    assert_eq!(value["meta"]["compact"], true, "stdout: {stdout}");
    assert_eq!(value["meta"]["truncated"], false, "stdout: {stdout}");
    let _ = std::fs::remove_dir_all(&db_dir);
    let _ = std::fs::remove_dir_all(&home);
}

#[test]
fn malformed_input_has_structured_error_data() {
    let stdout = run(&["symbols_in_file", "--json", "this is not json"]);
    let value: serde_json::Value = serde_json::from_str(&stdout).expect("stdout is JSON");
    assert_eq!(value["ok"], false, "stdout: {stdout}");
    assert_eq!(value["schema_version"], 1, "stdout: {stdout}");
    assert_eq!(value["outcome"], "tool-error", "stdout: {stdout}");
    assert_eq!(
        value["data"]["error"]["code"], "invalid_input",
        "stdout: {stdout}"
    );
    assert!(
        value["data"]["error"]["message"].is_string(),
        "stdout: {stdout}"
    );
    assert_eq!(value["meta"]["compact"], false, "stdout: {stdout}");
    assert_eq!(value["meta"]["truncated"], false, "stdout: {stdout}");
}

#[test]
fn successful_data_outcome_is_promoted_to_the_envelope() {
    let output = varde_code::query::render(Ok::<_, varde_code::query::ApiError>(
        serde_json::json!({ "outcome": "code-quality-error" }),
    ));
    let value: serde_json::Value = serde_json::from_str(&output).expect("output is JSON");
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["ok"], true);
    assert_eq!(value["outcome"], "code-quality-error");
    assert_eq!(value["data"]["outcome"], "code-quality-error");
}

#[test]
fn missing_required_field_keeps_the_stable_error_code() {
    let db_dir = std::env::temp_dir().join(format!("varde-qenv-miss-{}", std::process::id()));
    std::fs::create_dir_all(&db_dir).expect("temp dir creates");
    let db = db_dir.join("index.db");
    // Missing filePath.
    let json = format!(r#"{{"dbPath":"{}"}}"#, db.display());
    let stdout = run(&["symbols_in_file", "--json", &json]);
    let value: serde_json::Value = serde_json::from_str(&stdout).expect("stdout is JSON");
    assert_eq!(value["ok"], false, "stdout: {stdout}");
    assert_eq!(value["schema_version"], 1, "stdout: {stdout}");
    assert_eq!(value["outcome"], "tool-error", "stdout: {stdout}");
    assert_eq!(
        value["data"]["error"]["code"], "invalid_input",
        "stdout: {stdout}"
    );
    let _ = std::fs::remove_dir_all(&db_dir);
}

#[test]
fn batch_children_have_complete_envelopes() {
    let dir = std::env::temp_dir().join(format!("varde-qenv-batch-{}", std::process::id()));
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    let file = dir.join("input.rs");
    std::fs::write(&file, "alpha(1);\n").expect("fixture writes");
    let json = format!(
        r#"{{"calls":[{{"mode":"find_pattern","filePath":"{}","pattern":"alpha($A)"}},{{"mode":"unknown_mode"}}]}}"#,
        file.display()
    );

    let stdout = run(&["batch", "--json", &json]);
    let value: serde_json::Value = serde_json::from_str(&stdout).expect("stdout is JSON");
    let calls = value["data"].as_array().expect("batch results array");
    assert_eq!(calls.len(), 2, "stdout: {stdout}");
    assert_eq!(calls[0]["mode"], "find_pattern", "stdout: {stdout}");
    assert_eq!(calls[0]["ok"], true, "stdout: {stdout}");
    assert_eq!(calls[0]["schema_version"], 1, "stdout: {stdout}");
    assert_eq!(calls[0]["outcome"], "success", "stdout: {stdout}");
    assert!(calls[0].get("data").is_some(), "stdout: {stdout}");
    assert!(calls[0].get("meta").is_some(), "stdout: {stdout}");
    assert_eq!(calls[1]["mode"], "unknown_mode", "stdout: {stdout}");
    assert_eq!(calls[1]["ok"], false, "stdout: {stdout}");
    assert_eq!(calls[1]["schema_version"], 1, "stdout: {stdout}");
    assert_eq!(calls[1]["outcome"], "tool-error", "stdout: {stdout}");
    assert_eq!(calls[1]["data"]["error"]["code"], "unknown_mode");
    assert_eq!(calls[1]["meta"]["compact"], false, "stdout: {stdout}");
    assert_eq!(calls[1]["meta"]["truncated"], false, "stdout: {stdout}");
    let _ = std::fs::remove_dir_all(&dir);
}
