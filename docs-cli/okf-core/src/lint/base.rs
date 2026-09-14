//! `lint_base`: the structural checks every markdown concept document must
//! satisfy regardless of any spec (e.g. OKF) layered on top.
//!
//! Deliberately minimal — four checks only:
//! - frontmatter parses as a YAML mapping (delimited by `---` lines);
//! - the document is valid UTF-8;
//! - the slug is kebab-case (`^[a-z0-9]+(-[a-z0-9]+)*$`);
//! - the slug does not escape the bundle directory (path traversal).
//!
//! No OKF-specific check (a `type` field, a document state enumeration,
//! field-mutation rules, disallowed bundle filenames) belongs here — those
//! are opt-in checks layered on top elsewhere. A document with valid frontmatter, valid
//! UTF-8, and a valid slug passes `lint_base` even with no `type` field at
//! all: that's the behavior distinguishing "general markdown file" from
//! "OKF concept".

use crate::crud::validate_slug;
use crate::frontmatter::{self, FrontmatterError};
use thiserror::Error;

/// Typed errors for `lint_base` — one variant per structural check.
#[derive(Debug, Error)]
pub enum BaseLintError {
    /// The document failed to parse as `---`-delimited YAML frontmatter:
    /// not valid UTF-8, missing delimiters, not a mapping, or invalid YAML.
    #[error("frontmatter check failed: {0}")]
    Frontmatter(#[from] FrontmatterError),
    /// The slug is not kebab-case, which also rejects any slug containing
    /// path-traversal or separator characters (`..`, `/`, `\`).
    #[error("invalid slug `{slug}`: must be kebab-case, e.g. `my-concept`")]
    InvalidSlug { slug: String },
}

/// Run the base structural lint over a candidate document's raw bytes and
/// its slug. Returns `Ok(())` when the document has valid `---`-delimited
/// YAML-mapping frontmatter, is valid UTF-8, and `slug` is kebab-case with
/// no path traversal — regardless of what fields (if any) the frontmatter
/// contains.
pub fn lint_base(bytes: &[u8], slug: &str) -> Result<(), BaseLintError> {
    frontmatter::parse(bytes)?;
    if !validate_slug(slug) {
        return Err(BaseLintError::InvalidSlug {
            slug: slug.to_string(),
        });
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn base_lint_valid_frontmatter_kebab_slug_no_type_field_succeeds() {
        let bytes = b"---\ntitle: no type field here\n---\nbody text\n";
        assert!(lint_base(bytes, "my-concept").is_ok());
    }

    #[test]
    fn base_lint_invalid_yaml_frontmatter_is_rejected() {
        let bytes = b"---\n: not yaml :(\n---\nbody\n";
        let err = lint_base(bytes, "my-concept").unwrap_err();
        assert!(matches!(
            err,
            BaseLintError::Frontmatter(FrontmatterError::InvalidYaml(_))
        ));
    }

    #[test]
    fn base_lint_non_mapping_frontmatter_is_rejected() {
        let bytes = b"---\n- just\n- a\n- list\n---\nbody\n";
        let err = lint_base(bytes, "my-concept").unwrap_err();
        assert!(matches!(
            err,
            BaseLintError::Frontmatter(FrontmatterError::NotAMapping(_))
        ));
    }

    #[test]
    fn base_lint_non_utf8_bytes_are_rejected() {
        let bytes: &[u8] = b"---\ntitle: \xff\xfe invalid\n---\nbody\n";
        let err = lint_base(bytes, "my-concept").unwrap_err();
        assert!(matches!(
            err,
            BaseLintError::Frontmatter(FrontmatterError::NotUtf8(_))
        ));
    }

    #[test]
    fn base_lint_non_kebab_case_slug_is_rejected() {
        let bytes = b"---\ntitle: valid\n---\nbody\n";
        let err = lint_base(bytes, "Not_Kebab_Case").unwrap_err();
        assert!(matches!(err, BaseLintError::InvalidSlug { slug } if slug == "Not_Kebab_Case"));
    }

    #[test]
    fn base_lint_path_traversal_slug_is_rejected() {
        let bytes = b"---\ntitle: valid\n---\nbody\n";
        let err = lint_base(bytes, "../../etc/passwd").unwrap_err();
        assert!(matches!(err, BaseLintError::InvalidSlug { slug } if slug == "../../etc/passwd"));
    }

    #[test]
    fn base_lint_missing_delimiters_is_rejected() {
        let bytes = b"no frontmatter here";
        let err = lint_base(bytes, "my-concept").unwrap_err();
        assert!(matches!(
            err,
            BaseLintError::Frontmatter(FrontmatterError::MissingDelimiters)
        ));
    }
}
