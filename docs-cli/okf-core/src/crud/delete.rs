//! `concept delete`: hard-delete a concept file from the bundle.

use crate::crud::concept_path;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Typed errors for `concept delete`.
#[derive(Debug, Error)]
pub enum DeleteError {
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
pub fn delete(bundle: &Path, slug: &str) -> Result<String, DeleteError> {
    let Some(path) = concept_path(bundle, slug) else {
        return Err(DeleteError::InvalidSlug {
            slug: slug.to_string(),
        });
    };
    match std::fs::remove_file(&path) {
        Ok(()) => Ok(slug.to_string()),
        Err(e) if e.kind() == io::ErrorKind::NotFound => Err(DeleteError::NotFound {
            slug: slug.to_string(),
        }),
        Err(source) => Err(DeleteError::DeleteFailed { path, source }),
    }
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
}
