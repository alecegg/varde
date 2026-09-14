//! Shared input reading for command handlers.

use anyhow::{bail, Context, Result};
use std::io::Read;
use std::path::Path;

/// Read the concept document bytes from `--file` or, when absent, from
/// stdin. Shared by `concept create` and `concept update`; `create`
/// derives the slug from the filename on top of this.
///
/// Rejects empty input with a clear error rather than passing zero bytes
/// through to core, whose error (if any) would be far less legible.
pub fn read_input(file: Option<&Path>) -> Result<Vec<u8>> {
    let bytes = match file {
        Some(path) => std::fs::read(path)
            .with_context(|| format!("failed to read input file {}", path.display()))?,
        None => {
            let mut bytes = Vec::new();
            std::io::stdin()
                .read_to_end(&mut bytes)
                .context("failed to read the concept document from stdin")?;
            bytes
        }
    };
    if bytes.is_empty() {
        bail!("concept document is empty");
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A fresh, unique temp file path for this test module (no external
    /// tempfile crate dependency; mirrors `okf_core::test_support::tempdir`).
    fn temp_path(tag: &str) -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "varde-docs-input-{tag}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ))
    }

    #[test]
    fn rejects_empty_file() {
        let path = temp_path("empty");
        std::fs::write(&path, b"").unwrap();
        let err = read_input(Some(&path)).unwrap_err();
        std::fs::remove_file(&path).ok();
        assert!(err.to_string().contains("empty"), "{err}");
    }

    #[test]
    fn accepts_non_empty_file() {
        let path = temp_path("nonempty");
        std::fs::write(&path, b"---\ntype: note\n---\nbody").unwrap();
        let bytes = read_input(Some(&path)).unwrap();
        std::fs::remove_file(&path).ok();
        assert!(!bytes.is_empty());
    }
}
