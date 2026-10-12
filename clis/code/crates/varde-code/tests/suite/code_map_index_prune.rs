//! Integration tests for `varde map prune` (`index_prune::run_in`).
//!
//! Each test builds index folders under `$TMPDIR` and drives an explicit
//! config dir, so no test needs to redirect `HOME` unless it exercises a
//! `HOME`-derived entry point (`build::run`, `db::path::remove_index`).

use crate::ENV_LOCK;
use serde_json::{Value, json};
use std::ffi::{OsStr, OsString};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};
use varde_code::index_prune::run_in;

/// Serializes the few tests that mutate process-global environment variables.
struct EnvGuard(Vec<(&'static str, Option<OsString>)>);

impl EnvGuard {
    fn new() -> Self {
        Self(Vec::new())
    }

    fn set(&mut self, key: &'static str, value: impl AsRef<OsStr>) {
        if !self.0.iter().any(|(saved_key, _)| *saved_key == key) {
            self.0.push((key, std::env::var_os(key)));
        }
        unsafe { std::env::set_var(key, value) };
    }
}

impl Drop for EnvGuard {
    fn drop(&mut self) {
        for (key, value) in self.0.drain(..) {
            match value {
                Some(value) => unsafe { std::env::set_var(key, value) },
                None => unsafe { std::env::remove_var(key) },
            }
        }
    }
}

fn tempdir(label: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varde-code-prune-{label}-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    std::fs::create_dir_all(&dir).expect("temp dir creates");
    dir
}

fn index_folder(config_dir: &Path, label: &str) -> PathBuf {
    let folder = config_dir.join("repos").join(label);
    std::fs::create_dir_all(&folder).expect("index folder creates");
    std::fs::write(folder.join("index.db"), "index-bytes").expect("index.db writes");
    folder
}

fn write_sidecar(folder: &Path, source: &Path) {
    std::fs::write(
        folder.join("source-root"),
        format!("{}\n", source.display()),
    )
    .expect("sidecar writes");
}

fn run(config_dir: &Path, input: Value) -> Value {
    run_in(config_dir, &input).expect("prune succeeds")
}

fn counted(data: &Value, key: &str) -> u64 {
    data["counts"][key]
        .as_u64()
        .unwrap_or_else(|| panic!("counts.{key} must be a number: {data}"))
}

#[test]
fn prune_classifies_missing_present_and_unknown_and_applies() {
    let config = tempdir("classify-config");
    let present_source = tempdir("classify-present-source");
    let absent_source = tempdir("classify-absent-source");
    let present = index_folder(&config, "present-0000");
    write_sidecar(&present, &present_source);
    let missing = index_folder(&config, "missing-0000");
    write_sidecar(&missing, &absent_source);
    std::fs::remove_dir_all(&absent_source).expect("absent source removes");
    let unknown = index_folder(&config, "unknown-0000");

    let dry = run(&config, json!({}));
    assert_eq!(dry["apply"], false);
    assert_eq!(counted(&dry, "scanned"), 3);
    assert_eq!(counted(&dry, "wouldRemove"), 1);
    assert_eq!(counted(&dry, "unknown"), 1);
    assert_eq!(counted(&dry, "locked"), 0);
    assert_eq!(counted(&dry, "kept"), 1);
    assert!(dry["removed"].is_null(), "dry run has no `removed` key");
    let would_remove = dry["wouldRemove"].as_array().expect("wouldRemove array");
    assert_eq!(would_remove.len(), 1);
    assert_eq!(would_remove[0]["reason"], "source_missing");
    assert!(
        would_remove[0]["folder"]
            .as_str()
            .expect("folder is a string")
            .ends_with("missing-0000")
    );
    assert!(would_remove[0]["bytes"].as_u64().expect("bytes") >= 11);
    let unknown_list = dry["unknown"].as_array().expect("unknown array");
    assert_eq!(unknown_list.len(), 1);
    assert!(
        unknown_list[0]["folder"]
            .as_str()
            .expect("folder is a string")
            .ends_with("unknown-0000")
    );
    assert!(
        missing.exists() && present.exists() && unknown.exists(),
        "dry run deletes nothing"
    );

    let applied = run(&config, json!({"apply": true}));
    assert_eq!(applied["apply"], true);
    assert_eq!(counted(&applied, "removed"), 1);
    assert_eq!(counted(&applied, "unknown"), 1);
    assert_eq!(applied["removed"][0]["reason"], "source_missing");
    assert!(!missing.exists(), "apply removes the missing-source folder");
    assert!(present.exists(), "present-source folders stay");
    assert!(
        unknown.exists(),
        "unknown folders stay without an age opt-in"
    );

    let _ = std::fs::remove_dir_all(&config);
    let _ = std::fs::remove_dir_all(&present_source);
}

#[test]
fn unknown_folders_are_pruned_only_with_an_age_threshold() {
    let config = tempdir("age-config");
    let folder = index_folder(&config, "legacy-0000");
    age_index_db(&folder, 10);

    let without = run(&config, json!({}));
    assert_eq!(counted(&without, "wouldRemove"), 0);
    assert_eq!(counted(&without, "unknown"), 1);

    let too_young = run(&config, json!({"unknownOlderThanDays": 30}));
    assert_eq!(counted(&too_young, "wouldRemove"), 0);
    assert_eq!(counted(&too_young, "unknown"), 1);

    let old_enough = run(&config, json!({"unknownOlderThanDays": 5}));
    assert_eq!(counted(&old_enough, "wouldRemove"), 1);
    assert_eq!(counted(&old_enough, "unknown"), 0);
    assert_eq!(old_enough["wouldRemove"][0]["reason"], "unknown_idle");
    assert!(folder.exists(), "the age threshold is still a dry run");

    let applied = run(&config, json!({"unknownOlderThanDays": 5, "apply": true}));
    assert_eq!(counted(&applied, "removed"), 1);
    assert_eq!(applied["removed"][0]["reason"], "unknown_idle");
    assert!(!folder.exists());

    let _ = std::fs::remove_dir_all(&config);
}

#[test]
fn locked_index_folders_are_skipped() {
    let config = tempdir("locked-config");
    let source = tempdir("locked-source");
    let folder = index_folder(&config, "locked-0000");
    write_sidecar(&folder, &source);
    std::fs::remove_dir_all(&source).expect("source removes");

    // A live builder holds the lock: prune must skip the folder even though
    // its recorded source is gone.
    let lock = varde_code::repo_lock::acquire(&folder.join("index.db"), Duration::from_secs(1))
        .expect("test acquires the lock");
    let held = run(&config, json!({"apply": true}));
    assert_eq!(counted(&held, "locked"), 1);
    assert_eq!(counted(&held, "removed"), 0);
    assert!(folder.exists(), "a locked folder is left alone");

    drop(lock);
    let released = run(&config, json!({"apply": true}));
    assert_eq!(counted(&released, "locked"), 0);
    assert_eq!(counted(&released, "removed"), 1);
    assert!(!folder.exists());

    let _ = std::fs::remove_dir_all(&config);
}

#[test]
fn prune_rejects_invalid_input() {
    let config = tempdir("invalid-config");
    assert!(run_in(&config, &json!(["not", "an", "object"])).is_err());
    assert!(run_in(&config, &json!({"unknownOlderThanDays": "soon"})).is_err());
    let _ = std::fs::remove_dir_all(&config);
}

#[test]
fn build_records_source_root_and_remove_index_deletes_the_sidecar() {
    let _env_lock = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let home = tempdir("env-home");
    let config_root = tempdir("env-config-root");
    let repo = tempdir("env-repo");
    std::fs::write(repo.join("lib.rs"), "pub fn target() {}\n").expect("fixture writes");
    let mut env = EnvGuard::new();
    env.set("HOME", &home);
    env.set("VARDE_CONFIG_DIR", &config_root);

    varde_code::build::run(repo.to_str().expect("repo path is utf-8")).expect("build succeeds");

    let db_path = varde_code::db::path::repo_db_path(&repo);
    let folder = db_path.parent().expect("index folder").to_path_buf();
    let sidecar = folder.join(varde_code::db::path::SOURCE_ROOT_FILE);
    let canonical = std::fs::canonicalize(&repo).expect("repo canonicalizes");
    assert_eq!(
        std::fs::read_to_string(&sidecar).expect("build writes the sidecar"),
        format!("{}\n", canonical.to_string_lossy())
    );

    // With a recorded source root that still exists, prune keeps the folder.
    let config_dir = varde_code::db::path::config_dir();
    let kept = run(&config_dir, json!({}));
    assert_eq!(counted(&kept, "kept"), 1);
    assert_eq!(counted(&kept, "wouldRemove"), 0);

    assert!(varde_code::db::path::remove_index(&repo).expect("remove_index succeeds"));
    assert!(!db_path.exists(), "remove_index deletes index.db");
    assert!(!sidecar.exists(), "remove_index deletes the sidecar");

    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&config_root);
    let _ = std::fs::remove_dir_all(&repo);
}

/// The watcher and build-on-read reach the index through `slice::ensure_fresh`
/// (and explicit callers through `build_index_at`), never through
/// `build::run_with_force`. Those paths must record the source root too, or
/// `prune` can never prove their folders orphaned.
#[test]
fn ensure_fresh_and_build_index_at_record_the_source_root() {
    let _env_lock = ENV_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner);
    let home = tempdir("sidecar-home");
    let config_root = tempdir("sidecar-config-root");
    let repo = tempdir("sidecar-repo");
    std::fs::write(repo.join("lib.rs"), "pub fn target() {}\n").expect("fixture writes");
    let mut env = EnvGuard::new();
    env.set("HOME", &home);
    env.set("VARDE_CONFIG_DIR", &config_root);
    let repo_root = repo.to_str().expect("repo path is utf-8");
    let canonical = std::fs::canonicalize(&repo).expect("repo canonicalizes");
    let expected = format!("{}\n", canonical.to_string_lossy());

    varde_code::slice::ensure_fresh(
        &[varde_code::slice::Slice::Global],
        repo_root,
        &varde_code::slice::Scope::Repo,
    )
    .expect("ensure_fresh builds");
    let sidecar = varde_code::db::path::repo_db_path(&repo)
        .parent()
        .expect("index folder")
        .join(varde_code::db::path::SOURCE_ROOT_FILE);
    assert_eq!(
        std::fs::read_to_string(&sidecar).expect("ensure_fresh writes the sidecar"),
        expected
    );

    // An explicit `db_path` still yields a folder `prune` can scan.
    let explicit_dir = tempdir("sidecar-explicit");
    let explicit_db = explicit_dir.join("index.db");
    varde_code::build_index_at(repo_root, &explicit_db).expect("build_index_at builds");
    assert_eq!(
        std::fs::read_to_string(explicit_dir.join(varde_code::db::path::SOURCE_ROOT_FILE))
            .expect("build_index_at writes the sidecar"),
        expected
    );

    let _ = std::fs::remove_dir_all(&home);
    let _ = std::fs::remove_dir_all(&config_root);
    let _ = std::fs::remove_dir_all(&repo);
    let _ = std::fs::remove_dir_all(&explicit_dir);
}

