use super::common;
use serde_json::{Value, json};
use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};

fn text(output: &Output) -> String {
    format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    )
}

struct Fixture {
    root: PathBuf,
    task: PathBuf,
}
impl Fixture {
    fn new(tag: &str) -> Self {
        let root = common::temp_bundle(tag).canonicalize().unwrap();
        let task = root.join("task.md");
        let f = Self { root, task };
        f.git(&["init", "-q"]);
        f.git(&["config", "user.name", "Test"]);
        f.git(&["config", "user.email", "test@example.invalid"]);
        f.git(&["config", "commit.gpgsign", "false"]);
        f
    }
    fn git(&self, args: &[&str]) -> String {
        let output = Command::new("git")
            .arg("-C")
            .arg(&self.root)
            .args(args)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout).unwrap().trim().into()
    }
    fn commit(&self) -> String {
        self.git(&["add", "-A"]);
        self.git(&["commit", "-qm", "change"]);
        self.git(&["rev-parse", "HEAD"])
    }
    fn metadata(&self, text: &str) {
        fs::write(&self.task, format!("---\n{text}\n---\nbody\n")).unwrap();
    }
    fn run(&self, reference: &str) -> Output {
        self.run_with_tips(reference, &[])
    }
    fn run_with_tips(&self, reference: &str, trusted_tips: &[&str]) -> Output {
        let mut command = common::work_command();
        command
            .current_dir(&self.root)
            .args(["check-task-ownership", "--task"])
            .arg(&self.task)
            .args(["--commit", reference, "--json"]);
        for tip in trusted_tips {
            command.args(["--trusted-tip", tip]);
        }
        command.output().unwrap()
    }
    fn data(&self, reference: &str, exit: i32) -> Value {
        let output = self.run(reference);
        assert_eq!(
            output.status.code(),
            Some(exit),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        let envelope: Value = serde_json::from_slice(&output.stdout).unwrap();
        if exit == 2 {
            assert_eq!(envelope["ok"], false, "{envelope}");
            assert!(
                envelope["data"]["error"]["fix"].is_object(),
                "ownership failure omitted error.fix: {envelope}"
            );
            envelope["data"]["error"]["details"].clone()
        } else {
            assert_eq!(envelope["ok"], true);
            envelope["data"].clone()
        }
    }
}

#[test]
fn root_commit_in_scope_is_success() {
    let f = Fixture::new("ownership-root");
    f.metadata("creates: [source.txt]");
    fs::write(f.root.join("source.txt"), "source").unwrap();
    let commit = f.commit();
    assert_eq!(
        f.data(&commit, 0),
        json!({"status":"ok","stray":[],"declared":["source.txt"],"changed":["source.txt"]})
    );
}

#[test]
fn stray_paths_report_fix_guidance_in_json_and_text() {
    let f = Fixture::new("ownership-stray");
    f.metadata("modifies: []");
    fs::write(f.root.join("stray.txt"), "stray").unwrap();
    let commit = f.commit();
    let json_output = f.run(&commit);
    assert_eq!(json_output.status.code(), Some(2));
    let envelope: Value = serde_json::from_slice(&json_output.stdout).unwrap();
    assert_eq!(envelope["ok"], false);
    assert_eq!(envelope["data"]["error"]["code"], "ownership_stray");
    assert_eq!(
        envelope["data"]["error"]["details"]["stray"],
        json!(["stray.txt"])
    );
    assert!(envelope["data"]["error"]["fix"].is_object());

    let output = common::work_command()
        .args(["check-task-ownership", "--task"])
        .arg(&f.task)
        .args(["--commit", &commit, "--repo-root"])
        .arg(&f.root)
        .output()
        .unwrap();
    assert_eq!(output.status.code(), Some(2));
    let plain = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(plain.contains("stray.txt"), "{plain}");
    assert!(plain.contains("Fix:"), "text error omitted Fix: {plain}");
}

