mod common;

use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

struct Fixture {
    root: PathBuf,
    config: PathBuf,
}

impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(&format!("review-foundation-{tag}"));
        let config = root.join("isolated-config");
        fs::create_dir_all(&config).unwrap();
        fs::create_dir_all(root.join("src")).unwrap();
        fs::write(root.join("src/baseline.rs"), "baseline source\n").unwrap();
        Self { root, config }
    }

    fn run(&self, args: &[&str]) -> Output {
        Command::new(common::bin())
            .args(args)
            .current_dir(&self.root)
            .env("VARDE_CONFIG_DIR", &self.config)
            .env_remove("VARDE_WORKING_DIR")
            .env_remove("VARDE_KNOWLEDGE_DIR")
            .env_remove("VARDE_LEARN_STORE")
            .output()
            .unwrap()
    }

    fn plan(&self, body: &str) -> PathBuf {
        let path = self.root.join("memory-bank/working/plans/example/plan.md");
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        self.write_plan(&path, body);
        path
    }

    fn write_plan(&self, path: &Path, body: &str) {
        fs::write(
            path,
            format!("---\ntype: plan\nstatus: backlog\n---\n\n{body}\n\n## Progress\n- fixture\n"),
        )
        .unwrap();
    }

    fn init(&self, plan: &Path, scope: &str) -> Value {
        success(self.run(&[
            "review",
            "init",
            "--plan",
            plan.to_str().unwrap(),
            "--repository",
            self.root.to_str().unwrap(),
            "--scope",
            scope,
            "--json",
        ]))
    }

    fn inspect(&self, subject: &str) -> Value {
        success(self.run(&[
            "review",
            "inspect",
            "--subject",
            subject,
            "--phase",
            "pre-edit",
            "--json",
        ]))
    }

    fn git_init(&self) {
        let status = Command::new("git")
            .args(["init", "-q"])
            .current_dir(&self.root)
            .status()
            .unwrap();
        assert!(status.success());
    }
}

impl Drop for Fixture {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn success(output: Output) -> Value {
    assert!(
        output.status.success(),
        "status={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    common::json_data(&output.stdout)
}

fn failure(output: Output, exit: i32, code: &str) -> Value {
    assert_eq!(
        output.status.code(),
        Some(exit),
        "stdout={}\nstderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    let bytes = if output.stdout.is_empty() {
        &output.stderr
    } else {
        &output.stdout
    };
    let envelope: Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], code);
    envelope
}

