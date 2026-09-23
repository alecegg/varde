//! Core Concept data model: one markdown file with YAML frontmatter and a
//! markdown body, per OKF v0.2 §2 and §4.
//!
//! A Concept's identity is its kebab-case slug, which is the filename stem
//! of `<slug>.md` directly inside the bundle root.

use crate::frontmatter::{self, FrontmatterError};
use serde_yaml::Value;
use thiserror::Error;

/// A single unit of knowledge within a bundle.
#[derive(Debug, Clone, PartialEq)]
pub struct Concept {
    /// Kebab-case slug; the filename stem of the concept file.
    pub slug: String,
    /// Parsed YAML frontmatter block.
    pub frontmatter: Value,
    /// Markdown body: everything after the closing `---` delimiter.
    pub body: String,
}

/// Errors produced while parsing concept documents.
#[derive(Debug, Error)]
pub enum ConceptError {
    #[error(transparent)]
    Frontmatter(#[from] FrontmatterError),
}

/// Errors for metadata required on newly created Concepts.
#[derive(Debug, Error, Clone, PartialEq, Eq)]
pub enum ConceptMetadataError {
    #[error("concept description is required")]
    MissingDescription,
    #[error("concept description must be a non-empty string")]
    InvalidDescription,
    #[error("concept aliases must be a sequence of non-empty strings")]
    InvalidAliases,
}

impl Concept {
    /// Parse a concept document from its on-disk bytes.
    ///
    /// The document must be a YAML frontmatter block delimited by `---`
    /// lines at the top of the file, followed by the markdown body
    /// (OKF v0.2 §4). The slug is passed in — it is derived from the
    /// filename, which the bytes alone do not carry.
    pub fn from_bytes(bytes: &[u8], slug: impl Into<String>) -> Result<Self, ConceptError> {
        let (frontmatter, body) = frontmatter::parse(bytes)?;
        Ok(Concept {
            slug: slug.into(),
            frontmatter,
            body,
        })
    }

    /// Validate metadata required when creating a new Concept.
    pub fn validate_new_metadata(&self) -> Result<(), ConceptMetadataError> {
        let description = self
            .frontmatter
            .get("description")
            .ok_or(ConceptMetadataError::MissingDescription)?;
        if description
            .as_str()
            .is_none_or(|value| value.trim().is_empty())
        {
            return Err(ConceptMetadataError::InvalidDescription);
        }

        if let Some(aliases) = self.frontmatter.get("aliases") {
            let Some(items) = aliases.as_sequence() else {
                return Err(ConceptMetadataError::InvalidAliases);
            };
            if items
                .iter()
                .any(|item| item.as_str().is_none_or(|value| value.trim().is_empty()))
            {
                return Err(ConceptMetadataError::InvalidAliases);
            }
        }
        Ok(())
    }
}

/// Derive a Concept's slug from its filename: the filename stem of
/// `<slug>.md`. Returns `None` when the name does not end in `.md`.
pub fn slug_from_filename(filename: &str) -> Option<&str> {
    filename.strip_suffix(".md")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn slug_from_filename_strips_md_suffix() {
        assert_eq!(slug_from_filename("foo-bar.md"), Some("foo-bar"));
        assert_eq!(slug_from_filename("foo.md"), Some("foo"));
        assert_eq!(slug_from_filename("foo"), None);
    }

    #[test]
    fn from_bytes_parses_frontmatter_and_body() {
        let bytes = b"---\ntype: decision\ntitle: Test\n---\n# Body\n\nSome text.\n";
        let concept = Concept::from_bytes(bytes, "test-concept").unwrap();
        assert_eq!(concept.slug, "test-concept");
        assert_eq!(concept.frontmatter["type"], "decision");
        assert_eq!(concept.body, "# Body\n\nSome text.\n");
    }

    #[test]
    fn from_bytes_without_delimiters_errors() {
        let bytes = b"no frontmatter here";
        assert!(Concept::from_bytes(bytes, "x").is_err());
    }

    #[test]
    fn new_metadata_requires_non_empty_description() {
        let missing = Concept::from_bytes(b"---\ntype: decision\n---\nbody", "x").unwrap();
        assert!(matches!(
            missing.validate_new_metadata(),
            Err(ConceptMetadataError::MissingDescription)
        ));

        let blank = Concept::from_bytes(b"---\ntype: decision\ndescription: '   '\n---\nbody", "x")
            .unwrap();
        assert!(matches!(
            blank.validate_new_metadata(),
            Err(ConceptMetadataError::InvalidDescription)
        ));
    }

    #[test]
    fn new_metadata_requires_aliases_to_be_a_string_sequence() {
        let scalar = Concept::from_bytes(
            b"---\ntype: decision\ndescription: useful\naliases: shortcut\n---\nbody",
            "x",
        )
        .unwrap();
        assert!(matches!(
            scalar.validate_new_metadata(),
            Err(ConceptMetadataError::InvalidAliases)
        ));

        let valid = Concept::from_bytes(
            b"---\ntype: decision\ndescription: useful\naliases:\n  - shortcut\n---\nbody",
            "x",
        )
        .unwrap();
        assert!(valid.validate_new_metadata().is_ok());
    }
}
