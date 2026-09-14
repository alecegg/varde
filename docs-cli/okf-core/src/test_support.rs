//! Test-only support helpers shared by the inline `#[cfg(test)]` modules
//! of the okf-core crates (compiled only under `cargo test`).

use std::path::PathBuf;

/// A fresh, unique temporary directory for a unit-test module.
///
/// `tag` must be distinct per test module so parallel test runs never
/// collide on the same directory.
pub fn tempdir(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!(
        "okf-core-{tag}-{}-{}",
        std::process::id(),
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos()
    ));
    std::fs::create_dir_all(&dir).unwrap();
    dir
}
