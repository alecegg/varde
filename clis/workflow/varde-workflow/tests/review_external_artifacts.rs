mod common;
use serde_json::{Value, json};
use std::{
    fs,
    path::{Path, PathBuf},
    process::Output,
};
struct Fixture {
    root: PathBuf,
    working: PathBuf,
    contract: PathBuf,
}
impl Fixture {
    fn new() -> Self {
        let root = common::temp_bundle("external-artifacts")
            .canonicalize()
            .unwrap();
        let working = common::temp_inputs("external-working")
            .canonicalize()
            .unwrap();
        fs::create_dir_all(root.join("isolated-config")).unwrap();
        let contract = root.join("contract.json");
        fs::write(&contract, json!({"outcome":"Update document", "scope":[], "assumptions":[], "design":"Bounded edit", "open_choices":[], "verification":["Read document"]}).to_string()).unwrap();
        Self {
            root,
            working,
            contract,
        }
    }
    fn run(&self, args: &[&str]) -> Output {
        common::isolate_memory(&self.root)
            .env("VARDE_WORKING_DIR", &self.working)
            .args(args)
            .output()
            .unwrap()
    }
    fn init(&self, id: &str, path: &Path) -> Output {
        self.run(&[
            "review",
            "init",
            "--subject",
            id,
            "--contract",
            self.contract.to_str().unwrap(),
            "--repository",
            self.root.to_str().unwrap(),
            "--artifact",
            path.to_str().unwrap(),
            "--json",
        ])
    }
    fn inspect(&self, id: &str, phase: &str) -> Value {
        success(self.run(&[
            "review",
            "inspect",
            "--subject",
            id,
            "--phase",
            phase,
            "--json",
        ]))
    }
    fn approve(&self, id: &str, phase: &str, inspected: &Value) -> Output {
        let mut record = json!({"schema_version":1,"subject_id":id,"phase":phase,"reviewer":{"identity":"test-reviewer","provenance":"integration-test"},"verdict":"approved","unresolved_choices":[],"contract_fingerprint":inspected["contract_fingerprint"],"baseline_id":inspected["baseline_id"],"verification_approach":"Read artifact","verification_rationale":"Bounded document","verification_expected_results":"Correct text","rationale":"Approved"});
        if phase == "pre-edit" {
            record["structural_risk"] = json!("low");
            record["structural_risk_rationale"] = json!("Bounded fixture");
            record["implementation_review_required"] = json!(true);
        } else {
            record["change_fingerprint"] = inspected["change_fingerprint"].clone();
            record["coverage"] = json!("entire-subject-change");
        }
        let path = self.root.join("record.json");
        fs::write(&path, record.to_string()).unwrap();
        self.run(&[
            "review",
            "record",
            "--subject",
            id,
            "--expected-version",
            inspected["version"].as_str().unwrap(),
            "--file",
            path.to_str().unwrap(),
            "--json",
        ])
    }
}
impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
        let _ = fs::remove_dir_all(&self.working);
    }
}
fn success(output: Output) -> Value {
    assert!(
        output.status.success(),
        "{} {}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)
}
#[test]
fn external_working_artifact_has_immutable_baseline_and_stale_final_gate() {
    let f = Fixture::new();
    let path = f.working.join("document.md");
    fs::write(&path, "before").unwrap();
    let init = success(f.init("external", &path));
    assert_eq!(init["subject"]["artifact_scope"], json!([path]));
    let entry = &init["manifest"]["entries"][0];
    assert_eq!(entry["path"], format!("artifact:{}", path.display()));
    let blob = entry["baseline"]["content_path"].as_str().unwrap();
    assert_eq!(fs::read_to_string(blob).unwrap(), "before");
    success(f.approve("external", "pre-edit", &init));
    success(f.run(&[
        "review",
        "check",
        "--subject",
        "external",
        "--checkpoint",
        "start",
        "--json",
    ]));
    fs::write(&path, "after").unwrap();
    let final_state = f.inspect("external", "implementation");
    assert_ne!(
        init["change_fingerprint"],
        final_state["change_fingerprint"]
    );
    assert_eq!(fs::read_to_string(blob).unwrap(), "before");
    success(f.approve("external", "implementation", &final_state));
    success(f.run(&[
        "review",
        "check",
        "--subject",
        "external",
        "--checkpoint",
        "complete",
        "--json",
    ]));
    fs::write(&path, "later").unwrap();
    assert_eq!(
        f.run(&[
            "review",
            "check",
            "--subject",
            "external",
            "--checkpoint",
            "complete",
            "--json"
        ])
        .status
        .code(),
        Some(4)
    );
}

#[test]
fn future_artifact_under_missing_ancestors_tracks_addition_and_deletion() {
    let f = Fixture::new();
    let path = f.working.join("future/nested/document.md");
    let init = success(f.init("future", &path));
    assert_eq!(init["manifest"]["entries"], json!([]));
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(&path, "created").unwrap();
    let added = f.inspect("future", "implementation");
    assert_eq!(added["manifest"]["entries"][0]["change"], "added");
    fs::remove_file(&path).unwrap();
    assert_eq!(
        f.inspect("future", "implementation")["change_fingerprint"],
        init["change_fingerprint"]
    );
    // An existing baseline file becoming missing must instead remain visible as deleted.
    fs::write(&path, "existing").unwrap();
    success(f.init("existing", &path));
    fs::remove_file(&path).unwrap();
    assert_eq!(
        f.inspect("existing", "implementation")["manifest"]["entries"][0]["change"],
        "deleted"
    );
}

#[test]
fn mixed_scope_expansion_is_occ_protected_and_invalidates_prior_approval() {
    let f = Fixture::new();
    fs::write(f.root.join("source.md"), "source").unwrap();
    let initial = success(f.run(&[
        "review",
        "init",
        "--subject",
        "mixed",
        "--contract",
        f.contract.to_str().unwrap(),
        "--repository",
        f.root.to_str().unwrap(),
        "--scope",
        "source.md",
        "--json",
    ]));
    success(f.approve("mixed", "pre-edit", &initial));
    let approved = f.inspect("mixed", "pre-edit");
    let artifact = f.working.join("external.md");
    fs::write(&artifact, "outside").unwrap();
    let expand = |version: &str| {
        f.run(&[
            "review",
            "expand",
            "--subject",
            "mixed",
            "--expected-version",
            version,
            "--artifact",
            artifact.to_str().unwrap(),
            "--json",
        ])
    };
    let expanded = success(expand(approved["version"].as_str().unwrap()));
    assert_ne!(expanded["baseline_id"], initial["baseline_id"]);
    assert_eq!(expanded["subject"]["scope"], json!(["source.md"]));
    assert_eq!(expanded["manifest"]["entries"].as_array().unwrap().len(), 2);
    assert_eq!(
        expand(approved["version"].as_str().unwrap()).status.code(),
        Some(3)
    );
    assert_eq!(
        f.run(&[
            "review",
            "check",
            "--subject",
            "mixed",
            "--checkpoint",
            "start",
            "--json"
        ])
        .status
        .code(),
        Some(4)
    );
    success(f.approve("mixed", "pre-edit", &expanded));
    let current = f.inspect("mixed", "pre-edit");
    let unchanged = success(expand(current["version"].as_str().unwrap()));
    assert_eq!(unchanged["baseline_id"], expanded["baseline_id"]);
    // A repository root scope still excludes undeclared external files.
    let other = f.working.join("other.md");
    fs::write(&other, "one").unwrap();
    fs::write(&other, "two").unwrap();
    assert_eq!(
        f.inspect("mixed", "pre-edit")["change_fingerprint"],
        unchanged["change_fingerprint"]
    );
}

#[test]
fn invalid_external_paths_and_changed_types_fail_closed() {
    let f = Fixture::new();
    let inside = f.root.join("inside.md");
    fs::write(&inside, "x").unwrap();
    fs::create_dir_all(f.working.join("review-gates")).unwrap();
    for path in [
        PathBuf::from("relative.md"),
        inside,
        f.working.clone(),
        f.working.join("a/../escape.md"),
        f.working.join("a/./alias.md"),
        f.working.join("review-gates/own.json"),
        f.working.join(".varde-workflow.lock"),
    ] {
        let output = f.init("invalid", &path);
        assert!(!output.status.success(), "accepted {}", path.display());
    }
    let path = f.working.join("document.md");
    fs::write(&path, "x").unwrap();
    success(f.init("type-change", &path));
    fs::remove_file(&path).unwrap();
    fs::create_dir(&path).unwrap();
    assert!(
        !f.run(&[
            "review",
            "inspect",
            "--subject",
            "type-change",
            "--phase",
            "implementation",
            "--json"
        ])
        .status
        .success()
    );
}

#[cfg(unix)]
#[test]
fn symlink_artifacts_and_ancestor_aliases_are_rejected() {
    use std::os::unix::fs::symlink;
    let f = Fixture::new();
    let path = f.working.join("document.md");
    fs::write(&path, "x").unwrap();
    let alias = f.working.join("alias.md");
    symlink(&path, &alias).unwrap();
    assert!(!f.init("alias", &alias).status.success());
    let dir = f.working.join("alias-dir");
    symlink(&f.working, &dir).unwrap();
    assert!(!f.init("ancestor", &dir.join("missing.md")).status.success());
    success(f.init("changed-alias", &path));
    fs::remove_file(&path).unwrap();
    symlink(&alias, &path).unwrap();
    assert!(
        !f.run(&[
            "review",
            "inspect",
            "--subject",
            "changed-alias",
            "--phase",
            "implementation",
            "--json"
        ])
        .status
        .success()
    );
}

#[test]
fn legacy_subject_without_artifact_field_keeps_baseline_identity() {
    let f = Fixture::new();
    fs::write(f.root.join("source.md"), "source").unwrap();
    let init = success(f.run(&[
        "review",
        "init",
        "--subject",
        "legacy",
        "--contract",
        f.contract.to_str().unwrap(),
        "--repository",
        f.root.to_str().unwrap(),
        "--scope",
        "source.md",
        "--json",
    ]));
    let subject_path = f.working.join("review-gates/legacy/subject.json");
    let stored: Value = serde_json::from_slice(&fs::read(&subject_path).unwrap()).unwrap();
    assert!(stored.get("artifact_scope").is_none());
    let inspected = f.inspect("legacy", "pre-edit");
    assert_eq!(init["baseline_id"], inspected["baseline_id"]);
    success(f.approve("legacy", "pre-edit", &inspected));
    success(f.run(&[
        "review",
        "check",
        "--subject",
        "legacy",
        "--checkpoint",
        "start",
        "--json",
    ]));
}

#[test]
fn root_repository_scope_expansion_captures_external_baseline() {
    let f = Fixture::new();
    let init = success(f.run(&[
        "review",
        "init",
        "--subject",
        "root-expansion",
        "--contract",
        f.contract.to_str().unwrap(),
        "--repository",
        f.root.to_str().unwrap(),
        "--scope",
        ".",
        "--json",
    ]));
    let path = f.working.join("external.md");
    fs::write(&path, "baseline").unwrap();
    let expanded = success(f.run(&[
        "review",
        "expand",
        "--subject",
        "root-expansion",
        "--expected-version",
        init["version"].as_str().unwrap(),
        "--artifact",
        path.to_str().unwrap(),
        "--json",
    ]));
    let key = format!("artifact:{}", path.display());
    let entry = expanded["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["path"] == key)
        .unwrap();
    let blob = entry["baseline"]["content_path"].as_str().unwrap();
    assert_eq!(fs::read_to_string(blob).unwrap(), "baseline");
    fs::write(&path, "changed").unwrap();
    assert_eq!(fs::read_to_string(blob).unwrap(), "baseline");
    let after = f.inspect("root-expansion", "implementation");
    assert_eq!(
        after["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .find(|entry| entry["path"] == key)
            .unwrap()["change"],
        "modified"
    );
}

#[cfg(unix)]
#[test]
fn hardlinks_to_repository_or_evidence_are_rejected_on_init_and_reinspection() {
    let f = Fixture::new();
    let source = f.root.join("source.md");
    fs::write(&source, "source").unwrap();
    let link = f.working.join("source-alias.md");
    fs::hard_link(&source, &link).unwrap();
    assert!(!f.init("hardlink", &link).status.success());
    let path = f.working.join("document.md");
    fs::write(&path, "document").unwrap();
    let init = success(f.init("existing-link", &path));
    let evidence = init["manifest"]["entries"][0]["baseline"]["content_path"]
        .as_str()
        .unwrap();
    let evidence_link = f.working.join("evidence-alias.md");
    fs::hard_link(evidence, &evidence_link).unwrap();
    assert!(!f.init("evidence-link", &evidence_link).status.success());
    fs::hard_link(&path, f.working.join("later-alias.md")).unwrap();
    assert!(
        !f.run(&[
            "review",
            "inspect",
            "--subject",
            "existing-link",
            "--phase",
            "implementation",
            "--json"
        ])
        .status
        .success()
    );
}

#[test]
fn repository_expansion_does_not_capture_already_scoped_future_artifact() {
    let f = Fixture::new();
    fs::create_dir(f.root.join("src")).unwrap();
    let artifact = f.working.join("planned.md");
    let init = success(f.run(&[
        "review",
        "init",
        "--subject",
        "reverse-expansion",
        "--contract",
        f.contract.to_str().unwrap(),
        "--repository",
        f.root.to_str().unwrap(),
        "--scope",
        "src",
        "--artifact",
        artifact.to_str().unwrap(),
        "--json",
    ]));
    fs::write(&artifact, "created after initial approval").unwrap();
    let current = f.inspect("reverse-expansion", "pre-edit");
    let expanded = success(f.run(&[
        "review",
        "expand",
        "--subject",
        "reverse-expansion",
        "--expected-version",
        current["version"].as_str().unwrap(),
        "--scope",
        ".",
        "--json",
    ]));
    let key = format!("artifact:{}", artifact.display());
    let entry = expanded["manifest"]["entries"]
        .as_array()
        .unwrap()
        .iter()
        .find(|entry| entry["path"] == key)
        .unwrap();
    assert!(entry["baseline"].is_null());
    assert_eq!(entry["change"], "added");
    assert_ne!(init["baseline_id"], expanded["baseline_id"]);
}

#[cfg(unix)]
#[test]
fn external_file_mode_change_is_covered() {
    use std::os::unix::fs::PermissionsExt;
    let f = Fixture::new();
    let path = f.working.join("mode.md");
    fs::write(&path, "same bytes").unwrap();
    fs::set_permissions(&path, fs::Permissions::from_mode(0o600)).unwrap();
    success(f.init("mode", &path));
    fs::set_permissions(&path, fs::Permissions::from_mode(0o700)).unwrap();
    let inspected = f.inspect("mode", "implementation");
    assert_eq!(inspected["manifest"]["entries"][0]["change"], "modified");
}