#[test]
fn ownership_pin_lookup_errors_include_fix_guidance() {
    let mut f = Fixture::new("ownership-pin-error");
    let tasks = f.root.join("tasks");
    fs::create_dir_all(&tasks).unwrap();
    f.task = tasks.join("change.md");
    f.metadata("modifies: []");
    let missing_repository = f.root.join("missing-repository");
    let output = common::work_command()
        .args(["check-task-ownership", "--task"])
        .arg(&f.task)
        .args(["--commit", "HEAD", "--repo-root"])
        .arg(&missing_repository)
        .arg("--json")
        .output()
        .unwrap();
    assert!(!output.status.success());
    let envelope: Value = serde_json::from_slice(&output.stderr)
        .unwrap_or_else(|error| panic!("missing JSON error: {error}\n{}", text(&output)));
    assert!(
        envelope["data"]["error"]["fix"].is_object(),
        "ownership pin lookup error omitted error.fix: {}",
        text(&output)
    );
}

#[test]
fn directory_and_glob_ownership_matches_changed_files() {
    let f = Fixture::new("ownership-patterns");
    f.metadata("modifies: [src/, 'assets/*.json', 'nested/**/*.rs']\ncreates: []\nrenames: []");
    for path in [
        "src/module.rs",
        "assets/data.json",
        "nested/module.rs",
        "nested/deep/module.rs",
        "assets/nested/other.json",
        "outside.txt",
    ] {
        let path = f.root.join(path);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(path, "source").unwrap();
    }
    let commit = f.commit();
    let output = f.run(&commit);
    assert_eq!(output.status.code(), Some(2));
    let envelope: Value = serde_json::from_slice(&output.stdout).unwrap();
    let data = &envelope["data"]["error"]["details"];
    assert_eq!(envelope["data"]["error"]["code"], "ownership_stray");
    assert_eq!(
        data["stray"],
        json!(["assets/nested/other.json", "outside.txt"])
    );
    let error = &envelope["data"]["error"];
    assert!(
        error["message"]
            .as_str()
            .unwrap()
            .contains("assets/nested/other.json")
    );
    assert!(error["message"].as_str().unwrap().contains("outside.txt"));
    assert!(error["fix"].is_object());
}

#[test]
fn plan_generated_paths_are_in_scope_for_each_task() {
    let mut f = Fixture::new("ownership-generated");
    fs::create_dir_all(f.root.join("tasks")).unwrap();
    f.task = f.root.join("tasks/task.md");
    f.metadata("modifies: []\ncreates: []\nrenames: []");
    fs::write(
        f.root.join("plan.md"),
        "---\ntype: plan\ngenerated: [build/]\n---\n",
    )
    .unwrap();
    f.commit();
    fs::create_dir_all(f.root.join("build")).unwrap();
    fs::write(f.root.join("build/index.json"), "{}").unwrap();

    let commit = f.commit();
    let data = f.data(&commit, 0);
    assert_eq!(data["status"], "ok");
    assert_eq!(data["declared"], json!(["build/"]));
    assert_eq!(data["changed"], json!(["build/index.json"]));
}

#[test]
fn owns_globs_and_plan_shared_paths_are_in_scope() {
    let mut f = Fixture::new("ownership-owns-shared");
    fs::create_dir_all(f.root.join("tasks")).unwrap();
    f.task = f.root.join("tasks/change.md");
    f.metadata("owns: ['src/**']");
    fs::write(
        f.root.join("plan.md"),
        "---\ntype: plan\nshared: [shared.txt]\n---\n",
    )
    .unwrap();
    f.commit();
    fs::create_dir_all(f.root.join("src")).unwrap();
    fs::write(f.root.join("src/module.rs"), "source").unwrap();
    fs::write(f.root.join("shared.txt"), "shared").unwrap();
    let commit = f.commit();

    let data = f.data(&commit, 0);
    assert_eq!(data["status"], "ok");
    assert_eq!(data["declared"], json!(["shared.txt", "src/**"]));
    assert_eq!(data["changed"], json!(["shared.txt", "src/module.rs"]));
}

#[test]
fn owns_and_shared_reject_paths_outside_both() {
    let mut f = Fixture::new("ownership-owns-stray");
    fs::create_dir_all(f.root.join("tasks")).unwrap();
    f.task = f.root.join("tasks/change.md");
    f.metadata("owns: [src/]");
    fs::write(
        f.root.join("plan.md"),
        "---\ntype: plan\nshared: [shared.txt]\n---\n",
    )
    .unwrap();
    f.commit();
    fs::create_dir_all(f.root.join("src")).unwrap();
    fs::write(f.root.join("src/module.rs"), "source").unwrap();
    fs::write(f.root.join("stray.txt"), "stray").unwrap();
    let commit = f.commit();

    let data = f.data(&commit, 2);
    assert_eq!(data["stray"], json!(["stray.txt"]));
}