/// A removal that fails must not discard what was already reclaimed: the
/// failure is named in `failed`, and the scan finishes the other folders.
#[cfg(unix)]
#[test]
fn a_failed_removal_keeps_the_removed_list() {
    use std::os::unix::fs::PermissionsExt;

    let config = tempdir("partial-config");
    let absent_source = tempdir("partial-absent-source");
    let removable = index_folder(&config, "aaa-0000");
    write_sidecar(&removable, &absent_source);
    let failing = index_folder(&config, "zzz-0000");
    write_sidecar(&failing, &absent_source);
    std::fs::remove_dir_all(&absent_source).expect("absent source removes");
    // A read-only folder blocks `remove_dir_all` from unlinking its index.db.
    std::fs::set_permissions(&failing, std::fs::Permissions::from_mode(0o555))
        .expect("failing folder becomes read-only");

    let applied = run(&config, json!({"apply": true}));
    assert_eq!(counted(&applied, "removed"), 1);
    assert_eq!(counted(&applied, "failed"), 1);
    assert!(!removable.exists(), "the earlier folder is still removed");
    let failed = applied["failed"].as_array().expect("failed array");
    assert_eq!(failed.len(), 1);
    assert!(
        failed[0]["folder"]
            .as_str()
            .expect("folder is a string")
            .ends_with("zzz-0000")
    );
    assert!(
        failed[0]["error"]
            .as_str()
            .is_some_and(|error| !error.is_empty()),
        "the failure names its error: {applied}"
    );
    assert!(failing.exists(), "the failed folder is left in place");

    std::fs::set_permissions(&failing, std::fs::Permissions::from_mode(0o755))
        .expect("failing folder becomes writable again");
    let _ = std::fs::remove_dir_all(&config);
}