fn contract_fingerprints(tag: &str, first: &str, second: &str) -> (Value, Value) {
    let fixture = Fixture::new(tag);
    let plan = fixture.plan(first);
    let subject = fixture.init(&plan, "src")["subject"]["subject_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let before = fixture.inspect(&subject);
    fixture.write_plan(&plan, second);
    let after = fixture.inspect(&subject);
    (
        before["contract_fingerprint"].clone(),
        after["contract_fingerprint"].clone(),
    )
}

#[test]
fn prose_whitespace_is_normalized_but_inline_code_whitespace_is_preserved() {
    let prose = Fixture::new("prose-whitespace");
    let plan = prose.plan("## Problem\nA   prose\n sentence.");
    let subject = prose.init(&plan, "src")["subject"]["subject_id"]
        .as_str()
        .unwrap()
        .to_owned();
    let initial = prose.inspect(&subject);
    fs::write(
        &plan,
        "---\ntype: plan\nstatus: active\n---\n\n## Problem\nA prose sentence.\n\n## Progress\n- changed\n",
    )
    .unwrap();
    let reformatted = prose.inspect(&subject);
    assert_eq!(
        initial["contract_fingerprint"], reformatted["contract_fingerprint"],
        "ordinary prose whitespace remains formatting-only"
    );

    let cases = [
        ("single", "`let  value`", "`let value`"),
        ("multi", "``value  ` tail``", "``value ` tail``"),
        ("multiline", "`alpha  \nbeta`", "`alpha \nbeta`"),
    ];
    for (tag, original_code, changed_code) in cases {
        let fixture = Fixture::new(tag);
        let original = fixture.plan(&format!("## Problem\nRun {original_code} now."));
        let subject = fixture.init(&original, "src")["subject"]["subject_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let initial = fixture.inspect(&subject);
        fs::write(
            &original,
            format!(
                "---\ntype: plan\nstatus: backlog\n---\n\n## Problem\nRun {changed_code} now.\n"
            ),
        )
        .unwrap();
        let changed = fixture.inspect(&subject);
        assert_ne!(
            initial["contract_fingerprint"], changed["contract_fingerprint"],
            "whitespace inside {tag} inline code must remain contract-significant"
        );
    }
}

#[cfg(unix)]
#[test]
fn baseline_and_blob_roots_cannot_escape_the_subject_directory() {
    use std::os::unix::fs::symlink;

    for escaped_root in ["baseline", "blobs"] {
        let fixture = Fixture::new(escaped_root);
        let plan = fixture.plan("## Problem\nKeep the baseline local.");
        let created = fixture.init(&plan, "src");
        let subject = created["subject"]["subject_id"]
            .as_str()
            .unwrap()
            .to_owned();
        let subject_dir = fixture
            .root
            .join("memory-bank/working/review-gates")
            .join(&subject);
        let root = if escaped_root == "baseline" {
            subject_dir.join("baseline")
        } else {
            subject_dir.join("baseline/blobs")
        };
        let outside = fixture.root.join(format!("escaped-{escaped_root}"));
        fs::rename(&root, &outside).unwrap();
        symlink(&outside, &root).unwrap();

        failure(
            fixture.run(&[
                "review",
                "inspect",
                "--subject",
                &subject,
                "--phase",
                "pre-edit",
                "--json",
            ]),
            4,
            "review_invalid",
        );
    }
}

#[cfg(unix)]
#[test]
fn explicitly_scoped_git_fifo_is_rejected_instead_of_dropped() {
    let fixture = Fixture::new("git-fifo");
    fixture.git_init();
    let fifo = fixture.root.join("src/pipe");
    fs::create_dir_all(fifo.parent().unwrap()).unwrap();
    let status = Command::new("mkfifo").arg(&fifo).status().unwrap();
    assert!(status.success());

    let plan = fixture.plan("## Problem\nReject unsupported scope entries.");
    failure(
        fixture.run(&[
            "review",
            "init",
            "--plan",
            plan.to_str().unwrap(),
            "--repository",
            fixture.root.to_str().unwrap(),
            "--scope",
            "src/pipe",
            "--json",
        ]),
        4,
        "review_invalid",
    );
}

#[test]
fn git_inventory_keeps_explicit_ignored_files_and_future_missing_scope() {
    let ignored = Fixture::new("git-ignored-file");
    ignored.git_init();
    fs::write(ignored.root.join(".gitignore"), "ignored.out\n").unwrap();
    fs::write(ignored.root.join("ignored.out"), "explicitly scoped\n").unwrap();
    let plan = ignored.plan("## Problem\nKeep explicit ignored-file scope.");
    let created = ignored.init(&plan, "ignored.out");
    assert!(
        created["manifest"]["entries"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["path"] == "ignored.out")
    );

    let missing = Fixture::new("git-future-missing-scope");
    missing.git_init();
    let plan = missing.plan("## Problem\nAllow a future scoped path.");
    let created = missing.init(&plan, "src/future.rs");
    assert!(
        created["manifest"]["entries"]
            .as_array()
            .unwrap()
            .is_empty()
    );
}

#[test]
fn literal_heading_hashes_remain_part_of_the_title() {
    let (with_hash, without_hash) =
        contract_fingerprints("literal-heading-hash", "## Design C#", "## Design C");
    assert_ne!(with_hash, without_hash);
}

#[test]
fn progress_hash_suffix_does_not_exclude_contract_content() {
    let (before, after) = contract_fingerprints(
        "progress-hash-suffix",
        "## Progress#\nOriginal requirement text.",
        "## Progress#\nChanged requirement text.",
    );
    assert_ne!(before, after);
}

#[test]
fn atx_closing_hashes_escaped_hashes_and_empty_titles_follow_commonmark() {
    let (plain, closed) = contract_fingerprints(
        "valid-heading-closer",
        "## Design\nThe design.",
        "## Design ##\nThe design.",
    );
    assert_eq!(plain, closed);

    let (one_escaped_hash, two_escaped_hashes) =
        contract_fingerprints("escaped-heading-hashes", r"## Design \#", r"## Design \##");
    assert_ne!(one_escaped_hash, two_escaped_hashes);

    let (without_separator, with_separator) = contract_fingerprints("empty-heading", "##", "## ");
    assert_eq!(without_separator, with_separator);

    let (empty, empty_with_closer) = contract_fingerprints("empty-heading-closer", "##", "## ###");
    assert_eq!(empty, empty_with_closer);
}

#[test]
fn nested_acceptance_checkbox_state_is_normalized_but_label_and_structure_are_not() {
    let (unchecked, checked) = contract_fingerprints(
        "nested-checkbox-state",
        "## Acceptance criteria\n- [ ] Parent\n    - [ ] Child",
        "## Acceptance criteria\n- [ ] Parent\n    - [x] Child",
    );
    assert_eq!(unchecked, checked);

    let (original, changed_label) = contract_fingerprints(
        "nested-checkbox-label",
        "## Acceptance criteria\n- [ ] Parent\n    - [ ] Child",
        "## Acceptance criteria\n- [ ] Parent\n    - [ ] Other child",
    );
    assert_ne!(original, changed_label);

    let (nested, flattened) = contract_fingerprints(
        "nested-checkbox-structure",
        "## Acceptance criteria\n- [ ] Parent\n    - [ ] Child",
        "## Acceptance criteria\n- [ ] Parent\n  - [ ] Child",
    );
    assert_ne!(nested, flattened);

    let (tab_unchecked, tab_checked) = contract_fingerprints(
        "tab-nested-checkbox",
        "## Acceptance criteria\n10. Parent\n\t- [ ] Child",
        "## Acceptance criteria\n10. Parent\n\t- [x] Child",
    );
    assert_eq!(tab_unchecked, tab_checked);
}

#[test]
fn code_blocks_stay_material_outside_and_inside_list_items() {
    let (standalone_before, standalone_after) = contract_fingerprints(
        "standalone-indented-code",
        "## Problem\n    sample  value",
        "## Problem\n    sample value",
    );
    assert_ne!(standalone_before, standalone_after);

    let (nested_before, nested_after) = contract_fingerprints(
        "nested-indented-code",
        "## Problem\n- Parent\n      sample  value",
        "## Problem\n- Parent\n      sample value",
    );
    assert_ne!(nested_before, nested_after);

    let (fenced_before, fenced_after) = contract_fingerprints(
        "fenced-code",
        "## Problem\n```text\nsample  value\n```",
        "## Problem\n```text\nsample value\n```",
    );
    assert_ne!(fenced_before, fenced_after);
}
