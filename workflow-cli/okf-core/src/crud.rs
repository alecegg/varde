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
use sha2::{Digest, Sha256};
#[cfg(unix)]
use std::fs::File;
use std::io;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};
#[cfg(any(test, not(unix)))]
use std::time::{SystemTime, UNIX_EPOCH};
use thiserror::Error;

/// The on-disk path of a concept file in a bundle.
///
/// A slug is a bundle-root-relative path per OKF v0.2 §2/§3: `/`-separated
/// segments, each independently kebab-case (e.g. `pattern/rule-a`), or a
/// single flat segment for a bundle-root concept (e.g. `my-concept`).
///
/// Returns `None` when any segment is not kebab-case, or the slug contains a
/// traversal, absolute-path, or empty-segment shape. Callers surface that as
/// a typed `InvalidSlug` error. Containment checks are defense in depth, not
/// a security boundary against concurrent directory replacement.
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
pub(crate) fn concept_path_or(bundle: &Path, slug: &str) -> Result<PathBuf, ConceptIoError> {
    let Some(path) = concept_path(bundle, slug) else {
        return Err(ConceptIoError::InvalidSlug {
            slug: slug.to_string(),
        });
    };
    let contained =
        path_is_contained(bundle, &path).map_err(|source| ConceptIoError::ReadFailed {
            path: bundle.to_path_buf(),
            source,
        })?;
    if !contained {
        return Err(ConceptIoError::InvalidSlug {
            slug: slug.to_string(),
        });
    }
    Ok(path)
}

