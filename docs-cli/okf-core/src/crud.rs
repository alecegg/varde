//! Concept CRUD operations against a Knowledge Bundle directory
//! (a directory of `<slug>.md` concept files).

pub mod create;
pub mod delete;
pub mod list;
pub mod search;
pub mod show;
pub mod timestamps;
pub mod update;

use crate::concept::Concept;
use crate::frontmatter::{self, FrontmatterError};
use crate::occ;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// The on-disk path of a concept file in a bundle.
///
/// A slug is a bundle-root-relative path per OKF v0.2 §2/§3: `/`-separated
/// segments, each independently kebab-case (e.g. `pattern/rule-a`), or a
/// single flat segment for a bundle-root concept (e.g. `my-concept`).
///
/// Defense in depth: every caller is contained to the bundle by
/// construction. Returns `None` when any segment is not kebab-case, or the
/// slug contains a traversal/absolute-path/empty-segment shape (which would
/// allow escaping the bundle directory); callers surface that as a typed
/// `InvalidSlug` error.
pub(crate) fn concept_path(bundle: &Path, slug: &str) -> Option<PathBuf> {
    if !validate_slug(slug) {
        return None;
    }
    Some(bundle.join(format!("{slug}.md")))
}

/// Resolve `slug`'s on-disk path in `bundle`, mapping a non-kebab-case
/// slug to the shared [`ConceptIoError::InvalidSlug`] — the single
/// implementation every CRUD entry point uses to reject traversal slugs.
///
/// The shared-error refactor centralized the error surface in
/// [`ConceptIoError`], so this keeps the guard itself centralized too:
/// `create`, `show`, and [`occ_read_guard`] all convert with `?` instead
/// of re-declaring the `InvalidSlug` construction (update reaches the
/// guard through `occ_read_guard`).
pub(crate) fn concept_path_or(
    bundle: &Path,
    slug: &str,
) -> Result<PathBuf, ConceptIoError> {
    let Some(path) = concept_path(bundle, slug) else {
        return Err(ConceptIoError::InvalidSlug {
            slug: slug.to_string(),
        });
    };
    Ok(path)
}

/// Whether a slug satisfies the Concept-ID contract (OKF v0.2 §2/§3): a
/// `/`-separated path of one or more segments, each independently matching
/// `^[a-z0-9]+(-[a-z0-9]+)*$` (kebab-case).
///
/// Rejects, as defense in depth against escaping the bundle directory:
/// - a `..` segment (traversal),
/// - empty segments — leading slash (`/foo`), trailing slash (`foo/`), or a
///   doubled slash (`foo//bar`),
/// - a backslash anywhere (Windows-style separator).
///
/// Shared by every CRUD entry point via [`concept_path`]; `create` rejects
/// invalid slugs the same way `show`/`update`/`delete` do.
pub(crate) fn validate_slug(slug: &str) -> bool {
    if slug.is_empty() || slug.contains('\\') {
        return false;
    }
    slug.split('/').all(|segment| segment != ".." && validate_slug_segment(segment))
}

/// Whether a single `/`-delimited slug segment is kebab-case
/// (`^[a-z0-9]+(-[a-z0-9]+)*$`).
fn validate_slug_segment(segment: &str) -> bool {
    let mut chars = segment.chars();
    let Some(first) = chars.next() else {
        return false;
    };
    if !(first.is_ascii_lowercase() || first.is_ascii_digit()) {
        return false;
    }
    let mut last_was_dash = false;
    for c in chars {
        if c == '-' {
            if last_was_dash {
                return false;
            }
            last_was_dash = true;
        } else if c.is_ascii_lowercase() || c.is_ascii_digit() {
            last_was_dash = false;
        } else {
            return false;
        }
    }
    !last_was_dash
}

/// Derive a bundle-relative slug (per OKF v0.2 §2) from an on-disk concept
/// file `path` known to live under `bundle`: the path relative to `bundle`,
/// `/`-separated, with the `.md` suffix stripped.
///
/// Single source of truth for the slug-from-path derivation shared by
/// [`list`](crate::crud::list::list) and [`crate::registry::search`], so
/// both report the same identity for the same file.
pub(crate) fn relative_slug(bundle: &Path, path: &Path) -> String {
    let relative = path
        .strip_prefix(bundle)
        .unwrap_or(path)
        .to_string_lossy()
        .replace(std::path::MAIN_SEPARATOR, "/");
    relative.strip_suffix(".md").unwrap_or(&relative).to_string()
}

