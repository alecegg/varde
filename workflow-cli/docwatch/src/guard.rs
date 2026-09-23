//! Change-scope guard.
//!
//! Brackets an agent dispatch (see [`crate::dispatcher`]) with a pre-run
//! snapshot and a post-run diff of the repo root, so that any write the
//! dispatched agent made *outside* the target document is caught and
//! reverted. Files that already had uncommitted changes before the run are
//! normally left untouched and reported for manual review. If an agent resets
//! one of those files clean, the guard restores its pre-run bytes first.
//!
//! This module also doubles as the self-write-loop guard: the watcher's own
//! expected reply/edit write to the target document is not a "change
//! outside scope", and [`GuardResult::self_reply_only`] tells the caller
//! whether the only observed change was that expected reply so it can avoid
//! re-queuing its own write as a new trigger event.
//!
//! Two backends:
//! - git working tree: diffs `git status --porcelain` before/after the run.
//! - non-git fallback: walks the tree recording `(mtime, size)` per file
//!   before the run and restores changed files from a pre-run backup copy.
//!   A file is only *deleted* on revert when it did not exist before the run
//!   (a genuine new file); a pre-existing file is only ever *restored* from
//!   its backup, and if that backup is missing (e.g. the copy failed) the
//!   file is flagged for manual review rather than deleted, so an incomplete
//!   backup can never destroy content. This plain walk does not respect
//!   `.gitignore` (the `ignore` crate was judged not worth adding for this
//!   one fallback path — see task Progress notes for the tradeoff).

use std::collections::{BTreeSet, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::SystemTime;

/// Outcome of a guarded agent run.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct GuardResult {
    /// Paths (relative to the repo root) that changed during the run and
    /// were reverted because they were clean before the run.
    pub reverted: Vec<PathBuf>,
    /// Paths (relative to the repo root) that changed during the run and need
    /// manual review. Further edits to pre-dirty git paths stay in place;
    /// reset-to-clean paths are restored before being flagged.
    /// Non-git paths are flagged when their backup cannot restore them.
    pub pre_dirty_flagged: Vec<PathBuf>,
    /// True when the target document actually changed and that change was
    /// exactly the expected reply/`[done]` write, with no other files
    /// touched — i.e. this run resolved its trigger and should not be
    /// treated as producing a new one. `false` when nothing changed at all:
    /// an unchanged target is not evidence a reply was written.
    pub self_reply_only: bool,
}

impl GuardResult {
    /// True when nothing needed reverting and nothing needs manual review.
    pub fn is_clean(&self) -> bool {
        self.reverted.is_empty() && self.pre_dirty_flagged.is_empty()
    }
}

/// Run `run` bracketed by a pre/post snapshot of `repo_root`, reverting any
/// change to a file other than `target` (relative to `repo_root`) that
/// wasn't already dirty before the run.
///
/// Dispatches to the git-status-based backend when `repo_root` is a git
/// working tree, otherwise falls back to a plain mtime/size walk.
pub fn run_guarded<F: FnOnce()>(repo_root: &Path, target: &Path, run: F) -> GuardResult {
    if repo_root.join(".git").exists() {
        run_guarded_git(repo_root, target, run)
    } else {
        run_guarded_walk(repo_root, target, run)
    }
}

fn target_rel_string(target: &Path) -> String {
    target.to_string_lossy().replace('\\', "/")
}

fn read_target(repo_root: &Path, target: &Path) -> String {
    fs::read_to_string(repo_root.join(target)).unwrap_or_default()
}

