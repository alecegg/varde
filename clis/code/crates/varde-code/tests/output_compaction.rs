//! Public output-shape tests for compact, navigable tool results.

use std::fmt::Write as _;
use std::path::PathBuf;
use std::process::{Command, Output};

const BIN: &str = env!("CARGO_BIN_EXE_varde-code");
const RESULT_LIMIT: usize = 100;

fn tempdir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "varde-output-compaction-{tag}-{}",
        std::process::id()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp directory creates");
    dir
}

fn run(args: &[&str]) -> Output {
    Command::new(BIN)
        .args(args)
        .env("VARDE_CODE_TOZ", "0")
        .output()
        .expect("binary runs")
}

fn envelope(output: &Output) -> serde_json::Value {
    serde_json::from_slice(&output.stdout).unwrap_or_else(|err| {
        panic!(
            "stdout must be JSON: {err}; stdout: {}",
            String::from_utf8_lossy(&output.stdout)
        )
    })
}

fn assert_truncated(data: &serde_json::Value, list: &str, total: usize) {
    let truncation = &data["guide"]["truncated"][list];
    assert_eq!(truncation["shown"], RESULT_LIMIT);
    assert_eq!(truncation["total"], total);
}

#[test]
fn extract_uses_file_table_instead_of_repeating_paths() {
    let out = run(&["extract", "tests/fixtures/ts/mixed"]);
    assert!(out.status.success(), "extract must succeed: {out:?}");
    let payload = envelope(&out);
    let data = &payload["data"];

    assert!(
        data["files"]
            .as_array()
            .is_some_and(|files| !files.is_empty())
    );
    for key in ["entities", "symbols", "diagnostics"] {
        for item in data[key].as_array().expect("output list") {
            assert!(item["file_id"].as_u64().is_some(), "{key}: {item}");
            assert!(item.get("file").is_none(), "{key}: repeated path in {item}");
        }
    }
}

