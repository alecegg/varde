//! DB path convention: `varde_config_dir()/code/repos/<name>-<hash>/index.db`,
//! with the legacy store used until migration is marked complete.
//!
//! Mirrors varde's per-repo isolation + collision-safe hashing scheme under
//! varde-code's own namespace so it never collides with varde's
//! `intelligence.db`.
//!
//! `repo_db_path` best-effort canonicalizes its input before hashing (see
//! its doc comment). Root selection only checks the legacy directory and
//! migration marker; it does not create directories. Parent-directory
//! creation is the `persist()` entry point's responsibility.

use std::path::{Path, PathBuf};

/// Sidecar filename inside an index folder recording the canonical source
/// root the index was built from. The folder name carries only a hash of the
/// root, so this is the only durable proof of which source folder an index
/// belongs to.
pub const SOURCE_ROOT_FILE: &str = "source-root";

/// Hash algorithm: FNV-1a 64-bit over the repo root path exactly as passed.
///
/// Chosen over a cryptographic hash to keep the module dependency-free; 64
/// bits of FNV-1a is collision-safe for distinguishing repo roots, and the
/// hash covers the full path (not just the basename), so two different roots
/// that share a basename still produce different `<hash>` suffixes. The hash
/// is hex-encoded to 16 lowercase hex chars.
fn repo_hash(repo_root: &Path) -> String {
    format!("{:016x}", repo_identity(repo_root) as u64)
}

/// Stable repository identity stamped in indexes so an explicit dbPath can be
/// checked against its source root even when both repositories are empty.
pub fn repo_identity(repo_root: &Path) -> i64 {
    let canonical = std::fs::canonicalize(repo_root).unwrap_or_else(|_| repo_root.to_path_buf());
    const OFFSET: u64 = 0xcbf29ce484222325;
    const PRIME: u64 = 0x100000001b3;
    let mut hash = OFFSET;
    for byte in canonical.to_string_lossy().as_bytes() {
        hash ^= u64::from(*byte);
        hash = hash.wrapping_mul(PRIME);
    }
    hash as i64
}

/// Compute the index.db path for `repo_root`.
///
/// Deterministic *per repo*: callers reach this from different cwds and with
/// different spellings of the same repo (`.` vs. its absolute form, a path
/// through a symlink vs. the resolved target, `../sibling` from a different
/// cwd) — hashing the string verbatim would scatter one repo's index across
/// multiple DBs (e.g. `build --repo-root .` run from inside the repo vs.
/// `watch --repo <absolute path>` run from elsewhere silently landing on two
/// different files). So this first best-effort canonicalizes `repo_root` to
/// the real absolute path it refers to on disk, and hashes that; a `repo_root`
/// that doesn't exist yet (e.g. one a caller is about to create) falls back
/// to the input unchanged rather than erroring, so this call never fails.
pub fn repo_db_path(repo_root: &Path) -> PathBuf {
    repo_db_path_in(&config_dir(), repo_root)
}

/// A linked worktree's read-only base index: the main checkout's index, plus
/// the main checkout root and its hex identity hash.
///
/// The hash (never the path) is what a query envelope may carry, so callers
/// can say where an answer came from without leaking a machine-specific
/// absolute path. The root is in-process context for rewriting the index's
/// main-checkout paths onto the querying worktree; it must not be serialized.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BaseIndex {
    pub db_path: PathBuf,
    pub main_checkout_root: PathBuf,
    pub main_checkout_hash: String,
}

/// The main checkout's index for `repo_root`, when `repo_root` is a linked
/// git worktree and that base index file exists.
///
/// `None` for an ordinary checkout (its own index is authoritative), for a
/// worktree whose main checkout has never been indexed, and whenever git is
/// unavailable or `repo_root` is not in a repository. Callers use this only
/// when the worktree's own index is absent; nothing is built or written.
pub fn base_index_for(repo_root: &Path) -> Option<BaseIndex> {
    let main_root = main_checkout_root(repo_root)?;
    let db_path = repo_db_path(&main_root);
    if !db_path.is_file() {
        return None;
    }
    Some(BaseIndex {
        db_path,
        main_checkout_hash: repo_hash(&main_root),
        main_checkout_root: main_root,
    })
}

