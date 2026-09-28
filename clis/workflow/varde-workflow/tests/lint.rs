//! Integration tests for `varde-workflow lint`.

mod common;

use common::{bin, temp_bundle, temp_inputs};
use std::path::PathBuf;
use std::process::Command;

/// A valid Concept document: YAML frontmatter with a `type`, then a body.
fn concept(body: &str) -> String {
    format!("---\ntype: decision\n---\n{body}")
}

fn write(bundle: &std::path::Path, name: &str, content: &str) {
    std::fs::write(bundle.join(name), content).unwrap();
}

/// Run `lint` with a hermetic HOME.
fn lint_cmd() -> Command {
    let mut cmd = Command::new(bin());
    cmd.env("HOME", temp_inputs("lint-home-pin"));
    cmd
}

mod lint {
    use super::*;

    /// index.md at the root plus two Concepts linking each other, and a
    /// nested directory with its own index.md — no issues at all.
    fn clean_bundle(tag: &str) -> PathBuf {
        let bundle = temp_bundle(tag);
        write(&bundle, "index.md", "# index");
        write(&bundle, "a.md", &concept("See [b](b.md).\n"));
        write(
            &bundle,
            "b.md",
            &concept("See [a](a.md) and [c](sub/c.md).\n"),
        );
        let sub = bundle.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(&sub, "index.md", "# sub index");
        write(&sub, "c.md", &concept("See [b](../b.md).\n"));
        bundle
    }

    /// A broken bundle-internal link — an `Error`-severity issue.
    fn bundle_with_broken_link(tag: &str) -> PathBuf {
        let bundle = temp_bundle(tag);
        write(&bundle, "index.md", "# index");
        write(&bundle, "a.md", &concept("See [missing](/missing.md).\n"));
        write(&bundle, "b.md", &concept("See [a](a.md).\n"));
        bundle
    }

    /// Concepts but no `index.md` at the root — a `Warning`-severity issue
    /// and nothing else.
    fn bundle_with_missing_index(tag: &str) -> PathBuf {
        let bundle = temp_bundle(tag);
        write(&bundle, "a.md", &concept("See [b](b.md).\n"));
        write(&bundle, "b.md", &concept("See [a](a.md).\n"));
        bundle
    }

    #[test]
    fn clean_bundle_exits_zero_with_empty_output() {
        let bundle = clean_bundle("lint-cli-clean");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(stdout.is_empty(), "stdout: {stdout}");
    }

    #[test]
    fn json_lint_findings_are_bounded_and_recoverable() {
        let bundle = temp_bundle("lint-json-page");
        write(&bundle, "index.md", "# index");
        for index in 0..105 {
            write(
                &bundle,
                &format!("concept-{index:03}.md"),
                &concept(&format!("See [missing](missing-{index:03}.md).\n")),
            );
        }

        let first = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(!first.status.success());
        let first: serde_json::Value = serde_json::from_slice(&first.stdout).unwrap();
        assert_eq!(
            first["data"]["error"]["details"].as_array().unwrap().len(),
            100
        );
        assert_eq!(first["meta"]["pagination"]["truncated"], true);
        assert_eq!(first["meta"]["pagination"]["next_offset"], 100);

        let next = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .args(["--json", "--offset", "100"])
            .output()
            .unwrap();
        assert!(!next.status.success());
        let next: serde_json::Value = serde_json::from_slice(&next.stdout).unwrap();
        assert!(
            !next["data"]["error"]["details"]
                .as_array()
                .unwrap()
                .is_empty()
        );
        assert_eq!(next["meta"]["pagination"]["offset"], 100);
    }