/// A line-based heuristic for "the only difference between `pre` and `post`
/// is an appended/edited reply or `[done]` marker line". Every line present
/// in `post` but not accounted for in `pre` (by simple multiset diff) must
/// itself look like a reply/done marker for this to return `true`.
///
/// Returns `false` when `pre == post`: an *unchanged* target is not evidence
/// that a reply was written, and callers that use this to decide whether a
/// dispatch actually produced its expected reply (see
/// [`GuardResult::self_reply_only`]) must not conflate "nothing happened"
/// with "the reply happened".
fn diff_is_self_reply_only(pre: &str, post: &str) -> bool {
    if pre == post {
        return false;
    }
    let mut pre_counts: HashMap<&str, i32> = HashMap::new();
    for line in pre.lines() {
        *pre_counts.entry(line).or_insert(0) += 1;
    }
    let mut extra_lines = Vec::new();
    for line in post.lines() {
        if let Some(c) = pre_counts.get_mut(line)
            && *c > 0
        {
            *c -= 1;
            continue;
        }
        extra_lines.push(line);
    }
    if extra_lines.is_empty() {
        // Only removed content, no additions/edits that look like a reply —
        // treat conservatively as not a self-reply.
        return false;
    }
    extra_lines
        .iter()
        .all(|line| line.contains("-reply:") || line.trim_end().ends_with("[done]"))
}

// --- git backend ---------------------------------------------------------

