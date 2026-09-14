//! `_run-watcher` loop: debounced filesystem watching over a folder, with
//! ignore-pattern filtering and per-file locking, that calls the trigger
//! parser on changed `.md` files.
//!
//! `on_change` is a callback invoked with the parsed `PendingTask`s for a
//! file. [`Pipeline`] wires that callback to the real dispatch ->
//! change-scope-guard -> retry-cap flow: parse -> lock (already handled by
//! `process_change`) -> dispatch (injectable, matching
//! `dispatcher::dispatch`'s shape) -> guard::run_guarded -> on failure/scope
//! violation, write an `@<tag>-error:` line back into the target file.

use crate::dispatcher::DispatchResult;
use crate::guard;
use crate::lock::FileLock;
use crate::parser::{self, Agent, PendingTask};
use notify_debouncer_mini::{new_debouncer, DebouncedEventKind};
use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::mpsc::channel;
use std::time::Duration;

/// Number of consecutive dispatch failures for the same unresolved trigger
/// line before the pipeline gives up and writes an error marker instead of
/// redispatching.
pub const MAX_ATTEMPTS: u32 = 3;

/// In-memory per-trigger attempt counter, keyed by `(file path, trigger line
/// text)`. A changed trigger line produces a different key, which — since
/// nothing ever looks up the old key again — behaves exactly like resetting
/// the counter for that line.
#[derive(Debug, Default)]
pub struct RetryTracker {
    attempts: HashMap<(PathBuf, String), u32>,
}

impl RetryTracker {
    pub fn new() -> Self {
        Self::default()
    }

    /// Record a failed attempt for `key`, returning the new attempt count.
    fn record_failure(&mut self, key: (PathBuf, String)) -> u32 {
        let count = self.attempts.entry(key).or_insert(0);
        *count += 1;
        *count
    }

    /// Clear any tracked attempts for `key` (call on success/resolution).
    fn resolve(&mut self, key: &(PathBuf, String)) {
        self.attempts.remove(key);
    }

    /// Drop every tracked entry for `path`, regardless of trigger-line text.
    /// Call when a change event for `path` resolves to no pending tasks
    /// because the file no longer exists (deleted or renamed away) — without
    /// this, a trigger line's attempt count would linger in the map forever
    /// since nothing else ever looks it up again for that path.
    pub fn prune_path(&mut self, path: &Path) {
        self.attempts.retain(|(p, _), _| p != path);
    }

    /// Current attempt count for `key`, `0` if untracked.
    #[cfg(test)]
    fn attempts_for(&self, key: &(PathBuf, String)) -> u32 {
        self.attempts.get(key).copied().unwrap_or(0)
    }
}

/// Reconstructs the trigger line's original text (`<indent>@<tag>:
/// <prompt>`) as produced by the parser — used both as the retry-tracker key
/// and, as a fallback, to locate the line to replace with an error marker.
fn trigger_line_text(task: &PendingTask) -> String {
    format!("{}@{}: {}", task.indent, task.agent.tag(), task.prompt)
}

/// Replace the trigger line described by `task` in the file at `path` with
/// an `@<tag>-error: <message>` line. Looks the line up first by its
/// original line number (fast path — the common case, since a failed or
/// scope-violating run doesn't touch the target file's trigger line), and
/// falls back to a text search if the line moved.
///
/// Loop-termination invariant: rewriting the line to `@<tag>-error:` fires a
/// fresh fs event and a new debounce/scan cycle, but `@<tag>-error:` is
/// never matched as a trigger by `parser::scan` (`match_trigger` only
/// recognizes the exact `@c:`/`@cx:` prefixes — `@c-error:`'s `-` is not
/// `:`), so that cycle finds nothing pending and the retry loop terminates.
/// See `parser::error_marker_is_never_matched_as_a_trigger` for the pinning
/// test.
fn write_error_line(path: &Path, task: &PendingTask, message: &str) {
    let Ok(text) = fs::read_to_string(path) else {
        return;
    };

    let tag = task.agent.tag();
    let original_line = trigger_line_text(task);
    let replacement = format!("{}@{}-error: {}", task.indent, tag, message);

    let has_trailing_newline = text.ends_with('\n');
    let mut lines: Vec<String> = text.lines().map(|l| l.to_string()).collect();

    let idx_by_number = task.line_number.checked_sub(1);
    let target_idx = match idx_by_number {
        Some(idx) if lines.get(idx).map(|l| l.as_str()) == Some(original_line.as_str()) => {
            Some(idx)
        }
        _ => lines.iter().position(|l| l == &original_line),
    };

    let Some(target_idx) = target_idx else {
        return;
    };
    lines[target_idx] = replacement;

    let mut out = lines.join("\n");
    if has_trailing_newline {
        out.push('\n');
    }
    let _ = fs::write(path, out);
}

