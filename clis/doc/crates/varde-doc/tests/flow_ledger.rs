//! `varde doc flow ledger`: parity with the `ledger` half of `skill-flow.py`.
//!
//! The ledgers are the frozen `skills/tests/fixtures/flow-ledger/` fixtures;
//! hash, validate and check run on copies in temp dirs. `ledger-score.{txt,json}`
//! hold the script's output for `small.json`.

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use varde_doc::flow::ledger::{Output, run_captured};

const SMALL: &str = include_str!("../../../../../skills/tests/fixtures/flow-ledger/small.json");
const SOURCE: &str = include_str!("../../../../../skills/tests/fixtures/flow-ledger/src/a.md");

/// A copy of the `small` fixture: `(temp dir, ledger path)`; sources sit beside it.
fn small() -> (tempfile::TempDir, PathBuf) {
    let tmp = tempfile::tempdir().unwrap();
    fs::create_dir(tmp.path().join("src")).unwrap();
    fs::write(tmp.path().join("src/a.md"), SOURCE).unwrap();
    let ledger = tmp.path().join("ledger.json");
    fs::write(&ledger, SMALL).unwrap();
    (tmp, ledger)
}

fn ledger(args: &[&str], file: &Path, root: &Path) -> Output {
    let (file, root) = (file.to_str().unwrap(), root.to_str().unwrap());
    let mut argv = args.to_vec();
    argv.splice(1..1, [file, "--root", root]);
    run_captured(&argv).unwrap()
}

fn json(output: &Output) -> Value {
    serde_json::from_str(&output.stdout).unwrap()
}

#[test]
fn score_text_matches_the_script() {
    let (tmp, file) = small();
    let output = ledger(&["score"], &file, tmp.path());
    assert_eq!(output.code, 0);
    assert_eq!(
        output.stdout,
        include_str!("fixtures/flow/ledger-score.txt")
    );
}

#[test]
fn score_json_matches_the_script_by_value() {
    let (tmp, file) = small();
    let output = ledger(&["score", "--json"], &file, tmp.path());
    let expected: Value =
        serde_json::from_str(include_str!("fixtures/flow/ledger-score.json")).unwrap();
    assert_eq!(output.code, 0);
    assert_eq!(json(&output)["data"], expected);
}

#[test]
fn score_by_route_keeps_only_that_routes_phases() {
    let (tmp, file) = small();
    let output = ledger(&["score", "--route", "default"], &file, tmp.path());
    assert_eq!(
        output.stdout,
        "cyclomatic 2 cognitive 1 decisions 1 branch_units 1\n  gate: 1 decisions, 1 units, cognitive 1\n"
    );
}

#[test]
fn an_unknown_route_is_a_usage_error() {
    let (tmp, file) = small();
    let output = ledger(&["score", "--route", "nope"], &file, tmp.path());
    assert_eq!(output.code, 2);
    assert!(output.stderr.contains("ledger has no route 'nope'"));
}

#[test]
fn a_fresh_ledger_validates_and_checks_clean() {
    let (tmp, file) = small();
    for action in ["validate", "check"] {
        let output = ledger(&[action], &file, tmp.path());
        assert_eq!((output.code, output.stdout.as_str()), (0, ""), "{action}");
    }
}

#[test]
fn edited_lines_fail_validate_and_check() {
    let (tmp, file) = small();
    fs::write(
        tmp.path().join("src/a.md"),
        SOURCE.replace("approved", "rejected"),
    )
    .unwrap();
    let validate = ledger(&["validate"], &file, tmp.path());
    assert_eq!(validate.code, 1);
    assert_eq!(validate.stdout, "S-001: hash does not match cited lines\n");
    let check = ledger(&["check"], &file, tmp.path());
    assert_eq!(check.code, 1);
    assert_eq!(check.stdout, "S-001: changed or vanished\n");
}

#[test]
fn moved_lines_are_reported_with_their_new_range() {
    let (tmp, file) = small();
    fs::write(tmp.path().join("src/a.md"), format!("new\nnew\n{SOURCE}")).unwrap();
    let check = ledger(&["check"], &file, tmp.path());
    assert_eq!(check.code, 1);
    assert_eq!(
        check.stdout,
        "S-001: moved to src/a.md lines 5-6\nS-002: moved to src/a.md lines 8-8\n"
    );
}

