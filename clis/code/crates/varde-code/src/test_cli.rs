//! `test` orchestration: discover every rule carrying `[[test]]` entries and
//! run them through the pattern/SQL test runners (`rules::test_runner`),
//! merging the results into the same `{ok, data}` envelope `scan_cli.rs`
//! uses.
//!
//! Self-contained by design (per the plan's constraint): no `repoRoot` is
//! required. An optional `rulesDir` scopes discovery to a single directory
//! of rule-pack TOML files (testing one pack in isolation, no user/repo
//! merge, no built-ins); absent `rulesDir`, discovery mirrors `scan_cli.rs`'s
//! `load_rules(repo_root)` call, using the process's current directory as
//! `repo_root`.

use crate::query::ApiError;
use crate::rules::test_runner::{TestResult, run_pattern_rule_tests, run_sql_rule_tests};
use crate::rules::{Diagnostic, Rule, RuleKind};
use std::path::Path;

const RESULTS_LIMIT: usize = 100;

/// Run the `test` flow for `{ rulesDir? }` and return the merged
/// `{ results, summary, diagnostics }` payload.
///
/// `results` is one entry per `[[test]]` case across every rule carrying
/// `test: Some(_)`; `summary` counts pass/fail; `diagnostics` surfaces any
/// loader diagnostics (e.g. malformed `[[test]]` entries) exactly as
/// `scan_repo` surfaces its own loader diagnostics.
pub fn run_tests(input: &serde_json::Value) -> Result<serde_json::Value, ApiError> {
    let (rules, diagnostics, rule_paths) = load_rules_for_test(input)?;

    let mut results: Vec<TestResult> = Vec::new();
    for rule in rules.iter().filter(|r| r.test.is_some()) {
        match rule.kind {
            RuleKind::Pattern => results.extend(run_pattern_rule_tests(rule)),
            RuleKind::Sql => results.extend(run_sql_rule_tests(rule)),
        }
    }

    let passed = results.iter().filter(|r| r.pass).count();
    let failed = results.len() - passed;

    let mut results_json = results_json(&results, &rule_paths);
    let total = results_json.len();
    let (shown, reference) = page_results(&mut results_json, input);
    let mut payload = serde_json::json!({
        "results": results_json,
        "summary": { "passed": passed, "failed": failed },
        "diagnostics": diagnostics,
    });
    if total > RESULTS_LIMIT {
        payload["guide"]["truncated"]["results"] = serde_json::json!({
            "shown": shown,
            "total": total,
        });
        if let Some(reference) = reference {
            crate::toz::add_guide(
                &mut payload["guide"]["truncated"]["results"],
                &reference,
                shown,
                (shown + crate::toz::PAGE_LIMIT).min(total),
            );
            payload["guide"]["toz"] = reference;
        }
    }
    Ok(payload)
}

fn results_json(results: &[TestResult], rule_paths: &RulePathsById) -> Vec<serde_json::Value> {
    // `file` is the rule-pack TOML path, not a source file — but it's the
    // drill-down handle an agent needs to open the failing test/rule
    // definition without guessing where `rule_id` lives on disk.
    results
        .iter()
        .map(|r| {
            let mut entry = serde_json::json!({
                "rule_id": r.rule_id,
                "test_name": r.test_name,
                "status": if r.pass { "pass" } else { "fail" },
                "file": rule_paths.get(&r.rule_id),
            });
            if !r.pass
                && let Some(detail) = &r.detail
            {
                entry["detail"] = serde_json::json!(detail);
            }
            entry
        })
        .collect()
}

fn page_results(
    results_json: &mut Vec<serde_json::Value>,
    input: &serde_json::Value,
) -> (usize, Option<serde_json::Value>) {
    let total = results_json.len();
    if total > RESULTS_LIMIT && crate::toz::available() {
        // Match the compact representation produced at the later envelope
        // boundary, so a JSONL line equals the corresponding inline item.
        for result in results_json.iter_mut() {
            crate::query::output::postprocess(result, input);
        }
    }
    let reference = if total > RESULTS_LIMIT {
        crate::toz::capture_items("test", results_json)
    } else {
        None
    };
    let shown = if reference.is_some() {
        crate::toz::PAGE_LIMIT
    } else {
        RESULTS_LIMIT
    };
    results_json.truncate(shown);
    (shown, reference)
}

/// Resolve the rule set under test: `rulesDir` scopes discovery to the
/// TOML packs directly inside that directory (no user/repo merge, no
/// built-ins — testing one pack in isolation); absent `rulesDir`, mirrors
/// `scan_cli.rs`'s `load_rules(repo_root)` call using the current working
/// directory as `repo_root` (this operation takes no `repoRoot`).
type RulePathsById = std::collections::HashMap<String, String>;
type LoadedTestRules = (Vec<Rule>, Vec<Diagnostic>, RulePathsById);