/// Parses `git status --porcelain` output for `repo_root` into a map of
/// repo-root-relative path -> two-character status code.
fn git_status(repo_root: &Path) -> HashMap<String, String> {
    let mut map = HashMap::new();
    let output = Command::new("git")
        .arg("-C")
        .arg(repo_root)
        .arg("status")
        .arg("--porcelain")
        .arg("-z")
        .output();
    let Ok(output) = output else {
        return map;
    };
    // `-z` is NUL-terminated and, crucially, emits paths verbatim — unlike the
    // default porcelain, which wraps paths containing spaces in quotes and
    // octal-escapes non-ASCII bytes. Those quoted/escaped forms don't match
    // the real path, so `git checkout -- <path>` would silently no-op and the
    // out-of-scope write would escape the guard. Splitting on NUL keeps the
    // exact bytes we then hand back to git for reverting.
    let text = String::from_utf8_lossy(&output.stdout);
    let mut fields = text.split('\0');
    while let Some(entry) = fields.next() {
        // A status entry is `XY <space> PATH`; anything shorter (e.g. the
        // trailing empty field after the final NUL) isn't one.
        if entry.len() < 4 {
            continue;
        }
        let code = entry[0..2].to_string();
        let path = entry[3..].to_string();
        // Rename/copy entries are followed by a second NUL-terminated field
        // holding the old path; consume it so it isn't mis-read as its own
        // entry. We track the new path (`entry`), matching the prior `old ->
        // new` behaviour and the folder the agent actually wrote to.
        if code.starts_with('R') || code.starts_with('C') {
            let _ = fields.next();
        }
        map.insert(path, code);
    }
    map
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct IndexEntry {
    mode: String,
    object: String,
    stage: String,
}

fn git_index_entries(repo_root: &Path) -> HashMap<String, Vec<IndexEntry>> {
    let output = Command::new("git")
        .arg("-C")
        .arg(repo_root)
        .args(["ls-files", "-s", "-z"])
        .output();
    let Ok(output) = output else {
        return HashMap::new();
    };
    if !output.status.success() {
        return HashMap::new();
    }

    let mut entries = HashMap::new();
    for record in output.stdout.split(|byte| *byte == 0) {
        let Some(separator) = record.iter().position(|byte| *byte == b'\t') else {
            continue;
        };
        let (metadata, path_with_separator) = record.split_at(separator);
        let path = &path_with_separator[1..];
        let fields: Vec<&[u8]> = metadata
            .split(|byte| *byte == b' ')
            .filter(|field| !field.is_empty())
            .collect();
        if fields.len() != 3 {
            continue;
        }
        let path = String::from_utf8_lossy(path).into_owned();
        entries
            .entry(path)
            .or_insert_with(Vec::new)
            .push(IndexEntry {
                mode: String::from_utf8_lossy(fields[0]).into_owned(),
                object: String::from_utf8_lossy(fields[1]).into_owned(),
                stage: String::from_utf8_lossy(fields[2]).into_owned(),
            });
    }
    entries
}

fn restore_git_index_path(repo_root: &Path, path: &str, expected: &[IndexEntry]) -> bool {
    let removed = Command::new("git")
        .arg("-C")
        .arg(repo_root)
        .args(["update-index", "--force-remove", "--"])
        .arg(path)
        .status()
        .is_ok_and(|status| status.success());

    let mut restored = removed || expected.is_empty();
    for entry in expected {
        let status = if entry.stage == "0" {
            Command::new("git")
                .arg("-C")
                .arg(repo_root)
                .args(["update-index", "--add", "--cacheinfo"])
                .arg(format!("{},{},{}", entry.mode, entry.object, path))
                .status()
        } else {
            let input = format!(
                "{} {} {}\t{}\0",
                entry.mode, entry.object, entry.stage, path
            );
            let mut command = Command::new("git");
            command
                .arg("-C")
                .arg(repo_root)
                .args(["update-index", "-z", "--index-info"]);
            let Ok(mut child) = command.stdin(std::process::Stdio::piped()).spawn() else {
                restored = false;
                continue;
            };
            let write_ok = child.stdin.take().is_some_and(|mut stdin| {
                std::io::Write::write_all(&mut stdin, input.as_bytes()).is_ok()
            });
            if !write_ok {
                restored = false;
            }
            child.wait()
        };
        restored &= status.is_ok_and(|status| status.success());
    }

    restored
        && git_index_entries(repo_root)
            .get(path)
            .map_or_else(|| expected.is_empty(), |actual| actual == expected)
}

fn restore_git_worktree_path(
    repo_root: &Path,
    path: &str,
    pre_content: Option<&[u8]>,
    restore_from_index: bool,
) -> bool {
    let live_path = repo_root.join(path);
    let restored = if let Some(content) = pre_content {
        if let Some(parent) = live_path.parent() {
            let _ = fs::create_dir_all(parent);
        }
        fs::write(&live_path, content).is_ok()
    } else if restore_from_index {
        Command::new("git")
            .arg("-C")
            .arg(repo_root)
            .args(["checkout-index", "--force", "--"])
            .arg(path)
            .status()
            .is_ok_and(|status| status.success())
    } else {
        fs::remove_file(&live_path).map_or_else(
            |error| error.kind() == std::io::ErrorKind::NotFound,
            |_| true,
        )
    };

    let actual = fs::read(&live_path).ok();
    restored
        && if restore_from_index {
            actual.is_some()
        } else {
            actual.as_deref() == pre_content
        }
}

fn restore_clean_git_path(
    repo_root: &Path,
    path: &str,
    pre_index: &HashMap<String, Vec<IndexEntry>>,
) -> bool {
    let expected_index = pre_index.get(path).cloned().unwrap_or_default();
    let index_restored = restore_git_index_path(repo_root, path, &expected_index);
    let worktree_restored = if expected_index.is_empty() {
        restore_git_worktree_path(repo_root, path, None, false)
    } else {
        restore_git_worktree_path(repo_root, path, None, true)
    };
    index_restored
        && worktree_restored
        && !git_status(repo_root).contains_key(path)
        && git_index_entries(repo_root).get(path).map_or_else(
            || expected_index.is_empty(),
            |actual| actual == &expected_index,
        )
}

fn file_meta(path: &Path) -> Option<(SystemTime, u64)> {
    let meta = fs::metadata(path).ok()?;
    let mtime = meta.modified().ok()?;
    Some((mtime, meta.len()))
}

fn run_guarded_git<F: FnOnce()>(repo_root: &Path, target: &Path, run: F) -> GuardResult {
    let target_rel = target_rel_string(target);
    let pre_status = git_status(repo_root);
    let pre_index = git_index_entries(repo_root);
    // Snapshot full content for already-dirty paths so we can tell whether a
    // pre-dirty path was *further* modified during the run, since its git
    // status code (e.g. "M") typically won't change either way. Compares
    // actual bytes rather than `(mtime, size)`, which can both miss a
    // same-size rewrite that lands within one filesystem mtime tick and
    // false-positive on a mtime-only touch (e.g. `touch`) that changed
    // nothing — pre-dirty paths are typically few and small, so the extra
    // read is cheap.
    let pre_dirty_content: HashMap<String, Option<Vec<u8>>> = pre_status
        .keys()
        .map(|p| (p.clone(), fs::read(repo_root.join(p)).ok()))
        .collect();
    let pre_target_content = read_target(repo_root, target);

    run();

    let post_status = git_status(repo_root);
    let post_target_content = read_target(repo_root, target);

    let changed_paths: BTreeSet<String> = pre_status
        .keys()
        .chain(post_status.keys())
        .cloned()
        .collect();
    let mut reverted = Vec::new();
    let mut pre_dirty_flagged = Vec::new();
    for path in changed_paths {
        if path == target_rel {
            continue;
        }
        match restore_git_change(
            repo_root,
            &path,
            &pre_status,
            &post_status,
            &pre_index,
            &pre_dirty_content,
        ) {
            GitRestore::Unchanged => {}
            GitRestore::Reverted => reverted.push(PathBuf::from(path)),
            GitRestore::Flagged => pre_dirty_flagged.push(PathBuf::from(path)),
        }
    }

    let other_files_touched = !reverted.is_empty() || !pre_dirty_flagged.is_empty();
    let self_reply_only =
        !other_files_touched && diff_is_self_reply_only(&pre_target_content, &post_target_content);

    GuardResult {
        reverted,
        pre_dirty_flagged,
        self_reply_only,
    }
}

enum GitRestore {
    Unchanged,
    Reverted,
    Flagged,
}

fn restore_git_change(
    repo_root: &Path,
    path: &str,
    pre_status: &HashMap<String, String>,
    post_status: &HashMap<String, String>,
    pre_index: &HashMap<String, Vec<IndexEntry>>,
    pre_dirty_content: &HashMap<String, Option<Vec<u8>>>,
) -> GitRestore {
    let Some(pre_content) = pre_dirty_content.get(path) else {
        return restore_clean_git_change(repo_root, path, pre_index);
    };
    let post_content = fs::read(repo_root.join(path)).ok();
    let unchanged = post_content == *pre_content && post_status.get(path) == pre_status.get(path);
    if unchanged {
        return GitRestore::Unchanged;
    }
    if !post_status.contains_key(path) {
        restore_pre_dirty_path(repo_root, path, pre_status, pre_index, pre_content);
    }
    GitRestore::Flagged
}

fn restore_clean_git_change(
    repo_root: &Path,
    path: &str,
    pre_index: &HashMap<String, Vec<IndexEntry>>,
) -> GitRestore {
    if restore_clean_git_path(repo_root, path, pre_index) {
        return GitRestore::Reverted;
    }
    eprintln!("docwatch: could not restore clean path {path}; manual review required");
    GitRestore::Flagged
}

fn restore_pre_dirty_path(
    repo_root: &Path,
    path: &str,
    pre_status: &HashMap<String, String>,
    pre_index: &HashMap<String, Vec<IndexEntry>>,
    pre_content: &Option<Vec<u8>>,
) {
    let expected_index = pre_index.get(path).cloned().unwrap_or_default();
    let index_restored = restore_git_index_path(repo_root, path, &expected_index);
    let worktree_restored =
        restore_git_worktree_path(repo_root, path, pre_content.as_deref(), false);
    let status_restored = git_status(repo_root).get(path) == pre_status.get(path);
    if !index_restored || !worktree_restored || !status_restored {
        eprintln!("docwatch: could not restore pre-run dirty path {path}; manual review required");
    }
}

// --- non-git walk fallback -------------------------------------------------

/// Recursively walks `root`, returning a map of root-relative path ->
/// `(mtime, size)` for every regular file. Does not respect `.gitignore`
/// (see module docs) — acceptable for the non-git fallback path.
fn walk_snapshot(root: &Path) -> HashMap<PathBuf, (SystemTime, u64)> {
    let mut out = HashMap::new();
    walk_snapshot_into(root, root, &mut out);
    out
}

fn walk_snapshot_into(root: &Path, dir: &Path, out: &mut HashMap<PathBuf, (SystemTime, u64)>) {
    let Ok(entries) = fs::read_dir(dir) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Ok(file_type) = entry.file_type() else {
            continue;
        };
        if file_type.is_dir() {
            walk_snapshot_into(root, &path, out);
        } else if file_type.is_file()
            && let Ok(rel) = path.strip_prefix(root)
            && let Some(meta) = file_meta(&path)
        {
            out.insert(rel.to_path_buf(), meta);
        }
    }
}

fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    fs::create_dir_all(dst)?;
    for entry in fs::read_dir(src)? {
        let entry = entry?;
        let file_type = entry.file_type()?;
        let dest_path = dst.join(entry.file_name());
        if file_type.is_dir() {
            copy_dir_all(&entry.path(), &dest_path)?;
        } else if file_type.is_file() {
            fs::copy(entry.path(), &dest_path)?;
        }
    }
    Ok(())
}

fn run_guarded_walk<F: FnOnce()>(repo_root: &Path, target: &Path, run: F) -> GuardResult {
    let target_rel = PathBuf::from(target_rel_string(target));
    let pre_snapshot = walk_snapshot(repo_root);
    let pre_target_content = read_target(repo_root, target);

    let backup_dir = guard_backup_dir();
    // A failed/partial backup must never lead to destructive reverts. The
    // per-file logic below only *restores* files that are present in the
    // backup and only *deletes* files that did not exist before the run, so
    // an incomplete backup degrades to "flag for manual review" rather than
    // deleting or truncating a file we cannot safely restore. Surface the
    // failure instead of swallowing it.
    if let Err(e) = copy_dir_all(repo_root, &backup_dir) {
        eprintln!("docwatch: guard backup incomplete ({e}); reverts will be conservative");
    }

    run();

    let post_snapshot = walk_snapshot(repo_root);
    let post_target_content = read_target(repo_root, target);

    let mut reverted = Vec::new();
    let mut pre_dirty_flagged = Vec::new();
    let all_paths: BTreeSet<PathBuf> = pre_snapshot
        .keys()
        .chain(post_snapshot.keys())
        .cloned()
        .collect();

    for path in all_paths {
        if path == target_rel {
            continue;
        }
        let pre_meta = pre_snapshot.get(&path);
        let post_meta = post_snapshot.get(&path);
        if pre_meta == post_meta {
            continue;
        }
        match restore_walk_change(repo_root, &backup_dir, &path, pre_meta.is_some()) {
            WalkRestore::Reverted => reverted.push(path),
            WalkRestore::Flagged => pre_dirty_flagged.push(path),
        }
    }

    let other_files_touched = !reverted.is_empty() || !pre_dirty_flagged.is_empty();
    let self_reply_only =
        !other_files_touched && diff_is_self_reply_only(&pre_target_content, &post_target_content);

    let _ = fs::remove_dir_all(&backup_dir);

    GuardResult {
        reverted,
        pre_dirty_flagged,
        self_reply_only,
    }
}

