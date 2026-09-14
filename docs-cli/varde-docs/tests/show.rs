//! Integration tests for `varde-docs concept show`.

mod common;

use common::{bin, temp_bundle, temp_inputs};
use std::path::PathBuf;
use std::process::Command;

const DOC: &str = "---\ntype: decision\ntitle: Use Rust\n---\n# Body\n\nRust for the CLI.\n";

mod show {
    use super::*;

    /// A HOME directory with no Personal Vault — keeps tests hermetic now
    /// that `concept show` falls back to `$HOME/.varde-docs/`.
    fn empty_home(tag: &str) -> PathBuf {
        temp_inputs(tag)
    }

    /// A HOME directory whose `.varde-docs/` Personal Vault holds the
    /// given `slug` (with `DOC` content).
    fn home_with_personal_vault(tag: &str, slug: &str) -> PathBuf {
        let home = temp_inputs(tag);
        std::fs::create_dir_all(home.join(".varde-docs")).unwrap();
        std::fs::write(
            home.join(".varde-docs").join(format!("{slug}.md")),
            DOC,
        )
        .unwrap();
        home
    }

    #[test]
    fn existing_slug_prints_frontmatter_body_and_version() {
        let bundle = temp_bundle("show-existing");
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
        let home = empty_home("show-existing-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("type: decision"), "stdout: {text}");
        assert!(text.contains("# Body"), "stdout: {text}");
        assert!(text.contains("Rust for the CLI."), "stdout: {text}");
        let version = okf_core::occ::version(DOC.as_bytes());
        assert!(text.contains(&format!("version: {version}")), "stdout: {text}");
    }

    #[test]
    fn missing_slug_is_not_found_and_exits_nonzero() {
        let bundle = temp_bundle("show-missing");
        let home = empty_home("show-missing-home");
        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("nope")
            .output()
            .unwrap();
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("not found"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }

    #[test]
    fn json_flag_outputs_slug_version_frontmatter_and_body() {
        let bundle = temp_bundle("show-json");
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
        let home = empty_home("show-json-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());

        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed["slug"], "use-rust");
        assert_eq!(parsed["version"], okf_core::occ::version(DOC.as_bytes()));
        assert_eq!(parsed["frontmatter"]["type"], "decision");
        assert_eq!(parsed["body"], "# Body\n\nRust for the CLI.\n");
    }

    #[test]
    fn traversal_slug_is_invalid_and_reads_nothing_outside_bundle() {
        let bundle = temp_bundle("show-escape");
        let outside = bundle.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        let home = empty_home("show-escape-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("../outside/escape")
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "traversal slug must not read outside the bundle"
        );
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("invalid slug"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }

    #[test]
    fn frontmatter_only_outputs_json_without_body() {
        let bundle = temp_bundle("show-frontmatter-only");
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
        let home = empty_home("show-frontmatter-only-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--frontmatter-only")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let stdout = String::from_utf8_lossy(&out.stdout);
        let parsed: serde_json::Value = serde_json::from_str(&stdout).unwrap();
        assert_eq!(parsed["type"], "decision");
        assert_eq!(parsed["title"], "Use Rust");
        assert!(
            !stdout.contains("# Body") && !stdout.contains("Rust for the CLI."),
            "body text must be absent: {stdout}"
        );
        assert!(
            !stdout.contains("version"),
            "version must be absent: {stdout}"
        );
    }

    #[test]
    fn default_show_output_is_unchanged_without_the_flag() {
        let bundle = temp_bundle("show-default-unchanged");
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
        let home = empty_home("show-default-unchanged-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        // Frontmatter block, body, then version — the pre-existing shape.
        assert!(text.contains("type: decision"), "stdout: {text}");
        assert!(text.contains("# Body"), "stdout: {text}");
        assert!(text.contains("Rust for the CLI."), "stdout: {text}");
        let version = okf_core::occ::version(DOC.as_bytes());
        assert!(text.contains(&format!("version: {version}")), "stdout: {text}");
    }

    #[test]
    fn git_derived_timestamps_appear_in_json_and_text_without_frontmatter_keys() {
        let bundle = temp_bundle("show-timestamps");
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
        let home = empty_home("show-timestamps-home");
        // Commit twice with controlled dates so expectations are literals.
        let commit = |content: &str, msg: &str, date: &str| {
            std::fs::write(bundle.join("use-rust.md"), content).unwrap();
            let status = std::process::Command::new("git")
                .args(["-C"])
                .arg(&bundle)
                .args(["add", "use-rust.md"])
                .status()
                .unwrap();
            assert!(status.success());
            let status = std::process::Command::new("git")
                .arg("-C")
                .arg(&bundle)
                .env("GIT_COMMITTER_DATE", date)
                .env("GIT_AUTHOR_DATE", date)
                .args(["commit", "-qm", msg])
                .status()
                .unwrap();
            assert!(status.success());
        };
        for args in [
            vec!["init", "-q"],
            vec!["config", "user.email", "test@example.com"],
            vec!["config", "user.name", "test"],
        ] {
            let status = std::process::Command::new("git")
                .arg("-C")
                .arg(&bundle)
                .args(&args)
                .status()
                .unwrap();
            assert!(status.success());
        }
        // Two commits with different file content so the second one is not
        // a no-op "nothing to commit".
        commit(DOC, "c1", "2020-01-01T00:00:00Z");
        commit(
            "---\ntype: decision\ntitle: Use Rust\n---\n# Body\n\nRust v2.\n",
            "c2",
            "2021-06-15T12:30:45+02:00",
        );

        // JSON form: created/updated present, null-free, correct values.
        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed["created"], "2020-01-01T00:00:00Z");
        assert_eq!(parsed["updated"], "2021-06-15T12:30:45+02:00");

        // Text form: created/updated lines present.
        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .output()
            .unwrap();
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("created: 2020-01-01T00:00:00Z"), "stdout: {text}");
        assert!(text.contains("updated: 2021-06-15T12:30:45+02:00"), "stdout: {text}");

        // No frontmatter keys were written for the timestamps.
        let on_disk = std::fs::read_to_string(bundle.join("use-rust.md")).unwrap();
        assert!(
            !on_disk.contains("created") && !on_disk.contains("updated"),
            "timestamps must never be written to frontmatter: {on_disk}"
        );
    }

    #[test]
    fn personal_vault_fallback_show_still_gets_git_timestamps() {
        // A Concept served from the Personal Vault must compute its
        // timestamps against the Personal Vault's git history, not the
        // project bundle's (regression: fallback shows used to always
        // report None/None).
        let bundle = temp_bundle("show-personal-timestamps-project");
        // The project bundle is a git repo whose history must be ignored:
        // a `created.md` slug lives only in the Personal Vault.
        for args in [
            vec!["init", "-q"],
            vec!["config", "user.email", "test@example.com"],
            vec!["config", "user.name", "test"],
        ] {
            let status = std::process::Command::new("git")
                .arg("-C")
                .arg(&bundle)
                .args(&args)
                .status()
                .unwrap();
            assert!(status.success());
        }
        std::fs::write(bundle.join("unrelated.md"), DOC).unwrap();
        let status = std::process::Command::new("git")
            .args(["-C"])
            .arg(&bundle)
            .args(["add", "unrelated.md"])
            .status()
            .unwrap();
        assert!(status.success());
        let status = std::process::Command::new("git")
            .arg("-C")
            .arg(&bundle)
            .env("GIT_COMMITTER_DATE", "2019-01-01T00:00:00Z")
            .env("GIT_AUTHOR_DATE", "2019-01-01T00:00:00Z")
            .args(["commit", "-qm", "unrelated"])
            .status()
            .unwrap();
        assert!(status.success());

        // Personal Vault with its own git history for the fallback slug.
        let home = temp_inputs("show-personal-timestamps-home");
        let personal = home.join(".varde-docs");
        std::fs::create_dir_all(&personal).unwrap();
        for args in [
            vec!["init", "-q"],
            vec!["config", "user.email", "test@example.com"],
            vec!["config", "user.name", "test"],
        ] {
            let status = std::process::Command::new("git")
                .arg("-C")
                .arg(&personal)
                .args(&args)
                .status()
                .unwrap();
            assert!(status.success());
        }
        std::fs::write(personal.join("created.md"), DOC).unwrap();
        let status = std::process::Command::new("git")
            .args(["-C"])
            .arg(&personal)
            .args(["add", "created.md"])
            .status()
            .unwrap();
        assert!(status.success());
        let status = std::process::Command::new("git")
            .arg("-C")
            .arg(&personal)
            .env("GIT_COMMITTER_DATE", "2020-01-01T00:00:00Z")
            .env("GIT_AUTHOR_DATE", "2020-01-01T00:00:00Z")
            .args(["commit", "-qm", "create"])
            .status()
            .unwrap();
        assert!(status.success());

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("created")
            .arg("--json")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(
            parsed["created"], "2020-01-01T00:00:00Z",
            "fallback show must read the Personal Vault's history: {parsed}"
        );
        assert_eq!(parsed["updated"], "2020-01-01T00:00:00Z");
    }

    #[test]
    fn show_falls_back_to_personal_vault_from_home() {
        let bundle = temp_bundle("show-merge-personal");
        let home = home_with_personal_vault("show-merge-home", "only-personal");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("only-personal")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("type: decision"), "stdout: {text}");
        assert!(text.contains("Rust for the CLI."), "stdout: {text}");
        let version = okf_core::occ::version(DOC.as_bytes());
        assert!(
            text.contains(&format!("version: {version}")),
            "stdout: {text}"
        );
    }

    #[test]
    fn show_project_wins_over_personal_vault_collision() {
        let bundle = temp_bundle("show-merge-collision");
        std::fs::write(bundle.join("both.md"), DOC).unwrap();
        let home = temp_inputs("show-merge-collision-home");
        std::fs::create_dir_all(home.join(".varde-docs")).unwrap();
        std::fs::write(
            home.join(".varde-docs/both.md"),
            b"---\ntype: personal\n---\npersonal body\n",
        )
        .unwrap();

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("both")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(text.contains("type: decision"), "stdout: {text}");
        assert!(!text.contains("personal body"), "stdout: {text}");
    }

    #[test]
    fn show_not_found_in_either_vault_exits_nonzero() {
        let bundle = temp_bundle("show-merge-neither");
        let home = temp_inputs("show-merge-neither-home");
        std::fs::create_dir_all(home.join(".varde-docs")).unwrap();

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "show", "--bundle"])
            .arg(&bundle)
            .arg("nope")
            .output()
            .unwrap();
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("not found"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
    }
}
