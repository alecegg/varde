//! Agent subprocess dispatcher.
//!
//! Given a `PendingTask` found by the trigger parser, builds the
//! trigger-contract prompt and invokes the scoped `claude -p` / `codex exec`
//! subprocess in the resolved repo root. Does not implement the
//! change-scope guard (separate task) or the retry-cap counter (belongs to
//! the watch-loop wiring).

use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::{Duration, Instant};

use crate::parser::Agent;

/// Outcome of a dispatched agent run.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DispatchResult {
    Success,
    Failed,
}

/// Maximum time to let a dispatched agent process run before it is killed
/// and treated as `DispatchResult::Failed`.
pub const DISPATCH_TIMEOUT: Duration = Duration::from_secs(30 * 60);

/// Build the trigger-contract prompt for `tag` (`"c"`/`"cx"`) and `file`
/// (the only path the dispatched agent is allowed to write).
///
/// Pure function — no I/O, no process spawning.
pub fn build_prompt(tag: &str, file: &str) -> String {
    format!(
        "Read `{file}`. It contains a comment prefixed `{tag}:` with a request. \
You may read any file in this repository for context, but you may only \
write changes to `{file}` — do not create, modify, or delete any other \
file. Answer by appending a new line under the `{tag}:` line, prefixed \
`{tag}-reply: `. If the request is an edit, apply it directly to the \
surrounding text in `{file}` and append ` [done]` to the trigger line."
    )
}

/// Build (without spawning) the `std::process::Command` for dispatching
/// `agent` against `file` with the given contract `prompt`. The caller is
/// expected to set `current_dir` before spawning; this function does not.
///
/// Inspectable via `Command::get_program()` / `Command::get_args()`, so
/// tests can assert on program/args without actually running a process.
pub fn build_command(agent: Agent, file: &Path, prompt: &str) -> Command {
    let file_display = file.display().to_string();
    match agent {
        Agent::Claude => {
            let mut cmd = Command::new("claude");
            cmd.arg("-p")
                .arg(prompt)
                .arg("--permission-mode")
                .arg("acceptEdits")
                .arg("--allowedTools")
                .arg(format!(
                    "Read,Grep,Glob,Edit({file_display}),Write({file_display})"
                ));
            cmd
        }
        Agent::Codex => {
            let mut cmd = Command::new("codex");
            cmd.arg("exec").arg("--approve-for-me").arg(prompt);
            cmd
        }
    }
}

/// Resolve the repo root for a dispatched run by walking up from `start`
/// looking for the nearest ancestor directory containing a `.git` entry.
/// Falls back to `start` itself if no ancestor has one.
///
/// Pure/side-effect-free aside from filesystem existence checks; does not
/// spawn any process.
pub fn resolve_repo_root(start: &Path) -> PathBuf {
    let mut current = start;
    loop {
        if current.join(".git").exists() {
            return current.to_path_buf();
        }
        match current.parent() {
            Some(parent) => current = parent,
            None => return start.to_path_buf(),
        }
    }
}

/// Dispatch `agent` against `file`, using `watched_folder` to resolve the
/// repo root (nearest ancestor `.git`, else `watched_folder` itself). Builds
/// the trigger-contract prompt itself from `agent`/`file`.
///
/// Spawns the real subprocess — production entry point. Actually spawning
/// is not covered by tests; command construction is tested via
/// [`build_command`] instead.
pub fn dispatch(agent: Agent, file: &Path, watched_folder: &Path) -> DispatchResult {
    let repo_root = resolve_repo_root(watched_folder);
    let prompt = build_prompt(agent.tag(), &file.display().to_string());
    let mut cmd = build_command(agent, file, &prompt);
    cmd.current_dir(&repo_root);
    run_with_timeout(&mut cmd, DISPATCH_TIMEOUT)
}

/// Spawn `cmd` and wait for it to finish, killing it and returning
/// `DispatchResult::Failed` if it runs longer than `timeout`. A spawn
/// failure or non-zero exit also yields `DispatchResult::Failed`.
///
/// The child is spawned as its own process group leader (`process_group(0)`)
/// so a timeout kill can signal the whole group (`kill(-pid, SIGKILL)`)
/// instead of just the direct child — otherwise the dispatched agent's own
/// subprocesses (grandchildren) survive a `Child::kill` past the timeout.
fn run_with_timeout(cmd: &mut Command, timeout: Duration) -> DispatchResult {
    cmd.process_group(0);
    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(_) => return DispatchResult::Failed,
    };
    let pid = child.id();

    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                return if status.success() {
                    DispatchResult::Success
                } else {
                    DispatchResult::Failed
                };
            }
            Ok(None) => {
                if start.elapsed() >= timeout {
                    kill_process_group(pid);
                    let _ = child.wait();
                    return DispatchResult::Failed;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            Err(_) => return DispatchResult::Failed,
        }
    }
}

