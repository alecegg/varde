//! `concept delete`: hard-delete a concept file from the bundle.

use crate::crud::{ConceptIoError, concept_path, path_is_contained, with_slug_lock};
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Typed errors for `concept delete`.
#[derive(Debug, Error)]
pub enum DeleteError {
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error(
        "invalid slug `{slug}`: must be kebab-case path segments, e.g. `my-concept` or \
         `pattern/my-concept`"
    )]
    InvalidSlug { slug: String },
    #[error("concept `{slug}` not found in the bundle")]
    NotFound { slug: String },
    #[error("failed to delete `{path}`: {source}")]
    DeleteFailed { path: PathBuf, source: io::Error },
}

/// Hard-delete the concept `<slug>.md` from the bundle.
///
/// Not OCC-guarded per plan spec: no `--expected-version` is required.
/// The bundle directory topology must have trusted ownership. Containment
/// checks cannot prevent concurrent replacement by an untrusted actor.
pub fn delete(bundle: &Path, slug: &str) -> Result<String, DeleteError> {
    let Some(path) = concept_path(bundle, slug) else {
        return Err(DeleteError::InvalidSlug {
            slug: slug.to_string(),
        });
    };
    with_slug_lock(bundle, slug, || {
        let contained =
            path_is_contained(bundle, &path).map_err(|source| DeleteError::DeleteFailed {
                path: bundle.to_path_buf(),
                source,
            })?;
        if !contained {
            return Err(DeleteError::InvalidSlug {
                slug: slug.to_string(),
            });
        }
        match std::fs::remove_file(&path) {
            Ok(()) => Ok(slug.to_string()),
            Err(e) if e.kind() == io::ErrorKind::NotFound => Err(DeleteError::NotFound {
                slug: slug.to_string(),
            }),
            Err(source) => Err(DeleteError::DeleteFailed { path, source }),
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    #[test]
    fn delete_removes_file_and_returns_slug() {
        let dir = tempdir("okf-core-delete-existing");
        std::fs::write(dir.join("doc.md"), b"---\ntype: decision\n---\n").unwrap();
        let deleted = delete(&dir, "doc").unwrap();
        assert_eq!(deleted, "doc");
        assert!(!dir.join("doc.md").exists());
    }

    #[test]
    fn delete_missing_slug_is_not_found() {
        let dir = tempdir("okf-core-delete-missing");
        assert!(matches!(
            delete(&dir, "nope").unwrap_err(),
            DeleteError::NotFound { .. }
        ));
    }

    #[test]
    fn delete_traversal_slug_is_invalid_and_deletes_nothing_outside() {
        let dir = tempdir("okf-core-delete-escape");
        let outside = dir.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        assert!(matches!(
            delete(&dir, "../outside/escape").unwrap_err(),
            DeleteError::InvalidSlug { .. }
        ));
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"sentinel");
    }

    #[test]
    fn delete_nested_slug_removes_the_nested_file() {
        let dir = tempdir("okf-core-delete-nested");
        std::fs::create_dir_all(dir.join("pattern")).unwrap();
        std::fs::write(dir.join("pattern/rule-a.md"), b"---\ntype: decision\n---\n").unwrap();
        let deleted = delete(&dir, "pattern/rule-a").unwrap();
        assert_eq!(deleted, "pattern/rule-a");
        assert!(!dir.join("pattern/rule-a.md").exists());
    }

    #[cfg(unix)]
    #[test]
    fn delete_uses_the_shared_per_slug_mutation_lock() {
        let dir = tempdir("okf-core-delete-lock");
        let path = dir.join("doc.md");
        std::fs::write(&path, b"---\ntype: decision\n---\n").unwrap();
        let lock_path = dir.join(crate::crud::slug_lock_file_name("doc"));
        let held = crate::crud::acquire_slug_lock(&lock_path).unwrap();

        let error = delete(&dir, "doc").unwrap_err();
        assert!(matches!(
            error,
            DeleteError::Io(ConceptIoError::WriteFailed { source, .. })
                if source.kind() == io::ErrorKind::TimedOut
        ));
        assert!(path.exists());

        drop(held);
        assert_eq!(delete(&dir, "doc").unwrap(), "doc");
        assert!(!path.exists());
    }

    #[cfg(unix)]
    #[test]
    fn delete_alias_shares_lock_with_canonical_slug() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-delete-internal-alias-lock");
        std::fs::create_dir(dir.join("real")).unwrap();
        let path = dir.join("real/doc.md");
        std::fs::write(&path, b"---\ntype: decision\n---\n").unwrap();
        symlink("real", dir.join("alias")).unwrap();

        let result = crate::crud::with_slug_lock(&dir, "real/doc", || delete(&dir, "alias/doc"));

        assert!(matches!(
            result,
            Err(DeleteError::Io(ConceptIoError::WriteFailed { source, .. }))
                if source.kind() == std::io::ErrorKind::TimedOut
        ));
        assert!(path.exists());
    }

    #[cfg(unix)]
    #[test]
    fn delete_rejects_symlinked_parent_outside_bundle() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-delete-symlink-escape");
        let outside = tempdir("okf-core-delete-symlink-outside");
        let victim = outside.join("victim.md");
        std::fs::write(&victim, b"sentinel").unwrap();
        symlink(&outside, dir.join("linked")).unwrap();

        assert!(matches!(
            delete(&dir, "linked/victim").unwrap_err(),
            DeleteError::InvalidSlug { .. }
        ));
        assert_eq!(std::fs::read(&victim).unwrap(), b"sentinel");
    }

    #[cfg(unix)]
    #[test]
    fn delete_rejects_dangling_symlink_parent() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-delete-dangling");
        symlink(dir.join("missing-target"), dir.join("linked")).unwrap();

        assert!(matches!(
            delete(&dir, "linked/victim").unwrap_err(),
            DeleteError::InvalidSlug { .. }
        ));
        assert!(dir.join("linked").is_symlink());
    }
}
