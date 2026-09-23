//! `bundle_lint`: contradiction-aware health check over a single Knowledge
//! Bundle (OKF v0.2 §3: a directory tree from one root down through all
//! subdirectories).
//!
//! Report-only: never blocks or rejects a bundle, never writes to disk.
//! The default [`lint`] entry point runs five spec-agnostic check kinds:
//! - `BrokenLink` (`Error`): a bundle-internal markdown link (OKF §6.1's
//!   absolute bundle-relative `/…` and relative forms) whose resolved target
//!   file does not exist in the bundle. External (`http://`/`https://`) links
//!   are never checked, and `](` markers inside inline code spans or fenced
//!   code blocks are literal text, not links.
//! - `OrphanedConcept` (`Error`): a parseable Concept with zero incoming
//!   links from any other Concept in the bundle.
//! - `MissingIndex` (`Warning`): a directory containing at least one Concept
//!   file but no `index.md` directly inside it.
//! - `MalformedConcept` (`Error`): a `.md` file with YAML frontmatter that
//!   fails to parse — reported, then skipped by the other checks. Files
//!   without any frontmatter are not Concepts and are not linted. A missing
//!   `type` field is *not* malformed by default — that is an OKF-specific
//!   rule, not a structural one (see below). The scan continues rather than
//!   aborting.
//! - `UnreadableEntry` (`Error`): a subdirectory or file the scan could not
//!   read; reported, then skipped, so one unreadable subtree never aborts the
//!   whole report.
//!
//! Traversal scope: hidden entries (`.git`, …) and common artifact
//! directories (`target`, `node_modules`) are skipped, symlinks are never
//! followed (cycle guard), and `README.md` is bundle bookkeeping like
//! `index.md`/`log.md` — never a Concept.
//!
//! [`lint_okf`] is a distinct, opt-in entry point: it runs everything
//! [`lint`] does, plus OKF v0.2 spec checks (a required `type` field, the
//! §5.4 `status` enum, §5/§10 structured-field shape, and reserved bundle
//! filenames masking an accidental Concept). Like [`lint`], it is
//! report-only — an OKF violation is always a report entry, never an `Err`.

use crate::bundle::{is_artifact_dir, is_reserved};
use crate::concept::{Concept, ConceptError};
use crate::crud::{FieldError, STRUCTURED_FIELD_NAMES, has_valid_type, validate_field_mutation};
use crate::frontmatter::{self, FrontmatterError};
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
    /// OKF-mode only (§4.1): the concept has no non-empty `type` field.
    OkfMissingType,
    /// OKF-mode only (§5.4): the concept's `status` value is not one of the
    /// `draft | stable | deprecated` enum.
    OkfInvalidStatus,
    /// OKF-mode only (§5/§10): a structured list/object field
    /// (`sources`/`verified`/`generated`/`stale_after`/`runtime`/`executor`/
    /// `attester`) holds a bare scalar instead of its required shape.
    OkfInvalidFieldMutation,
    /// OKF-mode only: a reserved bundle filename (`index.md`/`log.md`/
    /// `README.md`) carries a `type` field, i.e. it looks like an
    /// accidental Concept hiding behind bundle bookkeeping.
    OkfReservedBundleName,
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

/// Lint a single Knowledge Bundle: walk it recursively, run all five check
/// kinds, and return the report. The scan keeps running past malformed
/// files and unreadable entries — surfacing every problem in one report is
/// its whole purpose. Only a missing bundle root is a hard error.
pub fn lint(bundle: &Path) -> Result<LintReport, LintError> {
    let mut issues = Vec::new();
    let mut concepts: Vec<(PathBuf, Concept)> = Vec::new();
    walk(bundle, &mut issues, &mut concepts, false)?;

    check_broken_links(&concepts, bundle, &mut issues);
    check_orphans(&concepts, bundle, &mut issues);

    sort_issues(&mut issues);
    Ok(LintReport { issues })
}