fn load_rules_for_test(input: &serde_json::Value) -> Result<LoadedTestRules, ApiError> {
    match input.get("rulesDir").and_then(|v| v.as_str()) {
        Some(dir) => {
            let dir_path = Path::new(dir);
            if !dir_path.is_dir() {
                return Err(ApiError::new(
                    "invalid_input",
                    format!("rulesDir is not a directory: {dir}"),
                ));
            }
            let mut rules = Vec::new();
            let mut diagnostics = Vec::new();
            let mut rule_paths = std::collections::HashMap::new();
            let entries = std::fs::read_dir(dir_path).map_err(|e| {
                ApiError::new("file_error", format!("failed to read rulesDir {dir}: {e}"))
            })?;
            let mut paths: Vec<std::path::PathBuf> = entries
                .flatten()
                .map(|entry| entry.path())
                .filter(|path| path.is_file() && path.extension().is_some_and(|ext| ext == "toml"))
                .collect();
            paths.sort();
            for path in paths {
                let (pack_rules, pack_diags) = crate::rules::parse_pack_file(&path);
                for rule in &pack_rules {
                    rule_paths.insert(rule.id.clone(), path.display().to_string());
                }
                rules.extend(pack_rules);
                diagnostics.extend(pack_diags);
            }
            Ok((rules, diagnostics, rule_paths))
        }
        None => {
            let repo_root = std::env::current_dir().map_err(|e| {
                ApiError::new(
                    "file_error",
                    format!("failed to resolve current directory: {e}"),
                )
            })?;
            let (rules, diagnostics) = crate::rules::load_rules(&repo_root);
            // `load_rules` merges user/repo/built-in scopes into flat
            // `Rule`s without the source path — re-derive a best-effort
            // id -> pack-file map from the same discovery pass so `test`
            // can still hand agents a drill-down handle.
            let user_dir = crate::rules::user_rules_dir();
            let mut rule_paths = std::collections::HashMap::new();
            for file in crate::rules::discover(&repo_root, Some(&user_dir)) {
                let (pack_rules, _) = crate::rules::parse_pack_file(&file.path);
                for rule in pack_rules {
                    rule_paths.insert(rule.id, file.path.display().to_string());
                }
            }
            Ok((rules, diagnostics, rule_paths))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::PathOverride;

    fn tempdir(tag: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!("varde-test-cli-{tag}-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    fn write(path: &Path, contents: &str) {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).expect("parent dir creates");
        }
        std::fs::write(path, contents).expect("fixture writes");
    }

    #[test]
    fn all_passing_tests_report_zero_failures() {
        let dir = tempdir("all-pass");
        write(
            &dir.join("pack.toml"),
            r#"
[[rule]]
id = "no-console-log"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"

[[rule.test]]
name = "flags console.log"
invalid = ["console.log(\"bad\");"]
"#,
        );

        let input = serde_json::json!({ "rulesDir": dir.display().to_string() });
        let payload = run_tests(&input).expect("run succeeds");
        let results = payload["results"].as_array().expect("results array");
        assert_eq!(results.len(), 1, "{results:?}");
        assert_eq!(results[0]["rule_id"], "no-console-log");
        assert_eq!(results[0]["test_name"], "flags console.log");
        assert_eq!(results[0]["status"], "pass");
        assert!(
            results[0].get("detail").is_none(),
            "no detail on pass: {:?}",
            results[0]
        );
        assert_eq!(
            payload["summary"],
            serde_json::json!({ "passed": 1, "failed": 0 })
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn mixed_pass_and_fail_across_rules_are_all_reported() {
        let dir = tempdir("mixed");
        write(
            &dir.join("pack.toml"),
            r#"
[[rule]]
id = "no-console-log"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"

[[rule.test]]
name = "flags console.log"
invalid = ["console.log(\"bad\");"]

[[rule.test]]
name = "wrongly expects clean code"
valid = ["console.log(\"still logs\");"]

[[rule]]
id = "no-console-trace"
kind = "pattern"
severity = "warning"
message = "console.trace detected"
pattern = "console.trace($MSG)"

[[rule.test]]
name = "flags console.trace"
invalid = ["console.trace(\"bad\");"]
"#,
        );

        let input = serde_json::json!({ "rulesDir": dir.display().to_string() });
        let payload = run_tests(&input).expect("run succeeds");
        let results = payload["results"].as_array().expect("results array");
        assert_eq!(results.len(), 3, "{results:?}");
        let passed = results.iter().filter(|r| r["status"] == "pass").count();
        let failed = results.iter().filter(|r| r["status"] == "fail").count();
        assert_eq!(passed, 2, "{results:?}");
        assert_eq!(failed, 1, "{results:?}");
        let failing = results
            .iter()
            .find(|r| r["status"] == "fail")
            .expect("one failing entry");
        assert_eq!(failing["test_name"], "wrongly expects clean code");
        assert!(
            failing["detail"].as_str().is_some_and(|d| !d.is_empty()),
            "failing entry carries a detail: {failing:?}"
        );
        assert_eq!(
            payload["summary"],
            serde_json::json!({ "passed": 2, "failed": 1 })
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn zero_rules_with_test_entries_is_a_successful_empty_run() {
        let dir = tempdir("zero");
        write(
            &dir.join("pack.toml"),
            r#"
[[rule]]
id = "no-test-entries"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"
"#,
        );

        let input = serde_json::json!({ "rulesDir": dir.display().to_string() });
        let payload = run_tests(&input).expect("run succeeds even with no [[test]] entries");
        assert_eq!(
            payload["results"],
            serde_json::json!([]),
            "no test entries anywhere: {payload:?}"
        );
        assert_eq!(
            payload["summary"],
            serde_json::json!({ "passed": 0, "failed": 0 })
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn malformed_test_entry_diagnostic_is_surfaced_alongside_results() {
        // `expect_rewrite` on a rule with no `rewrite` field is a malformed
        // `[[test]]` entry per the loader's validation — skip-and-report,
        // not a hard load failure (mirrors scan's diagnostic convention).
        let dir = tempdir("malformed");
        write(
            &dir.join("pack.toml"),
            r#"
[[rule]]
id = "no-console-log"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"

[[rule.test]]
name = "bogus rewrite expectation"
[rule.test.expect_rewrite]
"console.log(\"x\")" = "console.info(\"x\")"
"#,
        );

        let input = serde_json::json!({ "rulesDir": dir.display().to_string() });
        let payload =
            run_tests(&input).expect("run succeeds; malformed test entry is a diagnostic");
        let diagnostics = payload["diagnostics"]
            .as_array()
            .expect("diagnostics array");
        assert!(
            !diagnostics.is_empty(),
            "malformed [[test]] entry must surface a diagnostic: {payload:?}"
        );
        // The rule itself loaded fine (no `test` entries survived validation),
        // so there is nothing to run: zero results, not an error.
        assert_eq!(payload["results"], serde_json::json!([]));
        assert_eq!(
            payload["summary"],
            serde_json::json!({ "passed": 0, "failed": 0 })
        );

        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn nonexistent_rules_dir_is_an_invalid_input_error() {
        let input = serde_json::json!({ "rulesDir": "/nonexistent/varde-code-test-cli-path" });
        let err = run_tests(&input).expect_err("missing rulesDir must error");
        assert_eq!(err.code, "invalid_input");
    }

    #[test]
    fn long_results_capture_all_items_and_show_first_page() {
        let dir = tempdir("toz-results");
        let mut pack = String::from(
            "[[rule]]\nid = \"many-tests\"\nkind = \"pattern\"\nseverity = \"warning\"\nmessage = \"console.log detected\"\npattern = \"console.log($MSG)\"\n",
        );
        for index in 0..101 {
            pack.push_str(&format!(
                "\n[[rule.test]]\nname = \"case {index}\"\ninvalid = [\"console.log(1);\"]\n"
            ));
        }
        write(&dir.join("pack.toml"), &pack);

        let bin = dir.join("bin");
        std::fs::create_dir_all(&bin).expect("bin dir creates");
        let capture = dir.join("captured.jsonl");
        let script = format!(
            "#!/bin/sh\ncat > '{}'\nprintf '%s\\n' '{{\"handle\":\"test-handle\"}}'\n",
            capture.display()
        );
        let stub = bin.join("toz");
        write(&stub, &script);
        let mut perms = std::fs::metadata(&stub)
            .expect("stub metadata")
            .permissions();
        std::os::unix::fs::PermissionsExt::set_mode(&mut perms, 0o755);
        std::fs::set_permissions(&stub, perms).expect("stub permissions");
        let _override = PathOverride::new(&bin);
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "1") };

        let input = serde_json::json!({ "rulesDir": dir.display().to_string() });
        let payload = run_tests(&input).expect("run succeeds");
        assert_eq!(
            payload["summary"],
            serde_json::json!({ "passed": 101, "failed": 0 })
        );
        assert_eq!(payload["results"].as_array().unwrap().len(), 20);
        assert_eq!(payload["guide"]["truncated"]["results"]["shown"], 20);
        assert_eq!(payload["guide"]["truncated"]["results"]["total"], 101);
        assert_eq!(payload["guide"]["toz"]["handle"], "test-handle");
        assert_eq!(
            payload["guide"]["truncated"]["results"]["toz_read"],
            "toz query --handle test-handle --lines 21:40"
        );
        assert_eq!(
            payload["guide"]["truncated"]["results"]["toz_search"],
            "toz query --handle test-handle \"<term>\""
        );

        let captured = std::fs::read_to_string(&capture).expect("capture written");
        let items: Vec<serde_json::Value> = captured
            .lines()
            .map(|line| serde_json::from_str(line).expect("JSONL item"))
            .collect();
        assert_eq!(items.len(), 101);
        assert_eq!(&items[..20], payload["results"].as_array().unwrap());
        assert_eq!(items[0]["test_name"], "case 0");
        assert_eq!(items[100]["test_name"], "case 100");

        drop(_override);
        let _without_toz = PathOverride::without_toz();
        let fallback = run_tests(&input).expect("run succeeds without toz");
        assert_eq!(fallback["results"].as_array().unwrap().len(), 100);
        assert_eq!(
            fallback["guide"]["truncated"]["results"],
            serde_json::json!({
                "shown": 100,
                "total": 101,
            })
        );
        assert!(fallback["guide"].get("toz").is_none());

        drop(_without_toz);
        let _ = std::fs::remove_dir_all(&dir);
    }
}
