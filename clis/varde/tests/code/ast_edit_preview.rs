use std::fs;
use std::path::{Path, PathBuf};

use tempfile::TempDir;
use varde_code::ast_edit::{PreviewOptions, RewriteRule, preview};

fn tempdir() -> TempDir {
    tempfile::Builder::new()
        .prefix("varde-ast-edit-preview-")
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

fn run_preview(
    repo: &Path,
    cwd: &Path,
    paths: &[PathBuf],
    store: &Path,
    rules: Vec<RewriteRule>,
) -> varde_code::ast_edit::PreviewResult {
    preview(&PreviewOptions {
        repository_root: repo.to_path_buf(),
        invoking_cwd: cwd.to_path_buf(),
        paths: paths.to_vec(),
        store_dir: store.to_path_buf(),
        rules,
    })
    .expect("preview completes")
}

#[test]
fn writes_exact_read_only_proposal_and_unified_diff() {
    let repo = tempdir();
    let store = tempdir();
    let source = "function run() { logger.old( 1 ); }\n";
    fs::write(repo.path().join("main.ts"), source).unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![rule(
            "rename",
            "typescript",
            "logger.old($ARG)",
            "logger.new( $ARG )",
        )],
    );

    assert!(result.complete, "{:?}", result.diagnostics);
    assert!(result.applicable);
    let proposal = result.proposal.as_ref().expect("proposal exists");
    assert_eq!(proposal.files.len(), 1);
    assert_eq!(proposal.files[0].original_content, source);
    assert_eq!(
        proposal.files[0].replacement_content,
        "function run() { logger.new( 1 ); }\n"
    );
    assert_eq!(proposal.files[0].match_spans.len(), 1);
    assert!(
        result
            .diff
            .as_deref()
            .unwrap()
            .contains("-function run() { logger.old( 1 ); }")
    );
    assert!(
        result
            .diff
            .as_deref()
            .unwrap()
            .contains("+function run() { logger.new( 1 ); }")
    );
    assert_eq!(
        fs::read_to_string(repo.path().join("main.ts")).unwrap(),
        source
    );
    let proposal_path = result.proposal_path.as_ref().unwrap();
    let diff_path = result.diff_path.as_ref().unwrap();
    assert!(proposal_path.starts_with(store.path()));
    assert!(diff_path.starts_with(store.path()));
    assert_eq!(
        fs::read_to_string(proposal_path).unwrap(),
        result.proposal_json.unwrap()
    );
    assert_eq!(fs::read_to_string(diff_path).unwrap(), result.diff.unwrap());
}

#[cfg(unix)]
#[test]
fn proposal_store_and_artifacts_are_owner_only() {
    use std::os::unix::fs::PermissionsExt;

    let repo = tempdir();
    let root = tempdir();
    let store = root.path().join("proposals");
    fs::write(repo.path().join("main.ts"), "oldCall();\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        &store,
        vec![rule("rename", "typescript", "oldCall()", "newCall()")],
    );

    assert!(result.applicable, "{:?}", result.diagnostics);
    assert_eq!(
        fs::metadata(&store).unwrap().permissions().mode() & 0o777,
        0o700
    );
    for path in [
        result.proposal_path.as_ref().unwrap(),
        result.diff_path.as_ref().unwrap(),
    ] {
        assert_eq!(
            fs::metadata(path).unwrap().permissions().mode() & 0o777,
            0o600,
            "{}",
            path.display()
        );
    }
}

#[test]
fn cwd_relative_scopes_and_rule_order_produce_the_same_proposal() {
    let repo = tempdir();
    let store_a = tempdir();
    let store_b = tempdir();
    let cwd = repo.path().join("work");
    fs::create_dir_all(cwd.join("src")).unwrap();
    fs::write(cwd.join("src/main.ts"), "oldCall(1);\n").unwrap();
    fs::write(cwd.join("src/main.py"), "old_call(1)\n").unwrap();
    let rules = vec![
        rule("ts-rule", "typescript", "oldCall($ARG)", "newCall($ARG)"),
        rule("py-rule", "python", "old_call($ARG)", "new_call($ARG)"),
    ];

    let first = run_preview(
        repo.path(),
        &cwd,
        &[PathBuf::from("src")],
        store_a.path(),
        rules.clone(),
    );
    let reversed = run_preview(
        repo.path(),
        &cwd,
        &[PathBuf::from("src")],
        store_b.path(),
        rules.into_iter().rev().collect(),
    );

    assert!(first.applicable, "{:?}", first.diagnostics);
    assert!(reversed.applicable, "{:?}", reversed.diagnostics);
    assert_eq!(
        first.proposal.as_ref().unwrap().id,
        reversed.proposal.as_ref().unwrap().id
    );
    assert_eq!(first.proposal_json, reversed.proposal_json);
    assert_eq!(first.diff, reversed.diff);
    assert_eq!(
        first
            .proposal
            .as_ref()
            .unwrap()
            .files
            .iter()
            .map(|file| file.path.as_str())
            .collect::<Vec<_>>(),
        vec!["work/src/main.py", "work/src/main.ts"]
    );
}

