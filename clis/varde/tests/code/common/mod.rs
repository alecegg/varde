//! Shared helpers for integration tests: resolve fixture files in the
//! varde-code crate's `tests/fixtures/`.

use std::path::PathBuf;

/// Absolute path to a fixture file under varde-code's `tests/fixtures/<rel>`.
pub fn fixture_path(rel: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../code/crates/varde-code/tests/fixtures")
        .join(rel)
}

/// Contents of a fixture file under varde-code's `tests/fixtures/<rel>`.
#[allow(dead_code)] // not every test binary uses every helper
pub fn fixture(rel: &str) -> String {
    std::fs::read_to_string(fixture_path(rel)).expect("fixture exists")
}
