//! Integration tests for `varde-workflow concept delete`.

mod common;

use common::{bin, temp_bundle};
use std::process::Command;

mod delete {
    use super::*;

    #[test]
    fn existing_slug_is_hard_deleted() {
        let bundle = temp_bundle("delete-existing");
        std::fs::write(bundle.join("doc.md"), b"---\ntype: decision\n---\n").unwrap();

        let out = Command::new(bin())
            .args(["concept", "delete", "--bundle"])
            .arg(&bundle)
            .arg("doc")
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(!bundle.join("doc.md").exists());
        assert!(
            String::from_utf8_lossy(&out.stdout).contains("deleted doc"),
            "stdout: {}",
            String::from_utf8_lossy(&out.stdout)
        );
    }

    #[test]
    fn missing_slug_is_not_found_and_exits_nonzero() {
        let bundle = temp_bundle("delete-missing");
        let out = Command::new(bin())
            .args(["concept", "delete", "--bundle"])
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
    fn json_flag_confirms_deleted_slug() {
        let bundle = temp_bundle("delete-json");
        std::fs::write(bundle.join("doc.md"), b"---\ntype: decision\n---\n").unwrap();

        let out = Command::new(bin())
            .args(["concept", "delete", "--bundle"])
            .arg(&bundle)
            .arg("doc")
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());
        let parsed = common::json_data(&out.stdout);
        assert_eq!(parsed["slug"], "doc");
        assert_eq!(parsed["deleted"], true);
        assert!(!bundle.join("doc.md").exists());
    }

    #[test]
    fn traversal_slug_is_invalid_and_deletes_nothing_outside_bundle() {
        let bundle = temp_bundle("delete-escape");
        let outside = bundle.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();

        let out = Command::new(bin())
            .args(["concept", "delete", "--bundle"])
            .arg(&bundle)
            .arg("../outside/escape")
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "traversal slug must not delete outside the bundle"
        );
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("invalid slug"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert_eq!(
            std::fs::read(&sentinel).unwrap(),
            b"sentinel",
            "file outside the bundle must be untouched"
        );
    }
}