/// Write bytes atomically (unique temp file + rename) so a failed write
/// never leaves a partially-written concept file.
///
/// The temp name embeds the process id and a nanosecond timestamp so two
/// concurrent writers never share a temp file (each rename stays atomic),
/// and the temp file is removed on every failure path so no `.tmp`
/// artifact is leaked.
pub(crate) fn atomic_write(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = unique_temp_path(path);
    if let Err(e) = std::fs::write(&tmp, bytes) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    match std::fs::rename(&tmp, path) {
        Ok(()) => Ok(()),
        Err(e) => {
            let _ = std::fs::remove_file(&tmp);
            Err(e)
        }
    }
}

/// Write bytes to `path` only if it does not already exist: unlike
/// [`atomic_write`]'s unconditional rename, the final link step fails with
/// `AlreadyExists` if a concurrent writer created `path` first, instead of
/// silently overwriting it. Used by `create`, whose contract is "never
/// overwrite" (a plain rename cannot honor that under concurrent creates).
pub(crate) fn atomic_create(path: &Path, bytes: &[u8]) -> std::io::Result<()> {
    let tmp = unique_temp_path(path);
    if let Err(e) = std::fs::write(&tmp, bytes) {
        let _ = std::fs::remove_file(&tmp);
        return Err(e);
    }
    let result = std::fs::hard_link(&tmp, path);
    let _ = std::fs::remove_file(&tmp);
    result
}

/// Flattens a (possibly nested) slug into a single path segment safe to use
/// as a lock file name directly under the bundle root. `/` is replaced with
/// `__`, which never collides with a real slug segment — `validate_slug`
/// only permits lowercase ASCII/digits/single dashes per segment, so `_` can
/// never appear in a valid slug and no two distinct valid slugs can flatten
/// to the same name.
fn slug_lock_file_name(slug: &str) -> String {
    format!(".{}.lock", slug.replace('/', "__"))
}

/// Run `f` while holding an exclusive lock scoped to `slug`, so the
/// OCC read-check-write sequence in [`set_field`] and
/// [`update`](crate::crud::update) runs as one atomic unit across
/// threads/processes instead of racing on the version check. Spins on an
/// exclusive-create lock file (there is no cross-platform `flock` in std);
/// the lock file is removed once `f` returns.
///
/// The lock file always lives directly under `bundle` (see
/// [`slug_lock_file_name`]) rather than mirroring the slug's own nested path,
/// so locking works for nested slugs (e.g. `pattern/rule-a`) even when the
/// slug's own parent directory doesn't exist yet.
pub(crate) fn with_slug_lock<T>(bundle: &Path, slug: &str, f: impl FnOnce() -> T) -> T {
    let lock_path = bundle.join(slug_lock_file_name(slug));
    loop {
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&lock_path)
        {
            Ok(_) => break,
            Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                std::thread::yield_now();
            }
            // Can't create the lock file (e.g. read-only/missing bundle dir):
            // proceed unlocked rather than hang forever — the caller's own
            // read/write will surface the real error.
            Err(_) => break,
        }
    }
    let result = f();
    let _ = std::fs::remove_file(&lock_path);
    result
}

/// A per-write-unique temp path next to `path`: `<name>.<pid>.<nanos>.tmp`.
fn unique_temp_path(path: &Path) -> PathBuf {
    let name = path
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "concept".to_string());
    let nanos = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    path.with_file_name(format!("{name}.{}.{nanos}.tmp", std::process::id()))
}

/// Whether a parsed concept carries the OKF-required non-empty `type` field
/// (OKF v0.2 §4.1).
pub(crate) fn has_valid_type(concept: &Concept) -> bool {
    match concept.frontmatter.get("type") {
        Some(value) => value.as_str().is_some_and(|s| !s.is_empty()),
        None => false,
    }
}