fn guard_backup_dir() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    std::env::temp_dir().join(format!(
        "docwatch-guard-backup-{}-{nonce}",
        std::process::id()
    ))
}

enum WalkRestore {
    Reverted,
    Flagged,
}

fn restore_walk_change(
    repo_root: &Path,
    backup_dir: &Path,
    path: &Path,
    existed_before: bool,
) -> WalkRestore {
    let live_path = repo_root.join(path);
    if !existed_before {
        return if fs::remove_file(live_path).is_ok() {
            WalkRestore::Reverted
        } else {
            WalkRestore::Flagged
        };
    }
    let backup_path = backup_dir.join(path);
    if !backup_path.exists() {
        return WalkRestore::Flagged;
    }
    if let Some(parent) = live_path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if fs::copy(backup_path, live_path).is_ok() {
        WalkRestore::Reverted
    } else {
        WalkRestore::Flagged
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::process::Command as StdCommand;

    fn unique_dir(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "docwatch-guard-test-{}-{}",
            std::process::id(),
            name
        ))
    }

    fn git(dir: &Path, args: &[&str]) {
        let status = StdCommand::new("git")
            .current_dir(dir)
            .args(args)
            .status()
            .expect("git command failed to spawn");
        assert!(status.success(), "git {:?} failed", args);
    }

    fn init_git_repo(dir: &Path) {
        fs::create_dir_all(dir).unwrap();
        git(dir, &["init", "-q"]);
        git(dir, &["config", "user.email", "test@example.com"]);
        git(dir, &["config", "user.name", "Test"]);
    }

    fn commit_all(dir: &Path, msg: &str) {
        git(dir, &["add", "-A"]);
        git(dir, &["commit", "-q", "-m", msg]);
    }

    #[test]
    fn only_target_changed_reverts_nothing() {
        let dir = unique_dir("only_target_changed");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        commit_all(&dir, "init");

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
        });

        assert!(result.reverted.is_empty());
        assert!(result.pre_dirty_flagged.is_empty());
        assert!(result.is_clean());

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn unrelated_clean_file_touched_is_reverted() {
        let dir = unique_dir("unrelated_clean_file");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            fs::write(dir.join("other.md"), "tampered\n").unwrap();
        });

        assert_eq!(result.reverted, vec![PathBuf::from("other.md")]);
        assert!(result.pre_dirty_flagged.is_empty());
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "original\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn staged_out_of_scope_file_restores_index_and_worktree() {
        let dir = unique_dir("staged_out_of_scope");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            fs::write(dir.join("other.md"), "agent edit\n").unwrap();
            git(&dir, &["add", "other.md"]);
        });

        assert_eq!(result.reverted, vec![PathBuf::from("other.md")]);
        assert!(result.pre_dirty_flagged.is_empty());
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "original\n"
        );
        let status = StdCommand::new("git")
            .current_dir(&dir)
            .args(["status", "--porcelain", "--", "other.md"])
            .output()
            .unwrap();
        assert!(status.stdout.is_empty());

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn out_of_scope_file_with_spaces_in_name_is_reverted() {
        // Regression: default `git status --porcelain` quotes paths with
        // spaces (`"a file.md"`), so the pre-`-z` parser keyed the map on the
        // quoted form and `git checkout --` no-op'd, letting the write escape.
        let dir = unique_dir("spaced_name");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("a file.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            fs::write(dir.join("a file.md"), "tampered\n").unwrap();
        });

        assert_eq!(result.reverted, vec![PathBuf::from("a file.md")]);
        assert!(result.pre_dirty_flagged.is_empty());
        assert_eq!(
            fs::read_to_string(dir.join("a file.md")).unwrap(),
            "original\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn already_dirty_file_further_modified_is_flagged_not_reverted() {
        let dir = unique_dir("already_dirty");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        // Dirty the file before dispatch, without committing.
        fs::write(dir.join("other.md"), "user's own edit\n").unwrap();

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            std::thread::sleep(std::time::Duration::from_millis(20));
            fs::write(
                dir.join("other.md"),
                "user's own edit, further mangled by agent\n",
            )
            .unwrap();
        });

        assert!(result.reverted.is_empty());
        assert_eq!(result.pre_dirty_flagged, vec![PathBuf::from("other.md")]);
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "user's own edit, further mangled by agent\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn already_dirty_file_same_size_rewrite_within_mtime_tick_is_flagged() {
        // Regression test for CORRECTNESS-010: a same-size rewrite of a
        // pre-dirty file must be caught even without any elapsed time
        // between the pre-run snapshot and the rewrite (previously the
        // `(mtime, size)` comparison could miss this on a coarse-mtime
        // filesystem; content comparison catches it unconditionally).
        let dir = unique_dir("already_dirty_same_size");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        fs::write(dir.join("other.md"), "user's own edit\n").unwrap();

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            // Same byte length as "user's own edit\n" — no size change, and
            // no sleep, so mtime may not tick either on a coarse clock.
            fs::write(dir.join("other.md"), "user's swap edit\n").unwrap();
        });

        assert!(result.reverted.is_empty());
        assert_eq!(result.pre_dirty_flagged, vec![PathBuf::from("other.md")]);
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "user's swap edit\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn already_dirty_file_reset_clean_is_restored_and_flagged() {
        let dir = unique_dir("already_dirty_reset");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");
        fs::write(dir.join("other.md"), "user's own edit\n").unwrap();

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            git(&dir, &["checkout", "--", "other.md"]);
        });

        assert!(result.reverted.is_empty());
        assert_eq!(result.pre_dirty_flagged, vec![PathBuf::from("other.md")]);
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "user's own edit\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn already_staged_file_reset_clean_restores_index_and_worktree() {
        let dir = unique_dir("already_staged_reset");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");
        fs::write(dir.join("other.md"), "user's staged edit\n").unwrap();
        git(&dir, &["add", "other.md"]);

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            git(&dir, &["reset", "HEAD", "--", "other.md"]);
            git(&dir, &["checkout", "--", "other.md"]);
        });

        assert!(result.reverted.is_empty());
        assert_eq!(result.pre_dirty_flagged, vec![PathBuf::from("other.md")]);
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "user's staged edit\n"
        );
        let status = StdCommand::new("git")
            .current_dir(&dir)
            .args(["status", "--porcelain", "--", "other.md"])
            .output()
            .unwrap();
        assert_eq!(String::from_utf8_lossy(&status.stdout), "M  other.md\n");

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn non_git_fallback_reverts_unrelated_file() {
        let dir = unique_dir("non_git_fallback");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        fs::write(dir.join("other.md"), "original\n").unwrap();

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            fs::write(dir.join("other.md"), "tampered\n").unwrap();
        });

        assert_eq!(result.reverted, vec![PathBuf::from("other.md")]);
        assert_eq!(
            fs::read_to_string(dir.join("other.md")).unwrap(),
            "original\n"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn non_git_fallback_removes_newly_created_out_of_scope_file() {
        let dir = unique_dir("non_git_created");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
            // Agent creates an unrelated file that did not exist pre-run.
            fs::write(dir.join("scratch.md"), "junk\n").unwrap();
        });

        assert_eq!(result.reverted, vec![PathBuf::from("scratch.md")]);
        assert!(result.pre_dirty_flagged.is_empty());
        assert!(
            !dir.join("scratch.md").exists(),
            "new file should be removed"
        );

        fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn self_reply_only_diff_is_detected() {
        let pre = "c: what time is it?\n";
        let post = "c: what time is it?\nc-reply: it's noon\n";
        assert!(diff_is_self_reply_only(pre, post));

        let post_done = "c: fix this typo [done]\n";
        let pre_done = "c: fix this typo\n";
        assert!(diff_is_self_reply_only(pre_done, post_done));
    }

    #[test]
    fn substantive_edit_is_not_self_reply_only() {
        let pre = "c: hello\n";
        let post = "some completely different content that isn't a reply\n";
        assert!(!diff_is_self_reply_only(pre, post));
    }

    #[test]
    fn run_guarded_reports_self_reply_only_when_only_target_gets_a_reply() {
        let dir = unique_dir("self_reply_run");
        init_git_repo(&dir);
        fs::write(dir.join("target.md"), "c: hello\n").unwrap();
        commit_all(&dir, "init");

        let target = Path::new("target.md");
        let result = run_guarded(&dir, target, || {
            fs::write(dir.join("target.md"), "c: hello\nc-reply: hi [done]\n").unwrap();
        });

        assert!(result.self_reply_only);

        fs::remove_dir_all(&dir).unwrap();
    }
}