/// The main checkout root of a linked worktree `repo_root`.
///
/// A linked worktree's `--git-common-dir` is the main checkout's `.git`, whose
/// parent is the main checkout (non-bare repositories). An ordinary checkout
/// points `--git-dir` and `--git-common-dir` at the same directory, so this
/// returns `None` there.
fn main_checkout_root(repo_root: &Path) -> Option<PathBuf> {
    let output = crate::git::run_git(
        &["rev-parse", "--absolute-git-dir", "--git-common-dir"],
        repo_root,
    )?;
    let mut lines = output.lines();
    let git_dir = PathBuf::from(lines.next()?.trim());
    let common_dir = lines.next()?.trim();
    if common_dir.is_empty() {
        return None;
    }
    let common_dir = {
        let path = Path::new(common_dir);
        if path.is_absolute() {
            path.to_path_buf()
        } else {
            // `--git-common-dir` is printed relative to the invocation
            // directory, which `run_git` set to `repo_root`.
            repo_root.join(path)
        }
    };
    // Canonicalize before comparing so a symlinked temp root (e.g. macOS
    // `/var` vs `/private/var`) cannot make one spell of the same directory
    // look like a linked worktree.
    let git_dir = std::fs::canonicalize(&git_dir).unwrap_or(git_dir);
    let common_dir = std::fs::canonicalize(&common_dir).unwrap_or(common_dir);
    if git_dir == common_dir {
        return None;
    }
    std::fs::canonicalize(common_dir.parent()?).ok()
}

/// Remove the code index for `repo_root` if it exists, along with the
/// `source-root` sidecar beside it.
///
/// The path is derived through the same canonicalized repository identity as
/// every build and watch operation; callers never need to reproduce the hash.
pub fn remove_index(repo_root: &Path) -> anyhow::Result<bool> {
    remove_index_in(&config_dir(), repo_root)
}

fn remove_index_in(config_dir: &Path, repo_root: &Path) -> anyhow::Result<bool> {
    let index_path = repo_db_path_in(config_dir, repo_root);
    let removed = match std::fs::remove_file(&index_path) {
        Ok(()) => true,
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => false,
        Err(err) => {
            return Err(anyhow::anyhow!(
                "removing code index {}: {err}",
                index_path.display()
            ));
        }
    };
    if let Some(folder) = index_path.parent() {
        // Best-effort: the sidecar is prune metadata, not index data.
        let _ = std::fs::remove_file(folder.join(SOURCE_ROOT_FILE));
    }
    Ok(removed)
}

fn repo_db_path_in(config_dir: &Path, repo_root: &Path) -> PathBuf {
    let canonical = std::fs::canonicalize(repo_root).unwrap_or_else(|_| repo_root.to_path_buf());
    let name = canonical
        .file_name()
        .map(|s| s.to_string_lossy().into_owned())
        .unwrap_or_else(|| "repo".to_string());
    let hash = repo_hash(&canonical);
    config_dir
        .join("repos")
        .join(format!("{name}-{hash}"))
        .join("index.db")
}

/// Record `repo_root` as the source root of the index folder containing
/// `db_path`, writing `<index folder>/source-root`.
///
/// The canonical path is written as one UTF-8 line, and only rewritten when
/// the recorded value differs, so a second build of an unchanged root leaves
/// the file's mtime alone.
pub fn record_source_root(db_path: &Path, repo_root: &Path) -> anyhow::Result<()> {
    let Some(folder) = db_path.parent() else {
        return Ok(());
    };
    let canonical = std::fs::canonicalize(repo_root).unwrap_or_else(|_| repo_root.to_path_buf());
    let value = format!("{}\n", canonical.to_string_lossy());
    let sidecar = folder.join(SOURCE_ROOT_FILE);
    if std::fs::read_to_string(&sidecar).is_ok_and(|existing| existing == value) {
        return Ok(());
    }
    std::fs::create_dir_all(folder)?;
    std::fs::write(&sidecar, value)?;
    Ok(())
}