    #[test]
    fn error_severity_issue_exits_nonzero_and_prints_to_stdout() {
        let bundle = bundle_with_broken_link("lint-cli-broken");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "an Error-severity issue must fail the run"
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            stdout.contains("broken bundle-internal link"),
            "stdout: {stdout}"
        );
    }

    #[test]
    fn warnings_only_exit_zero_and_print_to_stdout() {
        let bundle = bundle_with_missing_index("lint-cli-warning");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--require-index")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "warnings alone must not fail the run; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(stdout.contains("no `index.md`"), "stdout: {stdout}");
    }

    #[test]
    fn missing_index_is_not_reported_without_the_flag() {
        let bundle = bundle_with_missing_index("lint-cli-missing-index-off");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            stdout.is_empty(),
            "MissingIndex must not run without --require-index, got stdout: {stdout}"
        );
    }

    #[test]
    fn json_mode_prints_issue_array_with_typed_fields() {
        let bundle = bundle_with_broken_link("lint-cli-json");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "an Error-severity issue must exit non-zero even in --json mode"
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        let parsed: serde_json::Value =
            serde_json::from_str(&stdout).expect("stdout must parse as JSON");
        let arr = parsed["data"]["error"]["details"]
            .as_array()
            .expect("error details must be a JSON array");
        assert!(!arr.is_empty(), "stdout: {stdout}");
        for issue in arr {
            let obj = issue.as_object().expect("each element must be an object");
            for key in ["severity", "check_kind", "path", "message"] {
                assert!(obj.contains_key(key), "missing key {key} in {issue}");
            }
        }
    }

    #[test]
    fn missing_bundle_path_is_a_typed_error_on_stderr() {
        let out = lint_cmd()
            .args(["lint", "--bundle", "/nonexistent/lint-cli-missing"])
            .output()
            .unwrap();
        assert!(!out.status.success(), "a missing bundle path must fail");
        let stderr = String::from_utf8_lossy(&out.stderr);
        assert!(stderr.contains("error:"), "stderr: {stderr}");
        assert!(
            stderr.contains("failed to read bundle directory"),
            "stderr: {stderr}"
        );
        assert!(!stderr.contains("panic"), "stderr: {stderr}");
    }

    #[test]
    fn text_and_json_share_the_same_issue_order() {
        // Errors first, then Warnings — text lines must match the `--json`
        // array order exactly.
        let bundle = temp_bundle("lint-cli-order");
        write(
            &bundle,
            "a.md",
            &concept("See [b](b.md) and [gone](/gone.md).\n"),
        );
        write(&bundle, "b.md", &concept("See [a](a.md).\n"));
        // No index.md -> MissingIndex (Warning) at the root, with --require-index.

        let text = Command::new(bin())
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--require-index")
            .output()
            .unwrap();
        let stdout = String::from_utf8_lossy(&text.stdout);
        let lines: Vec<&str> = stdout.lines().collect();
        assert_eq!(lines.len(), 2, "stdout: {stdout}");
        assert!(
            lines[0].starts_with("error:"),
            "first line must be the Error, got: {stdout}"
        );
        assert!(
            lines[1].starts_with("warning:"),
            "second line must be the Warning, got: {stdout}"
        );

        let json = Command::new(bin())
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--require-index")
            .arg("--json")
            .output()
            .unwrap();
        let parsed: serde_json::Value = serde_json::from_slice(&json.stdout).unwrap();
        let arr = parsed["data"]["error"]["details"]
            .as_array()
            .expect("error details must be a JSON array");
        assert_eq!(arr.len(), 2, "json: {parsed}");
        assert_eq!(arr[0]["severity"], "error");
        assert_eq!(arr[1]["severity"], "warning");
    }

    #[test]
    fn non_concept_md_files_do_not_fail_the_run() {
        // README.md (frontmatter, no type) and a frontmatter-less file are
        // not Concepts — the run must stay clean.
        let bundle = temp_bundle("lint-cli-non-concepts");
        write(&bundle, "index.md", "# index");
        write(&bundle, "a.md", &concept("See [b](b.md).\n"));
        write(&bundle, "b.md", &concept("See [a](a.md).\n"));
        write(&bundle, "README.md", "---\nid: readme\n---\n# Notes\n");
        write(&bundle, "notes.md", "plain notes, no frontmatter");

        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "non-concept files must not fail the run; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(stdout.is_empty(), "stdout: {stdout}");
    }

    /// `specs/index.md` links to `specs/a.md`, `specs/b.md`, and
    /// `specs/sub/c.md`; the bundle root has no `.md` files directly (only
    /// the `specs/` directory), `specs/` has its own `index.md`, and
    /// `specs/sub/` has none.
    fn bundle_linked_only_from_index(tag: &str) -> PathBuf {
        let bundle = temp_bundle(tag);
        let specs = bundle.join("specs");
        std::fs::create_dir(&specs).unwrap();
        write(
            &specs,
            "index.md",
            "# specs\n\nSee [a](a.md), [b](b.md), and [c](sub/c.md).\n",
        );
        write(&specs, "a.md", &concept("No links.\n"));
        write(&specs, "b.md", &concept("No links.\n"));
        let sub = specs.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(&sub, "c.md", &concept("No links.\n"));
        bundle
    }

    #[test]
    fn index_md_links_satisfy_orphan_check_and_missing_index_is_off_by_default() {
        let bundle = bundle_linked_only_from_index("lint-cli-index-links");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        let issues = parsed["data"]
            .as_array()
            .expect("success envelope must carry an issues array");
        assert!(
            issues.is_empty(),
            "index.md links must count as incoming and MissingIndex must stay off by default, got {parsed}"
        );
    }

    #[test]
    fn require_index_reports_missing_index_for_folders_without_one() {
        let bundle = bundle_linked_only_from_index("lint-cli-index-links-required");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .args(["--require-index", "--json"])
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "MissingIndex is a Warning and must not fail the run; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        let issues = parsed["data"]
            .as_array()
            .expect("success envelope must carry an issues array");
        assert!(
            issues
                .iter()
                .any(|issue| issue["check_kind"] == "missing_index"
                    && issue["path"].as_str().unwrap().ends_with("sub")),
            "expected a missing_index issue for specs/sub, got {parsed}"
        );
        assert!(
            !issues
                .iter()
                .any(|issue| issue["check_kind"] == "orphaned_concept"),
            "index.md links must still satisfy the orphan check, got {parsed}"
        );
    }
}
