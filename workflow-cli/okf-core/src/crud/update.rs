//! `concept update`: overwrite a concept file with OCC conflict rejection.
//!
//! Compare-and-swap on the file's content hash: the caller passes the
//! `expected_version` they last read; a mismatch means the file changed
//! underneath them and the write is rejected with a typed conflict error —
//! never a silent overwrite. On any failure the on-disk file is untouched.

use crate::concept::{Concept, ConceptError};
use crate::crud::{ConceptIoError, occ_read_guard, write_if_unchanged};
use crate::occ;
use std::path::Path;
use thiserror::Error;

/// Typed errors for `concept update`.
#[derive(Debug, Error)]
pub enum UpdateError {
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error("concept document is missing the required `type` field (a non-empty string)")]
    MissingType,
    #[error(transparent)]
    Concept(#[from] ConceptError),
}

/// The result of a successful update.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdatedConcept {
    pub slug: String,
    /// OCC version of the bytes that were on disk before the write.
    pub old_version: String,
    /// OCC version of the newly written bytes.
    pub new_version: String,
}

/// Update a concept, guarded by `expected_version`.
///
/// The file is only written when its current content hash equals
/// `expected_version`. No OKF-spec field (e.g. `type`) is required here —
/// only that the bytes parse as a valid markdown concept document. On error
/// the on-disk file is byte-identical to before the call.
pub fn update(
    bundle: &Path,
    slug: &str,
    expected_version: &str,
    bytes: &[u8],
) -> Result<UpdatedConcept, UpdateError> {
    crate::crud::with_slug_lock(bundle, slug, || {
        let (path, _current, actual) = occ_read_guard(bundle, slug, expected_version)?;
        let _concept = Concept::from_bytes(bytes, slug)?;
        write_if_unchanged(&path, slug, &actual, bytes)?;
        Ok(UpdatedConcept {
            slug: slug.to_string(),
            old_version: actual,
            new_version: occ::version(bytes),
        })
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::crud::create::create;
    use crate::test_support::tempdir;

    const DOC: &str = "---\ntype: decision\ndescription: A useful decision.\n---\n# Body\n";
    const DOC2: &str = "---\ntype: decision\ndescription: An updated decision.\n---\n# Body v2\n";

    /// Regression: a concept with no `type` field is accepted end-to-end by
    /// both `crud::create` and `crud::update` — the OKF-optional refactor
    /// removed the old required-`type` gate from both paths.
    #[test]
    fn create_update_no_type_succeeds() {
        let dir = tempdir("okf-core-create-update-no-type");
        let no_type: &str = "---\ntitle: No type\ndescription: A note without a type.\n---\nbody\n";
        let no_type2: &str =
            "---\ntitle: No type v2\ndescription: An updated note without a type.\n---\nbody v2\n";

        let created = create(&dir, no_type.as_bytes(), "no-type").unwrap();
        assert_eq!(created.slug, "no-type");

        let updated = update(
            &dir,
            "no-type",
            &occ::version(no_type.as_bytes()),
            no_type2.as_bytes(),
        )
        .unwrap();
        assert_eq!(updated.slug, "no-type");
        assert_eq!(
            std::fs::read(dir.join("no-type.md")).unwrap(),
            no_type2.as_bytes()
        );
    }

    #[test]
    fn update_happy_path_reports_old_and_new_versions() {
        let dir = tempdir("okf-core-update-happy");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        let upd = update(
            &dir,
            "use-rust",
            &occ::version(DOC.as_bytes()),
            DOC2.as_bytes(),
        )
        .unwrap();
        assert_eq!(upd.slug, "use-rust");
        assert_eq!(upd.old_version, occ::version(DOC.as_bytes()));
        assert_eq!(upd.new_version, occ::version(DOC2.as_bytes()));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            DOC2.as_bytes()
        );
    }

    #[test]
    fn update_stale_version_is_conflict_and_file_unchanged() {
        let dir = tempdir("okf-core-update-conflict");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        let err = update(&dir, "use-rust", "deadbeef", DOC2.as_bytes()).unwrap_err();
        assert!(matches!(
            err,
            UpdateError::Io(ConceptIoError::Conflict { .. })
        ));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            DOC.as_bytes()
        );
    }

    #[test]
    fn crud_update_nonenum_status_succeeds() {
        let dir = tempdir("okf-core-update-nonenum-status");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        let bad = b"---\ntype: decision\ndescription: A useful decision.\nstatus: bogus-status\n---\nbody\n";
        let upd = update(&dir, "use-rust", &occ::version(DOC.as_bytes()), bad).unwrap();
        assert_eq!(upd.slug, "use-rust");
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            bad.to_vec()
        );
    }

    #[test]
    fn update_missing_slug_is_not_found() {
        let dir = tempdir("okf-core-update-missing");
        assert!(matches!(
            update(&dir, "nope", "00000000", DOC.as_bytes()).unwrap_err(),
            UpdateError::Io(ConceptIoError::NotFound { .. })
        ));
    }

    #[test]
    fn update_missing_bundle_is_not_found_without_lock_artifact() {
        let parent = tempdir("okf-core-update-missing-bundle");
        let bundle = parent.join("missing");

        assert!(matches!(
            update(&bundle, "nope", "00000000", DOC.as_bytes()).unwrap_err(),
            UpdateError::Io(ConceptIoError::NotFound { .. })
        ));
        assert!(!bundle.exists());
    }

    #[test]
    fn concurrent_updates_racing_on_the_same_starting_version_never_both_succeed() {
        use std::sync::{Arc, Barrier};
        use std::thread;

        let dir = tempdir("okf-core-update-race");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        let dir = Arc::new(dir.to_path_buf());
        let starting_version = occ::version(DOC.as_bytes());
        let barrier = Arc::new(Barrier::new(2));

        let handles: Vec<_> = ["v1", "v2"]
            .into_iter()
            .map(|tag| {
                let dir = Arc::clone(&dir);
                let barrier = Arc::clone(&barrier);
                let starting_version = starting_version.clone();
                let bytes =
                    format!("---\ntype: decision\ndescription: A useful decision.\n---\n# {tag}\n")
                        .into_bytes();
                thread::spawn(move || {
                    barrier.wait();
                    update(&dir, "use-rust", &starting_version, &bytes)
                })
            })
            .collect();

        let results: Vec<_> = handles.into_iter().map(|h| h.join().unwrap()).collect();
        let successes = results.iter().filter(|r| r.is_ok()).count();
        let conflicts = results
            .iter()
            .filter(|r| matches!(r, Err(UpdateError::Io(ConceptIoError::Conflict { .. }))))
            .count();
        assert_eq!(successes, 1, "exactly one racing update must win");
        assert_eq!(
            conflicts, 1,
            "the loser must observe a typed Conflict, never a silent overwrite"
        );
    }

    #[test]
    fn update_traversal_slug_is_invalid_and_writes_nothing_outside() {
        let dir = tempdir("okf-core-update-escape");
        let outside = dir.join("../outside");
        std::fs::create_dir_all(&outside).unwrap();
        let sentinel = outside.join("escape.md");
        std::fs::write(&sentinel, b"sentinel").unwrap();
        assert!(matches!(
            update(&dir, "../outside/escape", "00000000", DOC2.as_bytes()).unwrap_err(),
            UpdateError::Io(ConceptIoError::InvalidSlug { .. })
        ));
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"sentinel");
    }

    #[test]
    fn update_nested_slug_writes_the_nested_file() {
        let dir = tempdir("okf-core-update-nested");
        std::fs::create_dir_all(dir.join("pattern")).unwrap();
        std::fs::write(dir.join("pattern/rule-a.md"), DOC).unwrap();
        let upd = update(
            &dir,
            "pattern/rule-a",
            &occ::version(DOC.as_bytes()),
            DOC2.as_bytes(),
        )
        .unwrap();
        assert_eq!(upd.slug, "pattern/rule-a");
        assert_eq!(
            std::fs::read(dir.join("pattern/rule-a.md")).unwrap(),
            DOC2.as_bytes()
        );
    }

    #[cfg(unix)]
    #[test]
    fn update_recovers_from_abandoned_lock_file() {
        let dir = tempdir("okf-core-update-abandoned-lock");
        std::fs::write(dir.join("use-rust.md"), DOC).unwrap();
        std::fs::write(dir.join(".use-rust.lock"), b"").unwrap();

        update(
            &dir,
            "use-rust",
            &occ::version(DOC.as_bytes()),
            DOC2.as_bytes(),
        )
        .unwrap();

        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            DOC2.as_bytes()
        );
    }

    #[cfg(unix)]
    #[test]
    fn update_alias_shares_lock_with_canonical_slug() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-update-internal-alias-lock");
        std::fs::create_dir(dir.join("real")).unwrap();
        std::fs::write(dir.join("real/doc.md"), DOC).unwrap();
        symlink("real", dir.join("alias")).unwrap();

        let result = crate::crud::with_slug_lock(&dir, "real/doc", || {
            update(
                &dir,
                "alias/doc",
                &occ::version(DOC.as_bytes()),
                DOC2.as_bytes(),
            )
        });

        assert!(matches!(
            result,
            Err(UpdateError::Io(ConceptIoError::WriteFailed { source, .. }))
                if source.kind() == std::io::ErrorKind::TimedOut
        ));
        assert_eq!(
            std::fs::read(dir.join("real/doc.md")).unwrap(),
            DOC.as_bytes()
        );
    }
}