/// Check every existing candidate component against the resolved bundle.
///
/// Missing ancestors are valid for nested concept creation. Existing
/// symlinked ancestors must resolve beneath the canonical bundle root.
/// Dangling symlinks are rejected instead of being mistaken for missing
/// directories. This point-in-time check assumes trusted bundle ownership.
pub(crate) fn path_is_contained(bundle: &Path, candidate: &Path) -> io::Result<bool> {
    let resolved_bundle = match std::fs::canonicalize(bundle) {
        Ok(path) => path,
        // Preserve the operation's own missing-bundle behavior. There is no
        // resolved bundle boundary to escape until the bundle exists.
        Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(true),
        Err(source) => return Err(source),
    };
    let Ok(relative) = candidate.strip_prefix(bundle) else {
        return Ok(false);
    };
    let mut current = bundle.to_path_buf();
    for component in relative.components() {
        current.push(component);
        match std::fs::symlink_metadata(&current) {
            Ok(metadata) if metadata.file_type().is_symlink() => {
                let resolved = match std::fs::canonicalize(&current) {
                    Ok(path) => path,
                    Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(false),
                    Err(source) => return Err(source),
                };
                if !resolved.starts_with(&resolved_bundle) {
                    return Ok(false);
                }
            }
            Ok(_) => {}
            Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(true),
            Err(source) => return Err(source),
        }
    }
    Ok(true)
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
    slug.split('/')
        .all(|segment| segment != ".." && validate_slug_segment(segment))
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
    relative
        .strip_suffix(".md")
        .unwrap_or(&relative)
        .to_string()
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

/// Hash a validated slug into a fixed-size bundle-root lock filename.
///
/// The domain and version prefix prevent accidental digest reuse. Changing
/// this pre-alpha scheme breaks lock coordination with older binaries.
pub(crate) fn slug_lock_file_name(slug: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(b"okf-core\0concept-slug-lock\0v1\0");
    hasher.update(slug.as_bytes());
    format!(".varde-lock-v1-{:x}.lock", hasher.finalize())
}

/// Resolve the storage identity used by mutation locks.
///
/// Existing files and internal symlink aliases must share one lock. Missing
/// files derive an identity from their nearest existing ancestor, so nested
/// paths remain lockable before their final components exist.
fn canonical_lock_slug(bundle: &Path, slug: &str) -> String {
    let Some(path) = concept_path(bundle, slug) else {
        return slug.to_string();
    };
    let Ok(canonical_bundle) = std::fs::canonicalize(bundle) else {
        return slug.to_string();
    };
    let Some(canonical_path) = canonicalize_for_lock(&path) else {
        return slug.to_string();
    };
    if !canonical_path.starts_with(&canonical_bundle) {
        return slug.to_string();
    }
    relative_slug(&canonical_bundle, &canonical_path)
}

/// Canonicalize a path whose final components may not exist yet.
///
/// This preserves the canonical identity of an existing symlinked parent
/// while allowing the caller to lock a nested path before creating it.
fn canonicalize_for_lock(path: &Path) -> Option<PathBuf> {
    let mut missing = Vec::new();
    let mut current = path;
    loop {
        match std::fs::canonicalize(current) {
            Ok(mut resolved) => {
                for component in missing.iter().rev() {
                    resolved.push(component);
                }
                return Some(resolved);
            }
            Err(source) if source.kind() == io::ErrorKind::NotFound => {
                missing.push(current.file_name()?.to_os_string());
                current = current.parent()?;
            }
            Err(_) => return None,
        }
    }
}

/// Run `f` while holding an exclusive lock scoped to `slug`, so the
/// mutation in [`set_field`], [`update`](crate::crud::update), and
/// [`delete`](crate::crud::delete) runs as one atomic unit across processes.
/// On Unix, the persistent lock file carries an advisory OS lock. The OS
/// releases that lock when a process exits. Acquisition remains bounded.
///
/// The lock file always lives directly under `bundle` (see
/// [`slug_lock_file_name`]) rather than mirroring the slug's own nested path,
/// so locking works for nested slugs (e.g. `pattern/rule-a`) even when the
/// slug's own parent directory doesn't exist yet.
pub(crate) fn with_slug_lock<T, E>(
    bundle: &Path,
    slug: &str,
    f: impl FnOnce() -> Result<T, E>,
) -> Result<T, E>
where
    E: From<ConceptIoError>,
{
    // Reject malformed paths before deriving a lock name. Containment stays
    // inside the locked operation. A missing bundle must reach that operation
    // to preserve its established NotFound and ReadFailed behavior.
    if concept_path(bundle, slug).is_none() {
        return Err(ConceptIoError::InvalidSlug {
            slug: slug.to_string(),
        }
        .into());
    }
    if !bundle.is_dir() {
        return f();
    }
    let lock_slug = canonical_lock_slug(bundle, slug);
    let lock_path = bundle.join(slug_lock_file_name(&lock_slug));
    let _guard = acquire_slug_lock(&lock_path).map_err(|source| {
        E::from(ConceptIoError::WriteFailed {
            path: lock_path,
            source,
        })
    })?;
    f()
}

#[cfg(not(test))]
const LOCK_WAIT: Duration = Duration::from_secs(2);
#[cfg(test)]
const LOCK_WAIT: Duration = Duration::from_millis(100);
const LOCK_RETRY: Duration = Duration::from_millis(5);
#[cfg(any(test, not(unix)))]
const STALE_LOCK_AGE: Duration = Duration::from_secs(30);

#[cfg(unix)]
fn acquire_slug_lock(path: &Path) -> io::Result<File> {
    use std::os::fd::AsRawFd;

    const LOCK_EX: i32 = 2;
    const LOCK_NB: i32 = 4;

    unsafe extern "C" {
        fn flock(fd: i32, operation: i32) -> i32;
    }

    let file = std::fs::OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)?;
    let deadline = Instant::now() + LOCK_WAIT;
    loop {
        // SAFETY: `file` owns a valid descriptor for this entire loop.
        let result = unsafe { flock(file.as_raw_fd(), LOCK_EX | LOCK_NB) };
        if result == 0 {
            return Ok(file);
        }
        let source = io::Error::last_os_error();
        if source.kind() != io::ErrorKind::WouldBlock {
            return Err(source);
        }
        if Instant::now() >= deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                format!("timed out acquiring concept lock `{}`", path.display()),
            ));
        }
        std::thread::sleep(LOCK_RETRY);
    }
}

#[cfg(any(test, not(unix)))]
struct OwnedLockFile {
    path: PathBuf,
    token: Vec<u8>,
}

#[cfg(any(test, not(unix)))]
impl Drop for OwnedLockFile {
    fn drop(&mut self) {
        let _ = remove_owned_lock(&self.path, &self.token);
    }
}

#[cfg(not(unix))]
fn acquire_slug_lock(path: &Path) -> io::Result<OwnedLockFile> {
    use std::io::Write;

    let deadline = Instant::now() + LOCK_WAIT;
    loop {
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
        {
            Ok(mut file) => {
                let token = new_lock_token(SystemTime::now());
                if let Err(source) = file.write_all(&token) {
                    let _ = std::fs::remove_file(path);
                    return Err(source);
                }
                return Ok(OwnedLockFile {
                    path: path.to_path_buf(),
                    token,
                });
            }
            Err(source) if source.kind() == io::ErrorKind::AlreadyExists => {
                if reclaim_stale_lock(path, SystemTime::now())? {
                    continue;
                }
                if Instant::now() >= deadline {
                    return Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        format!("timed out acquiring concept lock `{}`", path.display()),
                    ));
                }
                std::thread::sleep(LOCK_RETRY);
            }
            Err(source) => return Err(source),
        }
    }
}