#[test]
fn exact_odd_paths_and_yaml_aliases_are_preserved() {
    let f = Fixture::new("ownership-odd");
    let paths = [
        " leading ",
        "trailing ",
        "comma,name",
        "café.txt",
        "line\nbreak",
    ];
    for path in paths {
        fs::write(f.root.join(path), "source").unwrap();
    }
    f.metadata(&format!(
        "modifies: &owned {}\ncreates: *owned",
        serde_json::to_string(&paths).unwrap()
    ));
    let commit = f.commit();
    let data = f.data(&commit, 0);
    let expected = json!([
        " leading ",
        "café.txt",
        "comma,name",
        "line\nbreak",
        "trailing "
    ]);
    assert_eq!(data["changed"], expected);
    assert_eq!(data["declared"], expected);
}

#[test]
fn declared_paths_are_lexical_even_when_they_resolve_to_same_file() {
    let f = Fixture::new("ownership-lexical");
    f.metadata("creates: [./source.txt]");
    fs::write(f.root.join("source.txt"), "source").unwrap();
    let commit = f.commit();
    assert_eq!(f.data(&commit, 2)["stray"], json!(["source.txt"]));
}

#[test]
fn missing_ownership_and_spikes_skip_without_inspecting_git() {
    for (index, metadata) in ["status: todo", "kind: spike\ncreates: [planned]"]
        .iter()
        .enumerate()
    {
        let f = Fixture::new(&format!("ownership-skip-{index}"));
        f.metadata(metadata);
        let output = common::work_command()
            .args(["check-task-ownership", "--task"])
            .arg(&f.task)
            .args(["--commit", "invalid-ref", "--repo-root"])
            .arg(f.root.join("absent"))
            .arg("--json")
            .output()
            .unwrap();
        assert!(output.status.success());
        let result: Value = serde_json::from_slice(&output.stdout).unwrap();
        assert_eq!(result["data"]["status"], "skipped");
        assert_eq!(result["data"]["changed"], json!([]));
    }
}

#[test]
fn malformed_metadata_fails_before_skip() {
    for (index, metadata) in [
        "modifies: file",
        "creates: [42]",
        "renames: null",
        "renames: [old -> new -> third]",
        "kind: []",
        "kind: spike\nmodifies: false",
        "creates: [unterminated",
    ]
    .iter()
    .enumerate()
    {
        let f = Fixture::new(&format!("ownership-invalid-{index}"));
        f.metadata(metadata);
        let output = f.run("invalid-ref");
        assert_eq!(output.status.code(), Some(1), "{metadata}");
        let error: Value = serde_json::from_slice(&output.stderr).unwrap();
        assert_eq!(error["data"]["error"]["code"], "unreadable_task");
    }
}

#[test]
fn branch_tag_refs_resolve_but_options_ranges_and_missing_refs_fail() {
    let f = Fixture::new("ownership-refs");
    f.metadata("creates: [source]");
    fs::write(f.root.join("source"), "source").unwrap();
    f.commit();
    f.git(&["branch", "owned"]);
    f.git(&["tag", "owned-tag"]);
    for reference in ["HEAD", "owned", "owned-tag"] {
        assert_eq!(f.data(reference, 0)["status"], "ok");
    }
    for reference in ["ghost", "HEAD..HEAD", "--all", "HEAD^{tree}"] {
        let output = common::work_command()
            .args(["check-task-ownership", "--task"])
            .arg(&f.task)
            .arg(format!("--commit={reference}"))
            .arg("--repo-root")
            .arg(&f.root)
            .arg("--json")
            .output()
            .unwrap();
        assert_eq!(output.status.code(), Some(1), "{reference}");
        let error: Value = serde_json::from_slice(&output.stderr).unwrap();
        assert_eq!(error["data"]["error"]["code"], "git_error");
    }
}