/// Runs the dispatch -> guard -> retry-cap pipeline for one changed file's
/// pending trigger tasks, sequentially (never concurrently) per task.
///
/// `repo_root` is the resolved git-root (or fallback) directory used by the
/// change-scope guard; `path` is the absolute path of the changed file
/// (expected to live under `repo_root`); `log_path` is embedded in any error
/// marker text written back to the file; `dispatch_fn` stands in for
/// [`crate::dispatcher::dispatch`] so tests can inject a stub agent process.
pub fn dispatch_pending(
    repo_root: &Path,
    path: &Path,
    tasks: Vec<PendingTask>,
    log_path: &Path,
    tracker: &mut RetryTracker,
    dispatch_fn: &mut dyn FnMut(Agent, &Path, &Path) -> DispatchResult,
) {
    let target_rel = match path.strip_prefix(repo_root) {
        Ok(rel) => rel.to_path_buf(),
        Err(_) => return, // path isn't under repo_root; nothing sane to guard
    };

    for task in tasks {
        let key = (path.to_path_buf(), trigger_line_text(&task));

        let mut dispatch_result = DispatchResult::Failed;
        let guard_result = guard::run_guarded(repo_root, &target_rel, || {
            dispatch_result = dispatch_fn(task.agent, path, repo_root);
        });

        let scope_violation =
            !guard_result.reverted.is_empty() || !guard_result.pre_dirty_flagged.is_empty();

        if scope_violation {
            let mut touched: Vec<String> = guard_result
                .reverted
                .iter()
                .map(|p| p.display().to_string())
                .chain(
                    guard_result
                        .pre_dirty_flagged
                        .iter()
                        .map(|p| p.display().to_string()),
                )
                .collect();
            touched.sort();
            let message = format!(
                "run touched files outside this document; {} — see {}",
                touched.join(", "),
                log_path.display()
            );
            write_error_line(path, &task, &message);
            tracker.resolve(&key);
            continue;
        }

        // Treat as resolved either when the dispatch itself reported success,
        // or when the guard independently observed that the target document
        // ended up with only the expected self-reply/`[done]` write (and no
        // out-of-scope changes, per `scope_violation` above). The latter
        // covers a dispatch process that writes a valid reply but then
        // reports `Failed` for an unrelated reason (e.g. a nonzero exit
        // after the write) — without this, `dispatch_pending` would count a
        // failure and risk redispatching an already-answered trigger.
        if dispatch_result == DispatchResult::Success || guard_result.self_reply_only {
            tracker.resolve(&key);
            continue;
        }

        // Failed, and the guard found no out-of-scope writes: count against
        // the retry cap for this exact trigger line.
        let attempts = tracker.record_failure(key.clone());
        if attempts >= MAX_ATTEMPTS {
            let message = format!(
                "agent run failed after {MAX_ATTEMPTS} attempts — see {}",
                log_path.display()
            );
            write_error_line(path, &task, &message);
            tracker.resolve(&key);
        }
    }
}

/// Trailing debounce window before a coalesced batch of fs events for a
/// file is processed.
pub const DEBOUNCE_MS: u64 = 1800;

/// Returns `true` if `path` should be ignored by the watcher: `*.tmp`,
/// dotfiles matching `.*.swp`, `~*` backup files, or anything under a
/// `.git/` directory.
///
/// Pure function — no filesystem access — so it's testable directly against
/// arbitrary (possibly non-existent) paths.
pub fn is_ignored(path: &Path) -> bool {
    if path.components().any(|c| c.as_os_str() == ".git") {
        return true;
    }

    let Some(file_name) = path.file_name().and_then(|n| n.to_str()) else {
        return true;
    };

    if file_name.ends_with(".tmp") {
        return true;
    }
    if file_name.starts_with('.') && file_name.ends_with(".swp") {
        return true;
    }
    if file_name.starts_with('~') {
        return true;
    }

    false
}