#[test]
fn validate_reports_structure_problems() {
    let (tmp, file) = small();
    let broken = SMALL
        .replace("\"units\": 2", "\"units\": 5")
        .replace("\"depth\": 0", "\"depth\": -1")
        .replace("\"path\": \"src/a.md\"", "\"path\": \"src/gone.md\"")
        .replace(
            "\"unresolved_calls\": []",
            "\"unresolved_calls\": [{\"name\": \"x\", \"kind\": \"local\"}]",
        );
    fs::write(&file, broken).unwrap();
    let output = ledger(&["validate"], &file, tmp.path());
    assert_eq!(output.code, 1);
    assert_eq!(
        output.stdout,
        "S-001: invalid depth\nS-002: units do not match alternatives - 1\nfile missing: src/gone.md\n\
         unresolved local call: {\"kind\": \"local\", \"name\": \"x\"}\n"
    );
}

#[test]
fn json_envelopes_report_findings_under_details() {
    let (tmp, file) = small();
    fs::write(tmp.path().join("src/a.md"), "x\n").unwrap();
    let output = ledger(&["check", "--json"], &file, tmp.path());
    let envelope = json(&output);
    assert_eq!(output.code, 1);
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], "doc_ledger_stale");
    assert_eq!(
        envelope["data"]["error"]["details"]["stale"]
            .as_array()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn hash_restores_the_fixture_byte_for_byte() {
    let (tmp, file) = small();
    let stale = SMALL.replace(
        "9647a4152e38a5d7252b849e354feb466bf4ecef9713a84525c6aeb4a68aa264",
        &"0".repeat(64),
    );
    fs::write(&file, stale).unwrap();
    let output = ledger(&["hash"], &file, tmp.path());
    assert_eq!((output.code, output.stdout.as_str()), (0, ""));
    assert_eq!(fs::read_to_string(&file).unwrap(), SMALL);
}

#[test]
fn hash_escapes_non_ascii_text_like_python() {
    let tmp = tempfile::tempdir().unwrap();
    fs::write(tmp.path().join("a.md"), "x\n").unwrap();
    let ledger_text = |hash: &str| {
        format!(
            "{{\n  \"decisions\": [\n    {{\n      \"id\": \"D-1\",\n      \"phase\": \"p\",\n      \
             \"source\": \"a.md\",\n      \"line_start\": 1,\n      \"line_end\": 1,\n      \
             \"condition\": \"caf\\u00e9 \\ud83d\\ude00 \\\"q\\\" \\u007f\",\n      \
             \"alternatives\": [\n        \"a\",\n        \"b\"\n      ],\n      \"units\": 1,\n      \
             \"depth\": 0{hash}\n    }}\n  ],\n  \"files\": [],\n  \"extra\": {{}}\n}}\n"
        )
    };
    let file = tmp.path().join("ledger.json");
    fs::write(&file, ledger_text("")).unwrap();
    let output = ledger(&["hash"], &file, tmp.path());
    assert_eq!(output.code, 0);
    // Python: hashlib.sha256(b"x").hexdigest(); a new key lands last.
    let hash =
        ",\n      \"hash\": \"2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881\"";
    assert_eq!(fs::read_to_string(&file).unwrap(), ledger_text(hash));
}

#[test]
fn hash_fails_when_cited_lines_are_missing() {
    let (tmp, file) = small();
    fs::remove_file(tmp.path().join("src/a.md")).unwrap();
    let output = ledger(&["hash"], &file, tmp.path());
    assert_eq!(output.code, 1);
    assert_eq!(output.stderr, "S-001: cited lines not found\n");
    assert_eq!(fs::read_to_string(&file).unwrap(), SMALL);
}

#[test]
fn flow_without_paths_or_ledger_is_still_a_usage_error() {
    let command = varde_doc::cli_command();
    let error = command
        .clone()
        .try_get_matches_from(["varde doc", "flow"])
        .unwrap_err();
    assert_eq!(
        error.kind(),
        clap::error::ErrorKind::MissingRequiredArgument
    );
    assert!(
        command
            .clone()
            .try_get_matches_from(["varde doc", "flow", "ledger"])
            .is_err()
    );
    assert!(
        command
            .try_get_matches_from(["varde doc", "flow", "ledger", "score", "x.json"])
            .is_ok()
    );
}
