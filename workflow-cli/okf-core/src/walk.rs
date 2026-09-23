//! Shared bundle-tree visitor for the abort-on-first-error query
//! paths (`registry::search`, `crud::search::search_text`, `crud::list`).
//! Centralizes the hidden/artifact/symlink skip rules and the
//! read+parse-frontmatter sequence, parameterized by a per-caller reserved
//! predicate, so the reserved-file rule can't silently drift between
//! callers the way `crud::list`'s did before it was renamed to
//! `is_reserved_strict` (CODE-010) — the underlying duplication was the
//! root cause, tracked as ARCHITECTURE-002.
//!
//! `lint::walk` intentionally does NOT use this: it needs report-and-continue
//! semantics (an unreadable subtree or malformed concept becomes a report
//! entry, not an abort) plus per-directory `MissingIndex` bookkeeping that
//! doesn't fit this abort-on-first-error, flat-file-list shape.

use crate::bundle::is_artifact_dir;
use crate::frontmatter::{self, FrontmatterError};
use std::fs;
use std::io;
use std::path::{Path, PathBuf};

/// One concept-eligible file found while walking a bundle: its path, parsed
/// frontmatter, and raw body text.
pub struct WalkedFile {
    pub path: PathBuf,
    pub frontmatter: serde_yaml::Value,
    pub body: String,
}

/// The three ways a [`visit_concepts`] traversal can fail. Callers convert
/// this into their own typed error enum via a `From` impl — the field
/// shapes match `RegistryError`/`ListError`'s existing variants, so the
/// conversion is mechanical.
pub enum WalkError {
    ReadDirFailed {
        path: PathBuf,
        source: io::Error,
    },
    ReadFailed {
        path: PathBuf,
        source: io::Error,
    },
    InvalidConcept {
        path: PathBuf,
        source: FrontmatterError,
    },
}

/// Visit each Concept as it is parsed.
///
/// Hidden entries, artifact directories, and symlinks are skipped.
/// `reserved(name)` identifies bundle bookkeeping files. Traversal aborts
/// on the first unreadable directory, unreadable file, or malformed Concept.
pub fn visit_concepts(
    bundle: &Path,
    reserved: &dyn Fn(&str) -> bool,
    mut visitor: impl FnMut(WalkedFile),
) -> Result<(), WalkError> {
    visit_dir(bundle, reserved, &mut visitor)
}

fn visit_dir(
    dir: &Path,
    reserved: &dyn Fn(&str) -> bool,
    visitor: &mut impl FnMut(WalkedFile),
) -> Result<(), WalkError> {
    let entries = fs::read_dir(dir)
        .map_err(|source| WalkError::ReadDirFailed {
            path: dir.to_path_buf(),
            source,
        })?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| WalkError::ReadDirFailed {
            path: dir.to_path_buf(),
            source,
        })?;

    for entry in entries {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|n| n.to_str()) else {
            continue;
        };
        if name.starts_with('.') || is_artifact_dir(name) || path.is_symlink() {
            continue;
        }
        if path.is_dir() {
            visit_dir(&path, reserved, visitor)?;
            continue;
        }
        if !path.is_file() || reserved(name) || !name.ends_with(".md") {
            continue;
        }
        let bytes = fs::read(&path).map_err(|source| WalkError::ReadFailed {
            path: path.clone(),
            source,
        })?;
        let (frontmatter, body) =
            frontmatter::parse(&bytes).map_err(|source| WalkError::InvalidConcept {
                path: path.clone(),
                source,
            })?;
        visitor(WalkedFile {
            path,
            frontmatter,
            body,
        });
    }
    Ok(())
}
