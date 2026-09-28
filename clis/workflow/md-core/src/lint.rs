//! `bundle_lint`: contradiction-aware health check over a single Knowledge
//! Bundle (a directory tree from one root down through all
//! subdirectories).
//!
//! Report-only: never blocks or rejects a bundle, never writes to disk.
//! The default [`lint`] entry point runs four check kinds unconditionally,
//! plus a fifth gated behind [`LintOptions::require_index`]:
//! - `BrokenLink` (`Error`): a bundle-internal markdown link (an
//!   absolute bundle-relative `/…` or relative form) whose resolved target
//!   file does not exist in the bundle. External (`http://`/`https://`) links
//!   are never checked, and `](` markers inside inline code spans or fenced
//!   code blocks are literal text, not links.
//! - `OrphanedConcept` (`Warning`): a parseable Concept with zero incoming
//!   links from any other Concept in the bundle. Links from a reserved
//!   `index.md` file also count as incoming links to their targets — so an
//!   index page's own links keep the concepts it points to from reading as
//!   orphaned — but `index.md` itself is never a Concept and is never
//!   checked for orphan status. Other reserved files (`log.md`, `README.md`)
//!   are still never scanned as link sources.
//! - `MissingIndex` (`Warning`): only runs with [`LintOptions::require_index`]
//!   set; a directory containing at least one Concept file but no `index.md`
//!   directly inside it.
//! - `MalformedConcept` (`Error`): a `.md` file with YAML frontmatter that
//!   fails to parse — reported, then skipped by the other checks. Files
//!   without any frontmatter are not Concepts and are not linted. A missing
//!   `type` field is *not* malformed by default — that is a format-specific
//!   rule, not a structural one. The scan continues rather than aborting.
//! - `UnreadableEntry` (`Error`): a subdirectory or file the scan could not
//!   read; reported, then skipped, so one unreadable subtree never aborts the
//!   whole report.
//!
//! Traversal scope: hidden entries (`.git`, …) and common artifact
//! directories (`target`, `node_modules`) are skipped, symlinks are never
//! followed (cycle guard), and `README.md` is bundle bookkeeping like
//! `index.md`/`log.md` — never a Concept.

use crate::bundle::{is_artifact_dir, is_reserved};
use crate::concept::{Concept, ConceptError};
use crate::frontmatter::FrontmatterError;
use crate::lint::links::extract_links;
use serde::Serialize;
use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};
use thiserror::Error;

pub mod base;
pub mod links;

/// Severity of a lint issue.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Severity {
    Warning,
    Error,
}

/// Which structural check produced an issue.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckKind {
    OrphanedConcept,
    BrokenLink,
    MissingIndex,
    MalformedConcept,
    UnreadableEntry,
}

/// One lint issue: severity, check kind, affected path, human-readable
/// message.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize)]
pub struct LintIssue {
    pub severity: Severity,
    pub check_kind: CheckKind,
    /// The affected file or directory, as built from the bundle root
    /// (Concept file paths carry their slug as the filename stem).
    pub path: PathBuf,
    pub message: String,
}

/// The result of linting a bundle: every issue found, ephemeral and computed
/// fresh on each invocation (nothing is persisted).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LintReport {
    pub issues: Vec<LintIssue>,
}

/// Typed errors for `bundle_lint` — infrastructure failures only. Lint
/// findings are never errors; they are issues in the report.
#[derive(Debug, Error)]
pub enum LintError {
    #[error("failed to read bundle directory `{path}`: {source}")]
    ReadDirFailed { path: PathBuf, source: io::Error },
}

/// Options controlling which optional checks [`lint_with_options`] runs.
#[derive(Debug, Clone, Copy, Default)]
pub struct LintOptions {
    /// Also run the `MissingIndex` check. Off by default: a bundle without
    /// an `index.md` in every directory is not, on its own, broken.
    pub require_index: bool,
}

/// Lint a single Knowledge Bundle with default options (`MissingIndex` does
/// not run). See [`lint_with_options`] for the full contract.
pub fn lint(bundle: &Path) -> Result<LintReport, LintError> {
    lint_with_options(bundle, &LintOptions::default())
}

