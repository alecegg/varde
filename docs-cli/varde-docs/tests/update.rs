//! Integration tests for `varde-docs concept update`.

mod common;

use common::{bin, temp_bundle, temp_inputs};
use std::process::Command;

const DOC: &str = "---\ntype: decision\n---\n# Body\n";
const DOC2: &str = "---\ntype: decision\n---\n# Body v2\n";
const DOC_NO_TYPE: &str = "---\ntitle: No type\n---\nbody\n";

mod update {
    use super::*;

    fn fixture(bundle: &std::path::Path) {
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
    }

    #[test]
    fn happy_path_overwrites_and_reports_new_version() {
        let bundle = temp_bundle("update-happy");
        let inputs = temp_inputs("update-happy");
        fixture(&bundle);
        let input = inputs.join("doc2.md");
        std::fs::write(&input, DOC2).unwrap();
        let old = okf_core::occ::version(DOC.as_bytes());

        let out = Command::new(bin())
            .args(["concept", "update", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--expected-version")
            .arg(&old)
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        let new = okf_core::occ::version(DOC2.as_bytes());
        assert!(text.contains(&format!("version {old} -> {new}")), "stdout: {text}");

        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC2.as_bytes());
    }

    #[test]
    fn stale_version_is_conflict_and_file_unchanged() {
        let bundle = temp_bundle("update-conflict");
        fixture(&bundle);

        let out = Command::new(bin())
            .args(["concept", "update", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--expected-version")
            .arg("deadbeef")
            .arg("--file")
            .arg(bundle.join("doc2.md"))
            .output()
            .unwrap();
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("conflict"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        // Byte-identical to before the call.
        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC.as_bytes());
    }

    #[test]
    fn cli_update_no_type_succeeds() {
        let bundle = temp_bundle("update-missing-type");
        let inputs = temp_inputs("update-missing-type");
        fixture(&bundle);
        let input = inputs.join("bad.md");
        std::fs::write(&input, DOC_NO_TYPE).unwrap();

        let out = Command::new(bin())
            .args(["concept", "update", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--expected-version")
            .arg(okf_core::occ::version(DOC.as_bytes()))
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC_NO_TYPE.as_bytes());
    }

    #[test]
    fn json_flag_outputs_old_and_new_versions() {
        let bundle = temp_bundle("update-json");
        let inputs = temp_inputs("update-json");
        fixture(&bundle);
        let input = inputs.join("doc2.md");
        std::fs::write(&input, DOC2).unwrap();

        let out = Command::new(bin())
            .args(["concept", "update", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("--expected-version")
            .arg(okf_core::occ::version(DOC.as_bytes()))
            .arg("--file")
            .arg(&input)
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());

        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed["slug"], "use-rust");
        assert_eq!(parsed["old_version"], okf_core::occ::version(DOC.as_bytes()));
        assert_eq!(parsed["new_version"], okf_core::occ::version(DOC2.as_bytes()));
        assert_ne!(parsed["old_version"], parsed["new_version"]);
    }

    #[test]
    fn traversal_slug_is_invalid_and_writes_nothing_outside_bundle() {
        let bundle = temp_bundle("update-escape");
        let outside = bundle.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        let input = outside.join("escape.md");

        let out = Command::new(bin())
            .args(["concept", "update", "--bundle"])
            .arg(&bundle)
            .arg("../outside/escape")
            .arg("--expected-version")
            .arg("00000000")
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(
            !out.status.success(),
            "traversal slug must not write outside the bundle"
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