#[test]
fn duplicate_span_replacements_deduplicate_with_rule_provenance() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![
            rule("first", "typescript", "oldCall($ARG)", "newCall($ARG)"),
            rule("second", "typescript", "oldCall($ARG)", "newCall($ARG)"),
        ],
    );

    assert!(result.applicable, "{:?}", result.diagnostics);
    let edit = &result.proposal.as_ref().unwrap().files[0].match_spans[0];
    assert_eq!(edit.rule_ids, vec!["first", "second"]);
    assert_eq!(
        result.proposal.as_ref().unwrap().files[0].replacement_count,
        1
    );
}

#[test]
fn conflicting_or_overlapping_edits_return_diagnostics_without_a_proposal() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![
            rule("first", "typescript", "oldCall($ARG)", "newCall($ARG)"),
            rule("second", "typescript", "oldCall($ARG)", "otherCall($ARG)"),
        ],
    );

    assert!(!result.complete);
    assert!(!result.applicable);
    assert!(result.proposal.is_none());
    assert!(result.proposal_path.is_none());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "overlapping_edits" && diagnostic.rule_ids == vec!["first", "second"]
    }));
    assert_eq!(
        fs::read_to_string(repo.path().join("main.ts")).unwrap(),
        "oldCall(1);\n"
    );
    assert_eq!(fs::read_dir(store.path()).unwrap().count(), 0);
}

#[test]
fn nested_spans_from_different_rules_are_rejected_with_provenance() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![
            rule("outer", "typescript", "oldCall($ARG)", "newCall($ARG)"),
            rule("inner", "typescript", "1", "2"),
        ],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "overlapping_edits"
            && diagnostic.rule_ids == vec!["inner", "outer"]
            && diagnostic.start_byte == Some(0)
    }));
}

#[test]
fn relative_scope_escaping_root_is_rejected() {
    let parent = tempdir();
    let repo = parent.path().join("repo");
    let cwd = repo.join("nested/work");
    let store = tempdir();
    fs::create_dir_all(&cwd).unwrap();
    fs::write(parent.path().join("outside.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        &repo,
        &cwd,
        &[PathBuf::from("../../../outside.ts")],
        store.path(),
        vec![rule(
            "rename",
            "typescript",
            "oldCall($ARG)",
            "newCall($ARG)",
        )],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "unsafe_path")
    );
}

#[cfg(unix)]
#[test]
fn symlinked_directory_and_symlinked_file_are_rejected() {
    use std::os::unix::fs::symlink;

    let parent = tempdir();
    let repo = parent.path().join("repo");
    let store = tempdir();
    let outside = parent.path().join("outside");
    fs::create_dir_all(&repo).unwrap();
    fs::create_dir_all(&outside).unwrap();
    fs::write(outside.join("main.ts"), "oldCall(1);\n").unwrap();
    symlink(&outside, repo.join("linked-dir")).unwrap();
    symlink(outside.join("main.ts"), repo.join("linked-file.ts")).unwrap();
    let rewrite = rule("rename", "typescript", "oldCall($ARG)", "newCall($ARG)");

    for scope in ["linked-dir", "linked-file.ts"] {
        let result = run_preview(
            &repo,
            &repo,
            &[PathBuf::from(scope)],
            store.path(),
            vec![rewrite.clone()],
        );
        assert!(!result.complete, "{scope}: {:?}", result.diagnostics);
        assert!(result.proposal.is_none());
        assert!(
            result
                .diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "unsafe_path")
        );
    }

    let walked = run_preview(
        &repo,
        &repo,
        &[PathBuf::from(".")],
        store.path(),
        vec![rewrite],
    );
    assert!(!walked.complete, "{:?}", walked.diagnostics);
    assert!(walked.proposal.is_none());
    assert!(
        walked
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "unsafe_path")
    );
}

