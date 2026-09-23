//! End-to-end `scan` CLI tests: spawn the built binary against a fixture
//! repo and assert process exit codes, stdout, and output-file behavior.
//!
//! The DB lives under the conventional `$HOME/.config/varde-code/repos/...`
//! path, so each child process receives a throwaway tempdir as `HOME`.

use std::path::{Path, PathBuf};
use std::process::Command;

const TS_FIXTURE: &str = r#"
async function fetchData(): Promise<void> {
  console.trace("async log");
}
"#;

fn bin() -> PathBuf {
    PathBuf::from(env!("CARGO_BIN_EXE_varde-code"))
}

#[test]
fn explicit_rule_policy_gates_info_without_hiding_unselected_findings() {
    let (home, repo) = build_fixture("selected-info", "info");
    let input = serde_json::json!({"repoRoot": repo, "gateRules": ["no-console"]});
    let out = scan(&home, &[&input.to_string()]);
    let envelope: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(!out.status.success());
    assert_eq!(envelope["data"]["gate"]["status"], "fail");
    assert_eq!(envelope["data"]["gate"]["blocking_findings"], 1);
    assert_eq!(
        envelope["data"]["gate"]["rule_ids"],
        serde_json::json!(["no-console"])
    );
    assert_eq!(
        envelope["data"]["gate"]["severity_threshold"],
        serde_json::Value::Null
    );

    let input = serde_json::json!({"repoRoot": repo, "gateRules": ["function-complexity-gate"]});
    let out = scan(&home, &[&input.to_string()]);
    let envelope: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(out.status.success());
    assert_eq!(envelope["data"]["gate"]["status"], "pass");
    assert_eq!(envelope["data"]["findings"].as_array().unwrap().len(), 1);
    let _ = std::fs::remove_dir_all(home);
    let _ = std::fs::remove_dir_all(repo);
}

#[test]
fn explicit_rule_policy_rejects_invalid_selection_before_writes() {
    let (home, repo) = build_fixture("selected-invalid", "info");
    for selection in [
        serde_json::json!([]),
        serde_json::json!("no-console"),
        serde_json::json!([null]),
        serde_json::json!(["unknown-rule"]),
        serde_json::json!(["no-console", "no-console"]),
    ] {
        let input = serde_json::json!({"repoRoot": repo, "gateRules": selection, "apply": true, "force": true});
        let out = scan(&home, &[&input.to_string()]);
        let envelope: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert!(!out.status.success(), "{selection}");
        assert_eq!(envelope["ok"], false);
        assert_eq!(envelope["data"]["error"]["code"], "invalid_input");
        assert_eq!(
            std::fs::read_to_string(repo.join("main.ts")).unwrap(),
            TS_FIXTURE
        );
    }
    let input = serde_json::json!({"repoRoot": repo, "gateRules": ["no-console"], "severityThreshold": "error"});
    let out = scan(&home, &[&input.to_string()]);
    assert!(!out.status.success());
    let envelope: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "invalid_input");
    let _ = std::fs::remove_dir_all(home);
    let _ = std::fs::remove_dir_all(repo);
}

#[test]
fn explicit_rule_policy_preserves_incomplete_analysis() {
    let (home, repo) = build_fixture("selected-incomplete", "info");
    write(&repo.join(".varde-code/rules/broken.toml"), "[[rule");
    let input = serde_json::json!({"repoRoot": repo, "gateRules": ["function-complexity-gate"]});
    let out = scan(&home, &[&input.to_string()]);
    let envelope: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
    assert!(!out.status.success());
    assert_eq!(envelope["outcome"], envelope["data"]["outcome"]);
    assert_eq!(envelope["data"]["gate"]["status"], "unknown");
    assert_eq!(envelope["data"]["analysis"]["status"], "incomplete");
    assert_eq!(envelope["data"]["outcome"], "analysis-incomplete");
    assert_eq!(envelope["data"]["gate"]["blocking_findings"], 0);
    assert!(
        envelope["data"]["gate"]["diagnostic_count"]
            .as_u64()
            .unwrap()
            > 0
    );
    let _ = std::fs::remove_dir_all(home);
    let _ = std::fs::remove_dir_all(repo);
}

fn tempdir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varde-scan-it-{tag}-{}", std::process::id()));
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

