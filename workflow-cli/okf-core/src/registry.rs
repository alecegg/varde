//! Ephemeral in-memory frontmatter registry: walk one or more Knowledge
//! Bundles, parse each Concept's frontmatter, and return the entries whose
//! fields exactly match the given filter values.
//!
//! Rebuilt fully on every call — no cached index file, no staleness
//! tracking (per plan decision). Matching is exact-value only: a scalar
//! field matches when its canonical string form equals the filter value,
//! and a sequence field (e.g. `tags`) matches when any element matches.
//! Fuzzy/substring/full-text matching is out of scope.
//!
//! Traversal mirrors `lint.rs`'s bundle-tree walk (OKF v0.2 §3: a
//! directory tree from one root down through all subdirectories): hidden
//! entries, artifact directories (`target`, `node_modules`), and symlinks
//! are skipped; `index.md`/`log.md`/`README.md` are bundle bookkeeping,
//! never Concepts.

use crate::bundle::is_reserved;
use crate::frontmatter::FrontmatterError;
use serde::Serialize;
use std::collections::BTreeMap;
use std::io;
use std::path::PathBuf;
use thiserror::Error;

/// One registry hit: the Concept's slug, its `type` (absent when the
/// Concept has no `type` field — that is not an error at this layer, see
/// [`RegistryError`]), and its full parsed frontmatter (so callers can
/// surface the matching field without a second read).
#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct RegistryEntry {
    pub slug: String,
    #[serde(rename = "type")]
    pub type_: Option<String>,
    pub frontmatter: serde_yaml::Value,
}

/// Typed errors for registry queries — infrastructure and conformance
/// failures only. A Concept with unparseable frontmatter is a typed error,
/// never a silent skip, matching `crud::list`'s strictness. A Concept with
/// no `type` field is *not* an error here — it's absent-optional: it
/// appears in unfiltered results and is naturally excluded (not erroring)
/// by a `type=X` filter.
#[derive(Debug, Error)]
pub enum RegistryError {
    #[error("failed to read bundle directory `{path}`: {source}")]
    ReadDirFailed { path: PathBuf, source: io::Error },
    #[error("failed to read `{path}`: {source}")]
    ReadFailed { path: PathBuf, source: io::Error },
    #[error("`{path}` is not a valid OKF concept: {source}")]
    InvalidConcept {
        path: PathBuf,
        source: FrontmatterError,
    },
}

impl From<crate::walk::WalkError> for RegistryError {
    fn from(err: crate::walk::WalkError) -> Self {
        match err {
            crate::walk::WalkError::ReadDirFailed { path, source } => {
                RegistryError::ReadDirFailed { path, source }
            }
            crate::walk::WalkError::ReadFailed { path, source } => {
                RegistryError::ReadFailed { path, source }
            }
            crate::walk::WalkError::InvalidConcept { path, source } => {
                RegistryError::InvalidConcept { path, source }
            }
        }
    }
}

/// Query the registry across one or more bundles.
///
/// Every entry whose frontmatter matches *all* filters (`AND` semantics
/// across `filters`) is returned, deduplicated by slug with **later bundles
/// in the slice winning** same-slug collisions (mirroring
/// [`crate::vault::list_merged`]'s insert-later-wins precedence), sorted by
/// slug. A `filter`'s key that is absent from a Concept's frontmatter never
/// matches. Passing an empty filter list returns every Concept.
///
/// A filter value matches a frontmatter field exactly:
/// - a YAML string matches when it equals the filter value;
/// - any other scalar (`number`, `bool`) matches when its canonical string
///   form equals the filter value (e.g. `42`, `true`);
/// - a sequence (e.g. `tags: [a, b]`) matches when any element matches;
/// - a mapping or null never matches.
pub fn search(
    bundles: &[PathBuf],
    filters: &[(String, String)],
) -> Result<Vec<RegistryEntry>, RegistryError> {
    let mut merged: BTreeMap<String, RegistryEntry> = BTreeMap::new();
    for bundle in bundles {
        crate::walk::visit_concepts(
            bundle,
            &is_reserved,
            |crate::walk::WalkedFile {
                 path, frontmatter, ..
             }| {
                // A missing/empty `type` is absent-optional, not an error: the
                // Concept still participates in unfiltered results and is
                // simply excluded by a `type=X` filter via `matches_all` below.
                let type_ = frontmatter
                    .get("type")
                    .and_then(|v| v.as_str())
                    .filter(|s| !s.is_empty())
                    .map(str::to_string);
                if !matches_all(&frontmatter, filters) {
                    return;
                }
                let slug = crate::crud::relative_slug(bundle, &path);
                // Inserting later bundles last makes them win same-slug
                // collisions, and the map keeps the result sorted by slug.
                merged.insert(
                    slug.clone(),
                    RegistryEntry {
                        slug,
                        type_,
                        frontmatter,
                    },
                );
            },
        )?;
    }
    Ok(merged.into_values().collect())
}

