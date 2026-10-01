use assert_cmd::Command;
use predicates::str::contains;

#[test]
fn eval_help_mentions_billed_runs_and_codex_proxy() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "--help"])
        .assert()
        .success()
        .stdout(contains("billed"))
        .stdout(contains("Codex"));
}

#[test]
fn trigger_without_harness_exits_2() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "trigger", "x", "q.json"])
        .assert()
        .code(2);
}

#[test]
fn trigger_help_documents_timeout_option() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "trigger", "--help"])
        .assert()
        .success()
        .stdout(contains("--timeout-seconds"))
        .stdout(contains("default: 300"));
}

#[test]
fn adopt_record_help_lists_record_fields() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["adopt", "record", "--help"])
        .assert()
        .success()
        .stdout(contains("--items"))
        .stdout(contains("--summary"))
        .stdout(contains("--files"))
        .stdout(contains("--eval-before"))
        .stdout(contains("--eval-after"));
}

#[test]
fn adopt_record_json_parse_errors_keep_the_shared_error_envelope() {
    let output = Command::cargo_bin("varde-learn")
        .unwrap()
        .args([
            "adopt",
            "record",
            "--items",
            "not-an-id",
            "--summary",
            "test",
            "--files",
            "src/lib.rs",
            "--json",
        ])
        .output()
        .expect("run invalid adopt record command");
    assert_eq!(output.status.code(), Some(2));
    let error: serde_json::Value = serde_json::from_slice(&output.stderr).expect("error JSON");
    assert_eq!(error["schema_version"], 1);
    assert_eq!(error["envelope_version"], 1);
    assert_eq!(error["data"]["error"]["code"], "usage_error");
}

#[test]
fn adopt_recurrence_help_documents_bounded_pages() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["adopt", "recurrence", "--help"])
        .assert()
        .success()
        .stdout(contains("--offset"))
        .stdout(contains("--limit"))
        .stdout(contains("--json"));
}

#[test]
fn output_help_exposes_codex_luna_and_explicit_model_selection() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["eval", "output", "--help"])
        .assert()
        .success()
        .stdout(contains("--harness"))
        .stdout(contains("default: codex"))
        .stdout(contains("gpt-6-luna"))
        .stdout(contains("--model"))
        .stdout(contains("--judge-model"));
}

#[test]
fn diagnose_help_lists_live_and_frozen_bounded_intakes() {
    Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["diagnose", "inspect", "--help"])
        .assert()
        .success()
        .stdout(contains("--harness"))
        .stdout(contains("--current"))
        .stdout(contains("--session"))
        .stdout(contains("--path"))
        .stdout(contains("--snapshot-out"))
        .stdout(contains("--snapshot-in"))
        .stdout(contains("--cutoff-anchor"))
        .stdout(contains("--offset"))
        .stdout(contains("--limit"));
}

#[test]
fn diagnose_capture_help_lists_file_and_flag_form_inputs() {
    let output = Command::cargo_bin("varde-learn")
        .unwrap()
        .args(["diagnose", "capture", "--help"])
        .output()
        .unwrap();
    assert!(output.status.success());
    let help = String::from_utf8(output.stdout).unwrap();
    for flag in [
        "--file",
        "--snapshot",
        "--source-id",
        "--record-index",
        "--native-id",
        "--kind",
        "--evidence",
        "--item-id",
        "--item-source",
        "--item-title",
        "--item-target",
    ] {
        assert!(help.contains(flag), "help lacks {flag}");
    }
}