/// OKF v0.2 opt-in lint mode: an entry point distinct from [`lint`].
///
/// Runs every check [`lint`] runs — no OKF violation suppresses or replaces
/// a base check — then layers OKF v0.2 spec checks on top as additional
/// report entries: a required `type` field (§4.1), the `status` enum
/// (§5.4), structured-field shape (§5/§10, reusing
/// [`crate::crud::validate_field_mutation`] so the rule is defined once),
/// and reserved bundle filenames masking an accidental Concept.
///
/// Report-only, like [`lint`]: an OKF spec violation is always a report
/// entry, never an `Err`. The only `Err` this can return is the same
/// infrastructure failure `lint` itself can hit (a missing/unreadable
/// bundle root).
pub fn lint_okf(bundle: &Path) -> Result<LintReport, LintError> {
    let mut issues = Vec::new();
    let mut concepts: Vec<(PathBuf, Concept)> = Vec::new();
    walk(bundle, &mut issues, &mut concepts, true)?;

    check_broken_links(&concepts, bundle, &mut issues);
    check_orphans(&concepts, bundle, &mut issues);
    for (path, concept) in &concepts {
        check_okf(concept, path, &mut issues);
    }

    sort_issues(&mut issues);
    Ok(LintReport { issues })
}

/// Deterministic report order shared by [`lint`] and [`lint_okf`]: `Error`
/// before `Warning`, then by path, then by check kind. Text and `--json`
/// output share this order.
fn sort_issues(issues: &mut [LintIssue]) {
    issues.sort_by(|a, b| {
        severity_rank(a.severity)
            .cmp(&severity_rank(b.severity))
            .then_with(|| a.path.cmp(&b.path))
            .then_with(|| a.check_kind.cmp(&b.check_kind))
    });
}

/// OKF-mode-only checks for one already-parsed concept (§4.1 `type`, §5.4
/// `status` enum, §5/§10 structured-field shape). Reuses
/// [`crate::crud::has_valid_type`] and
/// [`crate::crud::validate_field_mutation`] rather than re-implementing the
/// OKF rules a second time — every violation becomes a report entry, never
/// an `Err`.
fn check_okf(concept: &Concept, path: &Path, issues: &mut Vec<LintIssue>) {
    if !has_valid_type(concept) {
        issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::OkfMissingType,
            path: path.to_path_buf(),
            message: format!(
                "`{}` is missing the required `type` field (OKF v0.2 §4.1)",
                path.display()
            ),
        });
    }

    if let Some(status) = concept.frontmatter.get("status").and_then(|v| v.as_str())
        && let Err(err) = validate_field_mutation("status", Some(status))
    {
        issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::OkfInvalidStatus,
            path: path.to_path_buf(),
            message: format!("`{}`: {}", path.display(), lint_field_error_message(&err)),
        });
    }

    for key in STRUCTURED_FIELD_NAMES {
        let Some(value) = concept.frontmatter.get(key) else {
            continue;
        };
        // Only a bare scalar is invalid shape; sequences/mappings/null are
        // fine (or handled elsewhere) — mirror what `validate_field_mutation`
        // actually rejects.
        let Some(scalar) = value.as_str() else {
            continue;
        };
        if let Err(err) = validate_field_mutation(key, Some(scalar)) {
            issues.push(LintIssue {
                severity: Severity::Error,
                check_kind: CheckKind::OkfInvalidFieldMutation,
                path: path.to_path_buf(),
                message: format!("`{}`: {}", path.display(), lint_field_error_message(&err)),
            });
        }
    }
}