/// A dry run must be read-only: same tree, same file contents, same mtimes,
/// and no lock files created (the lock probe opens without `create`).
#[test]
fn dry_run_leaves_the_config_root_untouched() {
    let config = tempdir("dry-write-config");
    let present_source = tempdir("dry-write-present-source");
    let absent_source = tempdir("dry-write-absent-source");
    let present = index_folder(&config, "present-0000");
    write_sidecar(&present, &present_source);
    let missing = index_folder(&config, "missing-0000");
    write_sidecar(&missing, &absent_source);
    std::fs::remove_dir_all(&absent_source).expect("absent source removes");
    index_folder(&config, "unknown-0000");

    let before = tree_snapshot(&config);
    let dry = run(&config, json!({"unknownOlderThanDays": 14}));
    // The fresh unknown folder is not 14 days old, so only the missing-source
    // folder is selectable; the age opt-in exercises the unknown path.
    assert_eq!(counted(&dry, "wouldRemove"), 1);
    assert_eq!(counted(&dry, "unknown"), 1);
    assert_eq!(tree_snapshot(&config), before, "dry run writes nothing");
    let _ = std::fs::remove_dir_all(&config);
    let _ = std::fs::remove_dir_all(&present_source);
}

/// Recursively capture every file and directory under `root` as
/// `(relative path, size, mtime, is_dir)`, sorted, for byte-for-byte
/// comparison of a tree before/after a read-only operation.
fn tree_snapshot(root: &Path) -> Vec<(String, u64, SystemTime, bool)> {
    let mut out = Vec::new();
    let mut stack: Vec<(PathBuf, String)> = vec![(root.to_path_buf(), String::new())];
    while let Some((dir, rel)) = stack.pop() {
        for entry in std::fs::read_dir(&dir)
            .expect("config root reads")
            .flatten()
        {
            let name = entry.file_name().to_string_lossy().into_owned();
            let rel_path = if rel.is_empty() {
                name.clone()
            } else {
                format!("{rel}/{name}")
            };
            let metadata = entry.metadata().expect("entry metadata reads");
            let mtime = metadata.modified().expect("mtime reads");
            if metadata.is_dir() {
                out.push((rel_path.clone(), 0, mtime, true));
                stack.push((entry.path(), rel_path));
            } else {
                out.push((rel_path, metadata.len(), mtime, false));
            }
        }
    }
    out.sort();
    out
}

/// Backdate `<folder>/index.db` by `days_old` so the unknown-idle age check
/// sees a settled folder.
fn age_index_db(folder: &Path, days_old: u64) {
    let path = folder.join("index.db");
    let when = SystemTime::now() - Duration::from_secs(days_old * 86_400);
    std::fs::File::options()
        .write(true)
        .open(&path)
        .expect("index.db opens for writing")
        .set_modified(when)
        .expect("index.db mtime sets");
}
