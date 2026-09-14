//! Shared helpers for CLI integration tests.

use std::path::PathBuf;

pub fn bin() -> &'static str {
    env!("CARGO_BIN_EXE_varde-docs")
}

/// A fresh, empty bundle directory unique to this test run.
pub fn temp_bundle(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "ck-test-{tag}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}

/// A directory holding input documents, kept separate from any bundle.
/// Only some test crates use it; shared helpers may be unused per crate.
#[allow(dead_code)]
pub fn temp_inputs(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "ck-inputs-{tag}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).unwrap();
    dir
}
