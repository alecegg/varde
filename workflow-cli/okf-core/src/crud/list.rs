//! `concept list`: enumerate the concept files in a bundle.
//!
//! Per OKF v0.2 §3, a bundle is a directory *tree*: subdirectories organize
//! concepts into groups, and a concept's id is its path within the bundle
//! (slashes, `.md` suffix removed). This walks the tree recursively rather
//! than reading only the bundle root.
//!
//! Per OKF v0.2 §3.1/§11, `index.md` and `log.md` are reserved filenames
//! (not concepts) at any level of the hierarchy and are excluded, as are
//! non-`.md` files. A concept file with unparseable frontmatter is a typed
//! error, not a silent skip. A missing `type` field is not an error: it is
//! absent-optional, listed like any other concept.

use crate::crud::ConceptIoError;
use crate::frontmatter::FrontmatterError;
use serde::Serialize;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// A concept entry in a bundle listing. `type_` is absent when the concept
/// has no `type` field — that is not an error, see [`ListError`].
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ListedConcept {
    pub slug: String,
    #[serde(rename = "type")]
    pub type_: Option<String>,
}

/// Typed errors for `concept list`. A concept with unparseable frontmatter
/// is a typed error, never a silent skip. A missing `type` field is *not*
/// an error here — it's absent-optional, matching `registry::search`.
#[derive(Debug, Error)]
pub enum ListError {
    #[error("failed to read bundle directory `{path}`: {source}")]
    ReadDirFailed { path: PathBuf, source: io::Error },
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error("`{path}` is not a valid OKF concept: {source}")]
    InvalidConcept {
        path: PathBuf,
        source: FrontmatterError,
    },
}

impl From<crate::walk::WalkError> for ListError {
    fn from(err: crate::walk::WalkError) -> Self {
        match err {
            crate::walk::WalkError::ReadDirFailed { path, source } => {
                ListError::ReadDirFailed { path, source }
            }
            crate::walk::WalkError::ReadFailed { path, source } => {
                ListError::Io(ConceptIoError::ReadFailed { path, source })
            }
            crate::walk::WalkError::InvalidConcept { path, source } => {
                ListError::InvalidConcept { path, source }
            }
        }
    }
}

/// List the concepts in a bundle, sorted by slug.
///
/// Walks the bundle directory tree recursively; a concept's slug is its
/// path relative to the bundle root (with `/` separators), `.md` suffix
/// removed, per the OKF v0.2 §2 Concept ID definition.
pub fn list(bundle: &Path, include_deprecated: bool) -> Result<Vec<ListedConcept>, ListError> {
    let mut concepts = Vec::new();
    crate::walk::visit_concepts(
        bundle,
        &is_reserved_strict,
        |crate::walk::WalkedFile {
             path, frontmatter, ..
         }| {
            // A missing/empty `type` is absent-optional, not an error: the
            // concept is still listed, just with no `type`.
            let type_ = frontmatter
                .get("type")
                .and_then(|v| v.as_str())
                .filter(|s| !s.is_empty())
                .map(str::to_string);
            let deprecated = frontmatter
                .get("status")
                .and_then(|v| v.as_str())
                .is_some_and(|s| s == "deprecated");
            if deprecated && !include_deprecated {
                return;
            }
            concepts.push(ListedConcept {
                slug: crate::crud::relative_slug(bundle, &path),
                type_,
            });
        },
    )?;
    concepts.sort_by(|a, b| a.slug.cmp(&b.slug));
    Ok(concepts)
}