/// The shared OCC read guard: read `slug`'s current bytes from `bundle`,
/// compute their version, and reject a stale `expected_version` with a
/// typed conflict — the compare-and-swap prelude every OCC-guarded
/// mutation ([`set_field`] and [`update`](crate::crud::update)) runs
/// before touching anything.
///
/// Returns `(path, current_bytes, actual_version)`; on error the on-disk
/// file is untouched and nothing has been written. The error is the shared
/// [`ConceptIoError`], which every op enum wraps, so callers convert with
/// `?` instead of re-declaring the variants.
pub(crate) fn occ_read_guard(
    bundle: &Path,
    slug: &str,
    expected_version: &str,
) -> Result<(PathBuf, Vec<u8>, String), ConceptIoError> {
    let path = concept_path_or(bundle, slug)?;
    let current = match std::fs::read(&path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            return Err(ConceptIoError::NotFound {
                slug: slug.to_string(),
            });
        }
        Err(e) => return Err(ConceptIoError::ReadFailed { path, source: e }),
    };
    let actual = occ::version(&current);
    if actual != expected_version {
        return Err(ConceptIoError::Conflict {
            slug: slug.to_string(),
            expected: expected_version.to_string(),
            actual,
        });
    }
    Ok((path, current, actual))
}

/// The shared I/O surface every CRUD op's typed error enum re-declares:
/// invalid slug, not-found, OCC version conflict, and read/write failure —
/// identical variants and messages across `FieldError`, `CreateError`,
/// `ShowError`, `UpdateError`, and `ListError`. Single source of truth:
/// each op enum wraps this via `#[error(transparent)]`/`#[from]` and keeps
/// only its genuinely distinct variants locally.
///
/// The [`ConceptIoError::Conflict`] variant is deliberately wider than the
/// ops that can construct it: only the OCC-guarded mutators (`set_field`,
/// [`update`]) can produce a conflict, yet `CreateError`/
/// `ShowError`/`ListError` also expose `Io(ConceptIoError::Conflict)` via
/// the `#[from]` blanket. This is behaviorally sound — the variant, its
/// message, and its construction sites are byte-identical to the
/// pre-refactor `UpdateError::Conflict`, and no consumer outside okf-core
/// matches on the op enums (the CLI consumes `Display` only) — and it is
/// the deliberate trade-off the plan's shared-error AC forced: the
/// alternative (a dedicated `OccConflictError`) was explicitly rejected.
/// Accepted as a pre-alpha API smell; revisit if the error surface grows a
/// real external consumer (review ARCHITECTURE-002).
#[derive(Debug, Error)]
pub enum ConceptIoError {
    #[error(
        "invalid slug `{slug}`: must be kebab-case path segments, e.g. `my-concept` or \
         `pattern/my-concept`"
    )]
    InvalidSlug { slug: String },
    #[error("concept `{slug}` not found in the bundle")]
    NotFound { slug: String },
    #[error(
        "version conflict for `{slug}`: expected {expected} but the file is at {actual}; \
         it changed since it was read — re-read and retry"
    )]
    Conflict {
        slug: String,
        expected: String,
        actual: String,
    },
    #[error("failed to read `{path}`: {source}")]
    ReadFailed { path: PathBuf, source: io::Error },
    #[error("failed to write `{path}`: {source}")]
    WriteFailed { path: PathBuf, source: io::Error },
}

/// Typed errors for OCC-guarded single-frontmatter-field mutations — the
/// shared error surface of `concept set-field`, kept in the parent file per
/// the cross-cutting-errors convention.
#[derive(Debug, Error)]
pub enum FieldError {
    #[error(transparent)]
    Io(#[from] ConceptIoError),
    #[error("concept is missing the required `type` field")]
    MissingType,
    #[error("invalid `status` value `{value}`: must be one of `draft`, `stable`, `deprecated`")]
    InvalidStatus { value: String },
    #[error(
        "`type` must be a non-empty string and can never be removed: it is the \
         OKF-required identity field"
    )]
    InvalidType,
    #[error(
        "`{key}` is a structured list/object field per OKF v0.2 §5/§10 and cannot be \
         overwritten with a bare scalar value"
    )]
    ReservedStructuredField { key: String },
    #[error("`{path}` is not a valid OKF concept: {source}")]
    InvalidConcept {
        path: PathBuf,
        source: FrontmatterError,
    },
}