/// Index folders under `<config_dir>/repos`, sorted.
///
/// A missing `repos` directory yields an empty list rather than an error:
/// prune must work on a machine that has never built an index.
pub fn list_index_folders(config_dir: &Path) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(config_dir.join("repos")) else {
        return Vec::new();
    };
    let mut folders: Vec<PathBuf> = entries
        .flatten()
        .map(|entry| entry.path())
        .filter(|path| path.is_dir())
        .collect();
    folders.sort();
    folders
}

/// The varde-code config root, retaining the legacy store until migration.
/// After the migration marker exists, the new root remains authoritative.
pub fn config_dir() -> PathBuf {
    resolve_config_dir(&home_dir(), &varde_core::paths::varde_config_dir())
}

fn resolve_config_dir(home: &Path, config_root: &Path) -> PathBuf {
    let legacy = home.join(".config").join("varde-code");
    let new = config_root.join("code");
    if new.join(".varde-migration-complete").exists() || !legacy.exists() {
        new
    } else {
        legacy
    }
}

/// The user's home directory, read from the `HOME` environment variable.
///
/// Falls back to the literal path segment `~` when `HOME` is unset so the
/// function stays total; `persist()` will fail with a clear error if the
/// resulting parent directory cannot be created.
fn home_dir() -> PathBuf {
    std::env::var_os("HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("~"))
}

#[cfg(test)]
mod path_convention {
    use super::*;

    struct TestRoots {
        fixture: PathBuf,
        home: PathBuf,
        config_root: PathBuf,
        legacy: PathBuf,
        new: PathBuf,
    }

    fn test_roots(label: &str) -> TestRoots {
        // These temporary roots stand in for HOME and varde_config_dir(); no
        // process environment or real user config directory is touched.
        let fixture = std::env::temp_dir().join(format!(
            "varde-code-config-root-{label}-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&fixture);
        std::fs::create_dir_all(&fixture).expect("fixture creates");
        let home = fixture.join("home");
        let config_root = fixture.join("xdg-config-home/varde");
        let legacy = fixture.join("home/.config/varde-code");
        let new = fixture.join("xdg-config-home/varde/code");
        TestRoots {
            fixture,
            home,
            config_root,
            legacy,
            new,
        }
    }

    #[test]
    fn config_dir_uses_new_root_when_neither_directory_exists() {
        let roots = test_roots("neither");

        assert_eq!(
            resolve_config_dir(&roots.home, &roots.config_root),
            roots.new
        );

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn config_dir_uses_legacy_root_when_only_it_exists_and_xdg_is_elsewhere() {
        let roots = test_roots("legacy-only");
        std::fs::create_dir_all(&roots.legacy).unwrap();

        assert_eq!(
            resolve_config_dir(&roots.home, &roots.config_root),
            roots.legacy
        );

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn config_dir_uses_new_root_when_only_it_exists() {
        let roots = test_roots("new-only");
        std::fs::create_dir_all(&roots.new).unwrap();

        assert_eq!(
            resolve_config_dir(&roots.home, &roots.config_root),
            roots.new
        );

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn config_dir_prefers_legacy_root_until_marker_exists() {
        let roots = test_roots("both-before-marker");
        std::fs::create_dir_all(&roots.legacy).unwrap();
        std::fs::create_dir_all(&roots.new).unwrap();

        assert_eq!(
            resolve_config_dir(&roots.home, &roots.config_root),
            roots.legacy
        );

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn config_dir_keeps_new_root_after_legacy_reappears() {
        let roots = test_roots("marker-and-reappeared-legacy");
        std::fs::create_dir_all(&roots.legacy).unwrap();
        std::fs::create_dir_all(&roots.new).unwrap();
        std::fs::write(roots.new.join(".varde-migration-complete"), "").unwrap();

        assert_eq!(
            resolve_config_dir(&roots.home, &roots.config_root),
            roots.new
        );

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn returns_expected_shape_and_is_deterministic() {
        let roots = test_roots("path-shape");
        let config_dir = roots.new.clone();
        let root = Path::new("/work/example-repo");
        let first = repo_db_path_in(&config_dir, root);
        let second = repo_db_path_in(&config_dir, root);
        assert_eq!(first, second, "same input → identical path");

        let text = first.to_string_lossy();
        assert!(
            first.starts_with(config_dir.join("repos")),
            "must live under {config_dir:?}/repos: {text}"
        );
        assert!(
            text.contains("/example-repo-"),
            "basename must appear before the hash: {text}"
        );
        assert!(text.ends_with("/index.db"), "got: {text}");
        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn same_basename_different_roots_hash_differently() {
        let roots = test_roots("same-basename");
        let config_dir = roots.new.clone();
        let a = repo_db_path_in(&config_dir, Path::new("/work/example-repo"));
        let b = repo_db_path_in(&config_dir, Path::new("/elsewhere/example-repo"));
        assert_ne!(
            a, b,
            "roots sharing a basename must not collide; {a:?} vs {b:?}"
        );
        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn nonexistent_repo_root_still_produces_an_index_path() {
        // Canonicalization falls back to the input when the repo is absent.
        let roots = test_roots("no-filesystem-io");
        let root = Path::new("/nonexistent-root-xyz/example-repo");
        let result = repo_db_path_in(&roots.new, root);
        assert!(result.to_string_lossy().contains("example-repo-"));
        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn remove_index_uses_the_derived_repo_path_and_is_idempotent() {
        let roots = test_roots("remove-index");
        let repo_root = roots.fixture.join("repo");
        std::fs::create_dir_all(&repo_root).unwrap();

        let index_path = repo_db_path_in(&roots.new, &repo_root);
        let folder = index_path.parent().unwrap();
        std::fs::create_dir_all(folder).unwrap();
        std::fs::write(&index_path, "index").unwrap();
        let neighboring_file = folder.join("keep.txt");
        std::fs::write(&neighboring_file, "keep").unwrap();
        let sidecar = folder.join(SOURCE_ROOT_FILE);
        std::fs::write(&sidecar, "/somewhere/repo\n").unwrap();

        assert!(remove_index_in(&roots.new, &repo_root).unwrap());
        assert!(!index_path.exists());
        assert!(!sidecar.exists(), "remove_index deletes the sidecar");
        assert_eq!(std::fs::read_to_string(neighboring_file).unwrap(), "keep");
        assert!(!remove_index_in(&roots.new, &repo_root).unwrap());

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }

    #[test]
    fn record_source_root_writes_canonically_and_leaves_unchanged_files_alone() {
        let roots = test_roots("record-source-root");
        let repo = roots.fixture.join("repo");
        std::fs::create_dir_all(&repo).unwrap();
        let db_path = repo_db_path_in(&roots.new, &repo);

        record_source_root(&db_path, &repo).unwrap();
        let sidecar = db_path.parent().unwrap().join(SOURCE_ROOT_FILE);
        let canonical = std::fs::canonicalize(&repo).unwrap();
        assert_eq!(
            std::fs::read_to_string(&sidecar).unwrap(),
            format!("{}\n", canonical.to_string_lossy())
        );

        let before = std::fs::metadata(&sidecar).unwrap().modified().unwrap();
        record_source_root(&db_path, &repo).unwrap();
        let after = std::fs::metadata(&sidecar).unwrap().modified().unwrap();
        assert_eq!(before, after, "an unchanged source root must not rewrite");

        std::fs::remove_dir_all(roots.fixture).unwrap();
    }
}