/// Returns `true` if `path` is a markdown file the watcher should scan for
/// triggers (not ignored, and has a `.md` extension).
pub fn is_watchable_markdown(path: &Path) -> bool {
    if is_ignored(path) {
        return false;
    }
    path.extension().and_then(|e| e.to_str()) == Some("md")
}

/// Read `path` and scan it for pending trigger tasks via the trigger
/// parser. Returns an empty vec (rather than erroring the whole watch loop)
/// if the file can't be read, e.g. it was deleted between the fs event and
/// this read.
pub fn scan_file(path: &Path) -> Vec<PendingTask> {
    match std::fs::read_to_string(path) {
        Ok(text) => parser::scan(&text),
        Err(_) => Vec::new(),
    }
}

/// Process a single changed path for one debounce cycle: skip ignored /
/// non-markdown paths, try to acquire the per-file lock (dropping the event
/// for this cycle if it's already held), scan for pending trigger tasks,
/// and invoke `on_change` with the results. The lock is released when this
/// function returns.
///
/// `on_change` stands in for the eventual dispatcher call.
pub fn process_change(
    app_support_root: &Path,
    path: &Path,
    on_change: &mut dyn FnMut(&Path, Vec<PendingTask>),
) {
    if !is_watchable_markdown(path) {
        return;
    }

    let lock = match FileLock::try_acquire(app_support_root, path) {
        Ok(Some(lock)) => lock,
        Ok(None) => return, // already locked; drop this cycle's event
        Err(_) => return,   // couldn't set up locking; fail closed for now
    };

    let tasks = scan_file(path);
    on_change(path, tasks);

    drop(lock);
}

/// Run the debounced watch loop over `folder`, calling `on_change` with the
/// parsed pending tasks whenever a watchable markdown file settles after a
/// debounce cycle. Blocks until the watcher's channel closes (i.e. forever
/// in normal operation, until the process is killed).
pub fn run(
    folder: &Path,
    app_support_root: &Path,
    mut on_change: impl FnMut(&Path, Vec<PendingTask>),
) -> notify::Result<()> {
    let (tx, rx) = channel();

    let mut debouncer = new_debouncer(Duration::from_millis(DEBOUNCE_MS), tx)?;
    debouncer
        .watcher()
        .watch(folder, notify::RecursiveMode::Recursive)?;

    for result in rx {
        let events: Vec<PathBuf> = match result {
            Ok(events) => events
                .into_iter()
                .filter(|e| matches!(e.kind, DebouncedEventKind::Any))
                .map(|e| e.path)
                .collect(),
            Err(_) => continue,
        };

        // Coalesce: a single debounce batch may still contain duplicate
        // paths transitively across multiple change kinds; dedupe so the
        // parser runs at most once per path per cycle.
        let mut seen = std::collections::HashSet::new();
        for path in events {
            if seen.insert(path.clone()) {
                process_change(app_support_root, &path, &mut on_change);
            }
        }
    }

    Ok(())
}