/// Reserved bundle filenames (OKF v0.2 §3.1, strict set): never concept
/// documents. Deliberately narrower than [`crate::bundle::is_reserved`]
/// (which also skips `README.md`) — `README.md` with frontmatter is listed
/// here as a concept, unlike in `registry::search`/`search_text`. Named
/// `_strict` rather than shadowing `bundle::is_reserved` so this divergence
/// is visible at the call site instead of silent.
fn is_reserved_strict(name: &str) -> bool {
    matches!(name, "index.md" | "log.md")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    #[test]
    fn list_returns_sorted_slugs_with_types() {
        let dir = tempdir("okf-core-list-sorted");
        std::fs::write(dir.join("zebra.md"), b"---\ntype: animal\n---\nz").unwrap();
        std::fs::write(dir.join("apple.md"), b"---\ntype: fruit\n---\na").unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(
            got,
            vec![
                ListedConcept {
                    slug: "apple".into(),
                    type_: Some("fruit".into())
                },
                ListedConcept {
                    slug: "zebra".into(),
                    type_: Some("animal".into())
                },
            ]
        );
    }

    #[test]
    fn list_excludes_reserved_and_non_md_files() {
        let dir = tempdir("okf-core-list-excludes");
        std::fs::write(dir.join("doc.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(dir.join("index.md"), b"# index").unwrap();
        std::fs::write(dir.join("log.md"), b"# log").unwrap();
        std::fs::write(dir.join("notes.txt"), b"not a concept").unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].slug, "doc");
    }

    #[test]
    fn list_recurses_into_subdirectories() {
        let dir = tempdir("okf-core-list-recurses");
        std::fs::write(dir.join("root.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::create_dir(dir.join("decision")).unwrap();
        std::fs::write(
            dir.join("decision/nested.md"),
            b"---\ntype: decision\n---\n",
        )
        .unwrap();
        std::fs::write(dir.join("decision/index.md"), b"# index").unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(
            got,
            vec![
                ListedConcept {
                    slug: "decision/nested".into(),
                    type_: Some("decision".into())
                },
                ListedConcept {
                    slug: "root".into(),
                    type_: Some("decision".into())
                },
            ]
        );
    }

    #[test]
    fn list_empty_bundle_is_empty_vec() {
        let dir = tempdir("okf-core-list-empty");
        assert_eq!(list(&dir, false).unwrap(), Vec::<ListedConcept>::new());
    }

    /// Regression: the same no-`type` concept, both indexed by the registry
    /// and listed via `crud::list::list`, errors on neither path.
    #[test]
    fn registry_list_no_type_no_error() {
        let dir = tempdir("okf-core-registry-list-no-type");
        std::fs::write(dir.join("bad.md"), b"---\ntitle: no type\n---\n").unwrap();

        let registry_got = crate::registry::search(std::slice::from_ref(&dir), &[]).unwrap();
        assert_eq!(
            registry_got
                .iter()
                .map(|e| e.slug.as_str())
                .collect::<Vec<_>>(),
            vec!["bad"]
        );

        let list_got = list(&dir, false).unwrap();
        assert_eq!(
            list_got,
            vec![ListedConcept {
                slug: "bad".into(),
                type_: None,
            }]
        );
    }

    #[test]
    fn crud_list_missing_type_no_error() {
        let dir = tempdir("okf-core-list-missing-type");
        std::fs::write(dir.join("bad.md"), b"---\ntitle: no type\n---\n").unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(
            got,
            vec![ListedConcept {
                slug: "bad".into(),
                type_: None,
            }],
            "a concept with no `type` field is not an error and is listed: {got:?}"
        );
    }

    #[test]
    fn filter_excludes_missing_type() {
        // `list` itself has no `type=X` filter parameter — the filtering
        // semantics live in `registry::search` — but this documents that a
        // concept missing `type` still surfaces with `type_: None` so a
        // caller filtering on the listed result excludes it naturally.
        let dir = tempdir("okf-core-list-filter-excludes-missing-type");
        std::fs::write(dir.join("typed.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(dir.join("untyped.md"), b"---\ntitle: no type\n---\n").unwrap();
        let got = list(&dir, false).unwrap();
        let matching_decision: Vec<_> = got
            .iter()
            .filter(|c| c.type_.as_deref() == Some("decision"))
            .map(|c| c.slug.as_str())
            .collect();
        assert_eq!(
            matching_decision,
            vec!["typed"],
            "a concept missing `type` must be excluded from a type=X filter, not error: {got:?}"
        );
    }
    #[test]
    fn list_excludes_deprecated_by_default() {
        let dir = tempdir("okf-core-list-deprecated-default");
        std::fs::write(dir.join("live.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(
            dir.join("dead.md"),
            b"---\ntype: decision\nstatus: deprecated\n---\n",
        )
        .unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(got.len(), 1);
        assert_eq!(got[0].slug, "live");
    }

    #[test]
    fn list_includes_deprecated_with_flag() {
        let dir = tempdir("okf-core-list-deprecated-included");
        std::fs::write(dir.join("live.md"), b"---\ntype: decision\n---\n").unwrap();
        std::fs::write(
            dir.join("dead.md"),
            b"---\ntype: decision\nstatus: deprecated\n---\n",
        )
        .unwrap();
        let got = list(&dir, true).unwrap();
        assert_eq!(got.len(), 2);
    }

    #[test]
    fn list_without_deprecated_concepts_is_unchanged() {
        let dir = tempdir("okf-core-list-none-deprecated");
        std::fs::write(
            dir.join("draft.md"),
            b"---\ntype: decision\nstatus: draft\n---\n",
        )
        .unwrap();
        let got = list(&dir, false).unwrap();
        assert_eq!(
            got.len(),
            1,
            "draft is not deprecated and must still be listed"
        );
    }
}