/// Lint a single Knowledge Bundle: walk it recursively, run every check kind
/// `options` enables, and return the report. The scan keeps running past
/// malformed files and unreadable entries — surfacing every problem in one
/// report is its whole purpose. Only a missing bundle root is a hard error.
pub fn lint_with_options(bundle: &Path, options: &LintOptions) -> Result<LintReport, LintError> {
    let mut issues = Vec::new();
    let mut concepts: Vec<(PathBuf, Concept)> = Vec::new();
    let mut index_links: Vec<(PathBuf, String)> = Vec::new();
    walk(
        bundle,
        &mut issues,
        &mut concepts,
        &mut index_links,
        options,
    )?;

    check_broken_links(&concepts, bundle, &mut issues);
    check_orphans(&concepts, &index_links, bundle, &mut issues);

    sort_issues(&mut issues);
    Ok(LintReport { issues })
}

/// Deterministic report order: `Error` before `Warning`, then by path, then
/// by check kind. Text and `--json` output share this order.
fn sort_issues(issues: &mut [LintIssue]) {
    issues.sort_by(|a, b| {
        severity_rank(a.severity)
            .cmp(&severity_rank(b.severity))
            .then_with(|| a.path.cmp(&b.path))
            .then_with(|| a.check_kind.cmp(&b.check_kind))
    });
}

/// Sort rank for the report: Errors surface before Warnings.
fn severity_rank(severity: Severity) -> u8 {
    match severity {
        Severity::Error => 0,
        Severity::Warning => 1,
    }
}

/// `BrokenLink` check: every bundle-internal link target that resolves to a
/// file that does not exist.
fn check_broken_links(concepts: &[(PathBuf, Concept)], bundle: &Path, issues: &mut Vec<LintIssue>) {
    for (path, concept) in concepts {
        for target in extract_links(&concept.body) {
            let resolved = resolve_link(target, bundle, path);
            if !resolved.is_file() {
                issues.push(LintIssue {
                    severity: Severity::Error,
                    check_kind: CheckKind::BrokenLink,
                    path: resolved.clone(),
                    message: format!(
                        "broken bundle-internal link `{target}` referenced from `{}`",
                        path.display()
                    ),
                });
            }
        }
    }
}

/// `OrphanedConcept` check: a Concept with zero incoming links from any
/// other Concept in the bundle (self-links don't count). Links from a
/// reserved `index.md` file also count as incoming, since an index page
/// exists to point at the concepts underneath it; other reserved files
/// (`log.md`, `README.md`) are never scanned as link sources, and
/// `index.md` itself is never a candidate for this check.
fn check_orphans(
    concepts: &[(PathBuf, Concept)],
    index_links: &[(PathBuf, String)],
    bundle: &Path,
    issues: &mut Vec<LintIssue>,
) {
    let normalized_bundle = normalize_path(bundle);
    let mut incoming: HashMap<PathBuf, usize> = HashMap::new();
    for (path, concept) in concepts {
        for target in extract_links(&concept.body) {
            let resolved = resolve_link(target, bundle, path);
            if resolved != *path {
                *incoming.entry(resolved).or_insert(0) += 1;
            }
        }
    }
    for (path, body) in index_links {
        for target in extract_links(body) {
            let resolved = resolve_link(target, bundle, path);
            *incoming.entry(resolved).or_insert(0) += 1;
        }
    }
    for (path, _) in concepts {
        if path
            .strip_prefix(&normalized_bundle)
            .ok()
            .and_then(|relative| relative.components().next())
            .is_some_and(|first| {
                first.as_os_str() == "conclusions" || first.as_os_str() == "promotions"
            })
        {
            continue;
        }
        if incoming.get(path).copied().unwrap_or(0) == 0 {
            issues.push(LintIssue {
                severity: Severity::Warning,
                check_kind: CheckKind::OrphanedConcept,
                path: path.clone(),
                message: format!(
                    "no other Concept in the bundle links to `{}`",
                    path.display()
                ),
            });
        }
    }
}