/// Dedupe a raw batch of changed paths from a single debounce cycle down to
/// the unique set that should each be scanned exactly once.
///
/// This is the coalescing logic pulled out as a pure function so it's
/// testable without going through real filesystem events / the notify
/// crate's timing.
pub fn coalesce(paths: Vec<PathBuf>) -> Vec<PathBuf> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::new();
    for path in paths {
        if seen.insert(path.clone()) {
            out.push(path);
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;
    use tempfile::tempdir;

    #[test]
    fn ignores_tmp_files() {
        assert!(is_ignored(Path::new("/watched/notes.tmp")));
    }

    #[test]
    fn ignores_swp_files() {
        assert!(is_ignored(Path::new("/watched/.notes.md.swp")));
    }

    #[test]
    fn ignores_tilde_backup_files() {
        assert!(is_ignored(Path::new("/watched/~notes.md")));
    }

    #[test]
    fn ignores_paths_under_dot_git() {
        assert!(is_ignored(Path::new("/watched/.git/HEAD")));
        assert!(is_ignored(Path::new("/watched/.git/refs/heads/main")));
    }

    #[test]
    fn does_not_ignore_ordinary_markdown() {
        assert!(!is_ignored(Path::new("/watched/notes.md")));
    }

    #[test]
    fn watchable_markdown_requires_md_extension() {
        assert!(is_watchable_markdown(Path::new("/watched/notes.md")));
        assert!(!is_watchable_markdown(Path::new("/watched/notes.txt")));
        assert!(!is_watchable_markdown(Path::new("/watched/notes.tmp")));
    }

    #[test]
    fn coalesce_dedupes_repeated_paths_preserving_first_order() {
        let a = PathBuf::from("/watched/a.md");
        let b = PathBuf::from("/watched/b.md");
        let paths = vec![a.clone(), a.clone(), b.clone(), a.clone()];
        assert_eq!(coalesce(paths), vec![a, b]);
    }

    #[test]
    fn coalesce_of_two_rapid_saves_yields_single_entry() {
        let a = PathBuf::from("/watched/a.md");
        let paths = vec![a.clone(), a.clone()];
        assert_eq!(coalesce(paths), vec![a]);
    }

    #[test]
    fn process_change_invokes_callback_once_for_watchable_markdown_with_trigger() {
        let watched = tempdir().unwrap();
        let app_support = tempdir().unwrap();
        let file_path = watched.path().join("notes.md");
        std::fs::write(&file_path, "@c: unresolved question\n").unwrap();

        let mut calls: Vec<(PathBuf, usize)> = Vec::new();
        process_change(app_support.path(), &file_path, &mut |path, tasks| {
            calls.push((path.to_path_buf(), tasks.len()));
        });

        assert_eq!(calls.len(), 1);
        assert_eq!(calls[0], (file_path, 1));
    }

    #[test]
    fn process_change_skips_ignored_paths_without_scanning() {
        let watched = tempdir().unwrap();
        let app_support = tempdir().unwrap();
        let file_path = watched.path().join("notes.tmp");
        std::fs::write(&file_path, "@c: unresolved question\n").unwrap();

        let mut called = false;
        process_change(app_support.path(), &file_path, &mut |_, _| {
            called = true;
        });

        assert!(!called, "ignored path should never reach the callback");
    }

    #[test]
    fn process_change_drops_event_when_file_already_locked() {
        let watched = tempdir().unwrap();
        let app_support = tempdir().unwrap();
        let file_path = watched.path().join("notes.md");
        std::fs::write(&file_path, "@c: unresolved question\n").unwrap();

        let held = FileLock::try_acquire(app_support.path(), &file_path)
            .unwrap()
            .expect("lock should be free initially");

        let mut called = false;
        process_change(app_support.path(), &file_path, &mut |_, _| {
            called = true;
        });

        assert!(!called, "locked file's event should be dropped this cycle");
        drop(held);

        let mut called_after_unlock = false;
        process_change(app_support.path(), &file_path, &mut |_, _| {
            called_after_unlock = true;
        });
        assert!(called_after_unlock, "once unlocked, next cycle should scan normally");
    }

    // --- dispatch_pending pipeline tests -----------------------------------

    fn git(dir: &Path, args: &[&str]) {
        let status = std::process::Command::new("git")
            .current_dir(dir)
            .args(args)
            .status()
            .expect("git command failed to spawn");
        assert!(status.success(), "git {:?} failed", args);
    }

    fn init_git_repo(dir: &Path) {
        std::fs::create_dir_all(dir).unwrap();
        git(dir, &["init", "-q"]);
        git(dir, &["config", "user.email", "test@example.com"]);
        git(dir, &["config", "user.name", "Test"]);
    }

    fn commit_all(dir: &Path, msg: &str) {
        git(dir, &["add", "-A"]);
        git(dir, &["commit", "-q", "-m", msg]);
    }

    fn unique_repo(name: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "docwatch-watcher-pipeline-test-{}-{}",
            std::process::id(),
            name
        ))
    }

    #[test]
    fn dispatch_pending_success_appends_reply_and_touches_no_other_file() {
        let dir = unique_repo("success_reply");
        init_git_repo(&dir);
        std::fs::write(dir.join("notes.md"), "@c: unresolved question\n").unwrap();
        std::fs::write(dir.join("other.md"), "untouched\n").unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
        assert_eq!(tasks.len(), 1);

        let mut tracker = RetryTracker::new();
        let mut calls = 0;
        dispatch_pending(
            &dir,
            &notes_path,
            tasks,
            Path::new("/tmp/docwatch-test.log"),
            &mut tracker,
            &mut |_agent, file, _repo_root| {
                calls += 1;
                let mut content = std::fs::read_to_string(file).unwrap();
                content.push_str("@c-reply: here you go [done]\n");
                std::fs::write(file, content).unwrap();
                DispatchResult::Success
            },
        );

        assert_eq!(calls, 1);
        let notes_content = std::fs::read_to_string(&notes_path).unwrap();
        assert!(notes_content.contains("@c-reply: here you go [done]"));
        assert_eq!(
            std::fs::read_to_string(dir.join("other.md")).unwrap(),
            "untouched\n",
            "unrelated file must not change"
        );

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn dispatch_pending_scope_violation_reverts_other_file_and_writes_error() {
        let dir = unique_repo("scope_violation");
        init_git_repo(&dir);
        std::fs::write(dir.join("notes.md"), "@cx: unresolved question\n").unwrap();
        std::fs::write(dir.join("other.md"), "original\n").unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());

        let mut tracker = RetryTracker::new();
        dispatch_pending(
            &dir,
            &notes_path,
            tasks,
            Path::new("/tmp/docwatch-test.log"),
            &mut tracker,
            &mut |_agent, file, repo_root| {
                std::fs::write(file, "@cx: unresolved question\n@cx-reply: done [done]\n").unwrap();
                std::fs::write(repo_root.join("other.md"), "tampered").unwrap();
                DispatchResult::Success
            },
        );

        assert_eq!(
            std::fs::read_to_string(dir.join("other.md")).unwrap(),
            "original\n",
            "out-of-scope write must be reverted"
        );
        let notes_content = std::fs::read_to_string(&notes_path).unwrap();
        assert!(
            notes_content.starts_with("@cx-error: run touched files outside this document"),
            "got: {notes_content}"
        );
        assert!(notes_content.contains("/tmp/docwatch-test.log"));

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn dispatch_pending_writes_error_marker_after_three_consecutive_failures() {
        let dir = unique_repo("retry_cap");
        init_git_repo(&dir);
        std::fs::write(dir.join("notes.md"), "@c: unresolved question\n").unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let mut tracker = RetryTracker::new();

        for attempt in 1..=3 {
            let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
            assert_eq!(tasks.len(), 1, "attempt {attempt}: trigger should still be pending");
            dispatch_pending(
                &dir,
                &notes_path,
                tasks,
                Path::new("/tmp/docwatch-test.log"),
                &mut tracker,
                &mut |_agent, _file, _repo_root| DispatchResult::Failed,
            );
        }

        let notes_content = std::fs::read_to_string(&notes_path).unwrap();
        assert!(
            notes_content.starts_with("@c-error: agent run failed after 3 attempts"),
            "got: {notes_content}"
        );
        assert!(notes_content.contains("/tmp/docwatch-test.log"));

        // The line is now resolved (no more `@c:` trigger), so a further
        // scan finds nothing left to dispatch — no further attempts happen.
        let tasks_after = parser::scan(&notes_content);
        assert!(tasks_after.is_empty());

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn dispatch_pending_resolves_on_self_reply_only_even_if_dispatch_reports_failed() {
        // Regression test for the unwired `self_reply_only` guard: a dispatch
        // that writes a valid reply to the target document but reports
        // `Failed` for an unrelated reason must still be treated as resolved
        // (not counted against the retry cap), since the guard confirms the
        // only change was the expected self-reply.
        let dir = unique_repo("self_reply_only_treated_as_resolved");
        init_git_repo(&dir);
        std::fs::write(dir.join("notes.md"), "@c: unresolved question\n").unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
        assert_eq!(tasks.len(), 1);

        let mut tracker = RetryTracker::new();
        dispatch_pending(
            &dir,
            &notes_path,
            tasks,
            Path::new("/tmp/docwatch-test.log"),
            &mut tracker,
            &mut |_agent, file, _repo_root| {
                let mut content = std::fs::read_to_string(file).unwrap();
                content.push_str("@c-reply: here you go [done]\n");
                std::fs::write(file, content).unwrap();
                DispatchResult::Failed
            },
        );

        let key = (
            notes_path.clone(),
            "@c: unresolved question".to_string(),
        );
        assert_eq!(
            tracker.attempts_for(&key),
            0,
            "self-reply-only outcome must not count as a failed attempt"
        );
        let notes_content = std::fs::read_to_string(&notes_path).unwrap();
        assert!(
            !notes_content.contains("-error:"),
            "no error marker should have been written: {notes_content}"
        );

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn dispatch_pending_resets_counter_when_trigger_text_changes() {
        let dir = unique_repo("resets_on_change");
        init_git_repo(&dir);
        std::fs::write(dir.join("notes.md"), "@c: original question\n").unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let mut tracker = RetryTracker::new();

        // Two failures against the original line text.
        for _ in 0..2 {
            let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
            dispatch_pending(
                &dir,
                &notes_path,
                tasks,
                Path::new("/tmp/docwatch-test.log"),
                &mut tracker,
                &mut |_agent, _file, _repo_root| DispatchResult::Failed,
            );
        }
        let key_before = (notes_path.clone(), "@c: original question".to_string());
        assert_eq!(tracker.attempts_for(&key_before), 2);

        // User edits the trigger line's text before the 3rd attempt fires.
        std::fs::write(&notes_path, "@c: edited question\n").unwrap();
        let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
        dispatch_pending(
            &dir,
            &notes_path,
            tasks,
            Path::new("/tmp/docwatch-test.log"),
            &mut tracker,
            &mut |_agent, _file, _repo_root| DispatchResult::Failed,
        );

        // The changed line only has 1 failure against its own key, not 3 —
        // no error marker should have been written yet.
        let notes_content = std::fs::read_to_string(&notes_path).unwrap();
        assert_eq!(notes_content, "@c: edited question\n");
        let key_after = (notes_path.clone(), "@c: edited question".to_string());
        assert_eq!(tracker.attempts_for(&key_after), 1);

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn prune_path_removes_only_entries_for_that_path() {
        let mut tracker = RetryTracker::new();
        let renamed = PathBuf::from("/watched/notes.md");
        let other = PathBuf::from("/watched/other.md");

        tracker.record_failure((renamed.clone(), "@c: q1".to_string()));
        tracker.record_failure((renamed.clone(), "@cx: q2".to_string()));
        tracker.record_failure((other.clone(), "@c: unrelated".to_string()));

        tracker.prune_path(&renamed);

        assert_eq!(
            tracker.attempts_for(&(renamed.clone(), "@c: q1".to_string())),
            0
        );
        assert_eq!(
            tracker.attempts_for(&(renamed, "@cx: q2".to_string())),
            0
        );
        assert_eq!(
            tracker.attempts_for(&(other, "@c: unrelated".to_string())),
            1,
            "unrelated path's entry must survive"
        );
    }

    #[test]
    fn dispatch_pending_runs_two_distinct_triggers_sequentially_not_concurrently() {
        let dir = unique_repo("sequential_triggers");
        init_git_repo(&dir);
        std::fs::write(
            dir.join("notes.md"),
            "@c: first trigger\n@cx: second trigger\n",
        )
        .unwrap();
        commit_all(&dir, "init");

        let notes_path = dir.join("notes.md");
        let tasks = parser::scan(&std::fs::read_to_string(&notes_path).unwrap());
        assert_eq!(tasks.len(), 2);

        let mut tracker = RetryTracker::new();
        let order = std::sync::Arc::new(std::sync::Mutex::new(Vec::new()));
        let order_clone = order.clone();
        dispatch_pending(
            &dir,
            &notes_path,
            tasks,
            Path::new("/tmp/docwatch-test.log"),
            &mut tracker,
            &mut move |agent, file, _repo_root| {
                order_clone.lock().unwrap().push(agent);
                // Each dispatch appends its own reply so the next task's
                // guard snapshot sees a clean target file.
                let tag = match agent {
                    Agent::Claude => "c",
                    Agent::Codex => "cx",
                };
                let mut content = std::fs::read_to_string(file).unwrap();
                content.push_str(&format!("@{tag}-reply: ok [done]\n"));
                std::fs::write(file, content).unwrap();
                DispatchResult::Success
            },
        );

        let recorded = order.lock().unwrap().clone();
        assert_eq!(recorded, vec![Agent::Claude, Agent::Codex]);

        std::fs::remove_dir_all(&dir).unwrap();
    }
}