#[test]
fn merge_commits_charge_only_paths_different_from_every_parent() {
    let f = Fixture::new("ownership-merge");
    f.metadata("modifies: []");
    fs::write(f.root.join("both.txt"), "base\n").unwrap();
    f.commit();
    let branch = f.git(&["branch", "--show-current"]);
    f.git(&["checkout", "-qb", "side"]);
    fs::write(f.root.join("both.txt"), "side\n").unwrap();
    fs::write(f.root.join("side.txt"), "side\n").unwrap();
    f.commit();
    f.git(&["checkout", "-q", &branch]);
    fs::write(f.root.join("both.txt"), "main\n").unwrap();
    fs::write(f.root.join("main.txt"), "main\n").unwrap();
    f.commit();
    let merge = Command::new("git")
        .args(["merge", "--no-ff", "side", "-m", "merge"])
        .current_dir(&f.root)
        .output()
        .unwrap();
    assert!(!merge.status.success(), "expected a content conflict");
    fs::write(f.root.join("both.txt"), "resolved\n").unwrap();
    f.git(&["add", "both.txt"]);
    f.git(&["commit", "-qm", "resolve merge"]);
    let output = f.run("HEAD");
    assert_eq!(output.status.code(), Some(2));
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(
        result["data"]["error"]["details"]["changed"],
        json!(["both.txt"])
    );
    assert_eq!(
        result["data"]["error"]["details"]["stray"],
        json!(["both.txt"])
    );
}

#[test]
fn trusted_tips_must_be_ancestors_of_integration_head_and_name_the_commit() {
    let f = Fixture::new("ownership-trusted-tip");
    f.metadata("creates: [owned]");
    fs::write(f.root.join("owned"), "owned").unwrap();
    f.commit();
    let integration_head = f.git(&["rev-parse", "HEAD"]);
    f.git(&["checkout", "-qb", "unmerged"]);
    fs::write(f.root.join("side"), "side").unwrap();
    let unmerged = f.commit();
    f.git(&["checkout", "-q", "-"]);

    let output = f.run_with_tips("HEAD", &[&unmerged]);
    assert_eq!(output.status.code(), Some(1));
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["data"]["error"]["code"], "git_error");
    let message = error["data"]["error"]["message"].as_str().unwrap();
    assert!(message.contains(&unmerged));
    assert!(message.contains("integration branch HEAD"));
    assert_eq!(f.git(&["rev-parse", "HEAD"]), integration_head);
}

#[test]
fn replace_refs_do_not_change_ownership_history() {
    let f = Fixture::new("ownership-replace-ref");
    f.metadata("creates: [owned.txt]");
    fs::write(f.root.join("base.txt"), "base").unwrap();
    let base = f.commit();
    fs::write(f.root.join("owned.txt"), "owned").unwrap();
    let owned = f.commit();
    f.git(&["checkout", "-qb", "replacement", &base]);
    fs::write(f.root.join("stray.txt"), "stray").unwrap();
    let replacement = f.commit();
    f.git(&["replace", &owned, &replacement]);

    let output = f.run(&owned);
    assert_eq!(output.status.code(), Some(0));
    let result: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(result["data"]["changed"], json!(["owned.txt"]));
    assert_eq!(result["data"]["stray"], json!([]));
}

#[test]
fn rename_endpoints_and_deletions_are_audited_without_rename_detection() {
    let f = Fixture::new("ownership-rename");
    f.metadata("modifies: []");
    fs::write(f.root.join("old"), "old").unwrap();
    fs::write(f.root.join("deleted"), "delete").unwrap();
    f.commit();
    f.git(&["mv", "old", "new"]);
    fs::remove_file(f.root.join("deleted")).unwrap();
    f.metadata(
        "modifies: [deleted]
renames: [old -> new]",
    );
    let commit = f.commit();
    assert_eq!(
        f.data(&commit, 0)["changed"],
        json!(["deleted", "new", "old"])
    );
}

