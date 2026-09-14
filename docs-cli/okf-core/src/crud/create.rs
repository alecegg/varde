//! `concept create`: validate a document and OCC-safe-write it into the
//! bundle as `<slug>.md`.
//!
//! Create-only semantics: errors when the slug already exists. OCC
//! conflict rejection belongs to `update`; `create` never overwrites.

use crate::concept::{Concept, ConceptError};
use crate::crud::{ConceptIoError, atomic_create, concept_path_or};
use crate::occ;
use std::path::Path;
use thiserror::Error;

/// Typed errors for `concept create`.
#[derive(Debug, Error)]
pub enum CreateError {
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error("concept `{slug}` already exists in the bundle")]
    AlreadyExists { slug: String },
    #[error(transparent)]
    Concept(#[from] ConceptError),
    #[error("failed to create parent directory `{path}`: {source}")]
    CreateDirFailed {
        path: std::path::PathBuf,
        source: std::io::Error,
    },
}

/// The result of a successful create.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CreatedConcept {
    pub slug: String,
    /// OCC version hash of the written bytes.
    pub version: String,
}

/// Create a concept from the raw document bytes.
///
/// The document must parse as a valid markdown concept (frontmatter plus a
/// body); no `type` field or other OKF-spec field is required here. The
/// slug is validated, then the bytes are written atomically as `<slug>.md`.
/// Fails without writing when validation fails or the file already exists.
pub fn create(bundle: &Path, bytes: &[u8], slug: &str) -> Result<CreatedConcept, CreateError> {
    let path = concept_path_or(bundle, slug)?;
    let _concept = Concept::from_bytes(bytes, slug)?;
    // Nested slugs (e.g. `pattern/rule-a`) may need a type directory that
    // doesn't exist yet on first use; create any missing intermediate
    // directories under the bundle root before the atomic create.
    if let Some(parent) = path.parent()
        && parent != bundle
    {
        std::fs::create_dir_all(parent).map_err(|source| CreateError::CreateDirFailed {
            path: parent.to_path_buf(),
            source,
        })?;
    }
    match atomic_create(&path, bytes) {
        Ok(()) => {}
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            return Err(CreateError::AlreadyExists {
                slug: slug.to_string(),
            });
        }
        Err(source) => {
            return Err(CreateError::Io(ConceptIoError::WriteFailed { path, source }));
        }
    }
    Ok(CreatedConcept {
        slug: slug.to_string(),
        version: occ::version(bytes),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crud::validate_slug;
    use crate::test_support::tempdir;

    const DOC: &str = "---\ntype: decision\n---\n# Body\n";

    #[test]
    fn validate_slug_accepts_kebab_case() {
        assert!(validate_slug("my-concept"));
        assert!(validate_slug("a"));
        assert!(validate_slug("okf-core"));
        assert!(validate_slug("2026-08-13-okf-core-crud"));
    }

    #[test]
    fn validate_slug_rejects_bad_shapes() {
        for bad in [
            "",
            "-leading",
            "trailing-",
            "double--dash",
            "UPPER",
            "snake_case",
            "space in",
        ] {
            assert!(!validate_slug(bad), "should reject {bad:?}");
        }
    }

    #[test]
    fn validate_slug_accepts_nested_kebab_case_paths() {
        assert!(validate_slug("a/b"));
        assert!(validate_slug("pattern/rule-a"));
        assert!(validate_slug("a/b/c-d"));
    }

    #[test]
    fn validate_slug_rejects_traversal_and_empty_segments() {
        for bad in ["..", "../etc/passwd", "a/../b", "/abs", "foo/", "foo//bar", "a\\b"] {
            assert!(!validate_slug(bad), "should reject {bad:?}");
        }
    }

    #[test]
    fn create_rejects_traversal_slug_without_escaping_bundle() {
        let dir = tempdir("okf-core-create-escape");
        let outside = dir.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        assert!(matches!(
            create(&dir, DOC.as_bytes(), "../outside/escape").unwrap_err(),
            CreateError::Io(ConceptIoError::InvalidSlug { .. })
        ));
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"sentinel");
    }

    #[test]
    fn crud_create_no_type_succeeds() {
        let dir = tempdir("okf-core-create-no-type");
        let bytes = b"---\ntitle: No type\n---\nbody\n";
        let created = create(&dir, bytes, "no-type").unwrap();
        assert_eq!(created.slug, "no-type");
        assert_eq!(
            std::fs::read(dir.join("no-type.md")).unwrap(),
            bytes.to_vec()
        );
    }

    #[test]
    fn create_invalid_slug_is_rejected() {
        let dir = tempdir("okf-core-create-invalid-slug");
        assert!(matches!(
            create(&dir, DOC.as_bytes(), "Bad Slug").unwrap_err(),
            CreateError::Io(ConceptIoError::InvalidSlug { .. })
        ));
    }

    #[test]
    fn create_already_exists_errors() {
        let dir = tempdir("okf-core-create-dup");
        create(&dir, DOC.as_bytes(), "dup").unwrap();
        assert!(matches!(
            create(&dir, DOC.as_bytes(), "dup").unwrap_err(),
            CreateError::AlreadyExists { .. }
        ));
    }

    #[test]
    fn concurrent_create_of_the_same_slug_never_clobbers_the_winner() {
        use std::sync::{Arc, Barrier};
        use std::thread;

        let dir = tempdir("okf-core-create-race");
        let dir = Arc::new(dir.to_path_buf());
        let barrier = Arc::new(Barrier::new(2));
        let doc_a = "---\ntype: decision\n---\n# A\n";
        let doc_b = "---\ntype: decision\n---\n# B\n";

        let handles: Vec<_> = [doc_a, doc_b]
            .into_iter()
            .map(|doc| {
                let dir = Arc::clone(&dir);
                let barrier = Arc::clone(&barrier);
                thread::spawn(move || {
                    barrier.wait();
                    create(&dir, doc.as_bytes(), "race").map(|_| doc)
                })
            })
            .collect();

        let results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        let successes: Vec<_> = results.iter().filter_map(|r| r.as_ref().ok()).collect();
        assert_eq!(successes.len(), 1, "exactly one concurrent create must win");

        let on_disk = std::fs::read(dir.join("race.md")).unwrap();
        assert_eq!(
            on_disk,
            successes[0].as_bytes(),
            "the file on disk must match the winning create's bytes, never a torn/clobbered mix"
        );
    }

    #[test]
    fn create_writes_file_and_reports_version() {
        let dir = tempdir("okf-core-create-write");
        let created = create(&dir, DOC.as_bytes(), "use-rust").unwrap();
        assert_eq!(created.slug, "use-rust");
        assert_eq!(created.version, occ::version(DOC.as_bytes()));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            DOC.as_bytes()
        );
    }

    #[test]
    fn create_nested_slug_creates_missing_parent_directories() {
        let dir = tempdir("okf-core-create-nested");
        assert!(!dir.join("pattern").exists());
        let created = create(&dir, DOC.as_bytes(), "pattern/rule-a").unwrap();
        assert_eq!(created.slug, "pattern/rule-a");
        assert_eq!(
            std::fs::read(dir.join("pattern/rule-a.md")).unwrap(),
            DOC.as_bytes()
        );
    }

    #[test]
    fn create_deeply_nested_slug_creates_all_missing_parents() {
        let dir = tempdir("okf-core-create-deep-nested");
        create(&dir, DOC.as_bytes(), "a/b/c-d").unwrap();
        assert_eq!(
            std::fs::read(dir.join("a/b/c-d.md")).unwrap(),
            DOC.as_bytes()
        );
    }
}