#[test]
fn invalid_utf8_source_is_reported_and_blocks_a_proposal() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();
    fs::write(repo.path().join("broken.ts"), [0xff, 0xfe]).unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from(".")],
        store.path(),
        vec![rule(
            "rename",
            "typescript",
            "oldCall($ARG)",
            "newCall($ARG)",
        )],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "unreadable_file" && diagnostic.path.as_deref() == Some("broken.ts")
    }));
}

#[test]
fn preexisting_parse_errors_may_remain_but_a_rewrite_cannot_add_more() {
    let repo = tempdir();
    let store = tempdir();
    let source = "const = 1;\noldCall(1);\n";
    fs::write(repo.path().join("main.ts"), source).unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![rule(
            "rename",
            "typescript",
            "oldCall($ARG)",
            "newCall($ARG)",
        )],
    );

    assert!(result.applicable, "{:?}", result.diagnostics);
    assert_eq!(
        result.proposal.as_ref().unwrap().files[0].original_error_nodes,
        result.proposal.as_ref().unwrap().files[0].replacement_error_nodes
    );
    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "preexisting_syntax_errors")
    );
}

#[test]
fn invalid_capture_template_is_reported_without_persisting_a_proposal() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![rule(
            "bad",
            "typescript",
            "oldCall($ARG)",
            "newCall($UNKNOWN)",
        )],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(
        result
            .diagnostics
            .iter()
            .any(|diagnostic| diagnostic.code == "invalid_rewrite_template")
    );
    assert_eq!(fs::read_dir(store.path()).unwrap().count(), 0);
}

#[test]
fn invalid_replacement_syntax_is_rejected_by_error_node_comparison() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![rule(
            "invalid-syntax",
            "typescript",
            "oldCall($ARG)",
            "const =",
        )],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.code == "rewrite_added_syntax_errors"
            && diagnostic.rule_ids == vec!["invalid-syntax"]
    }));
}

#[test]
fn unsupported_rule_language_is_reported_without_falling_back_to_extraction_languages() {
    let repo = tempdir();
    let store = tempdir();
    fs::write(repo.path().join("main.ts"), "oldCall(1);\n").unwrap();

    let result = run_preview(
        repo.path(),
        repo.path(),
        &[PathBuf::from("main.ts")],
        store.path(),
        vec![rule(
            "unknown-language",
            "language-not-linked",
            "oldCall($ARG)",
            "newCall($ARG)",
        )],
    );

    assert!(!result.complete);
    assert!(result.proposal.is_none());
    assert!(result.diagnostics.iter().any(|diagnostic| {
        diagnostic.rule_ids == vec!["unknown-language"]
            && diagnostic.message.contains("unsupported language")
    }));
    assert_eq!(fs::read_dir(store.path()).unwrap().count(), 0);
}

#[test]
fn unconfigured_working_store_writes_proposals_under_config_root() {
    let root = tempdir();
    let repo = root.path().join("repo");
    let home = root.path().join("home");
    let config = root.path().join("config");
    for directory in [&repo, &home, &config] {
        fs::create_dir_all(directory).unwrap();
    }
    let git = std::process::Command::new("git")
        .args(["init", "--quiet"])
        .current_dir(&repo)
        .env("HOME", &home)
        .output()
        .expect("git is installed");
    assert!(git.status.success());
    fs::write(repo.join("main.ts"), "const value = oldCall(1);\n").unwrap();

    let output = std::process::Command::new(env!("CARGO_BIN_EXE_varde"))
        .args([
            "edit",
            "preview",
            "--language",
            "typescript",
            "--pattern",
            "oldCall($ARG)",
            "--replacement",
            "newCall($ARG)",
            "--path",
            "main.ts",
            "--json",
        ])
        .current_dir(&repo)
        .env("HOME", &home)
        .env("XDG_CONFIG_HOME", root.path().join("xdg"))
        .env("VARDE_CONFIG_DIR", &config)
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE")
        .output()
        .expect("varde binary runs");
    assert!(
        output.status.success(),
        "{}{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let store = config.join("ast-edit");
    assert!(store.is_dir(), "proposal store missing under config root");
    assert!(fs::read_dir(&store).unwrap().count() > 0);
    assert!(!repo.join("memory-bank").exists());
    let mut repo_entries: Vec<_> = fs::read_dir(&repo)
        .unwrap()
        .map(|entry| entry.unwrap().file_name())
        .collect();
    repo_entries.sort();
    assert_eq!(repo_entries, [".git", "main.ts"]);
}