/// Recursively walk one directory: collect every non-reserved `.md` Concept
/// file at any depth, parse it (reporting parse/type failures as
/// `MalformedConcept` issues without aborting), and run the `MissingIndex`
/// check for this directory.
///
/// Hidden entries (`.git`, dotfiles), artifact directories (`target`,
/// `node_modules`), and symlinks are skipped. A subdirectory that cannot be
/// read is reported as an `UnreadableEntry` issue and skipped, so one
/// unreadable subtree never aborts the scan.
fn walk(
    dir: &Path,
    issues: &mut Vec<LintIssue>,
    concepts: &mut Vec<(PathBuf, Concept)>,
    index_links: &mut Vec<(PathBuf, String)>,
    options: &LintOptions,
) -> Result<(), LintError> {
    let entries = fs::read_dir(dir)
        .map_err(|source| LintError::ReadDirFailed {
            path: dir.to_path_buf(),
            source,
        })?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|source| LintError::ReadDirFailed {
            path: dir.to_path_buf(),
            source,
        })?;

    let mut has_concept = false;
    let mut has_index = false;
    for entry in entries {
        let found = walk_entry(entry.path(), issues, concepts, index_links, options);
        has_concept |= found.concept;
        has_index |= found.index;
    }

    if options.require_index && has_concept && !has_index {
        issues.push(LintIssue {
            severity: Severity::Warning,
            check_kind: CheckKind::MissingIndex,
            path: dir.to_path_buf(),
            message: format!(
                "directory `{}` contains Concept files but no `index.md`",
                dir.display()
            ),
        });
    }
    Ok(())
}

#[derive(Default)]
struct WalkEntry {
    concept: bool,
    index: bool,
}

fn walk_entry(
    path: PathBuf,
    issues: &mut Vec<LintIssue>,
    concepts: &mut Vec<(PathBuf, Concept)>,
    index_links: &mut Vec<(PathBuf, String)>,
    options: &LintOptions,
) -> WalkEntry {
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return WalkEntry::default();
    };
    if name.starts_with('.') || is_artifact_dir(name) || path.is_symlink() {
        return WalkEntry::default();
    }
    if path.is_dir() {
        walk_subdirectory(&path, issues, concepts, index_links, options);
        return WalkEntry::default();
    }
    if !path.is_file() {
        return WalkEntry::default();
    }
    if name == "index.md" {
        // index.md is bundle bookkeeping, never a Concept — but its links
        // still count as incoming links to their targets for the
        // OrphanedConcept check, so capture its body.
        if let Ok(body) = fs::read_to_string(&path) {
            index_links.push((normalize_path(&path), body));
        }
        return WalkEntry {
            index: true,
            ..WalkEntry::default()
        };
    }
    if is_reserved(name) {
        return WalkEntry::default();
    }
    if !name.ends_with(".md") {
        return WalkEntry::default();
    }
    scan_concept_file(&path, name, issues, concepts);
    WalkEntry {
        concept: true,
        ..WalkEntry::default()
    }
}

fn walk_subdirectory(
    path: &Path,
    issues: &mut Vec<LintIssue>,
    concepts: &mut Vec<(PathBuf, Concept)>,
    index_links: &mut Vec<(PathBuf, String)>,
    options: &LintOptions,
) {
    if let Err(error) = walk(path, issues, concepts, index_links, options) {
        issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::UnreadableEntry,
            path: path.to_path_buf(),
            message: format!("failed to read directory `{}`: {error}", path.display()),
        });
    }
}

/// Read and parse one candidate Concept file. Files without YAML frontmatter
/// are not Concepts and are skipped silently; unparseable frontmatter is
/// reported as `MalformedConcept` (a missing `type` field is *not*
/// malformed here); unreadable files are reported as `UnreadableEntry`. The
/// scan never aborts on a single file.
fn scan_concept_file(
    path: &Path,
    name: &str,
    issues: &mut Vec<LintIssue>,
    concepts: &mut Vec<(PathBuf, Concept)>,
) {
    let slug = name.strip_suffix(".md").unwrap();
    let bytes = match fs::read(path) {
        Ok(bytes) => bytes,
        Err(source) => {
            issues.push(LintIssue {
                severity: Severity::Error,
                check_kind: CheckKind::UnreadableEntry,
                path: path.to_path_buf(),
                message: format!("failed to read `{}`: {source}", path.display()),
            });
            return;
        }
    };
    match Concept::from_bytes(&bytes, slug) {
        Ok(concept) => {
            // A missing `type` field is not a structural/malformed-document
            // problem. A parseable document with valid frontmatter is a
            // well-formed Concept regardless of what fields it carries.
            concepts.push((normalize_path(path), concept));
        }
        Err(ConceptError::Frontmatter(FrontmatterError::MissingDelimiters)) => {
            // No frontmatter at all — not a Concept document, not linted.
        }
        Err(source) => issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::MalformedConcept,
            path: path.to_path_buf(),
            message: format!("`{}` is not a valid concept: {source}", path.display()),
        }),
    }
}