/// Send `SIGKILL` to the process group led by `pid` (a negative pid targets
/// the whole group in POSIX `kill(2)`), reaping the dispatched agent's own
/// subprocesses along with it. Requires the spawned `Command` to have set
/// `process_group(0)` so `pid` is also its own group leader.
fn kill_process_group(pid: u32) {
    // SAFETY: kill(2) with a negative pid is a plain signal-delivery
    // syscall; no aliasing/lifetime concerns to uphold here.
    unsafe {
        libc::kill(-(pid as libc::pid_t), libc::SIGKILL);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_prompt_names_file_as_only_writable_path() {
        let prompt = build_prompt("c", "notes/todo.md");
        assert_eq!(
            prompt,
            "Read `notes/todo.md`. It contains a comment prefixed `c:` with a request. \
You may read any file in this repository for context, but you may only \
write changes to `notes/todo.md` — do not create, modify, or delete any other \
file. Answer by appending a new line under the `c:` line, prefixed \
`c-reply: `. If the request is an edit, apply it directly to the \
surrounding text in `notes/todo.md` and append ` [done]` to the trigger line."
        );
    }

    #[test]
    fn build_prompt_uses_cx_tag_for_codex() {
        let prompt = build_prompt("cx", "docs/plan.md");
        assert!(prompt.contains("`cx:`"));
        assert!(prompt.contains("`cx-reply: `"));
        assert!(prompt.contains("`docs/plan.md`"));
        assert!(!prompt.contains("`c:`"));
    }

    #[test]
    fn tag_for_maps_agents_to_short_tags() {
        assert_eq!(Agent::Claude.tag(), "c");
        assert_eq!(Agent::Codex.tag(), "cx");
    }

    #[test]
    fn claude_command_has_expected_program_and_args() {
        let file = Path::new("/repo/notes/todo.md");
        let prompt = build_prompt(Agent::Claude.tag(), &file.display().to_string());
        let cmd = build_command(Agent::Claude, file, &prompt);

        assert_eq!(cmd.get_program(), "claude");
        let args: Vec<String> = cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            args,
            vec![
                "-p".to_string(),
                prompt.clone(),
                "--permission-mode".to_string(),
                "acceptEdits".to_string(),
                "--allowedTools".to_string(),
                "Read,Grep,Glob,Edit(/repo/notes/todo.md),Write(/repo/notes/todo.md)"
                    .to_string(),
            ]
        );
    }

    #[test]
    fn codex_command_has_expected_program_and_args() {
        let file = Path::new("/repo/docs/plan.md");
        let prompt = build_prompt(Agent::Codex.tag(), &file.display().to_string());
        let cmd = build_command(Agent::Codex, file, &prompt);

        assert_eq!(cmd.get_program(), "codex");
        let args: Vec<String> = cmd
            .get_args()
            .map(|a| a.to_string_lossy().into_owned())
            .collect();
        assert_eq!(
            args,
            vec!["exec".to_string(), "--approve-for-me".to_string(), prompt.clone()]
        );
    }

    #[test]
    fn resolve_repo_root_walks_up_to_nearest_dot_git() {
        let dir = std::env::temp_dir().join(format!(
            "docwatch-dispatcher-test-{}-{}",
            std::process::id(),
            "repo_root_walks_up"
        ));
        let repo_root = dir.join("repo");
        let nested = repo_root.join("sub").join("deep");
        std::fs::create_dir_all(&nested).unwrap();
        std::fs::create_dir_all(repo_root.join(".git")).unwrap();

        let resolved = resolve_repo_root(&nested);
        assert_eq!(resolved, repo_root);

        std::fs::remove_dir_all(&dir).unwrap();
    }

    #[test]
    fn resolve_repo_root_falls_back_to_start_when_no_git_found() {
        let dir = std::env::temp_dir().join(format!(
            "docwatch-dispatcher-test-{}-{}",
            std::process::id(),
            "no_git_found"
        ));
        let watched = dir.join("watched_folder");
        std::fs::create_dir_all(&watched).unwrap();

        let resolved = resolve_repo_root(&watched);
        assert_eq!(resolved, watched);

        std::fs::remove_dir_all(&dir).unwrap();
    }

    /// Regression for ARCHITECTURE-005: a timeout must reap the dispatched
    /// process's own children (grandchildren of `run_with_timeout`'s
    /// caller), not just the direct child. Spawns a shell that backgrounds a
    /// long-running grandchild `sleep`, writes its pid to a file, then waits
    /// on it — so the shell itself hangs past the timeout too. After
    /// `run_with_timeout` kills the group, the grandchild pid must no
    /// longer be signalable.
    #[test]
    fn run_with_timeout_kills_grandchild_processes() {
        let pid_file = std::env::temp_dir().join(format!(
            "docwatch-dispatcher-test-{}-grandchild.pid",
            std::process::id()
        ));
        let _ = std::fs::remove_file(&pid_file);

        let mut cmd = Command::new("sh");
        cmd.arg("-c").arg(format!(
            "sleep 30 & echo $! > {}; wait",
            pid_file.display()
        ));

        let result = run_with_timeout(&mut cmd, Duration::from_millis(200));
        assert_eq!(result, DispatchResult::Failed);

        // The grandchild writes its pid before the parent shell blocks on
        // `wait`, but the write may briefly race the timeout — poll for it.
        let mut grandchild_pid: Option<i32> = None;
        for _ in 0..50 {
            if let Ok(text) = std::fs::read_to_string(&pid_file)
                && let Ok(pid) = text.trim().parse()
            {
                grandchild_pid = Some(pid);
                break;
            }
            std::thread::sleep(Duration::from_millis(20));
        }
        let grandchild_pid = grandchild_pid.expect("grandchild pid was never written");

        // kill(pid, 0) checks liveness without sending a real signal;
        // ESRCH means the process is gone.
        let alive = unsafe { libc::kill(grandchild_pid, 0) } == 0;
        assert!(
            !alive,
            "grandchild pid {grandchild_pid} survived the process-group kill"
        );

        let _ = std::fs::remove_file(&pid_file);
    }
}