#[test]
fn task_file_exclusion_resolves_aliases_and_outside_task_files_work() {
    let f = Fixture::new("ownership-taskalias");
    f.metadata("modifies: []");
    let commit = f.commit();
    assert_eq!(f.data(&commit, 0)["changed"], json!([]));
    let alias = f.root.join("task-alias.md");
    std::os::unix::fs::symlink("task.md", &alias).unwrap();
    let output = common::work_command()
        .args(["check-task-ownership", "--task"])
        .arg(alias)
        .args(["--commit", &commit, "--repo-root"])
        .arg(&f.root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(output.status.success());
    let outside = common::temp_bundle("ownership-outside").join("task.md");
    fs::write(&outside, "---\ncreates: [task.md]\n---\n").unwrap();
    let output = common::work_command()
        .args(["check-task-ownership", "--task"])
        .arg(outside)
        .args(["--commit", &commit, "--repo-root"])
        .arg(&f.root)
        .arg("--json")
        .output()
        .unwrap();
    assert!(output.status.success());
    let data: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(data["data"]["changed"], json!(["task.md"]));
}

#[test]
fn invalid_utf8_git_paths_fail_instead_of_losing_identity() {
    use std::io::Write;
    use std::process::Stdio;
    let f = Fixture::new("ownership-utf8");
    f.metadata("modifies: []");
    // Create the tree directly: some filesystems cannot materialize this name.
    let blob = f.git(&["hash-object", "-w", "--stdin"]);
    let mut child = Command::new("git")
        .arg("-C")
        .arg(&f.root)
        .args(["mktree", "-z"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    let mut entry = format!("100644 blob {blob}\tbad").into_bytes();
    entry.extend_from_slice(&[255, 0]);
    child.stdin.take().unwrap().write_all(&entry).unwrap();
    let tree = child.wait_with_output().unwrap();
    assert!(tree.status.success());
    let tree = String::from_utf8(tree.stdout).unwrap();
    let commit = f.git(&["commit-tree", tree.trim(), "-m", "invalid filename"]);
    let output = f.run(&commit);
    assert_eq!(output.status.code(), Some(1));
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["data"]["error"]["code"], "git_error");
}

fn snapshot(root: &std::path::Path) -> Vec<(PathBuf, Vec<u8>)> {
    let mut files = Vec::new();
    for entry in fs::read_dir(root).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            files.extend(snapshot(&path));
        } else {
            files.push((path.clone(), fs::read(path).unwrap()));
        }
    }
    files.sort();
    files
}

#[test]
fn audit_does_not_change_repository_files() {
    let f = Fixture::new("ownership-readonly");
    f.metadata("modifies: []");
    let commit = f.commit();
    let before = snapshot(&f.root);
    f.data(&commit, 0);
    assert_eq!(snapshot(&f.root), before);
}

#[test]
fn ambiguous_short_refs_fail_even_when_repository_disables_warnings() {
    let f = Fixture::new("ownership-ambiguous");
    f.metadata("creates: [owned]");
    fs::write(f.root.join("owned"), "owned").unwrap();
    f.commit();
    f.git(&["tag", "collision"]);
    fs::write(f.root.join("stray"), "stray").unwrap();
    f.commit();
    f.git(&["branch", "collision"]);
    f.git(&["config", "core.warnAmbiguousRefs", "false"]);
    let output = f.run("collision");
    assert_eq!(output.status.code(), Some(1));
    let error: Value = serde_json::from_slice(&output.stderr).unwrap();
    assert_eq!(error["data"]["error"]["code"], "git_error");
    assert_eq!(
        f.data("refs/tags/collision", 0)["changed"],
        json!(["owned"])
    );
    assert_eq!(f.data("refs/heads/collision", 2)["stray"], json!(["stray"]));
    assert_eq!(
        f.git(&["config", "--get", "core.warnAmbiguousRefs"]),
        "false"
    );
}

#[test]
fn missing_modifies_are_rejected_but_creates_may_be_new() {
    let missing = Fixture::new("ownership-missing-modifies");
    missing.metadata("modifies: [src/missing.rs]\ncreates: []\nrenames: []");
    let missing_commit = missing.commit();
    let output = missing.run(&missing_commit);
    assert!(!output.status.success());
    let envelope: Value = serde_json::from_slice(&output.stdout).unwrap();
    assert_eq!(envelope["data"]["error"]["code"], "ownership_invalid");
    assert!(
        envelope["data"]["error"]["details"]["blockers"]
            .to_string()
            .contains("src/missing.rs")
    );
    assert!(envelope["data"]["error"]["fix"].is_object());
    let message = format!(
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(message.contains("src/missing.rs"), "{message}");

    let created = Fixture::new("ownership-missing-create");
    created.metadata("modifies: []\ncreates: [src/new.rs]\nrenames: []");
    let created_commit = created.commit();
    assert_eq!(created.data(&created_commit, 0)["status"], "ok");
}