/// Build the fixture repo and return (home, repo).
fn build_fixture(tag: &str, severity: &str) -> (PathBuf, PathBuf) {
    build_fixture_with_source(tag, severity, TS_FIXTURE)
}

fn build_fixture_with_source(tag: &str, severity: &str, source: &str) -> (PathBuf, PathBuf) {
    let home = tempdir(&format!("{tag}-home"));
    let repo = tempdir(&format!("{tag}-repo"));
    write(&repo.join("main.ts"), source);
    write(
        &repo.join(".varde-code/rules/pack.toml"),
        &format!(
            r#"
[[rule]]
id = "no-console"
kind = "pattern"
severity = "{severity}"
message = "console call detected"
pattern = "console.trace($MSG)"
"#
        ),
    );
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);
    (home, repo)
}

fn scan(home: &Path, args: &[&str]) -> std::process::Output {
    Command::new(bin())
        .args(["scan"])
        .arg("--json")
        .args(args)
        .env("HOME", home)
        .output()
        .expect("scan runs")
}

#[test]
fn error_finding_exits_nonzero_with_default_threshold() {
    let (home, repo) = build_fixture("err", "error");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    assert!(!out.status.success(), "error finding → non-zero exit");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["ok"], true);
    assert_eq!(payload["outcome"], payload["data"]["outcome"]);
    assert_eq!(payload["data"]["outcome"], "code-quality-error");
    assert_eq!(
        payload["data"]["outcome_reasons"],
        serde_json::json!(["code-quality-error"])
    );
    assert_eq!(
        payload["data"]["findings"].as_array().map(|a| a.len()),
        Some(1)
    );
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn scan_bounds_findings_and_supports_full_output_and_pages() {
    let traces = (0..101)
        .map(|index| format!("console.trace(\"trace-{index}\");"))
        .collect::<String>();
    let source = format!("function traceEverything() {{\n{traces}}}\n");
    let (home, repo) = build_fixture_with_source("unlimited", "warning", &source);

    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    assert!(out.status.success(), "warning findings → exit 0");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    let findings = payload["data"]["findings"]
        .as_array()
        .expect("findings array");
    assert_eq!(
        findings
            .iter()
            .filter(|finding| finding["rule_id"] == "no-console")
            .count(),
        100,
        "default scan output is bounded"
    );
    assert_eq!(payload["data"]["findings_summary"]["total"], 101);
    assert_eq!(payload["data"]["findings_summary"]["shown"], 100);
    assert_eq!(
        payload["data"]["guide"]["truncated"]["findings"]["next_offset"],
        100
    );

    let full = scan(
        &home,
        &[&format!(
            r#"{{"repoRoot":"{}","fullFindings":true}}"#,
            repo.display()
        )],
    );
    assert!(full.status.success(), "full warning scan → exit 0");
    let full_payload: serde_json::Value =
        serde_json::from_slice(&full.stdout).expect("full envelope JSON");
    assert_eq!(
        full_payload["data"]["findings"].as_array().unwrap().len(),
        101
    );
    assert_eq!(full_payload["data"]["findings_summary"]["truncated"], false);

    let page = scan(
        &home,
        &[&format!(
            r#"{{"repoRoot":"{}","findingsLimit":25,"findingsOffset":50}}"#,
            repo.display()
        )],
    );
    let page_payload: serde_json::Value =
        serde_json::from_slice(&page.stdout).expect("page envelope JSON");
    assert_eq!(
        page_payload["data"]["findings"].as_array().unwrap().len(),
        25
    );
    assert_eq!(page_payload["data"]["findings_summary"]["total"], 101);
    assert_eq!(page_payload["data"]["findings_summary"]["offset"], 50);
    assert_eq!(
        page_payload["data"]["guide"]["truncated"]["findings"]["next_offset"],
        75
    );

    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn info_only_findings_exit_zero_with_default_threshold() {
    let (home, repo) = build_fixture("info", "info");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    assert!(out.status.success(), "info findings → exit 0");
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn trusted_rust_complexity_blocks_completion() {
    let home = tempdir("trusted-complexity-home");
    let repo = tempdir("trusted-complexity-repo");
    let statements = (0..61)
        .map(|index| format!("    let value_{index} = {index};\n"))
        .collect::<String>();
    write(
        &repo.join("main.rs"),
        &format!("fn oversized() {{\n{statements}}}\n"),
    );

    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    assert!(!out.status.success(), "trusted complexity must block");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    let findings = payload["data"]["findings"]
        .as_array()
        .expect("findings array");
    assert!(findings.iter().any(|finding| {
        finding["rule_id"] == "function-complexity-gate"
            && finding["evidence"]["confidence"] == "high"
            && finding["evidence"]["line_span"]
                .as_u64()
                .unwrap_or_default()
                > 60
    }));

    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn output_path_writes_envelope_and_stdout_stays_empty() {
    let (home, repo) = build_fixture("out", "warning");
    let out_path = home.join("scan-out.json");
    let out = scan(
        &home,
        &[&format!(
            r#"{{"repoRoot":"{}","output":"{}"}}"#,
            repo.display(),
            out_path.display()
        )],
    );
    assert!(
        out.stdout.is_empty(),
        "nothing on stdout when output is set"
    );
    let written = std::fs::read_to_string(&out_path).expect("output file written");
    let payload: serde_json::Value = serde_json::from_str(&written).expect("envelope JSON");
    assert_eq!(payload["ok"], true);
    assert!(payload["data"]["findings"].as_array().is_some());
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn omitted_output_prints_envelope_to_stdout() {
    let (home, repo) = build_fixture("stdout", "warning");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["ok"], true);
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn gate_reports_pass_and_blocks_error_findings() {
    let (home, repo) = build_fixture("gate", "error");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    assert_eq!(payload["data"]["gate"]["severity_threshold"], "error");
    assert_eq!(payload["data"]["gate"]["blocking_findings"], 1);
    assert_eq!(payload["data"]["gate"]["diagnostic_count"], 0);
    assert_eq!(payload["data"]["gate"]["blocking_diagnostic_count"], 0);
    assert_eq!(payload["data"]["policy"]["mode"], "severity-threshold");
    assert!(
        payload["data"]["policy"]["active_rule_count"]
            .as_u64()
            .unwrap()
            > 0
    );
    assert!(
        payload["data"]["policy"]["gating_rule_count"]
            .as_u64()
            .unwrap()
            > 0
    );
    let first_fingerprint = payload["data"]["policy"]["fingerprint"].clone();
    let repeat = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let repeat_payload: serde_json::Value =
        serde_json::from_slice(&repeat.stdout).expect("repeat envelope JSON");
    assert_eq!(
        repeat_payload["data"]["policy"]["fingerprint"],
        first_fingerprint
    );

    let (home, repo) = build_fixture("gate-info", "info");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert_eq!(payload["data"]["gate"]["blocking_findings"], 0);
}

#[test]
fn invalid_scan_option_types_return_errors_without_freshening() {
    let (home, repo) = build_fixture("invalid-options", "warning");
    for input in [
        format!(
            r#"{{"repoRoot":"{}","severityThreshold":3}}"#,
            repo.display()
        ),
        format!(r#"{{"repoRoot":"{}","apply":"yes"}}"#, repo.display()),
        format!(r#"{{"repoRoot":"{}","force":1}}"#, repo.display()),
        format!(r#"{{"repoRoot":"{}","output":false}}"#, repo.display()),
        format!(
            r#"{{"repoRoot":"{}","fullFindings":"yes"}}"#,
            repo.display()
        ),
        format!(r#"{{"repoRoot":"{}","findingsLimit":0}}"#, repo.display()),
    ] {
        let out = scan(&home, &[&input]);
        assert!(!out.status.success(), "invalid input must fail: {input}");
        let payload: serde_json::Value =
            serde_json::from_slice(&out.stdout).expect("error envelope");
        assert_eq!(payload["ok"], false, "invalid input envelope: {payload}");
        assert_eq!(payload["data"]["error"]["code"], "invalid_input");
    }
}

#[test]
fn non_object_scan_input_with_cli_flags_returns_error() {
    let out = Command::new(bin())
        .args(["scan", "--json", "[]", "--apply"])
        .output()
        .expect("scan runs");
    assert!(!out.status.success());
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("error envelope");
    assert_eq!(payload["ok"], false);
    assert_eq!(payload["data"]["error"]["code"], "invalid_input");
}

#[test]
fn incomplete_scan_reports_diagnostics_and_skips_apply() {
    let home = tempdir("incomplete-apply-home");
    let repo = tempdir("incomplete-apply-repo");
    let source = "console.trace(\"keep\");\nfunction broken(\n";
    write(&repo.join("main.ts"), source);
    write(
        &repo.join(".varde-code/rules/pack.toml"),
        r#"
[[rule]]
id = "rewrite-console"
kind = "pattern"
severity = "error"
message = "console call detected"
pattern = "console.trace($MSG)"
rewrite = "console.info($MSG)"
"#,
    );
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let out = scan(
        &home,
        &[&format!(
            r#"{{"repoRoot":"{}","apply":true,"force":true}}"#,
            repo.display()
        )],
    );
    assert!(!out.status.success(), "incomplete gate must fail");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["ok"], true);
    assert_eq!(payload["outcome"], payload["data"]["outcome"]);
    assert_eq!(payload["data"]["gate"]["status"], "fail");
    assert_eq!(payload["data"]["analysis"]["status"], "incomplete");
    assert_eq!(payload["data"]["outcome"], "code-quality-error");
    assert_eq!(
        payload["data"]["outcome_reasons"],
        serde_json::json!(["code-quality-error", "analysis-incomplete"])
    );
    assert!(
        payload["data"]["gate"]["diagnostic_count"]
            .as_u64()
            .unwrap_or(0)
            > 0
    );
    assert!(
        !payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .is_empty()
    );
    assert!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|diagnostic| {
                diagnostic["source"] == "persisted"
                    && diagnostic["kind"] == "source"
                    && diagnostic["blocking"] == true
                    && diagnostic["location"]["file"]
                        .as_str()
                        .is_some_and(|path| path.ends_with("main.ts"))
                    && diagnostic["path"]
                        .as_str()
                        .is_some_and(|path| path.ends_with("main.ts"))
                    && diagnostic["message"] == "syntax error — partial extract kept"
            })
    );
    assert_eq!(
        std::fs::read_to_string(repo.join("main.ts")).unwrap(),
        source
    );
}

#[test]
fn explicitly_scoped_pattern_parse_failures_make_gate_incomplete() {
    let home = tempdir("scoped-pattern-home");
    let repo = tempdir("scoped-pattern-repo");
    write(&repo.join("main.ts"), TS_FIXTURE);
    write(
        &repo.join(".varde-code/rules/pack.toml"),
        r#"
[[rule]]
id = "broken-scoped-pattern"
kind = "pattern"
severity = "error"
message = "broken pattern"
pattern = "((("
languages = ["typescript"]
"#,
    );
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    assert!(!out.status.success(), "incomplete gate must fail");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["data"]["gate"]["status"], "unknown");
    assert_eq!(payload["data"]["analysis"]["status"], "incomplete");
    assert!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|diagnostic| {
                diagnostic["rule_id"] == "broken-scoped-pattern"
                    && diagnostic["reason"]
                        .as_str()
                        .is_some_and(|reason| reason.contains("explicitly targeted"))
            })
    );
}

#[test]
fn rule_directory_failures_are_incomplete_but_absent_dirs_are_valid() {
    let home = tempdir("rule-dir-home");
    let repo = tempdir("rule-dir-repo");
    write(&repo.join("main.ts"), "function clean(): void {}\n");
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let varde_dir = repo.join(".varde-code");
    std::fs::create_dir_all(&varde_dir).expect("varde directory creates");
    std::fs::write(varde_dir.join("rules"), "not a directory").expect("rules path writes");
    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["data"]["gate"]["status"], "unknown");
    assert!(
        payload["data"]["diagnostics"]
            .as_array()
            .unwrap()
            .iter()
            .any(|diagnostic| {
                diagnostic["reason"]
                    .as_str()
                    .is_some_and(|reason| reason.contains("unreadable rule directory"))
            })
    );

    let empty_home = tempdir("rule-dir-empty-home");
    let empty_repo = tempdir("rule-dir-empty-repo");
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&empty_repo)
        .env("HOME", &empty_home)
        .output()
        .expect("empty build runs");
    assert!(
        build.status.success(),
        "empty build fails: {:?}",
        build.status
    );
    let out = scan(
        &empty_home,
        &[&format!(r#"{{"repoRoot":"{}"}}"#, empty_repo.display())],
    );
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["data"]["gate"]["status"], "pass");
    assert_eq!(payload["data"]["gate"]["diagnostic_count"], 0);
}

/// Ruby `module`/`include` is mixin composition, not interface
/// implementation, so the interface-contract SOLID rules (solid-lsp,
/// too-many-interfaces) and fat-interface-on-a-module must NOT fire on Ruby —
/// while a genuine Ruby *class* with too many methods still can.
#[test]
fn ruby_mixins_do_not_trigger_interface_solid_rules() {
    let home = tempdir("ruby-solid-home");
    let repo = tempdir("ruby-solid-repo");
    // A fat mixin module (16 methods) + a class including 4 mixins: under the
    // old rules this produced fat-interface, too-many-interfaces, and 4×
    // solid-lsp findings. All are Ruby-idiom false positives.
    let mut big = String::from("module BigHelpers\n");
    for i in 0..16 {
        big.push_str(&format!("  def m{i}; end\n"));
    }
    big.push_str("end\n");
    write(&repo.join("big.rb"), &big);
    write(
        &repo.join("widget.rb"),
        "module A; def a; end; end\nmodule B; def b; end; end\nmodule C; def c; end; end\nmodule D; def d; end; end\nclass Widget\n  include A\n  include B\n  include C\n  include D\n  def own; end\nend\n",
    );
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    let findings = payload["data"]["findings"]
        .as_array()
        .expect("findings array");
    let interface_rules = [
        "solid-lsp",
        "solid-isp",
        "fat-interface",
        "too-many-interfaces",
    ];
    let offenders: Vec<&str> = findings
        .iter()
        .filter_map(|f| f["rule_id"].as_str())
        .filter(|id| interface_rules.contains(id))
        .collect();
    assert!(
        offenders.is_empty(),
        "Ruby mixins must not trigger interface SOLID rules, got: {offenders:?}"
    );
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn csharp_auto_properties_do_not_trigger_solid_isp() {
    let home = tempdir("csharp-auto-properties-home");
    let repo = tempdir("csharp-auto-properties-repo");
    write(
        &repo.join("Worker.cs"),
        r#"
interface IWide {
  void First(); void Second(); void Third(); void Fourth();
  void Fifth(); void Sixth(); void Seventh(); void Eighth();
}

class Worker : IWide {
  public int One { get; set; }
  public int Two { get; set; }
  public int Three { get; set; }
  public int Four { get; set; }
  public int Five { get; set; }
  public int Six { get; set; }
  public int Seven { get; set; }
  public int Eight { get; set; }

  public void First() { System.Console.WriteLine(); }
  public void Second() { System.Console.WriteLine(); }
  public void Third() { System.Console.WriteLine(); }
  public void Fourth() { System.Console.WriteLine(); }
  public void Fifth() { System.Console.WriteLine(); }
  public void Sixth() { System.Console.WriteLine(); }
  public void Seventh() { System.Console.WriteLine(); }
  public void Eighth() { System.Console.WriteLine(); }
}
"#,
    );
    let build = Command::new(bin())
        .args(["build", "--repo-root"])
        .arg(&repo)
        .env("HOME", &home)
        .output()
        .expect("build runs");
    assert!(build.status.success(), "build fails: {:?}", build.status);

    let out = scan(&home, &[&format!(r#"{{"repoRoot":"{}"}}"#, repo.display())]);
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    let findings = payload["data"]["findings"]
        .as_array()
        .expect("findings array");
    assert!(
        !findings
            .iter()
            .any(|finding| finding["rule_id"] == "solid-isp"),
        "auto-properties must not count as empty ISP stubs: {findings:?}"
    );
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}

#[test]
fn unwritable_output_emits_error_envelope_and_exits_nonzero() {
    let (home, repo) = build_fixture("unwritable", "warning");
    let missing_dir = home.join("no-such-dir/out.json");
    let out = scan(
        &home,
        &[&format!(
            r#"{{"repoRoot":"{}","output":"{}"}}"#,
            repo.display(),
            missing_dir.display()
        )],
    );
    assert!(!out.status.success(), "unwritable output → non-zero exit");
    let payload: serde_json::Value = serde_json::from_slice(&out.stdout).expect("envelope JSON");
    assert_eq!(payload["ok"], false);
    assert!(payload["data"]["error"]["code"].as_str().is_some());
    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&repo);
}
