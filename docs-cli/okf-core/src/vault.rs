//! Personal Vault + Project Vault layering: merge-at-recall for
//! `list`/`show`, with the Project Vault winning same-slug collisions
//! (`memory-bank/knowledge/decision/bundle-merge-precedence.md`).
//!
//! The Personal Vault is a plain Knowledge Bundle at a fixed default path
//! (see [`personal_vault_path`]); merging is a read-time concern only —
//! nothing merged is ever persisted.

use crate::crud::list::{ListError, ListedConcept, list};
use crate::crud::search::{TextSearchError, TextSearchResult, search_text};
use crate::crud::show::{ShowError, ShownConcept, show};
use crate::crud::ConceptIoError;
use crate::lint::{LintError, LintReport, lint, lint_okf};
use crate::registry::{self, RegistryEntry, RegistryError};
use std::collections::BTreeMap;
use std::env;
use std::io;
use std::path::{Path, PathBuf};

/// The fixed default location of the Personal Vault: `~/.varde-docs/`.
///
/// The Personal Vault is a plain Knowledge Bundle at this path, shared
/// across all projects (mirrors pi-llm-wiki's `~/.llm-wiki/` convention).
/// When `dirs::home_dir()` returns `None` — no usable home directory —
/// fall back to a relative `.varde-docs/` in the current working
/// directory rather than failing; a missing home directory must not make
/// vault-aware commands unusable.
pub fn personal_vault_path() -> PathBuf {
    dirs::home_dir()
        .map(|home| home.join(".varde-docs"))
        .unwrap_or_else(|| PathBuf::from(".varde-docs"))
}

/// Which vault a filtering call narrows to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum VaultSelector {
    /// The Personal Vault at [`personal_vault_path`] (`~/.varde-docs/`).
    Personal,
    /// The Project Vault — the bundle root the caller threads in (the CLI's
    /// `--bundle`), or the current working directory when absent.
    Project,
}

