//! Integration tests for `varde-docs concept set-field`.

mod common;

use common::{bin, temp_bundle};
use std::process::Command;

const DOC: &str = "---\ntype: decision\n---\n# Body\n";

mod set_field {
    use super::*;

    fn fixture(bundle: &std::path::Path) {
        std::fs::write(bundle.join("use-rust.md"), DOC).unwrap();
    }

    #[test]
    fn sets_status_deprecated_parity_with_old_deprecate() {
        let bundle = temp_bundle("set-field-status");
        fixture(&bundle);
        let old = okf_core::occ::version(DOC.as_bytes());

        let out = Command::new(bin())
            .args(["concept", "set-field", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("status")
            .arg("deprecated")
            .arg("--expected-version")
            .arg(&old)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let text = String::from_utf8_lossy(&out.stdout);
        assert!(
            text.contains(&format!("version {old} -> ")),
            "stdout: {text}"
        );
        let written = std::fs::read_to_string(bundle.join("use-rust.md")).unwrap();
        assert!(
            written.contains("status: deprecated"),
            "status must be set: {written}"
        );
    }

    #[test]
    fn sets_extension_field_unvalidated() {
        let bundle = temp_bundle("set-field-extension");
        fixture(&bundle);

        let out = Command::new(bin())
            .args(["concept", "set-field", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("recall_priority")
            .arg("high")
            .arg("--expected-version")
            .arg(okf_core::occ::version(DOC.as_bytes()))
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let written = std::fs::read_to_string(bundle.join("use-rust.md")).unwrap();
        assert!(
            written.contains("recall_priority: high"),
            "extension field passes through: {written}"
        );
    }

    #[test]
    fn rejects_bare_scalar_write_to_structured_field_and_leaves_file_unchanged() {
        let bundle = temp_bundle("set-field-reserved");
        fixture(&bundle);

        let out = Command::new(bin())
            .args(["concept", "set-field", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("sources")
            .arg("a-scalar")
            .arg("--expected-version")
            .arg(okf_core::occ::version(DOC.as_bytes()))
            .output()
            .unwrap();
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("structured"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC.as_bytes());
    }

    #[test]
    fn stale_version_is_conflict_and_file_unchanged() {
        let bundle = temp_bundle("set-field-conflict");
        fixture(&bundle);

        let out = Command::new(bin())
            .args(["concept", "set-field", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("status")
            .arg("deprecated")
            .arg("--expected-version")
            .arg("00000000")
            .output()
            .unwrap();
        assert!(!out.status.success());
        assert!(
            String::from_utf8_lossy(&out.stderr).contains("conflict"),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC.as_bytes());
    }

    #[test]
    fn json_flag_outputs_key_value_and_versions() {
        let bundle = temp_bundle("set-field-json");
        fixture(&bundle);

        let out = Command::new(bin())
            .args(["concept", "set-field", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .arg("status")
            .arg("draft")
            .arg("--expected-version")
            .arg(okf_core::occ::version(DOC.as_bytes()))
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());

        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed["slug"], "use-rust");
        assert_eq!(parsed["key"], "status");
        assert_eq!(parsed["value"], "draft");
        assert_eq!(parsed["old_version"], okf_core::occ::version(DOC.as_bytes()));
        assert_ne!(parsed["old_version"], parsed["new_version"]);
    }
}