#[test]
fn find_pattern_bounds_matches_and_keeps_navigation_details() {
    let dir = tempdir("find-pattern");
    let file = dir.join("many.rs");
    let source = (0..=RESULT_LIMIT)
        .map(|index| format!("alpha({index});"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&file, source).expect("fixture writes");
    let input = format!(
        r#"{{"filePath":"{}","pattern":"alpha($A)"}}"#,
        file.display()
    );

    let out = run(&["find_pattern", "--json", &input]);
    assert!(out.status.success(), "find_pattern must succeed: {out:?}");
    let payload = envelope(&out);
    assert_eq!(payload["meta"]["truncated"], true);
    let data = &payload["data"];
    let matches = data["matches"].as_array().expect("matches array");
    assert_eq!(matches.len(), RESULT_LIMIT);
    assert_truncated(data, "matches", RESULT_LIMIT + 1);
    assert!(matches.iter().all(|item| {
        item["file"].as_str().is_some()
            && item["span"]["start_line"].as_u64().is_some()
            && item["span"]["end_line"].as_u64().is_some()
    }));

    let _ = std::fs::remove_dir_all(&dir);
}

#[cfg(unix)]
#[test]
fn find_pattern_captures_searchable_previews_when_toz_is_available() {
    use std::os::unix::fs::PermissionsExt;

    let dir = tempdir("find-pattern-toz");
    let file = dir.join("many.rs");
    let captured = dir.join("captured.jsonl");
    let source = (0..=RESULT_LIMIT)
        .map(|index| format!("alpha({index});"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&file, source).expect("fixture writes");
    let stub = dir.join("toz");
    std::fs::write(
        &stub,
        "#!/bin/sh\ncase \" $* \" in *' --defer-index '*) ;; *) exit 3 ;; esac\ncat > \"$TOZ_CAPTURE_PATH\"\necho '{\"handle\":\"test-handle\",\"toc\":[]}'\n",
    )
    .expect("stub writes");
    std::fs::set_permissions(&stub, std::fs::Permissions::from_mode(0o755))
        .expect("stub is executable");
    let path = std::env::join_paths(std::iter::once(dir.clone()).chain(std::env::split_paths(
        &std::env::var_os("PATH").unwrap_or_default(),
    )))
    .expect("PATH joins");
    let input = format!(
        r#"{{"filePath":"{}","pattern":"alpha($A)"}}"#,
        file.display()
    );
    let out = Command::new(BIN)
        .args(["find_pattern", "--json", &input])
        .env("PATH", &path)
        .env("TOZ_CAPTURE_PATH", &captured)
        .env("VARDE_CODE_TOZ", "1")
        .output()
        .expect("binary runs");
    assert!(out.status.success(), "find_pattern must succeed: {out:?}");
    let payload = envelope(&out);
    assert_eq!(payload["data"]["matches"].as_array().unwrap().len(), 20);
    assert_eq!(payload["meta"]["toz"]["items"], RESULT_LIMIT + 1);
    assert_eq!(payload["meta"]["toz"]["projection"], "match_preview_160");
    assert_eq!(
        payload["data"]["guide"]["truncated"]["matches"]["toz_read"],
        "toz query --handle test-handle --lines 21:40"
    );
    let rows: Vec<serde_json::Value> = std::fs::read_to_string(&captured)
        .expect("capture exists")
        .lines()
        .map(|line| serde_json::from_str(line).expect("JSONL row"))
        .collect();
    assert_eq!(rows.len(), RESULT_LIMIT + 1);
    assert_eq!(rows[0]["preview"], "alpha(0)");
    assert!(rows[0]["captures"].is_null());
    assert_eq!(rows[100]["preview"], "alpha(100)");

    let explicit = format!(
        r#"{{"filePath":"{}","pattern":"alpha($A)","matchesLimit":50}}"#,
        file.display()
    );
    let out = Command::new(BIN)
        .args(["find_pattern", "--json", &explicit])
        .env("PATH", path)
        .env("TOZ_CAPTURE_PATH", &captured)
        .env("VARDE_CODE_TOZ", "1")
        .output()
        .expect("binary runs");
    let payload = envelope(&out);
    assert_eq!(payload["data"]["matches"].as_array().unwrap().len(), 50);
    assert_eq!(
        payload["data"]["guide"]["truncated"]["matches"]["limit"],
        50
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn batch_reports_nested_find_pattern_truncation() {
    let dir = tempdir("batch-find-pattern");
    let file = dir.join("many.rs");
    let source = (0..=RESULT_LIMIT)
        .map(|index| format!("alpha({index});"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(&file, source).expect("fixture writes");
    let input = format!(
        r#"{{"calls":[{{"mode":"find_pattern","filePath":"{}","pattern":"alpha($A)"}}]}}"#,
        file.display()
    );

    let out = run(&["batch", "--json", &input]);
    assert!(out.status.success(), "batch must succeed: {out:?}");
    let payload = envelope(&out);
    assert_eq!(payload["meta"]["truncated"], true);
    assert_eq!(payload["data"][0]["meta"]["truncated"], true);
    assert_truncated(&payload["data"][0]["data"], "matches", RESULT_LIMIT + 1);

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn test_bounds_results_and_keeps_rule_and_file_handles() {
    let dir = tempdir("rule-tests");
    let mut pack = String::from(
        r#"
[[rule]]
id = "many-tests"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"
"#,
    );
    for index in 0..=RESULT_LIMIT {
        writeln!(
            pack,
            r#"
[[rule.test]]
name = "case {index}"
invalid = ["console.log(\"{index}\");"]
"#,
        )
        .expect("test entry writes");
    }
    std::fs::write(dir.join("pack.toml"), pack).expect("rule pack writes");
    let input = format!(r#"{{"rulesDir":"{}"}}"#, dir.display());

    let out = run(&["test", "--json", &input]);
    let payload = envelope(&out);
    assert_eq!(payload["ok"], true, "test payload: {payload}");
    assert_eq!(payload["meta"]["truncated"], true);
    let data = &payload["data"];
    let results = data["results"].as_array().expect("results array");
    assert_eq!(results.len(), RESULT_LIMIT);
    assert_truncated(data, "results", RESULT_LIMIT + 1);
    assert!(results.iter().all(|result| {
        result["rule_id"].as_str().is_some()
            && result["test_name"].as_str().is_some()
            && result["file"].as_str().is_some()
    }));

    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn toz_query_results_round_trip_and_fallback_parity() {
    let built = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .join("toz/target/debug/toz");
    let toz = if built.is_file() {
        built
    } else {
        PathBuf::from("toz")
    };
    if Command::new(&toz).arg("--version").output().is_err() {
        return; // toz is optional; CI without it still exercises fallback above.
    }
    let dir = tempdir("toz-results");
    let repo = dir.join("repo");
    let home = dir.join("home");
    std::fs::create_dir_all(&repo).unwrap();
    std::fs::create_dir_all(&home).unwrap();
    let source = (0..120)
        .map(|i| format!("fn function_{i}() {{}}"))
        .collect::<Vec<_>>()
        .join("\n");
    std::fs::write(repo.join("many.rs"), source).unwrap();
    let config = dir.join("toz-config");
    let env_run = |command: &mut Command| -> Output {
        let mut paths = vec![
            toz.parent()
                .unwrap_or(std::path::Path::new("."))
                .to_path_buf(),
        ];
        paths.extend(std::env::split_paths(
            &std::env::var_os("PATH").unwrap_or_default(),
        ));
        command
            .env("HOME", &home)
            .env("TOZ_CONFIG_DIR", &config)
            .env("PATH", std::env::join_paths(paths).unwrap())
            .output()
            .expect("command runs")
    };
    let build = env_run(Command::new(BIN).args(["build", "--repo-root", repo.to_str().unwrap()]));
    assert!(
        build.status.success(),
        "build: {}",
        String::from_utf8_lossy(&build.stderr)
    );
    let query = |input: serde_json::Value, toz: Option<&str>| -> Output {
        let mut command = Command::new(BIN);
        command.args(["filter_symbols", "--json", &input.to_string()]);
        if let Some(setting) = toz {
            command.env("VARDE_CODE_TOZ", setting);
        }
        env_run(&mut command)
    };
    let input = serde_json::json!({"repoRoot": repo, "kind": "function"});
    let first = envelope(&query(input.clone(), None));
    assert_eq!(first["data"].as_array().unwrap().len(), 20);
    assert_eq!(first["meta"]["toz"]["items"], 120);
    assert!(
        first["meta"]["toz"]["toc"]
            .as_str()
            .unwrap()
            .contains("many.rs")
    );
    let handle = first["meta"]["toz"]["handle"].as_str().unwrap();
    let retrieved =
        env_run(Command::new(&toz).args(["query", "--handle", handle, "--lines", "101:120"]));
    assert!(retrieved.status.success());
    let lines: Vec<serde_json::Value> = retrieved
        .stdout
        .split(|byte| *byte == b'\n')
        .filter(|line| !line.is_empty())
        .map(|line| serde_json::from_slice(line).unwrap())
        .collect();
    let page = envelope(&query(
        serde_json::json!({"repoRoot": repo, "kind":"function", "resultsOffset":100, "resultsLimit":20}),
        None,
    ));
    assert_eq!(lines, *page["data"].as_array().unwrap());
    let explicit = envelope(&query(
        serde_json::json!({"repoRoot": repo, "kind":"function", "resultsLimit":50}),
        None,
    ));
    assert_eq!(explicit["data"].as_array().unwrap().len(), 50);
    assert!(explicit["meta"]["toz"]["handle"].is_string());
    let opted_out = query(input.clone(), Some("0"));
    let mut missing_command = Command::new(BIN);
    missing_command
        .args(["filter_symbols", "--json", &input.to_string()])
        .env("PATH", "/usr/bin:/bin")
        .env("HOME", &home)
        .env("TOZ_CONFIG_DIR", &config);
    let missing = missing_command.output().unwrap();
    assert_eq!(opted_out.stdout, missing.stdout);
    assert_eq!(envelope(&missing)["data"].as_array().unwrap().len(), 100);
    let _ = std::fs::remove_dir_all(&dir);
}