#[cfg(any(test, not(unix)))]
fn new_lock_token(created: SystemTime) -> Vec<u8> {
    static NEXT_TOKEN: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

    let created_nanos = created
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or(0);
    let nonce = NEXT_TOKEN.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    format!("{}:{created_nanos}:{nonce}", std::process::id()).into_bytes()
}

#[cfg(any(test, not(unix)))]
fn remove_owned_lock(path: &Path, token: &[u8]) -> io::Result<()> {
    match std::fs::read(path) {
        Ok(current) if current == token => std::fs::remove_file(path),
        Ok(_) => Ok(()),
        Err(source) if source.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(source) => Err(source),
    }
}

#[cfg(any(test, not(unix)))]
fn reclaim_stale_lock(path: &Path, now: SystemTime) -> io::Result<bool> {
    let observed = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(true),
        Err(source) => return Err(source),
    };
    if !lock_is_stale(path, &observed, now)? {
        return Ok(false);
    }
    // Re-read the ownership token immediately before deletion. A replaced
    // lock belongs to its new writer and must remain untouched.
    if std::fs::read(path).is_ok_and(|current| current == observed) {
        match std::fs::remove_file(path) {
            Ok(()) => return Ok(true),
            Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(true),
            Err(source) => return Err(source),
        }
    }
    Ok(false)
}

