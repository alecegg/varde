use assert_cmd::Command;
use predicates::prelude::*;
use predicates::str::contains;

fn learn_command() -> Command {
    let mut command = Command::cargo_bin("varde").expect("varde binary");
    command.arg("learn");
    command
}

#[test]
fn eval_help_mentions_billed_runs_and_codex_proxy() {
    learn_command()
        .args(["eval", "--help"])
        .assert()
        .success()
        .stdout(contains("billed"))
        .stdout(contains("Codex"));
}

#[test]
fn trigger_without_harness_exits_2() {
    learn_command()
        .args(["eval", "trigger", "x", "q.json"])
        .assert()
        .code(2);
}

#[test]
fn trigger_help_documents_timeout_option() {
    learn_command()
        .args(["eval", "trigger", "--help"])
        .assert()
        .success()
        .stdout(contains("--timeout-seconds"))
        .stdout(contains("default: 300"));
}

#[test]
fn adopt_record_help_lists_record_fields() {
    learn_command()
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
    let output = learn_command()
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
    learn_command()
        .args(["adopt", "recurrence", "--help"])
        .assert()
        .success()
        .stdout(contains("--offset"))
        .stdout(contains("--limit"))
        .stdout(contains("--json"));
}

#[test]
fn output_help_exposes_codex_luna_and_explicit_model_selection() {
    learn_command()
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
    learn_command()
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
    let output = learn_command()
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

#[test]
fn diagnose_list_help_documents_repo_harness_and_run_options() {
    learn_command()
        .args(["diagnose", "list", "--help"])
        .assert()
        .success()
        .stdout(contains("--harness"))
        .stdout(contains("--repository"))
        .stdout(contains("--limit"))
        .stdout(contains("default: 5"))
        .stdout(contains("--run"))
        .stdout(contains("--json"));
}

#[test]
fn learn_help_names_repository_and_hides_the_repo_alias() {
    let commands: [&[&str]; 3] = [
        &["diagnose", "list"],
        &["friction", "list"],
        &["friction", "import"],
    ];
    for command in commands {
        let mut args = command.to_vec();
        args.push("--help");
        learn_command()
            .args(&args)
            .assert()
            .success()
            .stdout(contains("--repository"))
            .stdout(contains("--repo ").not());
    }
}