/// Collapse `.` and `..` components lexically, so a resolved link target
/// (`sub/../b.md`) compares equal to the walked file path (`b.md`).
fn normalize_path(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out
}

/// Resolve a link target against the bundle: `/…` is bundle-relative,
/// anything else is relative to the linking Concept's own directory.
fn resolve_link(target: &str, bundle: &Path, from: &Path) -> PathBuf {
    let resolved = match target.strip_prefix('/') {
        Some(rest) => bundle.join(rest),
        None => from.parent().unwrap_or(bundle).join(target),
    };
    normalize_path(&resolved)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    /// A valid Concept document: YAML frontmatter with a `type`, then a body.
    fn concept(body: &str) -> String {
        format!("---\ntype: decision\n---\n{body}")
    }

    fn write(dir: &Path, name: &str, content: &str) {
        std::fs::write(dir.join(name), content).unwrap();
    }

    #[test]
    fn lint_clean_bundle_with_indexes_returns_empty_report() {
        let dir = tempdir("md-core-lint-clean");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md) and [c](sub/c.md).\n"));
        let sub = dir.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(&sub, "index.md", "# sub index");
        write(&sub, "c.md", &concept("See [b](../b.md).\n"));
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "expected no issues, got {report:?}"
        );
    }

    #[test]
    fn lint_malformed_concepts_are_reported_and_scan_continues() {
        let dir = tempdir("md-core-lint-malformed");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        write(&dir, "bad.md", "---\n: not yaml :(\n---\n");
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::MalformedConcept);
        assert_eq!(issue.severity, Severity::Error);
        assert!(issue.path.ends_with("bad.md"), "got {:?}", issue.path);
    }

    /// `lint` never flags a missing `type` field as malformed — that's a
    /// well-formed Concept as far as structural lint is concerned.
    #[test]
    fn lint_no_missing_type_checks() {
        let dir = tempdir("md-core-lint-no-missing-type-checks");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        write(
            &dir,
            "notype.md",
            "---\ntitle: no type here\n---\nSee [a](a.md).\n",
        );
        let report = lint(&dir).unwrap();
        assert!(
            !report
                .issues
                .iter()
                .any(|i| i.check_kind == CheckKind::MalformedConcept),
            "default lint must never flag missing `type` as MalformedConcept, got {report:?}"
        );
    }

    #[test]
    fn lint_broken_links_reported_external_links_skipped() {
        let dir = tempdir("md-core-lint-broken-links");
        write(&dir, "index.md", "# index");
        write(
            &dir,
            "a.md",
            &concept(
                "See [b](/b.md) and [b2](b.md), plus [x](/missing.md), [y](./missing.md), and [ext](https://example.com/nope).\n",
            ),
        );
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 2, "got {report:?}");
        for issue in &report.issues {
            assert_eq!(issue.check_kind, CheckKind::BrokenLink);
            assert_eq!(issue.severity, Severity::Error);
            assert!(issue.path.ends_with("missing.md"), "got {:?}", issue.path);
        }
    }

    #[test]
    fn lint_orphaned_concept_is_reported() {
        let dir = tempdir("md-core-lint-orphan");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("No links.\n"));
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::OrphanedConcept);
        assert_eq!(issue.severity, Severity::Warning);
        assert!(issue.path.ends_with("a.md"), "got {:?}", issue.path);
    }

    #[test]
    fn producer_records_are_not_orphans() {
        let dir = tempdir("md-core-lint-producer-records");
        for folder in ["conclusions", "promotions", "decision"] {
            std::fs::create_dir_all(dir.join(folder)).unwrap();
            write(&dir.join(folder), "record.md", &concept("No links.\n"));
        }
        let report = lint(&dir).unwrap();
        let orphan_paths: Vec<_> = report
            .issues
            .iter()
            .filter(|issue| issue.check_kind == CheckKind::OrphanedConcept)
            .map(|issue| issue.path.strip_prefix(&dir).unwrap().to_path_buf())
            .collect();
        assert_eq!(orphan_paths, vec![PathBuf::from("decision/record.md")]);
    }

    #[test]
    fn lint_index_links_count_as_incoming_for_orphan_check() {
        let dir = tempdir("md-core-lint-index-links");
        // a.md and b.md are only linked from index.md, never from each
        // other: without index.md's links counting, both would be orphaned.
        write(
            &dir,
            "index.md",
            "# index\n\nSee [a](a.md) and [b](b.md).\n",
        );
        write(&dir, "a.md", &concept("No links.\n"));
        write(&dir, "b.md", &concept("No links.\n"));
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "index.md links must count as incoming, got {report:?}"
        );
    }

    #[test]
    fn lint_missing_index_requires_flag_and_reports_for_root_and_nested_dirs() {
        let dir = tempdir("md-core-lint-missing-index");
        // Root: concepts but NO index.md.
        write(
            &dir,
            "a.md",
            &concept("See [b](b.md), [c](sub/c.md), and [d](sub2/d.md).\n"),
        );
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        // Nested: concept but NO index.md.
        let sub = dir.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(&sub, "c.md", &concept("See [a](../a.md).\n"));
        // Nested: concept AND index.md — no issue expected.
        let sub2 = dir.join("sub2");
        std::fs::create_dir(&sub2).unwrap();
        write(&sub2, "index.md", "# sub2 index");
        write(&sub2, "d.md", &concept("See [a](../a.md).\n"));

        let default_report = lint(&dir).unwrap();
        assert!(
            !default_report
                .issues
                .iter()
                .any(|i| i.check_kind == CheckKind::MissingIndex),
            "MissingIndex must not run without --require-index, got {default_report:?}"
        );

        let report = lint_with_options(
            &dir,
            &LintOptions {
                require_index: true,
            },
        )
        .unwrap();
        let missing_index: Vec<_> = report
            .issues
            .iter()
            .filter(|i| i.check_kind == CheckKind::MissingIndex)
            .collect();
        assert_eq!(missing_index.len(), 2, "got {report:?}");
        for issue in missing_index {
            assert_eq!(issue.severity, Severity::Warning);
        }
    }

    #[test]
    fn lint_reserved_files_are_not_concepts_and_only_index_is_a_link_source() {
        let dir = tempdir("md-core-lint-reserved");
        // index.md links to a.md and does count as an incoming link; log.md
        // also links to b.md but must never count as a link source.
        write(&dir, "index.md", "# index\n\nSee [a](a.md).\n");
        write(&dir, "log.md", "# log\n\nSee [b](b.md).\n");
        write(&dir, "a.md", &concept("No links.\n"));
        write(&dir, "b.md", &concept("No links.\n"));
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::OrphanedConcept);
        assert!(issue.path.ends_with("b.md"), "got {:?}", issue.path);
    }

    #[test]
    fn lint_missing_bundle_dir_is_typed_error() {
        let dir = tempdir("md-core-lint-missing-dir");
        let err = lint(&dir.join("does-not-exist")).unwrap_err();
        assert!(matches!(err, LintError::ReadDirFailed { .. }));
    }

    #[test]
    fn lint_inline_code_and_fenced_blocks_are_not_broken_links() {
        let dir = tempdir("md-core-lint-code-mask");
        write(&dir, "index.md", "# index");
        write(
            &dir,
            "a.md",
            &concept(
                "Inline: `see [x](x.md)` here, and `` `[text](path)` `` too.\n\
                 ```\n\
                 [y](y.md)\n\
                 ```\n\
                 Image: ![alt](img.png). Anchor: [b](b.md#section).\n\
                 Angle: [b](<b.md>). Real: [b](b.md).\n",
            ),
        );
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "inline-code/fenced `](`, images, anchors, and angle forms must not be broken links, got {report:?}"
        );
    }

    #[test]
    fn lint_link_to_directory_is_broken() {
        let dir = tempdir("md-core-lint-link-to-dir");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [sub](sub) and [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        let sub = dir.join("sub");
        std::fs::create_dir(&sub).unwrap();
        write(&sub, "index.md", "# sub index");
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::BrokenLink);
        assert!(issue.path.ends_with("sub"), "got {:?}", issue.path);
    }

    #[test]
    fn lint_files_without_frontmatter_and_readmes_are_not_concepts() {
        let dir = tempdir("md-core-lint-non-concepts");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        write(&dir, "plain.md", "no frontmatter here");
        write(&dir, "README.md", "---\nid: readme\n---\n# Notes\n");
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "frontmatter-less files and README.md are not linted, got {report:?}"
        );
    }

    #[test]
    fn lint_hidden_and_artifact_dirs_are_skipped() {
        let dir = tempdir("md-core-lint-hidden");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        for hidden in [".git", "target", "node_modules"] {
            let sub = dir.join(hidden);
            std::fs::create_dir(&sub).unwrap();
            write(&sub, "bad.md", "---\ntitle: no type\n---\n");
        }
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "hidden/artifact trees must not be scanned, got {report:?}"
        );
    }

    #[test]
    fn lint_report_sorted_by_severity_then_path() {
        let dir = tempdir("md-core-lint-order");
        write(&dir, "index.md", "# index");
        // aa.md gets no incoming link -> OrphanedConcept (Warning).
        write(&dir, "aa.md", &concept("See [bb](bb.md).\n"));
        write(&dir, "bb.md", &concept("See [gone](/gone.md).\n"));
        write(&dir, "zz.md", "---\n: not yaml :(\n---\n");
        let report = lint(&dir).unwrap();
        let kinds: Vec<CheckKind> = report.issues.iter().map(|i| i.check_kind).collect();
        // Errors first (by path: gone.md, zz.md), then the Warning (aa.md).
        assert_eq!(
            kinds,
            vec![
                CheckKind::BrokenLink,
                CheckKind::MalformedConcept,
                CheckKind::OrphanedConcept,
            ],
            "got {kinds:?}"
        );
        assert_eq!(report.issues[0].severity, Severity::Error);
        assert_eq!(report.issues[1].severity, Severity::Error);
        assert_eq!(report.issues[2].severity, Severity::Warning);
        assert_eq!(
            report.issues[2].path,
            dir.join("aa.md"),
            "the Warning is aa.md (orphaned), got {:?}",
            report.issues[2].path
        );
    }

    #[cfg(unix)]
    #[test]
    fn lint_unreadable_subdir_is_reported_and_scan_continues() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempdir("md-core-lint-unreadable");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        let locked = dir.join("locked");
        std::fs::create_dir(&locked).unwrap();
        write(&locked, "c.md", &concept("No links.\n"));
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o000)).unwrap();
        if std::fs::read_dir(&locked).is_ok() {
            // Running as root — permissions do not block reads, nothing to
            // test. Restore so the tempdir can be cleaned up.
            std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o755)).unwrap();
            return;
        }
        let report = lint(&dir).unwrap();
        std::fs::set_permissions(&locked, std::fs::Permissions::from_mode(0o755)).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::UnreadableEntry);
        assert_eq!(issue.severity, Severity::Error);
        assert!(issue.path.ends_with("locked"), "got {:?}", issue.path);
    }

    #[cfg(unix)]
    #[test]
    fn lint_symlinked_dirs_are_not_followed() {
        let dir = tempdir("md-core-lint-symlink");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        // A symlinked tree containing a malformed Concept: if it were
        // followed, linting would report it.
        let outside = tempdir("md-core-lint-symlink-outside");
        write(&outside, "bad.md", "---\ntitle: no type\n---\n");
        std::os::unix::fs::symlink(&outside, dir.join("linked")).unwrap();
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "symlinked trees must not be scanned, got {report:?}"
        );
    }
}