/// Render a [`FieldError`] for lint output rather than its mutation-oriented
/// `Display` text (e.g. "cannot be overwritten"), since `check_okf` is a
/// read-only check, not a write path — reuses `validate_field_mutation`'s
/// single-sourced rule, just not its CRUD-flavored wording.
fn lint_field_error_message(err: &FieldError) -> String {
    match err {
        FieldError::ReservedStructuredField { key } => format!(
            "`{key}` is a structured list/object field per OKF v0.2 §5/§10 and must not be a bare scalar value"
        ),
        FieldError::InvalidStatus { value } => format!(
            "invalid `status` value `{value}`: must be one of `draft`, `stable`, `deprecated`"
        ),
        other => other.to_string(),
    }
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
/// other Concept in the bundle (self-links don't count, and reserved files
/// are never scanned as link sources).
fn check_orphans(concepts: &[(PathBuf, Concept)], bundle: &Path, issues: &mut Vec<LintIssue>) {
    let mut incoming: HashMap<PathBuf, usize> = HashMap::new();
    for (path, concept) in concepts {
        for target in extract_links(&concept.body) {
            let resolved = resolve_link(target, bundle, path);
            if resolved != *path {
                *incoming.entry(resolved).or_insert(0) += 1;
            }
        }
    }
    for (path, _) in concepts {
        if incoming.get(path).copied().unwrap_or(0) == 0 {
            issues.push(LintIssue {
                severity: Severity::Error,
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
    okf: bool,
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
        let found = walk_entry(entry.path(), issues, concepts, okf);
        has_concept |= found.concept;
        has_index |= found.index;
    }

    if has_concept && !has_index {
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
    okf: bool,
) -> WalkEntry {
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return WalkEntry::default();
    };
    if name.starts_with('.') || is_artifact_dir(name) || path.is_symlink() {
        return WalkEntry::default();
    }
    if path.is_dir() {
        walk_subdirectory(&path, issues, concepts, okf);
        return WalkEntry::default();
    }
    if !path.is_file() {
        return WalkEntry::default();
    }
    if name == "index.md" {
        return WalkEntry {
            index: true,
            ..WalkEntry::default()
        };
    }
    if is_reserved(name) {
        if okf {
            check_reserved_bundle_name(&path, issues);
        }
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
    okf: bool,
) {
    if let Err(error) = walk(path, issues, concepts, okf) {
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
/// malformed here — that's an OKF-mode-only check, see `check_okf`);
/// unreadable files are reported as `UnreadableEntry`. The scan never
/// aborts on a single file.
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
            // problem — it's an OKF-specific rule, checked only in OKF mode
            // by `check_okf`. A parseable document with valid frontmatter
            // is a well-formed Concept for the default (non-OKF) lint path
            // regardless of what fields it carries.
            concepts.push((normalize_path(path), concept));
        }
        Err(ConceptError::Frontmatter(FrontmatterError::MissingDelimiters)) => {
            // No frontmatter at all — not a Concept document, not linted.
        }
        Err(source) => issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::MalformedConcept,
            path: path.to_path_buf(),
            message: format!("`{}` is not a valid OKF concept: {source}", path.display()),
        }),
    }
}

/// OKF-mode-only: a reserved bundle filename (`index.md`/`log.md`/
/// `README.md`) is bookkeeping, never a Concept — but if it happens to
/// carry a `type` field, that's very likely an accidental Concept hiding
/// behind a reserved name, so OKF mode reports it (report-only; the file is
/// never treated as a real Concept either way).
fn check_reserved_bundle_name(path: &Path, issues: &mut Vec<LintIssue>) {
    let Ok(bytes) = fs::read(path) else {
        return;
    };
    let Ok((frontmatter, _)) = frontmatter::parse(&bytes) else {
        return;
    };
    let has_type = frontmatter
        .get("type")
        .and_then(|v| v.as_str())
        .is_some_and(|s| !s.is_empty());
    if has_type {
        issues.push(LintIssue {
            severity: Severity::Error,
            check_kind: CheckKind::OkfReservedBundleName,
            path: path.to_path_buf(),
            message: format!(
                "`{}` is a reserved bundle filename but carries a `type` field — it can never be treated as an OKF concept",
                path.display()
            ),
        });
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
        let dir = tempdir("okf-core-lint-clean");
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
        let dir = tempdir("okf-core-lint-malformed");
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

    /// Default (non-OKF) `lint` never flags a missing `type` field — that
    /// unconditional-error behavior belongs to OKF mode only
    /// (`okf_lint_reports_violations`).
    #[test]
    fn default_lint_no_okf_checks() {
        let dir = tempdir("okf-core-lint-default-no-okf");
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

    /// Regression: for the same bundle with an OKF violation (missing
    /// `type`), `lint_okf` reports it while plain `lint` does not — checked
    /// in one test run so the two entry points' divergence is locked in
    /// together.
    #[test]
    fn lint_okf_vs_plain_diff() {
        let dir = tempdir("okf-core-lint-okf-vs-plain-diff");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        write(
            &dir,
            "notype.md",
            "---\ntitle: no type here\n---\nSee [a](a.md).\n",
        );

        let plain = lint(&dir).unwrap();
        assert!(
            !plain
                .issues
                .iter()
                .any(|i| i.check_kind == CheckKind::OkfMissingType),
            "plain lint must not report the OKF missing-type violation, got {plain:?}"
        );

        let okf = lint_okf(&dir).unwrap();
        assert!(
            okf.issues
                .iter()
                .any(|i| i.check_kind == CheckKind::OkfMissingType),
            "lint_okf must report the OKF missing-type violation, got {okf:?}"
        );
    }

    /// OKF-mode lint layers spec checks (missing `type`, non-enum `status`,
    /// invalid field-mutation shape, reserved bundle name) on top of the
    /// default checks, reporting each as an issue and never returning
    /// `Err` for a violation.
    #[test]
    fn okf_lint_reports_violations() {
        let dir = tempdir("okf-core-lint-okf-violations");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        // Missing `type`.
        write(
            &dir,
            "notype.md",
            "---\ntitle: no type here\n---\nSee [a](a.md).\n",
        );
        // Non-enum `status`.
        write(
            &dir,
            "badstatus.md",
            "---\ntype: decision\nstatus: not-a-real-status\n---\nSee [a](a.md).\n",
        );
        // Invalid field-mutation shape: `sources` must be a list/object, not
        // a bare scalar.
        write(
            &dir,
            "badfield.md",
            "---\ntype: decision\nsources: just-a-string\n---\nSee [a](a.md).\n",
        );
        // Reserved bundle filename carrying a `type` field.
        write(
            &dir,
            "log.md",
            "---\ntype: decision\n---\naccidental concept\n",
        );

        let report = lint_okf(&dir).unwrap();
        for kind in [
            CheckKind::OkfMissingType,
            CheckKind::OkfInvalidStatus,
            CheckKind::OkfInvalidFieldMutation,
            CheckKind::OkfReservedBundleName,
        ] {
            assert!(
                report.issues.iter().any(|i| i.check_kind == kind),
                "expected a {kind:?} issue, got {report:?}"
            );
        }
    }

    /// OKF-mode lint is advisory only: even with every kind of violation
    /// present, the call itself is always `Ok(Report)`, never `Err`.
    #[test]
    fn okf_lint_never_blocks() {
        let dir = tempdir("okf-core-lint-okf-never-blocks");
        write(&dir, "index.md", "# index");
        write(
            &dir,
            "notype.md",
            "---\ntitle: no type here\n---\nno links.\n",
        );
        write(
            &dir,
            "badstatus.md",
            "---\ntype: decision\nstatus: bogus\n---\nno links.\n",
        );
        write(
            &dir,
            "badfield.md",
            "---\ntype: decision\nsources: just-a-string\n---\nno links.\n",
        );
        write(
            &dir,
            "log.md",
            "---\ntype: decision\n---\naccidental concept\n",
        );

        let result = lint_okf(&dir);
        assert!(
            result.is_ok(),
            "OKF-mode lint must never return Err for a spec violation, got {result:?}"
        );
    }

    #[test]
    fn lint_broken_links_reported_external_links_skipped() {
        let dir = tempdir("okf-core-lint-broken-links");
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
        let dir = tempdir("okf-core-lint-orphan");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("No links.\n"));
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::OrphanedConcept);
        assert_eq!(issue.severity, Severity::Error);
        assert!(issue.path.ends_with("a.md"), "got {:?}", issue.path);
    }

    #[test]
    fn lint_missing_index_reported_for_root_and_nested_dirs() {
        let dir = tempdir("okf-core-lint-missing-index");
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
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 2, "got {report:?}");
        for issue in &report.issues {
            assert_eq!(issue.check_kind, CheckKind::MissingIndex);
            assert_eq!(issue.severity, Severity::Warning);
        }
    }

    #[test]
    fn lint_reserved_files_are_not_concepts_or_link_sources() {
        let dir = tempdir("okf-core-lint-reserved");
        // index.md and log.md both link to b.md: if either were scanned as a
        // link source, b.md would not be reported as orphaned.
        write(&dir, "index.md", "# index\n\nSee [b](b.md).\n");
        write(&dir, "log.md", "# log\n\nSee [b](b.md).\n");
        write(&dir, "a.md", &concept("No links.\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        let report = lint(&dir).unwrap();
        assert_eq!(report.issues.len(), 1, "got {report:?}");
        let issue = &report.issues[0];
        assert_eq!(issue.check_kind, CheckKind::OrphanedConcept);
        assert!(issue.path.ends_with("b.md"), "got {:?}", issue.path);
    }

    #[test]
    fn lint_missing_bundle_dir_is_typed_error() {
        let dir = tempdir("okf-core-lint-missing-dir");
        let err = lint(&dir.join("does-not-exist")).unwrap_err();
        assert!(matches!(err, LintError::ReadDirFailed { .. }));
    }

    #[test]
    fn lint_inline_code_and_fenced_blocks_are_not_broken_links() {
        let dir = tempdir("okf-core-lint-code-mask");
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
        let dir = tempdir("okf-core-lint-link-to-dir");
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
        let dir = tempdir("okf-core-lint-non-concepts");
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
        let dir = tempdir("okf-core-lint-hidden");
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
        let dir = tempdir("okf-core-lint-order");
        // No index.md at the root -> MissingIndex (Warning) for the root.
        write(&dir, "aa.md", &concept("See [bb](bb.md).\n"));
        write(&dir, "bb.md", &concept("See [gone](/gone.md).\n"));
        write(&dir, "zz.md", "---\n: not yaml :(\n---\n");
        let report = lint(&dir).unwrap();
        let kinds: Vec<CheckKind> = report.issues.iter().map(|i| i.check_kind).collect();
        // Errors first (by path: aa.md, gone.md, zz.md), then the Warning.
        assert_eq!(
            kinds,
            vec![
                CheckKind::OrphanedConcept,
                CheckKind::BrokenLink,
                CheckKind::MalformedConcept,
                CheckKind::MissingIndex,
            ],
            "got {kinds:?}"
        );
        assert_eq!(
            report.issues[3].path, dir,
            "the Warning is the root directory, got {:?}",
            report.issues[3].path
        );
    }

    #[cfg(unix)]
    #[test]
    fn lint_unreadable_subdir_is_reported_and_scan_continues() {
        use std::os::unix::fs::PermissionsExt;
        let dir = tempdir("okf-core-lint-unreadable");
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
        let dir = tempdir("okf-core-lint-symlink");
        write(&dir, "index.md", "# index");
        write(&dir, "a.md", &concept("See [b](b.md).\n"));
        write(&dir, "b.md", &concept("See [a](a.md).\n"));
        // A symlinked tree containing a malformed Concept: if it were
        // followed, linting would report it.
        let outside = tempdir("okf-core-lint-symlink-outside");
        write(&outside, "bad.md", "---\ntitle: no type\n---\n");
        std::os::unix::fs::symlink(&outside, dir.join("linked")).unwrap();
        let report = lint(&dir).unwrap();
        assert!(
            report.issues.is_empty(),
            "symlinked trees must not be scanned, got {report:?}"
        );
    }
}