/// Whether every filter matches `frontmatter` (AND semantics).
pub(crate) fn matches_all(frontmatter: &serde_yaml::Value, filters: &[(String, String)]) -> bool {
    filters
        .iter()
        .all(|(key, value)| field_matches(frontmatter.get(key), value))
}

/// Exact-value match of a single field against a filter value (see
/// [`search`] for the semantics).
fn field_matches(field: Option<&serde_yaml::Value>, filter: &str) -> bool {
    match field {
        None => false,
        Some(serde_yaml::Value::String(s)) => s == filter,
        Some(serde_yaml::Value::Bool(b)) => b.to_string() == filter,
        Some(serde_yaml::Value::Number(n)) => n.to_string() == filter,
        Some(serde_yaml::Value::Sequence(items)) => {
            items.iter().any(|item| field_matches(Some(item), filter))
        }
        Some(serde_yaml::Value::Tagged(tagged)) => field_matches(Some(&tagged.value), filter),
        Some(serde_yaml::Value::Mapping(_)) | Some(serde_yaml::Value::Null) => false,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;
    use serde_yaml::Value;
    use std::path::Path;

    fn write(dir: &Path, name: &str, content: &str) {
        std::fs::write(dir.join(name), content).unwrap();
    }

    fn concept(fields: &str, body: &str) -> String {
        format!("---\ntype: decision\n{fields}---\n{body}")
    }

    fn one_filter(key: &str, value: &str) -> Vec<(String, String)> {
        vec![(key.to_string(), value.to_string())]
    }

    #[test]
    fn type_filter_returns_only_matching_types() {
        let dir = tempdir("okf-core-registry-type");
        write(&dir, "decision-a.md", &concept("", "# a\n"));
        write(&dir, "pattern-b.md", "---\ntype: pattern\n---\n# b\n");
        write(&dir, "decision-c.md", "---\ntype: decision\n---\n# c\n");

        let got = search(&[dir], &one_filter("type", "decision")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["decision-a", "decision-c"],
            "only decision-typed concepts: {got:?}"
        );
    }

    #[test]
    fn status_filter_matches_only_concepts_with_that_status() {
        let dir = tempdir("okf-core-registry-status");
        write(
            &dir,
            "dead.md",
            &concept("status: deprecated\n", "# dead\n"),
        );
        write(&dir, "live.md", &concept("", "# live\n"));
        write(&dir, "draft.md", &concept("status: draft\n", "# draft\n"));

        let got = search(&[dir], &one_filter("status", "deprecated")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["dead"],
            "concepts without the status must not match: {got:?}"
        );
    }

    #[test]
    fn reserved_files_are_excluded() {
        let dir = tempdir("okf-core-registry-reserved");
        write(&dir, "index.md", "# index");
        write(&dir, "log.md", "# log");
        write(&dir, "README.md", "# readme");
        write(&dir, "doc.md", &concept("", "# doc\n"));
        write(&dir, "notes.txt", "not a concept");

        let got = search(&[dir], &[]).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["doc"],
            "reserved and non-`.md` files must not be entries: {got:?}"
        );
    }

    #[test]
    fn custom_extension_field_is_filterable() {
        let dir = tempdir("okf-core-registry-custom");
        write(
            &dir,
            "hot.md",
            &concept("recall_priority: high\n", "# hot\n"),
        );
        write(
            &dir,
            "cold.md",
            &concept("recall_priority: low\n", "# cold\n"),
        );
        write(&dir, "none.md", &concept("", "# none\n"));

        let got = search(&[dir], &one_filter("recall_priority", "high")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["hot"],
            "custom fields are filterable: {got:?}"
        );
    }

    #[test]
    fn multiple_bundles_merge_with_later_bundle_winning_collisions() {
        let a = tempdir("okf-core-registry-merge-a");
        let b = tempdir("okf-core-registry-merge-b");
        write(&a, "shared.md", "---\ntype: decision\norigin: a\n---\n");
        write(&a, "only-a.md", "---\ntype: decision\n---\n");
        write(&b, "shared.md", "---\ntype: decision\norigin: b\n---\n");
        write(&b, "only-b.md", "---\ntype: pattern\n---\n");

        let got = search(&[a, b], &[]).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["only-a", "only-b", "shared"],
            "union across bundles, sorted: {got:?}"
        );
        let shared = got.iter().find(|e| e.slug == "shared").unwrap();
        assert_eq!(
            shared.frontmatter["origin"],
            Value::String("b".into()),
            "later bundle wins the collision: {shared:?}"
        );
    }

    #[test]
    fn nested_subdirectory_concepts_are_found() {
        let dir = tempdir("okf-core-registry-nested");
        write(&dir, "index.md", "# index");
        let sub = dir.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(
            &sub,
            "leaf.md",
            &concept("status: deprecated\n", "# leaf\n"),
        );

        let got = search(&[dir], &one_filter("status", "deprecated")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["sub/leaf"],
            "a Concept at any depth is an entry, reported by its bundle-relative slug: {got:?}"
        );
    }

    #[test]
    fn nested_slug_reported_by_search_matches_list_and_is_showable() {
        // The slug `search` reports for a nested concept must agree with
        // `crud::list::list`'s slug (both derive from `crud::relative_slug`)
        // and must be directly addressable by `crud::show::show`.
        let dir = tempdir("okf-core-registry-nested-showable");
        std::fs::create_dir(dir.join("decision")).unwrap();
        write(&dir, "decision/nested.md", &concept("", "# nested\n"));

        let listed = crate::crud::list::list(&dir, false).unwrap();
        assert_eq!(listed.len(), 1);
        assert_eq!(listed[0].slug, "decision/nested");

        let found = search(std::slice::from_ref(&dir), &[]).unwrap();
        assert_eq!(found.len(), 1);
        assert_eq!(found[0].slug, listed[0].slug);

        let shown = crate::crud::show::show(&dir, &found[0].slug).unwrap();
        assert_eq!(shown.slug, "decision/nested");
    }

    #[test]
    fn tags_sequence_matches_any_element_exactly() {
        let dir = tempdir("okf-core-registry-tags");
        write(
            &dir,
            "tagged.md",
            &concept("tags:\n  - rust\n  - cli\n", "# tagged\n"),
        );
        write(&dir, "untagged.md", &concept("", "# untagged\n"));

        let got = search(&[dir], &one_filter("tags", "rust")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["tagged"],
            "a sequence field matches when any element matches: {got:?}"
        );
    }

    #[test]
    fn numeric_and_boolean_scalars_match_their_canonical_form() {
        let dir = tempdir("okf-core-registry-scalars");
        write(&dir, "num.md", &concept("priority: 42\n", "# num\n"));
        write(&dir, "flag.md", &concept("verified: true\n", "# flag\n"));

        let got = search(std::slice::from_ref(&dir), &one_filter("priority", "42")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["num"]
        );
        let got = search(&[dir], &one_filter("verified", "true")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["flag"]
        );
    }

    #[test]
    fn and_semantics_across_multiple_filters() {
        let dir = tempdir("okf-core-registry-and");
        write(
            &dir,
            "both.md",
            &concept("status: deprecated\nrecall_priority: high\n", "# both\n"),
        );
        write(
            &dir,
            "only-status.md",
            &concept("status: deprecated\n", "# only-status\n"),
        );

        let got = search(
            &[dir],
            &[
                ("status".to_string(), "deprecated".to_string()),
                ("recall_priority".to_string(), "high".to_string()),
            ],
        )
        .unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["both"],
            "all filters must match: {got:?}"
        );
    }

    #[test]
    fn empty_filter_list_returns_every_concept_sorted() {
        let dir = tempdir("okf-core-registry-all");
        write(&dir, "zebra.md", "---\ntype: animal\n---\n");
        write(&dir, "apple.md", "---\ntype: fruit\n---\n");

        let got = search(&[dir], &[]).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["apple", "zebra"],
            "no filters returns all entries sorted by slug"
        );
    }

    #[test]
    fn registry_search_missing_type_no_error() {
        let dir = tempdir("okf-core-registry-missing-type");
        write(&dir, "bad.md", "---\ntitle: no type\n---\n");
        let got = search(&[dir], &[]).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["bad"],
            "a concept with no `type` field is not an error and is included in unfiltered results: {got:?}"
        );
        assert_eq!(got[0].type_, None);
    }

    #[test]
    fn filter_excludes_missing_type() {
        let dir = tempdir("okf-core-registry-filter-excludes-missing-type");
        write(&dir, "typed.md", "---\ntype: decision\n---\n");
        write(&dir, "untyped.md", "---\ntitle: no type\n---\n");

        let got = search(&[dir], &one_filter("type", "decision")).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["typed"],
            "a concept missing `type` must be excluded (not erroring) by a type=X filter: {got:?}"
        );
    }

    #[test]
    fn unparseable_frontmatter_is_typed_error() {
        let dir = tempdir("okf-core-registry-bad-yaml");
        write(&dir, "bad.md", "---\n: not yaml :(\n---\n");
        assert!(matches!(
            search(&[dir], &[]).unwrap_err(),
            RegistryError::InvalidConcept { .. }
        ));
    }

    #[test]
    fn missing_bundle_dir_is_typed_error() {
        let dir = tempdir("okf-core-registry-missing-dir");
        assert!(matches!(
            search(&[dir.join("does-not-exist")], &[]).unwrap_err(),
            RegistryError::ReadDirFailed { .. }
        ));
    }

    #[test]
    fn hidden_and_artifact_dirs_are_skipped() {
        let dir = tempdir("okf-core-registry-hidden");
        write(&dir, "doc.md", &concept("", "# doc\n"));
        for hidden in [".git", "target", "node_modules"] {
            let sub = dir.join(hidden);
            std::fs::create_dir(&sub).unwrap();
            write(&sub, "bad.md", &concept("", "# bad\n"));
        }
        let got = search(&[dir], &[]).unwrap();
        assert_eq!(
            got.iter().map(|e| e.slug.as_str()).collect::<Vec<_>>(),
            vec!["doc"],
            "hidden/artifact trees must not be scanned: {got:?}"
        );
    }
}
