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

/// Run `lint` with a hermetic HOME (no Personal Vault interference).
fn lint_cmd() -> Command {
    let mut cmd = Command::new(bin());
    cmd.env("HOME", temp_inputs("lint-home-pin"));
    cmd
}

/// A HOME with a Personal Vault holding one concept document.
fn home_with_personal_vault(tag: &str, content: &str) -> PathBuf {
    let home = temp_inputs(tag);
    let vault = home.join(".varde-workflow");
    std::fs::create_dir_all(&vault).unwrap();
    std::fs::write(vault.join("personal.md"), content).unwrap();
    home
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
            .args(["lint", "--bundle", "/nonexistent/okf-lint-cli-missing"])
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
        // No index.md -> MissingIndex (Warning) at the root.

        let text = Command::new(bin())
            .args(["lint", "--bundle"])
            .arg(&bundle)
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

    #[test]
    fn default_merges_personal_vault_issues() {
        let bundle = temp_bundle("lint-merge-personal");
        // Clean project concept (only a MissingIndex warning at the root).
        write(&bundle, "ok.md", &concept("fine\n"));
        // Personal Vault carries the Error-severity issue.
        let home =
            home_with_personal_vault("lint-merge-personal-home", &concept("[b](missing.md)\n"));

        let out = lint_cmd()
            .env("HOME", &home)
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "personal-vault Error issue must fail the merged default run"
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(
            text.contains("missing.md"),
            "personal-vault issue must be reported: {text}"
        );
    }

    #[test]
    fn vault_project_excludes_personal_vault() {
        let bundle = temp_bundle("lint-project-only");
        // Project: warnings-only (missing index, no broken links, no
        // orphans — the two concepts link to each other).
        write(&bundle, "a.md", &concept("[b](b.md)\n"));
        write(&bundle, "b.md", &concept("[a](a.md)\n"));
        // Personal Vault has an Error-severity issue that must NOT surface.
        let home =
            home_with_personal_vault("lint-project-only-home", &concept("[b](missing.md)\n"));

        let out = lint_cmd()
            .env("HOME", &home)
            .args(["lint", "--vault", "project", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "vault project must not scan the Personal Vault; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(
            !text.contains("missing.md"),
            "personal issue must be absent: {text}"
        );
    }

    #[test]
    fn vault_personal_json_scopes_to_personal() {
        let home =
            home_with_personal_vault("lint-personal-json-home", &concept("[b](missing.md)\n"));

        let out = lint_cmd()
            .env("HOME", &home)
            .args(["lint", "--json", "--vault", "personal"])
            .output()
            .unwrap();
        assert!(!out.status.success());
        let parsed: serde_json::Value =
            serde_json::from_slice(&out.stdout).expect("stdout must be a JSON array");
        let issues = parsed["data"]["error"]["details"]
            .as_array()
            .expect("JSON array of issues");
        assert!(
            issues
                .iter()
                .any(|i| i["message"].as_str().unwrap_or("").contains("missing.md")),
            "issues: {issues:?}"
        );
    }

    /// A concept with frontmatter but no `type` field — an OKF-only
    /// violation (`OkfMissingType`), invisible to the default structural
    /// checks.
    fn bundle_with_okf_only_violation(tag: &str) -> PathBuf {
        let bundle = temp_bundle(tag);
        write(&bundle, "index.md", "# index");
        write(&bundle, "a.md", "---\nstatus: draft\n---\nSee [b](b.md).\n");
        // Links to `a.md` so the default OrphanedConcept check stays clean;
        // only the OKF-mode missing-`type` check should flag `a.md`.
        write(&bundle, "b.md", &concept("See [a](a.md).\n"));
        bundle
    }

    #[test]
    fn cli_lint_okf_flag_reports_violation() {
        let bundle = bundle_with_okf_only_violation("lint-cli-okf-flag-on");
        let out = lint_cmd()
            .args(["lint", "--okf", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            stdout.contains("missing the required `type` field"),
            "stdout: {stdout}"
        );
    }

    #[test]
    fn cli_lint_default_skips_okf_checks() {
        let bundle = bundle_with_okf_only_violation("lint-cli-okf-flag-off");
        let out = lint_cmd()
            .args(["lint", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "an OKF-only violation must not fail the default run; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        assert!(
            !stdout.contains("missing the required `type` field"),
            "stdout: {stdout}"
        );
    }

    #[test]
    fn no_flags_defaults_to_cwd_merged_with_personal() {
        let bundle = temp_bundle("lint-cwd-default");
        // Project (cwd): warnings-only — the two concepts link each other.
        write(&bundle, "a.md", &concept("[b](b.md)\n"));
        write(&bundle, "b.md", &concept("[a](a.md)\n"));
        // Personal Vault carries the Error-severity issue.
        let home = home_with_personal_vault("lint-cwd-default-home", &concept("[x](missing.md)\n"));

        let out = Command::new(bin())
            .env("HOME", &home)
            .current_dir(&bundle)
            .arg("lint")
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "merged default must fail on the personal Error issue; stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(
            text.contains("missing.md"),
            "personal issue must be reported: {text}"
        );
    }
}
