//! Integration tests for `varde-docs concept create`.

mod common;

use common::{bin, temp_bundle, temp_inputs};
use std::io::Write;
use std::process::{Command, Stdio};

const DOC: &str = "---\ntype: decision\ntitle: Use Rust\n---\n# Body\n\nRust for the CLI.\n";
const DOC_NO_TYPE: &str = "---\ntitle: No type\n---\n# Body\n";

mod create {
    use super::*;

    #[test]
    fn via_file_writes_bytes_to_slug_file() {
        let bundle = temp_bundle("create-file");
        let inputs = temp_inputs("create-file");
        let input = inputs.join("use-rust.md");
        std::fs::write(&input, DOC).unwrap();

        let out = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
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
        assert_eq!(written, DOC.as_bytes());
    }

    #[test]
    fn via_stdin_writes_identical_bytes_and_exit_code() {
        let bundle = temp_bundle("create-stdin");
        let mut child = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
            .arg("use-rust")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        child
            .stdin
            .as_mut()
            .unwrap()
            .write_all(DOC.as_bytes())
            .unwrap();
        let out = child.wait_with_output().unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );

        let written = std::fs::read(bundle.join("use-rust.md")).unwrap();
        assert_eq!(written, DOC.as_bytes());
    }

    #[test]
    fn cli_create_no_type_succeeds() {
        let bundle = temp_bundle("create-missing-type");
        let inputs = temp_inputs("create-missing-type");
        let input = inputs.join("no-type.md");
        std::fs::write(&input, DOC_NO_TYPE).unwrap();

        let out = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(
            out.status.success(),
            "stderr: {}",
            String::from_utf8_lossy(&out.stderr)
        );
        assert!(bundle.join("no-type.md").exists());
    }

    #[test]
    fn json_flag_outputs_slug_and_version() {
        let bundle = temp_bundle("create-json");
        let inputs = temp_inputs("create-json");
        let input = inputs.join("use-rust.md");
        std::fs::write(&input, DOC).unwrap();

        let out = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
            .arg("--file")
            .arg(&input)
            .arg("--json")
            .output()
            .unwrap();
        assert!(out.status.success());

        let parsed: serde_json::Value = serde_json::from_slice(&out.stdout).unwrap();
        assert_eq!(parsed["slug"], "use-rust");
        let version = parsed["version"].as_str().unwrap();
        assert_eq!(version.len(), okf_core::occ::version(b"x").len());
        // Version is the OCC hash of the exact bytes written.
        assert_eq!(version, okf_core::occ::version(DOC.as_bytes()));
    }

    #[test]
    fn already_exists_is_rejected() {
        let bundle = temp_bundle("create-dup");
        let inputs = temp_inputs("create-dup");
        let input = inputs.join("use-rust.md");
        std::fs::write(&input, DOC).unwrap();

        let first = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(first.status.success());

        let second = Command::new(bin())
            .args(["concept", "create", "--bundle"])
            .arg(&bundle)
            .arg("--file")
            .arg(&input)
            .output()
            .unwrap();
        assert!(!second.status.success());
        assert!(
            String::from_utf8_lossy(&second.stderr).contains("already exists"),
            "stderr: {}",
            String::from_utf8_lossy(&second.stderr)
        );
    }
}
