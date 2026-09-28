//! Integration tests for `varde-workflow concept list`.

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

    /// A hermetic HOME directory, unique to this test run.
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
        let parsed = common::json_data(&out.stdout);
        assert_eq!(parsed.as_array().unwrap().len(), 2);
        assert_eq!(parsed[0]["slug"], "apple");
        assert_eq!(parsed[0]["type"], "fruit");
        assert_eq!(parsed[1]["slug"], "zebra");
        assert_eq!(parsed[1]["type"], "animal");
    }

    #[test]
    fn json_listing_is_bounded_and_recoverable() {
        let bundle = temp_bundle("list-json-page");
        let home = empty_home("list-json-page-home");
        for index in 0..105 {
            std::fs::write(
                bundle.join(format!("concept-{index:03}.md")),
                b"---\ntype: reference\n---\n",
            )
            .unwrap();
        }

        let first = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .arg("--json")
            .output()
            .unwrap();
        assert!(first.status.success());
        let first: serde_json::Value = serde_json::from_slice(&first.stdout).unwrap();
        assert_eq!(first["data"].as_array().unwrap().len(), 100);
        assert_eq!(first["meta"]["pagination"]["total"], 105);
        assert_eq!(first["meta"]["pagination"]["truncated"], true);
        assert_eq!(first["meta"]["pagination"]["next_offset"], 100);

        let final_page = Command::new(bin())
            .env("HOME", &home)
            .args(["concept", "list", "--bundle"])
            .arg(&bundle)
            .args(["--json", "--offset", "100"])
            .output()
            .unwrap();
        assert!(final_page.status.success());
        let final_page: serde_json::Value = serde_json::from_slice(&final_page.stdout).unwrap();
        assert_eq!(final_page["data"].as_array().unwrap().len(), 5);
        assert_eq!(final_page["meta"]["pagination"]["truncated"], false);
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
        let parsed = common::json_data(&out.stdout);
        assert_eq!(parsed.as_array().unwrap().len(), 1);
        assert_eq!(parsed[0]["slug"], "doc");
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

    /// Without `--bundle`, `concept list` defaults to the project's
    /// resolved `<knowledge>` directory — the same resolution
    /// `varde-workflow paths` reports — even when run from a subdirectory.
    #[test]
    fn default_bundle_resolves_to_knowledge_dir_without_bundle_flag() {
        let repo = temp_bundle("list-default-bundle-repo");
        let knowledge = repo.join("memory-bank").join("knowledge");
        std::fs::create_dir_all(&knowledge).unwrap();
        std::fs::write(
            knowledge.join("doc.md"),
            b"---\ntype: decision\n---\n# doc\n",
        )
        .unwrap();
        let src = repo.join("src");
        std::fs::create_dir_all(&src).unwrap();
        let config_dir = temp_inputs("list-default-bundle-config");

        let out = Command::new(bin())
            .current_dir(&src)
            .env("VARDE_CONFIG_DIR", &config_dir)
            .env_remove("VARDE_WORKING_DIR")
            .env_remove("VARDE_KNOWLEDGE_DIR")
            .args(["concept", "list", "--json"])
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        let data = parsed["data"].as_array().unwrap();
        assert_eq!(
            data.len(),
            1,
            "stdout: {}",
            String::from_utf8_lossy(&out.stdout)
        );
        assert_eq!(data[0]["slug"], "doc");
    }
}