/// Structured §5/§10 frontmatter family names that are list/object-typed per
/// OKF v0.2 and therefore reject bare-scalar writes (a naive scalar write
/// would corrupt their YAML shape): `sources`/`verified`/`generated`
/// (provenance), `stale_after` (lifecycle), `runtime`/`executor`/`attester`
/// (runtime provenance).
pub(crate) const STRUCTURED_FIELD_NAMES: [&str; 7] = [
    "sources",
    "verified",
    "generated",
    "stale_after",
    "runtime",
    "executor",
    "attester",
];

/// The OKF v0.2 §5.4 `status` enum.
const STATUS_VALUES: [&str; 3] = ["draft", "stable", "deprecated"];

/// OCC-guarded mutation of a single frontmatter key.
///
/// `Some(value)` sets the key, overwriting any prior value; `None` removes
/// the key entirely — never serialized as `key: null`. Validation rules:
/// - `status` values are restricted to the OKF v0.2 §5.4 enum
///   (`draft | stable | deprecated`); removal (`None`) is always allowed
///   (absent implies `stable`).
/// - `type` must be a non-empty string when set, and can never be removed
///   (it is the OKF-required identity field, §4.1).
/// - The structured §5/§10 family names ([`STRUCTURED_FIELD_NAMES`]) reject
///   a bare-scalar `Some(value)` write — they are list/object-typed and a
///   scalar write would corrupt their YAML shape; removal is allowed.
/// - Any other key passes through unvalidated: producer-defined/extension
///   fields are permitted per spec §4/§11.
///
/// Shares [`occ_read_guard`]'s read/compare prelude with
/// [`update`](crate::crud::update): the file is only written when its
/// current content hash equals `expected_version`. On error the on-disk
/// file is byte-identical to before the call. Returns
/// `(old_version, new_version)`.
pub fn set_field(
    bundle: &Path,
    slug: &str,
    expected_version: &str,
    key: &str,
    value: Option<&str>,
) -> Result<(String, String), FieldError> {
    with_slug_lock(bundle, slug, || {
        let (path, current, actual) = occ_read_guard(bundle, slug, expected_version)?;
        let (mut frontmatter, body) =
            frontmatter::parse(&current).map_err(|source| FieldError::InvalidConcept {
                path: path.clone(),
                source,
            })?;
        // Validate the requested mutation against the key's contract before
        // touching the mapping.
        validate_field_mutation(key, value)?;
        let Some(map) = frontmatter.as_mapping_mut() else {
            return Err(FieldError::InvalidConcept {
                path: path.clone(),
                source: FrontmatterError::NotAMapping(
                    "expected a YAML mapping, e.g. `type: decision`",
                ),
            });
        };
        apply_field(map, key, value);
        // The result must still carry the OKF-required non-empty `type`
        // (§4.1): checked after the mutation so a `set_field(..., "type",
        // Some(..))` call can add a missing `type`, while any other
        // mutation that leaves the concept typeless (or a `type` write with
        // an empty value) is rejected with the file unchanged.
        let has_type = frontmatter
            .get("type")
            .and_then(|v| v.as_str())
            .is_some_and(|s| !s.is_empty());
        if !has_type {
            return Err(FieldError::MissingType);
        }
        let new_bytes = frontmatter::serialize(&frontmatter, &body).map_err(|source| {
            FieldError::InvalidConcept {
                path: path.clone(),
                source,
            }
        })?;
        write_if_unchanged(&path, slug, &actual, new_bytes.as_bytes())?;
        Ok((actual, occ::version(new_bytes.as_bytes())))
    })
}

/// Re-verify `path`'s on-disk version still equals `expected_actual`
/// immediately before committing `new_bytes`, narrowing the OCC
/// check-then-write race down to this final read-compare-write instead of
/// the whole request: [`set_field`] and [`update`](crate::crud::update)
/// both call this as their commit step, after [`occ_read_guard`] already
/// validated `expected_actual` against the version the caller supplied.
pub(crate) fn write_if_unchanged(
    path: &Path,
    slug: &str,
    expected_actual: &str,
    new_bytes: &[u8],
) -> Result<(), ConceptIoError> {
    let current = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(e) if e.kind() == io::ErrorKind::NotFound => {
            return Err(ConceptIoError::NotFound {
                slug: slug.to_string(),
            });
        }
        Err(e) => {
            return Err(ConceptIoError::ReadFailed {
                path: path.to_path_buf(),
                source: e,
            });
        }
    };
    let actual_now = occ::version(&current);
    if actual_now != expected_actual {
        return Err(ConceptIoError::Conflict {
            slug: slug.to_string(),
            expected: expected_actual.to_string(),
            actual: actual_now,
        });
    }
    atomic_write(path, new_bytes).map_err(|source| ConceptIoError::WriteFailed {
        path: path.to_path_buf(),
        source,
    })
}

