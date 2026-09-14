//! Integration tests for `varde-docs concept list`.

mod common;

use common::{bin, temp_bundle, temp_inputs};
use std::path::PathBuf;
use std::process::Command;

fn write_fixtures(bundle: &std::path::Path) {
    std::fs::write(bundle.join("apple.md"), b"---\ntype: fruit\n---\na\n").unwrap();
    std::fs::write(bundle.join("zebra.md"), b"---\ntype: animal\n---\nz\n").unwrap();
    std::fs::write(bundle.join("notes.txt"), b"not a concept").unwrap();
    std::fs::write(bundle.join("index.md"), b"# index").unwrap();
}

mod list {
    use super::*;

    /// A HOME directory with no Personal Vault — keeps tests hermetic now
    /// that `concept list` merges in `$HOME/.varde-docs/`.
    fn empty_home(tag: &str) -> PathBuf {
        temp_inputs(tag)
    }

    #[test]
    fn text_mode_lists_exactly_the_concepts_with_slug_and_type() {
        let bundle = temp_bundle("list-text");
        write_fixtures(&bundle);
        let home = empty_home("list-text-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2, "stdout: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("apple\tfruit")),
            "stdout: {text}"
        );
        assert!(
            lines.iter().any(|l| l.starts_with("zebra\tanimal")),
            "stdout: {text}"
        );
    }

    #[test]
    fn empty_bundle_exits_zero_and_indicates_zero() {
        let bundle = temp_bundle("list-empty");
        let home = empty_home("list-empty-home");
        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stdout).contains("no concepts"),
            "stdout: {}",
            String::from_utf8_lossy(&out.stdout)
        );
    }

    #[test]
    fn json_flag_outputs_array_of_slug_type_objects() {
        let bundle = temp_bundle("list-json");
        write_fixtures(&bundle);
        let home = empty_home("list-json-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed.as_array().unwrap().len(), 2);
        assert_eq!(parsed[0]["slug"], "apple");
        assert_eq!(parsed[0]["type"], "fruit");
        assert_eq!(parsed[1]["slug"], "zebra");
        assert_eq!(parsed[1]["type"], "animal");
    }

    #[test]
    fn non_md_files_are_excluded() {
        let bundle = temp_bundle("list-nonmd");
        std::fs::write(bundle.join("doc.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(bundle.join("notes.txt"), b"not a concept").unwrap();
        let home = empty_home("list-nonmd-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed.as_array().unwrap().len(), 1);
        assert_eq!(parsed[0]["slug"], "doc");
    }

    #[test]
    fn list_merges_personal_vault_from_home() {
        let bundle = temp_bundle("list-merge-personal");
        write_fixtures(&bundle);
        let home = temp_inputs("list-merge-home");
        std::fs::create_dir_all(home.join(".varde-docs")).unwrap();
        std::fs::write(
            home.join(".varde-docs/fig.md"),
            b"---\ntype: fruit\n---\nf\n",
        )
        .unwrap();

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 3, "stdout: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("apple\tfruit")),
            "stdout: {text}"
        );
        assert!(
            lines.iter().any(|l| l.starts_with("fig\tfruit")),
            "stdout: {text}"
        );
        assert!(
            lines.iter().any(|l| l.starts_with("zebra\tanimal")),
            "stdout: {text}"
        );
    }

    #[test]
    fn default_excludes_deprecated_concepts() {
        let bundle = temp_bundle("list-deprecated-default");
        std::fs::write(bundle.join("live.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(
            bundle.join("dead.md"),
            b"---\ntype: decision\nstatus: deprecated\n---\n",
        )
        .unwrap();
        let home = empty_home("list-deprecated-default-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 1, "stdout: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("live	decision")),
            "stdout: {text}"
        );
        assert!(
            !text.contains("dead"),
            "deprecated must be hidden by default: {text}"
        );
    }

    #[test]
    fn include_deprecated_flag_surfaces_deprecated_concepts() {
        let bundle = temp_bundle("list-deprecated-included");
        std::fs::write(bundle.join("live.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(
            bundle.join("dead.md"),
            b"---\ntype: decision\nstatus: deprecated\n---\n",
        )
        .unwrap();
        let home = empty_home("list-deprecated-included-home");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--include-deprecated", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2, "stdout: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("live	decision")),
            "stdout: {text}"
        );
        assert!(
            lines.iter().any(|l| l.starts_with("dead	decision")),
            "stdout: {text}"
        );
    }

    /// A HOME whose Personal Vault holds one concept.
    fn home_with_personal_vault(tag: &str, slug: &str, type_: &str) -> PathBuf {
        let home = temp_inputs(tag);
        let vault = home.join(".varde-docs");
        std::fs::create_dir_all(&vault).unwrap();
        std::fs::write(
            vault.join(format!("{slug}.md")),
            format!("---\ntype: {type_}\n---\n# {slug}\n"),
        )
        .unwrap();
        home
    }

    #[test]
    fn default_merge_preserved_with_bundle_only() {
        let bundle = temp_bundle("list-merge-default");
        std::fs::write(bundle.join("apple.md"), b"---\ntype: fruit\n---\n").unwrap();
        let home = home_with_personal_vault("list-merge-default-home", "fig", "fruit");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 2, "both vaults merged: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("apple\tfruit")),
            "{text}"
        );
        assert!(lines.iter().any(|l| l.starts_with("fig\tfruit")), "{text}");
    }

    #[test]
    fn vault_personal_narrows_to_personal_only() {
        let bundle = temp_bundle("list-personal-only");
        std::fs::write(bundle.join("apple.md"), b"---\ntype: fruit\n---\n").unwrap();
        let home = home_with_personal_vault("list-personal-only-home", "fig", "fruit");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .arg("--vault")
            .arg("personal")
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 1, "only the Personal Vault: {text}");
        assert!(lines.iter().any(|l| l.starts_with("fig\tfruit")), "{text}");
        assert!(!text.contains("apple"), "{text}");
    }

    #[test]
    fn vault_project_scopes_to_project_bundle() {
        let bundle = temp_bundle("list-project-only");
        std::fs::write(bundle.join("apple.md"), b"---\ntype: fruit\n---\n").unwrap();
        let home = home_with_personal_vault("list-project-only-home", "fig", "fruit");

        let out = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--vault", "project", "--bundle"])
            .arg(&bundle)
            .output()
            .unwrap();
        assert!(out.status.success());
        let text = String::from_utf8_lossy(&out.stdout);
        let lines: Vec<&str> = text.lines().collect();
        assert_eq!(lines.len(), 1, "only the Project Vault: {text}");
        assert!(
            lines.iter().any(|l| l.starts_with("apple\tfruit")),
            "{text}"
        );
        assert!(!text.contains("fig"), "{text}");
    }
}
