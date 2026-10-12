use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use tempfile::TempDir;
use varde_code::ast_edit::{
    ApplyOptions, ApplyStatus, PreviewOptions, Proposal, RewriteRule, apply, preview,
};

fn tempdir(prefix: &str) -> TempDir {
    tempfile::Builder::new()
        .prefix(prefix)
        .tempdir()
        .expect("temporary directory creates")
}

fn rule(id: &str, language: &str, pattern: &str, replacement: &str) -> RewriteRule {
    RewriteRule {
        id: id.into(),
        language: language.into(),
        pattern: pattern.into(),
        replacement: replacement.into(),
        inside: None,
        has: None,
        precedes: None,
        follows: None,
    }
}

fn proposal(repo: &Path, store: &Path, paths: &[&str], rules: Vec<RewriteRule>) -> Proposal {
    preview(&PreviewOptions {
        repository_root: repo.to_path_buf(),
        invoking_cwd: repo.to_path_buf(),
        paths: paths.iter().map(PathBuf::from).collect(),
        store_dir: store.to_path_buf(),
        rules,
    })
    .expect("preview completes")
    .proposal
    .expect("fixture produces an applicable proposal")
}

fn apply_to(repo: &Path, proposal: &Proposal) -> Result<varde_code::ast_edit::ApplyResult, String> {
    apply(
        proposal,
        &ApplyOptions {
            repository_root: repo.to_path_buf(),
        },
    )
    .map_err(|error| format!("{error:#}"))
}

#[test]
fn applies_saved_mixed_language_bytes_and_keeps_deduplicated_rule_provenance() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    let ts_source = "const value = oldCall(1);\n";
    let py_source = "value = old_call(2)\n";
    fs::write(repo.path().join("main.ts"), ts_source).unwrap();
    fs::write(repo.path().join("main.py"), py_source).unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts", "main.py"],
        vec![
            rule("ts-first", "typescript", "oldCall($ARG)", "newCall($ARG)"),
            rule("ts-second", "typescript", "oldCall($ARG)", "newCall($ARG)"),
            rule("py", "python", "old_call($ARG)", "new_call($ARG)"),
        ],
    );

    assert_eq!(proposal.files.len(), 2);
    let ts_change = proposal
        .files
        .iter()
        .find(|file| file.path == "main.ts")
        .unwrap();
    assert_eq!(ts_change.match_spans.len(), 1);
    assert_eq!(
        ts_change.match_spans[0]
            .rule_ids
            .iter()
            .map(String::as_str)
            .collect::<std::collections::BTreeSet<_>>(),
        ["ts-first", "ts-second"].into_iter().collect()
    );

    let result = apply_to(repo.path(), &proposal).unwrap();
    assert_eq!(result.files.len(), 2);
    assert!(result.files.iter().all(|file| file.is_applied()));
    assert_eq!(
        fs::read(repo.path().join("main.ts")).unwrap(),
        b"const value = newCall(1);\n"
    );
    assert_eq!(
        fs::read(repo.path().join("main.py")).unwrap(),
        b"value = new_call(2)\n"
    );
}

#[test]
fn applies_files_nested_under_directory_scopes() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    let source_path = repo.path().join("src/main.ts");
    fs::create_dir_all(source_path.parent().unwrap()).unwrap();
    fs::write(&source_path, "const value = oldCall();\n").unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["src"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );

    assert_eq!(proposal.scope, ["src"]);
    assert_eq!(proposal.files[0].path, "src/main.ts");
    let result = apply_to(repo.path(), &proposal).unwrap();

    assert!(result.files[0].is_applied());
    assert_eq!(
        fs::read(&source_path).unwrap(),
        b"const value = newCall();\n"
    );
}

#[test]
fn rejects_mismatched_stored_root_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let other = tempdir("varde-ast-edit-outside-");
    let store = tempdir("varde-ast-edit-store-");
    let source = "oldCall();\n";
    fs::write(repo.path().join("main.js"), source).unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.js"],
        vec![rule("rename", "javascript", "oldCall()", "newCall()")],
    );
    proposal.repository_root = other.path().display().to_string();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("repository root"));
    assert_eq!(
        fs::read(repo.path().join("main.js")).unwrap(),
        source.as_bytes()
    );
}