/// The Project Vault root when the caller threads no path in: the current
/// working directory (documented fallback — running the CLI inside a
/// bundle's root must work without a `--bundle` flag).
fn project_root_fallback() -> PathBuf {
    env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

/// List concepts under a filtering resolution (see [`list_filtered`]).
///
/// Resolution matrix, applied by [`list_filtered`]/[`lint_filtered`] with
/// `vault` = the vault selector and `bundle` = the caller-threaded path
/// (the CLI's `--bundle`):
///
/// - `(None, None)`: default both-vaults merge; the Project Vault root is
///   [`project_root_fallback`].
/// - `(None, Some(p))`: default both-vaults merge; `p` is the Project Vault
///   root — today's `--bundle` behavior, unchanged.
/// - `(Some(Personal), None)`: the Personal Vault alone. A missing
///   Personal Vault directory is an empty result, never an error.
/// - `(Some(Personal), Some(p))`: a **relative** `p` filters within the
///   Personal Vault root (`personal_vault_path().join(p)`); an absolute
///   `p` has nothing to filter against (the root is fixed) and is
///   ignored, falling back to the Personal Vault alone.
/// - `(Some(Project), None)`: the Project Vault alone at
///   [`project_root_fallback`].
/// - `(Some(Project), Some(p))`: the Project Vault alone at `p` — `p` is
///   scanned directly (typically a subdirectory of the project root), and
///   the Personal Vault is excluded.
///
/// This is composition only: `list`/`list_merged` are reused unmodified.
pub fn list_filtered(
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    include_deprecated: bool,
) -> Result<Vec<ListedConcept>, ListError> {
    match (vault, bundle) {
        (None, None) => list_merged(&project_root_fallback(), include_deprecated),
        (None, Some(p)) => list_merged(p, include_deprecated),
        (Some(VaultSelector::Personal), None) => {
            list_or_empty(&personal_vault_path(), include_deprecated)
        }
        (Some(VaultSelector::Personal), Some(p)) if p.is_relative() => {
            list_or_empty(&personal_vault_path().join(p), include_deprecated)
        }
        (Some(VaultSelector::Personal), Some(_)) => {
            list_or_empty(&personal_vault_path(), include_deprecated)
        }
        (Some(VaultSelector::Project), None) => list(&project_root_fallback(), include_deprecated),
        (Some(VaultSelector::Project), Some(p)) => list(p, include_deprecated),
    }
}

/// Lint concepts under the same filtering resolution as [`list_filtered`]:
/// the default is a two-vault lint whose report concatenates the Project
/// and Personal Vault reports (a missing Personal Vault contributes
/// nothing); a single-vault or single-path resolution lints just that
/// target. Composition only — [`lint`] is reused unmodified.
///
/// `okf` selects the opt-in OKF-mode entry point ([`lint_okf`]) instead of
/// the default base-only [`lint`] for every bundle this call touches.
pub fn lint_filtered(
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    okf: bool,
) -> Result<LintReport, LintError> {
    match (vault, bundle) {
        (None, None) => lint_merged(&project_root_fallback(), okf),
        (None, Some(p)) => lint_merged(p, okf),
        (Some(VaultSelector::Personal), None) => lint_or_empty(&personal_vault_path(), okf),
        (Some(VaultSelector::Personal), Some(p)) if p.is_relative() => {
            lint_or_empty(&personal_vault_path().join(p), okf)
        }
        (Some(VaultSelector::Personal), Some(_)) => lint_or_empty(&personal_vault_path(), okf),
        (Some(VaultSelector::Project), None) => lint_with_mode(&project_root_fallback(), okf),
        (Some(VaultSelector::Project), Some(p)) => lint_with_mode(p, okf),
    }
}

/// Dispatch to [`lint`] or [`lint_okf`] based on `okf`.
fn lint_with_mode(bundle: &Path, okf: bool) -> Result<LintReport, LintError> {
    if okf { lint_okf(bundle) } else { lint(bundle) }
}

/// [`list`] treating a missing bundle directory as an empty result.
fn list_or_empty(bundle: &Path, include_deprecated: bool) -> Result<Vec<ListedConcept>, ListError> {
    match list(bundle, include_deprecated) {
        Ok(concepts) => Ok(concepts),
        Err(ListError::ReadDirFailed { source, .. })
            if source.kind() == io::ErrorKind::NotFound =>
        {
            Ok(Vec::new())
        }
        Err(err) => Err(err),
    }
}

/// Query the frontmatter registry under a filtering resolution — the
/// registry analogue of [`list_filtered`], with the same vault/bundle
/// resolution matrix (Personal Vault first, Project Vault last so the
/// Project Vault wins same-slug collisions, per
/// `memory-bank/knowledge/decision/bundle-merge-precedence.md`).
///
/// Composition only: [`registry::search`] is reused unmodified; a missing
/// Personal Vault directory contributes nothing, never an error.
pub fn search_filtered(
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    filters: &[(String, String)],
) -> Result<Vec<RegistryEntry>, RegistryError> {
    match (vault, bundle) {
        (None, None) => search_merged(&project_root_fallback(), filters),
        (None, Some(p)) => search_merged(p, filters),
        (Some(VaultSelector::Personal), None) => search_or_empty(&personal_vault_path(), filters),
        (Some(VaultSelector::Personal), Some(p)) if p.is_relative() => {
            search_or_empty(&personal_vault_path().join(p), filters)
        }
        (Some(VaultSelector::Personal), Some(_)) => search_or_empty(&personal_vault_path(), filters),
        (Some(VaultSelector::Project), None) => {
            registry::search(std::slice::from_ref(&project_root_fallback()), filters)
        }
        (Some(VaultSelector::Project), Some(p)) => {
            registry::search(std::slice::from_ref(&p.to_path_buf()), filters)
        }
    }
}

/// Query the registry across the merged Project + Personal Vault set: the
/// Personal Vault first, the Project Vault last (Project Vault wins
/// same-slug collisions). A missing Personal Vault directory is skipped;
/// a missing Project bundle is a real error, matching [`list_merged`].
pub fn search_merged(
    project_bundle: &Path,
    filters: &[(String, String)],
) -> Result<Vec<RegistryEntry>, RegistryError> {
    let personal = personal_vault_path();
    let mut bundles = Vec::new();
    if personal.is_dir() {
        bundles.push(personal);
    }
    bundles.push(project_bundle.to_path_buf());
    registry::search(&bundles, filters)
}

/// [`registry::search`] treating a missing bundle directory as an empty
/// result (the registry analogue of [`list_or_empty`]).
fn search_or_empty(
    bundle: &Path,
    filters: &[(String, String)],
) -> Result<Vec<RegistryEntry>, RegistryError> {
    match registry::search(&[bundle.to_path_buf()], filters) {
        Ok(entries) => Ok(entries),
        Err(RegistryError::ReadDirFailed { source, .. })
            if source.kind() == io::ErrorKind::NotFound =>
        {
            Ok(Vec::new())
        }
        Err(err) => Err(err),
    }
}

/// Ranked lexical full-text search (`concept search --text`) under the same
/// filtering resolution as [`search_filtered`]: same vault/bundle
/// resolution matrix, same Personal-Vault-first/Project-Vault-wins merge
/// precedence. Composition only — [`crate::crud::search::search_text`] is
/// reused unmodified.
pub fn search_text_filtered(
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    query: &str,
    limit: usize,
) -> Result<Vec<TextSearchResult>, TextSearchError> {
    match (vault, bundle) {
        (None, None) => search_text_merged(&project_root_fallback(), query, limit),
        (None, Some(p)) => search_text_merged(p, query, limit),
        (Some(VaultSelector::Personal), None) => {
            search_text_or_empty(&personal_vault_path(), query, limit)
        }
        (Some(VaultSelector::Personal), Some(p)) if p.is_relative() => {
            search_text_or_empty(&personal_vault_path().join(p), query, limit)
        }
        (Some(VaultSelector::Personal), Some(_)) => {
            search_text_or_empty(&personal_vault_path(), query, limit)
        }
        (Some(VaultSelector::Project), None) => {
            search_text(&[project_root_fallback()], query, limit)
        }
        (Some(VaultSelector::Project), Some(p)) => search_text(&[p.to_path_buf()], query, limit),
    }
}

/// Full-text search across the merged Project + Personal Vault set: the
/// Personal Vault first, the Project Vault last (Project Vault wins
/// same-slug collisions), mirroring [`search_merged`].
pub fn search_text_merged(
    project_bundle: &Path,
    query: &str,
    limit: usize,
) -> Result<Vec<TextSearchResult>, TextSearchError> {
    let personal = personal_vault_path();
    let mut bundles = Vec::new();
    if personal.is_dir() {
        bundles.push(personal);
    }
    bundles.push(project_bundle.to_path_buf());
    search_text(&bundles, query, limit)
}

/// [`crate::crud::search::search_text`] treating a missing bundle directory
/// as an empty result (the full-text analogue of [`search_or_empty`]).
fn search_text_or_empty(
    bundle: &Path,
    query: &str,
    limit: usize,
) -> Result<Vec<TextSearchResult>, TextSearchError> {
    match search_text(&[bundle.to_path_buf()], query, limit) {
        Ok(entries) => Ok(entries),
        Err(TextSearchError::ReadDirFailed { source, .. })
            if source.kind() == io::ErrorKind::NotFound =>
        {
            Ok(Vec::new())
        }
        Err(err) => Err(err),
    }
}

/// Two-vault lint: concatenate the Project and Personal Vault reports. A
/// missing Personal Vault contributes nothing; real errors propagate.
fn lint_merged(project_bundle: &Path, okf: bool) -> Result<LintReport, LintError> {
    let project = lint_with_mode(project_bundle, okf)?;
    let personal = lint_or_empty(&personal_vault_path(), okf)?;
    Ok(LintReport {
        issues: project.issues.into_iter().chain(personal.issues).collect(),
    })
}

/// [`lint`]/[`lint_okf`] treating a missing bundle directory as an empty
/// report.
fn lint_or_empty(bundle: &Path, okf: bool) -> Result<LintReport, LintError> {
    match lint_with_mode(bundle, okf) {
        Ok(report) => Ok(report),
        Err(LintError::ReadDirFailed { source, .. })
            if source.kind() == io::ErrorKind::NotFound =>
        {
            Ok(LintReport { issues: Vec::new() })
        }
        Err(err) => Err(err),
    }
}

/// List the merged Personal + Project Vault concept sets.
///
/// The Personal Vault is listed first, then any Project Vault entry with
/// the same slug overrides the Personal Vault entry (Project Vault wins).
/// A missing Personal Vault directory counts as an empty list, not an
/// error. The result is sorted by slug, matching [`list`]'s contract.
pub fn list_merged(
    project_bundle: &Path,
    include_deprecated: bool,
) -> Result<Vec<ListedConcept>, ListError> {
    list_merged_at(project_bundle, &personal_vault_path(), include_deprecated)
}

/// [`list_merged`] with a substitutable Personal Vault path (test seam).
fn list_merged_at(
    project_bundle: &Path,
    personal_vault: &Path,
    include_deprecated: bool,
) -> Result<Vec<ListedConcept>, ListError> {
    let personal = match list(personal_vault, include_deprecated) {
        Ok(concepts) => concepts,
        // A missing Personal Vault directory is silently empty — opt-in
        // layering must not fail before the Vault exists. Matches the
        // io-error-kind inspection style of `crud::show::show`.
        Err(ListError::ReadDirFailed { source, .. })
            if source.kind() == io::ErrorKind::NotFound =>
        {
            Vec::new()
        }
        Err(err) => return Err(err),
    };

    let mut merged: BTreeMap<String, ListedConcept> = BTreeMap::new();
    for concept in personal {
        merged.insert(concept.slug.clone(), concept);
    }
    // Inserting the Project Vault entries last makes them win same-slug
    // collisions, and the map keeps the result sorted by slug.
    for concept in list(project_bundle, include_deprecated)? {
        merged.insert(concept.slug.clone(), concept);
    }
    Ok(merged.into_values().collect())
}

/// A concept shown through the merged vault view, plus the bundle that
/// actually served it.
///
/// The serving bundle is the Project Vault on a direct hit and the
/// Personal Vault on the [`ConceptIoError::NotFound`] fallback; callers
/// that need vault-derived context (e.g. git timestamps) must use it
/// rather than assuming the Project Vault.
#[derive(Debug, Clone, PartialEq)]
pub struct ShownConceptWithSource {
    /// The concept as shown.
    pub concept: ShownConcept,
    /// The bundle that served the request.
    pub bundle: PathBuf,
}

/// Show a concept from the Project Vault, falling back to the Personal
/// Vault only when the Project Vault reports
/// [`ConceptIoError::NotFound`] (wrapped in [`ShowError::Io`]).
///
/// Any other error (invalid slug, read failure, concept parse error)
/// propagates immediately without consulting the Personal Vault.
pub fn show_merged(
    project_bundle: &Path,
    slug: &str,
) -> Result<ShownConceptWithSource, ShowError> {
    show_merged_at(project_bundle, slug, &personal_vault_path())
}

/// [`show_merged`] with a substitutable Personal Vault path (test seam).
fn show_merged_at(
    project_bundle: &Path,
    slug: &str,
    personal_vault: &Path,
) -> Result<ShownConceptWithSource, ShowError> {
    match show(project_bundle, slug) {
        Ok(concept) => Ok(ShownConceptWithSource {
            concept,
            bundle: project_bundle.to_path_buf(),
        }),
        Err(ShowError::Io(ConceptIoError::NotFound { .. })) => {
            match show(personal_vault, slug) {
                Ok(concept) => Ok(ShownConceptWithSource {
                    concept,
                    bundle: personal_vault.to_path_buf(),
                }),
                Err(err) => Err(err),
            }
        }
        Err(err) => Err(err),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::lint::CheckKind;
    use crate::test_support::tempdir;

    /// Write a minimal OKF concept (`slug.md`) with the given `type`.
    fn write_concept(dir: &Path, slug: &str, type_: &str, body: &str) {
        std::fs::write(
            dir.join(format!("{slug}.md")),
            format!("---\ntype: {type_}\n---\n{body}"),
        )
        .unwrap();
    }

    #[test]
    fn list_merged_project_wins_on_collision_and_stays_sorted() {
        let project = tempdir("okf-core-vault-list-project");
        let personal = tempdir("okf-core-vault-list-personal");
        write_concept(&project, "a", "project-a", "");
        write_concept(&personal, "a", "personal-a", "");
        write_concept(&personal, "b", "personal-b", "");

        let got = list_merged_at(&project, &personal, false).unwrap();
        assert_eq!(
            got,
            vec![
                ListedConcept {
                    slug: "a".into(),
                    type_: Some("project-a".into()),
                },
                ListedConcept {
                    slug: "b".into(),
                    type_: Some("personal-b".into()),
                },
            ]
        );
    }

    #[test]
    fn list_merged_missing_personal_vault_is_empty_list() {
        let project = tempdir("okf-core-vault-list-project-only");
        let missing_personal = tempdir("okf-core-vault-list-missing-parent").join("no-vault-here");
        write_concept(&project, "a", "project-a", "");

        let got = list_merged_at(&project, &missing_personal, false).unwrap();
        assert_eq!(
            got,
            vec![ListedConcept {
                slug: "a".into(),
                type_: Some("project-a".into()),
            }]
        );
    }

    #[test]
    fn list_merged_personal_vault_missing_type_is_not_error() {
        let project = tempdir("okf-core-vault-list-personal-error-project");
        let personal = tempdir("okf-core-vault-list-personal-error-personal");
        // A concept missing `type` is absent-optional, not an error: it
        // still surfaces in the merged listing with `type_: None`.
        std::fs::write(personal.join("bad.md"), b"---\ntitle: no type\n---\n").unwrap();

        let got = list_merged_at(&project, &personal, false).unwrap();
        assert_eq!(
            got.iter().map(|c| c.slug.as_str()).collect::<Vec<_>>(),
            vec!["bad"],
            "missing `type` in the Personal Vault must not fail the merged listing: {got:?}"
        );
    }

    #[test]
    fn list_merged_project_vault_error_propagates() {
        let project = tempdir("okf-core-vault-list-project-error");
        let personal = tempdir("okf-core-vault-list-project-error-personal");
        // Unparseable frontmatter remains a typed error (unchanged): the
        // merged listing must still fail.
        std::fs::write(project.join("bad.md"), b"---\n: not yaml :(\n---\n").unwrap();

        assert!(matches!(
            list_merged_at(&project, &personal, false).unwrap_err(),
            ListError::InvalidConcept { .. }
        ));
    }

    #[test]
    fn show_merged_falls_back_to_personal_vault_on_not_found() {
        let project = tempdir("okf-core-vault-show-project");
        let personal = tempdir("okf-core-vault-show-personal");
        write_concept(&personal, "only-personal", "decision", "personal body\n");

        let shown = show_merged_at(&project, "only-personal", &personal).unwrap();
        assert_eq!(shown.concept.slug, "only-personal");
        assert_eq!(shown.concept.frontmatter["type"], "decision");
        assert_eq!(shown.concept.body, "personal body\n");
        // The Personal Vault served the fallback, so it must be reported.
        assert_eq!(shown.bundle, personal);
    }

    #[test]
    fn show_merged_project_wins_without_consulting_personal_vault() {
        let project = tempdir("okf-core-vault-show-project-wins");
        let personal = tempdir("okf-core-vault-show-personal-wins");
        write_concept(&project, "both", "project-type", "project body\n");
        write_concept(&personal, "both", "personal-type", "personal body\n");

        let shown = show_merged_at(&project, "both", &personal).unwrap();
        assert_eq!(shown.concept.frontmatter["type"], "project-type");
        assert_eq!(shown.concept.body, "project body\n");
        // The Project Vault won the collision, so it must be reported.
        assert_eq!(shown.bundle, project);
    }

    #[test]
    fn show_merged_not_found_in_either_vault_is_not_found() {
        let project = tempdir("okf-core-vault-show-neither-project");
        let personal = tempdir("okf-core-vault-show-neither-personal");

        assert!(matches!(
            show_merged_at(&project, "nope", &personal).unwrap_err(),
            ShowError::Io(ConceptIoError::NotFound { .. })
        ));
    }

    #[test]
    fn show_merged_non_not_found_errors_do_not_fall_back() {
        let project = tempdir("okf-core-vault-show-invalid-project");
        let personal = tempdir("okf-core-vault-show-invalid-personal");
        write_concept(&personal, "UPPER", "decision", "");

        // An invalid slug is an `InvalidSlug` error from the Project Vault
        // call — it must propagate without falling back to the Personal
        // Vault, even though a matching file exists there.
        assert!(matches!(
            show_merged_at(&project, "UPPER", &personal).unwrap_err(),
            ShowError::Io(ConceptIoError::InvalidSlug { .. })
        ));
    }

    #[test]
    fn personal_vault_path_points_at_dot_varde_docs() {
        assert!(personal_vault_path().ends_with(".varde-docs"));
    }

    /// Serializes HOME-mutating tests: `dirs::home_dir` reads `$HOME`.
    static HOME_LOCK: std::sync::Mutex<()> = std::sync::Mutex::new(());

    /// Set `$HOME` to a fresh temp dir for the duration of `f`.
    fn with_home<F: FnOnce(&Path)>(f: F) {
        let _guard = HOME_LOCK.lock().unwrap();
        let original = std::env::var_os("HOME");
        let home = tempdir("okf-core-vault-filtered-home");
        unsafe { std::env::set_var("HOME", &home) };
        f(&home);
        match original {
            Some(v) => unsafe { std::env::set_var("HOME", v) },
            None => unsafe { std::env::remove_var("HOME") },
        }
    }

    fn write_personal(home: &Path, slug: &str, type_: &str) {
        let vault = home.join(".varde-docs");
        std::fs::create_dir_all(&vault).unwrap();
        std::fs::write(
            vault.join(format!("{slug}.md")),
            format!("---\ntype: {type_}\n---\n# Body\n"),
        )
        .unwrap();
    }

    #[test]
    fn list_filtered_default_merge_matches_list_merged() {
        with_home(|home| {
            write_personal(home, "fig", "fruit");
            let project = tempdir("okf-core-vault-filtered-merge-project");
            std::fs::write(
                project.join("apple.md"),
                b"---\ntype: fruit\n---\n# Apple\n",
            )
            .unwrap();
            let got = list_filtered(None, Some(&project), false).unwrap();
            let expected = list_merged(&project, false).unwrap();
            assert_eq!(got, expected);
            assert_eq!(got.len(), 2, "project + personal concepts");
            assert_eq!(got[0].slug, "apple");
            assert_eq!(got[1].slug, "fig");
        });
    }

    #[test]
    fn list_filtered_personal_only_excludes_project_concepts() {
        with_home(|home| {
            write_personal(home, "fig", "fruit");
            write_personal(home, "apple", "fruit");
            let project = tempdir("okf-core-vault-filtered-personal-project");
            std::fs::write(
                project.join("apple.md"),
                b"---\ntype: decision\n---\n# Project apple\n",
            )
            .unwrap();
            // vault alone, and vault with a caller-threaded path (ignored
            // for the Personal Vault, whose root is fixed).
            for bundle in [None, Some(project.as_path())] {
                let got = list_filtered(Some(VaultSelector::Personal), bundle, false).unwrap();
                assert_eq!(got.len(), 2, "personal only: {got:?}");
                assert!(got.iter().all(|c| c.type_.as_deref() == Some("fruit")));
                assert!(
                    got.iter().all(|c| c.type_.as_deref() != Some("decision")),
                    "project same-slug concept must not win: {got:?}"
                );
            }
        });
    }

    #[test]
    fn list_filtered_project_only_excludes_personal() {
        with_home(|home| {
            write_personal(home, "fig", "fruit");
            let project = tempdir("okf-core-vault-filtered-project-project");
            std::fs::write(
                project.join("apple.md"),
                b"---\ntype: fruit\n---\n# Apple\n",
            )
            .unwrap();
            let got = list_filtered(Some(VaultSelector::Project), Some(&project), false).unwrap();
            assert_eq!(got.len(), 1);
            assert_eq!(got[0].slug, "apple");
        });
    }

    #[test]
    fn list_filtered_project_bundle_subdirectory_scopes_scan() {
        let root = tempdir("okf-core-vault-filtered-subdir");
        std::fs::write(root.join("a.md"), b"---\ntype: decision\n---\n").unwrap();
        let sub = root.join("sub");
        std::fs::create_dir_all(&sub).unwrap();
        std::fs::write(sub.join("b.md"), b"---\ntype: decision\n---\n").unwrap();
        let got = list_filtered(Some(VaultSelector::Project), Some(&sub), false).unwrap();
        assert_eq!(
            got.len(),
            1,
            "only concepts under the subdirectory: {got:?}"
        );
        assert_eq!(got[0].slug, "b");
    }

    #[test]
    fn list_filtered_missing_personal_vault_is_empty_not_error() {
        with_home(|_home| {
            // No `.varde-docs` under this HOME.
            let project = tempdir("okf-core-vault-filtered-missing-project");
            std::fs::write(project.join("apple.md"), b"---\ntype: fruit\n---\n").unwrap();
            for bundle in [None, Some(project.as_path())] {
                let got = list_filtered(Some(VaultSelector::Personal), bundle, false).unwrap();
                assert!(got.is_empty(), "missing Personal Vault must be empty");
            }
        });
    }

    #[test]
    fn search_filtered_default_merge_finds_concepts_in_both_vaults() {
        with_home(|home| {
            write_personal(home, "fig", "decision");
            let project = tempdir("okf-core-vault-search-merge-project");
            std::fs::write(
                project.join("apple.md"),
                b"---\ntype: decision\n---\n# Apple\n",
            )
            .unwrap();
            let got = search_filtered(None, Some(&project), &[]).unwrap();
            assert_eq!(got.len(), 2, "project + personal concepts: {got:?}");
            assert_eq!(got[0].slug, "apple");
            assert_eq!(got[1].slug, "fig");
        });
    }

    #[test]
    fn search_filtered_project_wins_same_slug_collision() {
        with_home(|home| {
            write_personal(home, "fig", "decision");
            write_personal(home, "apple", "personal-type");
            let project = tempdir("okf-core-vault-search-project-wins");
            std::fs::write(
                project.join("apple.md"),
                b"---\ntype: project-type\n---\n# Project apple\n",
            )
            .unwrap();
            let got = search_filtered(None, Some(&project), &[]).unwrap();
            let apple = got.iter().find(|e| e.slug == "apple").unwrap();
            assert_eq!(
                apple.type_.as_deref(),
                Some("project-type"),
                "Project Vault must win: {got:?}"
            );
        });
    }

    #[test]
    fn search_filtered_project_only_excludes_personal() {
        with_home(|home| {
            write_personal(home, "fig", "decision");
            let project = tempdir("okf-core-vault-search-project-project");
            std::fs::write(project.join("apple.md"), b"---\ntype: decision\n---\n").unwrap();
            let got = search_filtered(Some(VaultSelector::Project), Some(&project), &[]).unwrap();
            assert_eq!(got.len(), 1);
            assert_eq!(got[0].slug, "apple");
        });
    }

    #[test]
    fn search_filtered_personal_only_with_missing_vault_is_empty() {
        with_home(|_home| {
            let got = search_filtered(Some(VaultSelector::Personal), None, &[]).unwrap();
            assert!(got.is_empty(), "missing Personal Vault must be empty");
        });
    }

    #[test]
    fn search_merged_missing_personal_vault_is_project_only() {
        with_home(|_home| {
            let project = tempdir("okf-core-vault-search-merged-missing-personal");
            std::fs::write(project.join("apple.md"), b"---\ntype: decision\n---\n").unwrap();
            let got = search_merged(&project, &[]).unwrap();
            assert_eq!(got.len(), 1);
            assert_eq!(got[0].slug, "apple");
        });
    }

    #[test]
    fn search_filtered_project_bundle_missing_is_error() {
        with_home(|_home| {
            let missing = tempdir("okf-core-vault-search-missing-project").join("nope");
            assert!(matches!(
                search_filtered(Some(VaultSelector::Project), Some(&missing), &[]).unwrap_err(),
                RegistryError::ReadDirFailed { .. }
            ));
        });
    }

    #[test]
    fn lint_filtered_default_merges_reports_from_both_vaults() {
        with_home(|home| {
            write_personal(home, "fig", "fruit");
            let project = tempdir("okf-core-vault-filtered-lint-merge-project");
            // Broken internal link -> Error-severity BrokenLink issue.
            std::fs::write(
                project.join("a.md"),
                b"---\ntype: decision\n---\n[b](missing.md)\n",
            )
            .unwrap();
            let report = lint_filtered(None, Some(&project), false).unwrap();
            let kinds: Vec<_> = report.issues.iter().map(|i| i.check_kind).collect();
            assert!(
                kinds.contains(&CheckKind::BrokenLink),
                "project issue must be reported: {kinds:?}"
            );
            assert!(
                kinds.contains(&CheckKind::MissingIndex),
                "personal-vault issue must be reported: {kinds:?}"
            );
        });
    }

    #[test]
    fn lint_filtered_personal_only_scopes_to_personal() {
        with_home(|home| {
            write_personal(home, "fig", "fruit");
            let project = tempdir("okf-core-vault-filtered-lint-personal-project");
            std::fs::write(
                project.join("a.md"),
                b"---\ntype: decision\n---\n[b](missing.md)\n",
            )
            .unwrap();
            let report = lint_filtered(Some(VaultSelector::Personal), None, false).unwrap();
            let kinds: Vec<_> = report.issues.iter().map(|i| i.check_kind).collect();
            assert!(
                kinds.contains(&CheckKind::MissingIndex),
                "personal issues reported: {kinds:?}"
            );
            assert!(
                !kinds.contains(&CheckKind::BrokenLink),
                "project issues must not appear: {kinds:?}"
            );
        });
    }

    #[test]
    fn lint_filtered_missing_personal_vault_is_empty_report() {
        with_home(|_home| {
            let report = lint_filtered(Some(VaultSelector::Personal), None, false).unwrap();
            assert!(report.issues.is_empty());
        });
    }

    #[test]
    fn list_filtered_personal_relative_bundle_filters_subdirectory() {
        with_home(|home| {
            let vault = home.join(".varde-docs");
            std::fs::create_dir_all(vault.join("sub")).unwrap();
            std::fs::write(vault.join("root.md"), b"---\ntype: decision\n---\n").unwrap();
            std::fs::write(
                vault.join("sub").join("leaf.md"),
                b"---\ntype: decision\n---\n",
            )
            .unwrap();
            let got = list_filtered(Some(VaultSelector::Personal), Some(Path::new("sub")), false)
                .unwrap();
            assert_eq!(got.len(), 1, "only the subdirectory: {got:?}");
            assert_eq!(got[0].slug, "leaf");
        });
    }

    #[test]
    fn lint_filtered_personal_relative_bundle_filters_subdirectory() {
        with_home(|home| {
            let vault = home.join(".varde-docs");
            std::fs::create_dir_all(vault.join("sub")).unwrap();
            // Root has a broken link (Error); the subdirectory is clean.
            std::fs::write(
                vault.join("root.md"),
                b"---\ntype: decision\n---\n[b](missing.md)\n",
            )
            .unwrap();
            std::fs::write(
                vault.join("sub").join("leaf.md"),
                b"---\ntype: decision\n---\n",
            )
            .unwrap();
            let report =
                lint_filtered(Some(VaultSelector::Personal), Some(Path::new("sub")), false).unwrap();
            let kinds: Vec<_> = report.issues.iter().map(|i| i.check_kind).collect();
            assert!(
                !kinds.contains(&CheckKind::BrokenLink),
                "root issue must be out of scope: {kinds:?}"
            );
        });
    }
}