/// Validate a single field mutation against the key's contract, before the
/// mapping is touched. Returns `Ok` when the mutation is legal for `key`.
///
/// `pub(crate)`: also reused by the OKF-mode lint checks
/// ([`crate::lint::lint_okf`]) to validate an existing concept's `status`
/// and structured-field values without duplicating the OKF v0.2 §5.4/§5/§10
/// rules a second time.
pub(crate) fn validate_field_mutation(key: &str, value: Option<&str>) -> Result<(), FieldError> {
    match key {
        "status" => {
            if let Some(value) = value
                && !STATUS_VALUES.contains(&value)
            {
                return Err(FieldError::InvalidStatus {
                    value: value.to_string(),
                });
            }
        }
        "type" => {
            let empty = value.is_none_or(|v| v.is_empty());
            if empty {
                return Err(FieldError::InvalidType);
            }
        }
        key if STRUCTURED_FIELD_NAMES.contains(&key) && value.is_some() => {
            return Err(FieldError::ReservedStructuredField {
                key: key.to_string(),
            });
        }
        _ => {}
    }
    Ok(())
}

/// Apply a validated mutation to a frontmatter mapping: `Some(value)`
/// inserts/overwrites `key`; `None` removes it entirely (never serialized
/// as `key: null`).
fn apply_field(map: &mut serde_yaml::Mapping, key: &str, value: Option<&str>) {
    match value {
        Some(value) => {
            map.insert(key.into(), serde_yaml::Value::String(value.to_string()));
        }
        None => {
            map.remove(key);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    #[test]
    fn concept_path_accepts_only_kebab_case_slugs() {
        let bundle = Path::new("/bundle");
        assert_eq!(
            concept_path(bundle, "my-concept"),
            Some(PathBuf::from("/bundle/my-concept.md"))
        );
        for bad in [
            "../outside/x",
            "..",
            "",
            "UPPER",
            "space in",
            "/abs",
            "foo/",
            "foo//bar",
            "a/../b",
            "a\\b",
        ] {
            assert_eq!(concept_path(bundle, bad), None, "should reject {bad:?}");
        }
    }

    #[test]
    fn concept_path_accepts_nested_kebab_case_slugs() {
        let bundle = Path::new("/bundle");
        assert_eq!(
            concept_path(bundle, "pattern/rule-a"),
            Some(PathBuf::from("/bundle/pattern/rule-a.md"))
        );
        assert_eq!(
            concept_path(bundle, "a/b/c-d"),
            Some(PathBuf::from("/bundle/a/b/c-d.md"))
        );
    }

    #[test]
    fn atomic_write_renames_and_leaves_no_temp_artifact() {
        let dir = tempdir("okf-core-crud-atomic");
        let target = dir.join("doc.md");
        atomic_write(&target, b"hello").unwrap();
        assert_eq!(std::fs::read(&target).unwrap(), b"hello");
        let entries: Vec<_> = std::fs::read_dir(&dir)
            .unwrap()
            .map(|e| e.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        assert_eq!(entries, vec!["doc.md"], "no .tmp artifact may remain");
    }

    #[test]
    fn atomic_write_overwrites_existing_file() {
        let dir = tempdir("okf-core-crud-atomic-overwrite");
        let target = dir.join("doc.md");
        std::fs::write(&target, b"old").unwrap();
        atomic_write(&target, b"new content").unwrap();
        assert_eq!(std::fs::read(&target).unwrap(), b"new content");
    }
    const CONCEPT: &str = "---\ntype: decision\ntitle: Test\n---\n# Body\n";
    const DEPRECATED: &str = "---\ntype: decision\nstatus: deprecated\n---\n# Body\n";

    #[test]
    fn set_field_deprecates_and_reports_old_and_new_versions() {
        let dir = tempdir("okf-core-field-deprecate");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        let (old, new) = set_field(
            &dir,
            "use-rust",
            &occ::version(CONCEPT.as_bytes()),
            "status",
            Some("deprecated"),
        )
        .unwrap();
        assert_eq!(old, occ::version(CONCEPT.as_bytes()));
        let on_disk = std::fs::read(dir.join("use-rust.md")).unwrap();
        assert_eq!(new, occ::version(&on_disk));
        let text = String::from_utf8(on_disk).unwrap();
        assert!(text.contains("status: deprecated"));
        assert!(text.contains("type: decision"));
        assert!(text.contains("# Body"));
    }

    #[test]
    fn set_field_none_removes_the_key_entirely_never_null() {
        let dir = tempdir("okf-core-field-clear");
        std::fs::write(dir.join("use-rust.md"), DEPRECATED).unwrap();
        let (old, new) = set_field(
            &dir,
            "use-rust",
            &occ::version(DEPRECATED.as_bytes()),
            "status",
            None,
        )
        .unwrap();
        assert_eq!(old, occ::version(DEPRECATED.as_bytes()));
        let on_disk = std::fs::read(dir.join("use-rust.md")).unwrap();
        assert_eq!(new, occ::version(&on_disk));
        let text = String::from_utf8(on_disk).unwrap();
        assert!(
            !text.contains("status"),
            "status key must be absent, never `status: null`: {text}"
        );
        let (frontmatter, _) = frontmatter::parse(text.as_bytes()).unwrap();
        assert!(frontmatter.get("status").is_none());
    }

    #[test]
    fn set_field_some_overwrites_any_prior_value() {
        let dir = tempdir("okf-core-field-overwrite");
        let draft = "---\ntype: decision\nstatus: draft\n---\n# Body\n";
        std::fs::write(dir.join("use-rust.md"), draft).unwrap();
        set_field(
            &dir,
            "use-rust",
            &occ::version(draft.as_bytes()),
            "status",
            Some("deprecated"),
        )
        .unwrap();
        let text = std::fs::read_to_string(dir.join("use-rust.md")).unwrap();
        assert!(text.contains("status: deprecated"));
        assert!(!text.contains("status: draft"));
    }

    #[test]
    fn set_field_stale_version_is_conflict_and_file_unchanged() {
        let dir = tempdir("okf-core-field-conflict");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        let err =
            set_field(&dir, "use-rust", "00000000", "status", Some("deprecated")).unwrap_err();
        assert!(matches!(err, FieldError::Io(ConceptIoError::Conflict { .. })));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            CONCEPT.as_bytes()
        );
    }

    #[test]
    fn set_field_missing_slug_is_not_found() {
        let dir = tempdir("okf-core-field-missing");
        assert!(matches!(
            set_field(&dir, "nope", "00000000", "status", Some("deprecated")).unwrap_err(),
            FieldError::Io(ConceptIoError::NotFound { .. })
        ));
    }

    #[test]
    fn set_field_traversal_slug_is_invalid_and_writes_nothing_outside() {
        let dir = tempdir("okf-core-field-traversal");
        std::fs::write(dir.join("doc.md"), CONCEPT).unwrap();
        let err = set_field(&dir, "../doc", "00000000", "status", Some("deprecated")).unwrap_err();
        assert!(matches!(
            err,
            FieldError::Io(ConceptIoError::InvalidSlug { .. })
        ));
        assert_eq!(
            std::fs::read(dir.join("doc.md")).unwrap(),
            CONCEPT.as_bytes()
        );
    }

    #[test]
    fn set_field_rejects_non_enum_status_and_leaves_file_unchanged() {
        let dir = tempdir("okf-core-field-bad-status");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        let err = set_field(
            &dir,
            "use-rust",
            &occ::version(CONCEPT.as_bytes()),
            "status",
            Some("bogus"),
        )
        .unwrap_err();
        assert!(matches!(err, FieldError::InvalidStatus { .. }));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            CONCEPT.as_bytes(),
            "a rejected status write must leave the file byte-identical"
        );
    }

    #[test]
    fn set_field_allows_every_status_enum_value() {
        let dir = tempdir("okf-core-field-status-enum");
        for (value, expected) in [
            ("draft", "draft"),
            ("stable", "stable"),
            ("deprecated", "deprecated"),
        ] {
            std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
            set_field(
                &dir,
                "use-rust",
                &occ::version(CONCEPT.as_bytes()),
                "status",
                Some(value),
            )
            .unwrap();
            let text = std::fs::read_to_string(dir.join("use-rust.md")).unwrap();
            assert!(
                text.contains(&format!("status: {expected}")),
                "{value} must be accepted: {text}"
            );
        }
    }

    #[test]
    fn set_field_rejects_bare_scalar_write_to_structured_field() {
        let dir = tempdir("okf-core-field-reserved");
        for key in [
            "sources",
            "verified",
            "generated",
            "stale_after",
            "runtime",
            "executor",
            "attester",
        ] {
            std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
            let err = set_field(
                &dir,
                "use-rust",
                &occ::version(CONCEPT.as_bytes()),
                key,
                Some("a-scalar"),
            )
            .unwrap_err();
            assert!(
                matches!(err, FieldError::ReservedStructuredField { key: k } if k == key),
                "{key} must reject a bare scalar write"
            );
            assert_eq!(
                std::fs::read(dir.join("use-rust.md")).unwrap(),
                CONCEPT.as_bytes(),
                "a rejected structured-field write must leave the file unchanged"
            );
        }
    }

    #[test]
    fn set_field_none_removes_structured_field_allowed() {
        // Removal is not a scalar write: clearing a structured field is
        // shape-safe and must be permitted.
        let dir = tempdir("okf-core-field-reserved-remove");
        let with_sources = "---\ntype: decision\nsources:\n  - okf.md\n---\n# Body\n";
        std::fs::write(dir.join("use-rust.md"), with_sources).unwrap();
        set_field(
            &dir,
            "use-rust",
            &occ::version(with_sources.as_bytes()),
            "sources",
            None,
        )
        .unwrap();
        let text = std::fs::read_to_string(dir.join("use-rust.md")).unwrap();
        assert!(!text.contains("sources"), "sources must be removed: {text}");
    }

    #[test]
    fn set_field_unknown_extension_field_passes_through_unvalidated() {
        let dir = tempdir("okf-core-field-extension");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        set_field(
            &dir,
            "use-rust",
            &occ::version(CONCEPT.as_bytes()),
            "my_custom_field",
            Some("anything"),
        )
        .unwrap();
        let text = std::fs::read_to_string(dir.join("use-rust.md")).unwrap();
        assert!(
            text.contains("my_custom_field: anything"),
            "extension fields pass through unvalidated: {text}"
        );
    }

    #[test]
    fn set_field_type_must_be_non_empty_when_set() {
        let dir = tempdir("okf-core-field-empty-type");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        let err = set_field(
            &dir,
            "use-rust",
            &occ::version(CONCEPT.as_bytes()),
            "type",
            Some(""),
        )
        .unwrap_err();
        assert!(matches!(err, FieldError::InvalidType));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            CONCEPT.as_bytes()
        );
    }

    #[test]
    fn set_field_removing_type_is_rejected() {
        let dir = tempdir("okf-core-field-remove-type");
        std::fs::write(dir.join("use-rust.md"), CONCEPT).unwrap();
        let err = set_field(
            &dir,
            "use-rust",
            &occ::version(CONCEPT.as_bytes()),
            "type",
            None,
        )
        .unwrap_err();
        assert!(matches!(err, FieldError::InvalidType));
        assert_eq!(
            std::fs::read(dir.join("use-rust.md")).unwrap(),
            CONCEPT.as_bytes()
        );
    }

    #[test]
    fn set_field_adding_type_to_typeless_concept_succeeds() {
        // A `type` write repairs a concept that lacks the OKF-required
        // field; other mutations on a typeless concept are rejected.
        let dir = tempdir("okf-core-field-fix-type");
        let no_type = "---\ntitle: no type\n---\n# Body\n";
        std::fs::write(dir.join("doc.md"), no_type).unwrap();
        set_field(
            &dir,
            "doc",
            &occ::version(no_type.as_bytes()),
            "type",
            Some("decision"),
        )
        .unwrap();
        let text = std::fs::read_to_string(dir.join("doc.md")).unwrap();
        assert!(
            text.contains("type: decision"),
            "type must be added: {text}"
        );
    }

    #[test]
    fn set_field_mutation_on_typeless_concept_is_missing_type() {
        let dir = tempdir("okf-core-field-typeless-status");
        let no_type = "---\ntitle: no type\n---\n# Body\n";
        std::fs::write(dir.join("doc.md"), no_type).unwrap();
        let err = set_field(
            &dir,
            "doc",
            &occ::version(no_type.as_bytes()),
            "status",
            Some("deprecated"),
        )
        .unwrap_err();
        assert!(matches!(err, FieldError::MissingType));
        assert_eq!(
            std::fs::read(dir.join("doc.md")).unwrap(),
            no_type.as_bytes()
        );
    }

    #[test]
    fn validate_field_mutation_rejects_bad_status_and_allows_removal() {
        assert!(matches!(
            validate_field_mutation("status", Some("bogus")).unwrap_err(),
            FieldError::InvalidStatus { .. }
        ));
        validate_field_mutation("status", None).unwrap();
        validate_field_mutation("some_extension", Some("anything")).unwrap();
    }

    #[test]
    fn set_field_nested_slug_round_trips() {
        let dir = tempdir("okf-core-field-nested");
        std::fs::create_dir_all(dir.join("pattern")).unwrap();
        std::fs::write(dir.join("pattern/rule-a.md"), CONCEPT).unwrap();
        let (old, new) = set_field(
            &dir,
            "pattern/rule-a",
            &occ::version(CONCEPT.as_bytes()),
            "status",
            Some("deprecated"),
        )
        .unwrap();
        assert_eq!(old, occ::version(CONCEPT.as_bytes()));
        let on_disk = std::fs::read(dir.join("pattern/rule-a.md")).unwrap();
        assert_eq!(new, occ::version(&on_disk));
        assert!(String::from_utf8(on_disk).unwrap().contains("status: deprecated"));
    }

    #[test]
    fn slug_lock_file_name_flattens_nested_slug_under_bundle_root() {
        assert_eq!(slug_lock_file_name("rule-a"), ".rule-a.lock");
        assert_eq!(slug_lock_file_name("pattern/rule-a"), ".pattern__rule-a.lock");
    }

    #[test]
    fn with_slug_lock_actually_locks_nested_slug_across_threads() {
        // Regression test for the nested-slug lock no-op: before the fix,
        // `bundle/.pattern/rule-a.lock`'s parent didn't exist, so
        // `create_new` failed with `NotFound` and the lock silently
        // proceeded unlocked. Two threads racing `with_slug_lock` on the
        // same nested slug must still serialize.
        let dir = tempdir("okf-core-nested-lock");
        std::fs::create_dir_all(dir.join("pattern")).unwrap();

        let counter = std::sync::Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let overlap = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
        let mut handles = Vec::new();
        for _ in 0..8 {
            let dir = dir.clone();
            let counter = counter.clone();
            let overlap = overlap.clone();
            handles.push(std::thread::spawn(move || {
                with_slug_lock(&dir, "pattern/rule-a", || {
                    let before = counter.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                    if before != 0 {
                        overlap.store(true, std::sync::atomic::Ordering::SeqCst);
                    }
                    std::thread::sleep(std::time::Duration::from_millis(5));
                    counter.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
                });
            }));
        }
        for h in handles {
            h.join().unwrap();
        }

        assert!(
            !overlap.load(std::sync::atomic::Ordering::SeqCst),
            "with_slug_lock let two nested-slug critical sections overlap"
        );
        // The flattened lock file must have lived directly under `bundle`
        // (not under the nonexistent `bundle/pattern/` dir) and been
        // cleaned up.
        assert!(!dir.join(".pattern__rule-a.lock").exists());
    }

    #[test]
    fn apply_field_inserts_and_removes_without_null() {
        let mut map = serde_yaml::Mapping::new();
        apply_field(&mut map, "my_key", Some("v"));
        assert_eq!(
            map.get("my_key"),
            Some(&serde_yaml::Value::String("v".into()))
        );
        apply_field(&mut map, "my_key", None);
        assert!(map.get("my_key").is_none(), "removal must drop the key");
    }
}