#[cfg(any(test, not(unix)))]
fn lock_is_stale(path: &Path, token: &[u8], now: SystemTime) -> io::Result<bool> {
    let token_time = std::str::from_utf8(token)
        .ok()
        .and_then(|text| text.split(':').nth(1))
        .and_then(|value| value.parse::<u128>().ok())
        .and_then(|nanos| u64::try_from(nanos).ok())
        .map(|nanos| UNIX_EPOCH + Duration::from_nanos(nanos));
    let created = match token_time {
        Some(created) => created,
        None => std::fs::metadata(path)?.modified()?,
    };
    Ok(now
        .duration_since(created)
        .is_ok_and(|age| age >= STALE_LOCK_AGE))
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

    #[cfg(unix)]
    #[test]
    fn concept_path_or_rejects_symlinked_parent_outside_bundle() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-contained-path");
        let outside = tempdir("okf-core-contained-path-outside");
        symlink(&outside, dir.join("linked")).unwrap();

        assert!(matches!(
            concept_path_or(&dir, "linked/victim").unwrap_err(),
            ConceptIoError::InvalidSlug { .. }
        ));
    }

    #[cfg(unix)]
    #[test]
    fn concept_path_or_rejects_dangling_symlink_parent() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-contained-dangling");
        symlink(dir.join("missing-target"), dir.join("linked")).unwrap();

        assert!(matches!(
            concept_path_or(&dir, "linked/victim").unwrap_err(),
            ConceptIoError::InvalidSlug { .. }
        ));
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
        assert!(matches!(
            err,
            FieldError::Io(ConceptIoError::Conflict { .. })
        ));
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
        assert!(
            String::from_utf8(on_disk)
                .unwrap()
                .contains("status: deprecated")
        );
    }

    #[cfg(unix)]
    #[test]
    fn set_field_alias_shares_lock_with_canonical_slug() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-field-internal-alias-lock");
        std::fs::create_dir(dir.join("real")).unwrap();
        std::fs::write(dir.join("real/doc.md"), CONCEPT).unwrap();
        symlink("real", dir.join("alias")).unwrap();

        let result = with_slug_lock(&dir, "real/doc", || {
            set_field(
                &dir,
                "alias/doc",
                &occ::version(CONCEPT.as_bytes()),
                "status",
                Some("deprecated"),
            )
        });

        assert!(matches!(
            result,
            Err(FieldError::Io(ConceptIoError::WriteFailed { source, .. }))
                if source.kind() == io::ErrorKind::TimedOut
        ));
        assert_eq!(
            std::fs::read(dir.join("real/doc.md")).unwrap(),
            CONCEPT.as_bytes()
        );
    }

    #[test]
    fn slug_lock_file_name_has_stable_known_vector() {
        assert_eq!(
            slug_lock_file_name("pattern/rule-a"),
            ".varde-lock-v1-71de862b99ec3de6dcc33858a5bdc802af2a1ca08f4248265796328353ce7623.lock"
        );
    }

    #[test]
    fn slug_lock_file_name_is_fixed_size_lowercase_hex() {
        let name = slug_lock_file_name("pattern/rule-a");
        assert_eq!(name.len(), 84);
        let digest = name
            .strip_prefix(".varde-lock-v1-")
            .and_then(|value| value.strip_suffix(".lock"))
            .unwrap();
        assert_eq!(digest.len(), 64);
        assert!(digest.bytes().all(|byte| byte.is_ascii_hexdigit()));
        assert_eq!(digest, digest.to_ascii_lowercase());
        assert_ne!(name, slug_lock_file_name("pattern/rule-b"));
    }

    #[test]
    fn with_slug_lock_supports_long_nested_slug() {
        let dir = tempdir("okf-core-long-lock-slug");
        let slug = format!("{}/{}", "a".repeat(200), "b".repeat(200));
        let lock_path = dir.join(slug_lock_file_name(&slug));

        with_slug_lock(&dir, &slug, || Ok::<(), ConceptIoError>(())).unwrap();

        assert!(lock_path.exists());
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
                    Ok::<(), ConceptIoError>(())
                })
                .unwrap();
            }));
        }
        for h in handles {
            h.join().unwrap();
        }

        assert!(
            !overlap.load(std::sync::atomic::Ordering::SeqCst),
            "with_slug_lock let two nested-slug critical sections overlap"
        );
        let lock_path = dir.join(slug_lock_file_name("pattern/rule-a"));
        assert!(lock_path.exists());
    }

    #[cfg(unix)]
    #[test]
    fn with_slug_lock_aliases_missing_nested_path_to_canonical_parent() {
        use std::os::unix::fs::symlink;

        let dir = tempdir("okf-core-nested-alias-lock");
        std::fs::create_dir(dir.join("real")).unwrap();
        symlink("real", dir.join("alias")).unwrap();

        let result = with_slug_lock(&dir, "real/new-doc", || {
            with_slug_lock(&dir, "alias/new-doc", || Ok::<(), ConceptIoError>(()))
        });

        assert!(matches!(
            result,
            Err(ConceptIoError::WriteFailed { source, .. })
                if source.kind() == io::ErrorKind::TimedOut
        ));
    }

    #[cfg(unix)]
    #[test]
    fn with_slug_lock_returns_bounded_error_for_live_owner() {
        let dir = tempdir("okf-core-live-lock-timeout");
        let lock_path = dir.join(slug_lock_file_name("doc"));
        let _held = acquire_slug_lock(&lock_path).unwrap();
        let started = Instant::now();
        let result = with_slug_lock(&dir, "doc", || Ok::<(), ConceptIoError>(()));

        assert!(matches!(
            result,
            Err(ConceptIoError::WriteFailed { source, .. })
                if source.kind() == io::ErrorKind::TimedOut
        ));
        assert!(started.elapsed() < Duration::from_secs(1));
    }

    #[test]
    fn with_slug_lock_rejects_invalid_slug_without_artifact() {
        let dir = tempdir("okf-core-invalid-lock-slug");
        let result = with_slug_lock(&dir, "../bad", || Ok::<(), ConceptIoError>(()));

        assert!(matches!(result, Err(ConceptIoError::InvalidSlug { .. })));
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 0);
    }

    #[test]
    fn with_slug_lock_does_not_create_missing_bundle() {
        let parent = tempdir("okf-core-missing-lock-bundle");
        let bundle = parent.join("missing");
        let result = with_slug_lock(&bundle, "doc", || {
            Err::<(), _>(ConceptIoError::NotFound { slug: "doc".into() })
        });

        assert!(matches!(result, Err(ConceptIoError::NotFound { .. })));
        assert!(!bundle.exists());
    }

    #[test]
    fn owned_lock_cleanup_preserves_replacement_owner() {
        let dir = tempdir("okf-core-owned-lock-cleanup");
        let path = dir.join("lock");
        let token = new_lock_token(SystemTime::now());
        std::fs::write(&path, &token).unwrap();
        let guard = OwnedLockFile {
            path: path.clone(),
            token,
        };
        let replacement = new_lock_token(SystemTime::now());
        std::fs::write(&path, &replacement).unwrap();

        drop(guard);

        assert_eq!(std::fs::read(path).unwrap(), replacement);
    }

    #[test]
    fn stale_owned_lock_is_reclaimed() {
        let dir = tempdir("okf-core-stale-lock-recovery");
        let path = dir.join("lock");
        let old = SystemTime::now() - STALE_LOCK_AGE - Duration::from_secs(1);
        std::fs::write(&path, new_lock_token(old)).unwrap();

        assert!(reclaim_stale_lock(&path, SystemTime::now()).unwrap());
        assert!(!path.exists());
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
