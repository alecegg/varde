mod common;

use std::fs;
use std::process::{Command, Output, Stdio};

fn parse_channel(output: &Output) -> serde_json::Value {
    let bytes = if output.status.success() {
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
    let mut child = Command::new(common::bin())
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

    let missing = Command::new(common::bin())
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

    let invalid = Command::new(common::bin())
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

    let migrated = Command::new(common::bin())
        .arg("migrate")
        .arg(bundle.join("doc.md"))
        .arg("--apply")
        .output()
        .unwrap();
    assert!(migrated.status.success());

    let mut conflict = Command::new(common::bin())
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
    let internal = Command::new(common::bin())
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

    let migration_error = Command::new(common::bin())
        .arg("migrate")
        .arg(bundle.join("absent.md"))
        .arg("--json")
        .output()
        .unwrap();
    assert_eq!(migration_error.status.code(), Some(1));
    assert_eq!(
        parse_channel(&migration_error)["data"]["error"]["code"],
        "internal"
    );

    fs::remove_dir_all(bundle).unwrap();
}
