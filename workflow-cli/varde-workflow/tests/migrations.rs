mod common;

use std::fs;
use std::io::Write;
use std::process::{Command, Stdio};

#[test]
fn preview_is_stable_and_rejected_mutation_preserves_bytes() {
    let bundle = common::temp_bundle("migration-preview");
    let artifact = bundle.join("legacy.md");
    let bytes = b"---\ntype: reference\nstatus: stable\n---\nlegacy body\n";
    fs::write(&artifact, bytes).unwrap();

    let preview = || {
        let output = Command::new(common::bin())
            .arg("migrate")
            .arg(&artifact)
            .arg("--json")
            .output()
            .unwrap();
        assert!(output.status.success());
        common::json_data(&output.stdout)
    };
    assert_eq!(preview(), preview());
    assert_eq!(fs::read(&artifact).unwrap(), bytes);

    let mut child = Command::new(common::bin())
        .args(["concept", "update", "--bundle"])
        .arg(&bundle)
        .args(["legacy", "--expected-version"])
        .arg(okf_core::occ::version(bytes))
        .arg("--json")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(b"---\ntype: reference\n---\nchanged\n")
        .unwrap();
    let rejected = child.wait_with_output().unwrap();
    assert_eq!(rejected.status.code(), Some(4));
    let envelope: serde_json::Value = serde_json::from_slice(&rejected.stdout).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "migration_required");
    assert!(envelope["data"]["error"]["details"]["content"].is_string());
    assert_eq!(fs::read(&artifact).unwrap(), bytes);

    fs::remove_dir_all(bundle).unwrap();
}

#[test]
fn apply_is_explicit_and_produces_versioned_artifact() {
    let bundle = common::temp_bundle("migration-apply");
    let artifact = bundle.join("legacy.md");
    fs::write(&artifact, "---\ntype: reference\n---\nbody\n").unwrap();

    let output = Command::new(common::bin())
        .arg("migrate")
        .arg(&artifact)
        .args(["--apply", "--json"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let applied = common::json_data(&output.stdout);
    assert_eq!(applied["applied"], true);

    let inspected = Command::new(common::bin())
        .arg("inspect")
        .arg(&artifact)
        .arg("--json")
        .output()
        .unwrap();
    let inspected = common::json_data(&inspected.stdout);
    assert_eq!(inspected["legacy"], false);
    assert_eq!(inspected["id"], applied["id"]);

    fs::remove_dir_all(bundle).unwrap();
}
