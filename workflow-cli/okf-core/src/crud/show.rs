//! `concept show`: read a concept file from the bundle and expose its
//! frontmatter, body, and current OCC version.

use crate::concept::{Concept, ConceptError};
use crate::crud::{ConceptIoError, concept_path_or};
use crate::occ;
use serde_yaml::Value;
use std::path::Path;
use thiserror::Error;

/// Typed errors for `concept show`.
#[derive(Debug, Error)]
pub enum ShowError {
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error(transparent)]
    Concept(#[from] ConceptError),
}

/// A concept read from the bundle, with its current version.
#[derive(Debug, Clone, PartialEq)]
pub struct ShownConcept {
    pub slug: String,
    /// OCC version hash of the on-disk bytes.
    pub version: String,
    pub frontmatter: Value,
    pub body: String,
}

/// Show a concept by slug.
pub fn show(bundle: &Path, slug: &str) -> Result<ShownConcept, ShowError> {
    let path = concept_path_or(bundle, slug)?;
    let bytes = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Err(ShowError::Io(ConceptIoError::NotFound {
                slug: slug.to_string(),
            }));
        }
        Err(e) => {
            return Err(ShowError::Io(ConceptIoError::ReadFailed {
                path,
                source: e,
            }));
        }
    };
    let concept = Concept::from_bytes(&bytes, slug)?;
    Ok(ShownConcept {
        slug: slug.to_string(),
        version: occ::version(&bytes),
        frontmatter: concept.frontmatter,
        body: concept.body,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    const DOC: &str = "---\ntype: decision\ntitle: Use Rust\n---\n# Body\n\nRust for the CLI.\n";

    #[test]
    fn show_reads_frontmatter_body_and_version() {
        let dir = tempdir("okf-core-show-read");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        let shown = show(&dir, "use-rust").unwrap();
        assert_eq!(shown.slug, "use-rust");
        assert_eq!(shown.version, occ::version(DOC.as_bytes()));
        assert_eq!(shown.frontmatter["type"], "decision");
        assert_eq!(shown.body, "# Body\n\nRust for the CLI.\n");
    }

    #[test]
    fn show_missing_slug_is_not_found() {
        let dir = tempdir("okf-core-show-missing");
        assert!(matches!(
            show(&dir, "nope").unwrap_err(),
            ShowError::Io(ConceptIoError::NotFound { .. })
        ));
    }

    #[test]
    fn show_traversal_slug_is_invalid_and_reads_nothing() {
        let dir = tempdir("okf-core-show-escape");
        let outside = dir.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        assert!(matches!(
            show(&dir, "../outside/escape").unwrap_err(),
            ShowError::Io(ConceptIoError::InvalidSlug { .. })
        ));
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"sentinel");
    }

    #[test]
    fn show_nested_slug_reads_the_nested_file() {
        let dir = tempdir("okf-core-show-nested");
        std::fs::create_dir_all(dir.join("pattern")).unwrap();
        std::fs::write(dir.join("pattern/rule-a.md"), DOC).unwrap();
        let shown = show(&dir, "pattern/rule-a").unwrap();
        assert_eq!(shown.slug, "pattern/rule-a");
        assert_eq!(shown.version, occ::version(DOC.as_bytes()));
    }
}
