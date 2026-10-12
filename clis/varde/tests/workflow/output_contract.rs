use super::common;

use std::fs;
use std::process::{Output, Stdio};

fn parse_channel(output: &Output) -> serde_json::Value {
    let bytes = if output.status.success() || !output.stdout.is_empty() {
        &output.stdout
    } else {
        &output.stderr
    };
    let text = std::str::from_utf8(bytes).unwrap().trim();
    assert_eq!(text.lines().count(), 1, "expected one JSON envelope");
    let value: serde_json::Value = serde_json::from_str(text).unwrap();
    assert_eq!(value["schema_version"], 1);
    assert_eq!(value["envelope_version"], 1);
    assert!(value["outcome"].is_string());
    assert!(value["meta"].is_object());
    value
}

fn create(bundle: &std::path::Path, slug: &str) -> Output {
    let mut child = common::work_command()
        .args(["concept", "create", "--bundle"])
        .arg(bundle)
        .args([slug, "--json"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    use std::io::Write;
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"---\ntype: reference\ndescription: A reference note.\n---\nbody\n")
        .unwrap();
    child.wait_with_output().unwrap()
}

#[test]
fn every_exit_class_uses_one_versioned_envelope() {
    let bundle = common::temp_bundle("output-contract");

    let success = create(&bundle, "doc");
    assert_eq!(success.status.code(), Some(0));
    assert_eq!(parse_channel(&success)["ok"], true);

    let duplicate = create(&bundle, "doc");
    assert_eq!(duplicate.status.code(), Some(5));
    assert_eq!(
        parse_channel(&duplicate)["data"]["error"]["code"],
        "already_exists"
    );

    let missing = common::work_command()
        .args(["concept", "show", "--bundle"])
        .arg(&bundle)
        .args(["missing", "--json"])
        .output()
        .unwrap();
    assert_eq!(missing.status.code(), Some(2));
    assert_eq!(
        parse_channel(&missing)["data"]["error"]["code"],
        "not_found"
    );

    let invalid = common::work_command()
        .args(["concept", "delete", "--bundle"])
        .arg(&bundle)
        .args(["../bad", "--json"])
        .output()
        .unwrap();
    assert_eq!(invalid.status.code(), Some(4));
    assert_eq!(
        parse_channel(&invalid)["data"]["error"]["code"],
        "invalid_input"
    );

    let mut conflict = common::work_command()
        .args(["concept", "update", "--bundle"])
        .arg(&bundle)
        .args(["doc", "--expected-version", "stale", "--json"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    use std::io::Write as _;
    conflict
        .stdin
        .take()
        .unwrap()
        .write_all(b"---\ntype: reference\n---\nchanged\n")
        .unwrap();
    let conflict = conflict.wait_with_output().unwrap();
    assert_eq!(conflict.status.code(), Some(3));
    assert_eq!(
        parse_channel(&conflict)["data"]["error"]["code"],
        "conflict"
    );

    let missing_bundle = bundle.join("absent");
    let internal = common::work_command()
        .args(["lint", "--bundle"])
        .arg(missing_bundle)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(internal.status.code(), Some(1));
    assert_eq!(
        parse_channel(&internal)["data"]["error"]["code"],
        "internal"
    );

    fs::remove_dir_all(bundle).unwrap();
}

#[test]
fn error_fix_uses_the_existing_versioned_envelope() {
    let root = common::temp_bundle("output-contract-error-fix");
    let plan = root.join("memory-bank/working/plans/2026-10-09-empty");
    fs::create_dir_all(&plan).unwrap();
    let output = common::isolate_memory(&root)
        .arg("conclude")
        .arg(&plan)
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(1));
    let envelope = parse_channel(&output);
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], "review_invalid");
    assert!(envelope["data"]["error"]["fix"]["reason"].is_string());
    fs::remove_dir_all(root).unwrap();
}
