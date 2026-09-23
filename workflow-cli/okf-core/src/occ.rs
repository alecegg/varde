//! OCC (optimistic concurrency control) versioning for concept files.
//!
//! The version of a concept file is a SHA-256 hash of its current on-disk
//! bytes, truncated to the first 16 hex characters. There is no separate
//! version counter field.

use sha2::{Digest, Sha256};

/// Number of digest bytes retained to form the version string. Widened from
/// 4 to 8 (16 hex chars) to push collision probability well below the
/// birthday bound for an actively-edited bundle's distinct historical
/// contents; update the CLI reference
/// (`memory-bank/knowledge/reference/varde-workflow-cli.md`) if this
/// changes again.
const VERSION_BYTES: usize = 8;
/// Number of hex characters in the version string (`VERSION_BYTES * 2`).
const VERSION_HEX_LEN: usize = VERSION_BYTES * 2;

/// Compute the OCC version of a concept file from its bytes.
///
/// Deterministic: identical bytes always produce the identical version;
/// different bytes produce different versions (with overwhelming
/// probability).
pub fn version(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    let digest = hasher.finalize();
    let out: String = digest
        .iter()
        .take(VERSION_BYTES)
        .map(|b| format!("{b:02x}"))
        .collect();
    debug_assert_eq!(out.len(), VERSION_HEX_LEN);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_is_deterministic_and_8_hex() {
        let bytes = b"---\ntype: decision\n---\nbody";
        let a = version(bytes);
        let b = version(bytes);
        assert_eq!(a, b);
        assert_eq!(a.len(), VERSION_HEX_LEN);
        assert!(a.chars().all(|c| c.is_ascii_hexdigit()));
    }

    #[test]
    fn version_differs_for_different_bytes() {
        assert_ne!(
            version(b"---\ntype: decision\n---\nbody a"),
            version(b"---\ntype: decision\n---\nbody b")
        );
    }
}