#[test]
fn rejects_parent_traversal_out_of_the_repository() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.js"), "oldCall();\n").unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.js"],
        vec![rule("rename", "javascript", "oldCall()", "newCall()")],
    );
    proposal.files[0].path = "../outside.js".into();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("relative repository path"));
    assert_eq!(
        fs::read(repo.path().join("main.js")).unwrap(),
        b"oldCall();\n"
    );
}

#[test]
fn rejects_malformed_recorded_scope_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    let source = "oldCall();\n";
    fs::write(repo.path().join("main.js"), source).unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.js"],
        vec![rule("rename", "javascript", "oldCall()", "newCall()")],
    );
    proposal.scope = vec!["../outside".into()];

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("clean relative repository path"));
    assert_eq!(
        fs::read(repo.path().join("main.js")).unwrap(),
        source.as_bytes()
    );
}

#[cfg(unix)]
#[test]
fn rejects_parent_symlink_that_resolves_outside_the_repository() {
    use std::os::unix::fs::symlink;

    let repo = tempdir("varde-ast-edit-apply-");
    let outside = tempdir("varde-ast-edit-outside-");
    let store = tempdir("varde-ast-edit-store-");
    fs::create_dir(repo.path().join("src")).unwrap();
    fs::write(repo.path().join("src/main.ts"), "const x = oldCall();\n").unwrap();
    fs::write(outside.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["src/main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    fs::remove_file(repo.path().join("src/main.ts")).unwrap();
    fs::remove_dir(repo.path().join("src")).unwrap();
    symlink(outside.path(), repo.path().join("src")).unwrap();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("outside the repository"));
    assert_eq!(
        fs::read(outside.path().join("main.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[cfg(unix)]
#[test]
fn rejects_final_component_symlink() {
    use std::os::unix::fs::symlink;

    let repo = tempdir("varde-ast-edit-apply-");
    let outside = tempdir("varde-ast-edit-outside-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    fs::write(outside.path().join("target.ts"), "const x = oldCall();\n").unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    fs::remove_file(repo.path().join("main.ts")).unwrap();
    symlink(
        outside.path().join("target.ts"),
        repo.path().join("main.ts"),
    )
    .unwrap();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("final path component is a symlink"));
    assert_eq!(
        fs::read(outside.path().join("target.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[test]
fn validates_every_snapshot_before_writing_any_file() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    let first = "const x = oldCall();\n";
    fs::write(repo.path().join("a.ts"), first).unwrap();
    fs::write(repo.path().join("b.ts"), "const y = oldCall();\n").unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["a.ts", "b.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    fs::write(repo.path().join("b.ts"), "const y = staleCall();\n").unwrap();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("original snapshot"));
    assert_eq!(
        fs::read(repo.path().join("a.ts")).unwrap(),
        first.as_bytes()
    );
    assert_eq!(
        fs::read(repo.path().join("b.ts")).unwrap(),
        b"const y = staleCall();\n"
    );
}

#[test]
fn rejects_tampered_payload_digest_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    proposal.files[0].replacement_content = "const x = forgedCall();\n".into();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(format!("{error:#}").contains("replacement payload digest"));
    assert_eq!(
        fs::read(repo.path().join("main.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[test]
fn rejects_tampered_original_payload_digest_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    proposal.files[0].original_content = "const x = alteredCall();\n".into();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(error.contains("original payload digest"));
    assert_eq!(
        fs::read(repo.path().join("main.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[test]
fn rejects_tampered_proposal_body_digest_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    proposal.rules[0].replacement = "forgedCall()".into();

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(error.contains("proposal body digest"));
    assert_eq!(
        fs::read(repo.path().join("main.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[test]
fn rejects_unsupported_proposal_schema_version_before_writing() {
    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    fs::write(repo.path().join("main.ts"), "const x = oldCall();\n").unwrap();
    let mut proposal = proposal(
        repo.path(),
        store.path(),
        &["main.ts"],
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );
    proposal.version += 1;

    let error = apply_to(repo.path(), &proposal).unwrap_err();
    assert!(error.contains("unsupported AST edit proposal version"));
    assert_eq!(
        fs::read(repo.path().join("main.ts")).unwrap(),
        b"const x = oldCall();\n"
    );
}

#[cfg(unix)]
#[test]
fn reports_exact_partial_outcomes_when_a_read_only_directory_blocks_one_write() {
    use std::os::unix::fs::PermissionsExt;

    let repo = tempdir("varde-ast-edit-apply-");
    let store = tempdir("varde-ast-edit-store-");
    let locked_dir = repo.path().join("locked");
    fs::create_dir(&locked_dir).unwrap();
    fs::write(locked_dir.join("main.py"), "value = old_call()\n").unwrap();
    fs::write(repo.path().join("writable.ts"), "oldCall();\n").unwrap();
    let proposal = proposal(
        repo.path(),
        store.path(),
        &["locked/main.py", "writable.ts"],
        vec![
            rule("py", "python", "old_call()", "new_call()"),
            rule("ts", "typescript", "oldCall()", "newCall()"),
        ],
    );
    fs::set_permissions(&locked_dir, fs::Permissions::from_mode(0o555)).unwrap();

    let result = apply_to(repo.path(), &proposal).unwrap();

    fs::set_permissions(&locked_dir, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(result.files.len(), 2);
    assert_eq!(result.files[0].path, "locked/main.py");
    assert!(matches!(
        result.files[0].status,
        ApplyStatus::WriteFailed { .. }
    ));
    assert_eq!(result.files[1].path, "writable.ts");
    assert!(matches!(result.files[1].status, ApplyStatus::Applied));
    assert_eq!(
        fs::read(locked_dir.join("main.py")).unwrap(),
        b"value = old_call()\n"
    );
    assert_eq!(
        fs::read(repo.path().join("writable.ts")).unwrap(),
        b"newCall();\n"
    );
}

#[test]
fn applies_dirty_git_worktree_without_changing_the_index() {
    let repo = tempdir("varde-ast-edit-git-");
    let store = tempdir("varde-ast-edit-store-");
    let path = repo.path().join("main.rs");
    fs::write(&path, "fn main() { old(); let value = 0; }\n").unwrap();
    git(repo.path(), &["init", "--quiet"]);
    git(
        repo.path(),
        &["config", "user.email", "test@example.invalid"],
    );
    git(repo.path(), &["config", "user.name", "Test"]);
    git(repo.path(), &["add", "main.rs"]);
    git(repo.path(), &["commit", "--quiet", "-m", "fixture"]);

    fs::write(&path, "fn main() { old(); let value = 1; }\n").unwrap();
    git(repo.path(), &["add", "main.rs"]);
    let current_source = "fn main() { old(); let value = 2; }\n";
    fs::write(&path, current_source).unwrap();
    let index_before = git(repo.path(), &["ls-files", "--stage", "--", "main.rs"]);
    let status_before = git(repo.path(), &["status", "--porcelain", "--", "main.rs"]);
    assert!(String::from_utf8_lossy(&status_before.stdout).starts_with("MM "));

    let proposal = proposal(
        repo.path(),
        store.path(),
        &["main.rs"],
        vec![rule("rename", "rust", "old()", "new()")],
    );
    let result = apply_to(repo.path(), &proposal).unwrap();

    assert!(result.files[0].is_applied());
    assert_eq!(
        fs::read(&path).unwrap(),
        b"fn main() { new(); let value = 2; }\n"
    );
    assert_eq!(
        git(repo.path(), &["ls-files", "--stage", "--", "main.rs"]).stdout,
        index_before.stdout
    );
    assert_eq!(
        git(repo.path(), &["status", "--porcelain", "--", "main.rs"]).stdout,
        status_before.stdout
    );
}

fn git(repo: &Path, args: &[&str]) -> Output {
    let home = repo.join("test-home");
    let xdg_config_home = repo.join("test-xdg");
    fs::create_dir_all(&home).expect("test HOME creates");
    fs::create_dir_all(&xdg_config_home).expect("test XDG config directory creates");
    let output = Command::new("git")
        .args(args)
        .current_dir(repo)
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", &xdg_config_home)
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .output()
        .expect("git is installed for this test");
    assert!(
        output.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    output
}
