//! Shared helpers for CLI integration tests.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

static NEXT_TEMP_DIR: AtomicU64 = AtomicU64::new(0);

pub fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_varde-workflow")
}

/// Run a CLI fixture with an isolated default memory configuration.
pub fn isolate_memory(root: &Path) -> Command {
    let mut command = Command::new(bin());
    command
        .current_dir(root)
        .env("VARDE_CONFIG_DIR", root.join("isolated-config"))
        .env_remove("VARDE_WORKING_DIR")
        .env_remove("VARDE_KNOWLEDGE_DIR")
        .env_remove("VARDE_LEARN_STORE");
    command
}

#[allow(dead_code)]
pub fn json_data(bytes: &[u8]) -> serde_json::Value {
    let envelope: serde_json::Value = serde_json::from_slice(bytes).unwrap();
    assert_eq!(envelope["schema_version"], 1);
    assert_eq!(envelope["envelope_version"], 1);
    assert_eq!(envelope["ok"], true);
    assert_eq!(envelope["outcome"], "success");
    assert!(envelope["meta"].is_object());
    envelope["data"].clone()
}

/// A fresh, empty bundle directory unique to this test run.
pub fn temp_bundle(tag: &str) -> PathBuf {
    create_temp_dir("ck-test", tag)
}

/// A directory holding input documents, kept separate from any bundle.
/// Only some test crates use it; shared helpers may be unused per crate.
#[allow(dead_code)]
pub fn temp_inputs(tag: &str) -> PathBuf {
    create_temp_dir("ck-inputs", tag)
}

fn create_temp_dir(prefix: &str, tag: &str) -> PathBuf {
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_nanos();
    loop {
        let nonce = NEXT_TEMP_DIR.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "{prefix}-{tag}-{}-{timestamp}-{nonce}",
            std::process::id()
        ));
        match std::fs::create_dir(&dir) {
            Ok(()) => return dir,
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => panic!("could not create {}: {error}", dir.display()),
        }
    }
}

#[allow(dead_code)]
pub mod review;
