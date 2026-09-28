//! Run a command in its own process group with a deadline, replacing
//! `skills/eval-tools/claude-timeout.pl`.
//!
//! On timeout, the whole process group is signalled (`SIGTERM`, then
//! `SIGKILL` after a grace period) so no descendant survives. Because the
//! deadline enforcement happens on the caller's side rather than in a
//! standalone wrapper script, [`run_with_timeout`] also installs `SIGINT`/
//! `SIGTERM`/`SIGHUP` handlers for the duration of the run: if the calling
//! process itself is interrupted, the child's process group is killed before
//! the signal is allowed to take its default action.

use std::io::Write;
use std::os::fd::AsRawFd;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicI32, Ordering};
use std::time::{Duration, Instant};

use crate::error::LearnError;

/// Poll interval while waiting for the child to exit or the deadline to
/// pass, matching `claude-timeout.pl`'s `sleep 0.02`.
const POLL_INTERVAL: Duration = Duration::from_millis(20);

/// Grace period between `SIGTERM` and `SIGKILL` on timeout, matching
/// `claude-timeout.pl`.
const TERM_GRACE: Duration = Duration::from_millis(250);

/// Return to deadline and child polling between successful input writes.
const INPUT_CHUNK_BYTES: usize = 64 * 1024;

/// A command to run with a deadline.
pub struct RunRequest<'a> {
    pub program: &'a str,
    pub args: &'a [String],
    pub cwd: Option<&'a Path>,
    pub env: &'a [(String, String)],
    pub stdin: &'a [u8],
    pub stdout_path: &'a Path,
    pub stderr_path: &'a Path,
    pub timeout: Duration,
}

/// How a completed process exited.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExitResult {
    /// Exited normally with this exit code.
    Code(i32),
    /// Killed by this signal number.
    Signal(i32),
}

impl ExitResult {
    /// `128 + signal` for signal deaths, the exit code otherwise; the
    /// convention `claude-timeout.pl` and POSIX shells report.
    pub fn as_shell_code(self) -> i32 {
        match self {
            ExitResult::Code(code) => code,
            ExitResult::Signal(signal) => 128 + signal,
        }
    }
}

/// Outcome of [`run_with_timeout`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RunOutcome {
    /// The process exited before the deadline.
    Completed(ExitResult),
    /// The process exceeded its deadline; its process group was killed.
    TimedOut,
}

/// pgid of the child currently under a [`run_with_timeout`] deadline, so the
/// signal handler installed for the duration of the call can kill it. `0`
/// means no child is currently tracked.
static CHILD_PGID: AtomicI32 = AtomicI32::new(0);

/// Run `req.program` in its own process group, enforcing `req.timeout`.
///
/// Unix-only.
pub fn run_with_timeout(req: &RunRequest) -> Result<RunOutcome, LearnError> {
    let stdout_file = std::fs::File::create(req.stdout_path).map_err(|err| {
        LearnError::Usage(format!(
            "failed to open stdout file {}: {err}",
            req.stdout_path.display()
        ))
    })?;
    let stderr_file = std::fs::File::create(req.stderr_path).map_err(|err| {
        LearnError::Usage(format!(
            "failed to open stderr file {}: {err}",
            req.stderr_path.display()
        ))
    })?;

    let mut command = Command::new(req.program);
    command
        .args(req.args)
        .envs(req.env.iter().map(|(k, v)| (k.as_str(), v.as_str())))
        .stdin(Stdio::piped())
        .stdout(Stdio::from(stdout_file))
        .stderr(Stdio::from(stderr_file))
        // New process group led by the child, so the whole group can be
        // signalled together on timeout or caller interruption.
        .process_group(0);
    if let Some(cwd) = req.cwd {
        command.current_dir(cwd);
    }

    let deadline = Instant::now()
        .checked_add(req.timeout)
        .ok_or_else(|| LearnError::Usage("process timeout is too large".into()))?;
    let mut child = command
        .spawn()
        .map_err(|err| LearnError::Usage(format!("failed to launch {}: {err}", req.program)))?;

    let pgid = child.id() as i32;
    let guard = SignalGuard::install(pgid);
    let outcome = wait_with_deadline(&mut child, req.stdin, deadline);
    if outcome.is_err() {
        kill_group_with_grace(pgid);
        let _ = child.wait();
    }
    drop(guard);

    outcome
}

fn wait_with_deadline(
    child: &mut Child,
    stdin: &[u8],
    deadline: Instant,
) -> Result<RunOutcome, LearnError> {
    let mut pipe = child.stdin.take();
    if stdin.is_empty() {
        pipe = None;
    } else if let Some(pipe) = &pipe {
        let fd = pipe.as_raw_fd();
        // SAFETY: pipe owns a live write fd throughout both fcntl calls.
        // Preserve its existing flags; only the parent's write end is changed.
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
        if flags == -1 || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1
        {
            return Err(LearnError::Usage(format!(
                "failed to configure stdin pipe: {}",
                std::io::Error::last_os_error()
            )));
        }
    }
    let mut written = 0;
    loop {
        if let Some(status) = child
            .try_wait()
            .map_err(|err| LearnError::Usage(format!("failed to poll child: {err}")))?
        {
            return Ok(RunOutcome::Completed(to_exit_result(status)));
        }
        if Instant::now() >= deadline {
            break;
        }
        if let Some(input) = &mut pipe {
            let end = written + (stdin.len() - written).min(INPUT_CHUNK_BYTES);
            match input.write(&stdin[written..end]) {
                Ok(0) => {
                    return Err(LearnError::Usage(
                        "failed to write stdin: zero-byte write".into(),
                    ));
                }
                Ok(count) => {
                    written += count;
                    if written == stdin.len() {
                        pipe = None; // Deliver EOF as soon as all input is sent.
                    }
                    continue;
                }
                Err(err) if err.kind() == std::io::ErrorKind::BrokenPipe => pipe = None,
                Err(err) if err.kind() == std::io::ErrorKind::Interrupted => continue,
                Err(err) if err.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(err) => return Err(LearnError::Usage(format!("failed to write stdin: {err}"))),
            }
        }
        std::thread::sleep(POLL_INTERVAL);
    }

    drop(pipe);
    kill_group_with_grace(child.id() as i32);
    // Reap the child so it does not linger as a zombie; its own status is
    // irrelevant once it has been killed for timing out.
    let _ = child.wait();
    Ok(RunOutcome::TimedOut)
}

/// `SIGTERM` the group, wait up to [`TERM_GRACE`], then `SIGKILL` any
/// survivors.
fn kill_group_with_grace(pgid: i32) {
    unsafe {
        libc::killpg(pgid, libc::SIGTERM);
    }
    let grace_deadline = Instant::now() + TERM_GRACE;
    while Instant::now() < grace_deadline {
        if !group_alive(pgid) {
            return;
        }
        std::thread::sleep(POLL_INTERVAL);
    }
    if group_alive(pgid) {
        unsafe {
            libc::killpg(pgid, libc::SIGKILL);
        }
    }
}

/// Whether any process remains in process group `pgid`.
fn group_alive(pgid: i32) -> bool {
    let result = unsafe { libc::kill(-pgid, 0) };
    result == 0
}

fn to_exit_result(status: std::process::ExitStatus) -> ExitResult {
    match status.signal() {
        Some(signal) => ExitResult::Signal(signal),
        None => ExitResult::Code(status.code().unwrap_or(-1)),
    }
}

/// Installs `SIGINT`/`SIGTERM`/`SIGHUP` handlers for the lifetime of the
/// guard that kill `pgid`'s process group before letting the signal take its
/// default action, so an interrupted caller cannot leave the child group
/// running. Restores the previous handlers on drop.
struct SignalGuard {
    previous: [libc::sigaction; SIGNALS.len()],
}

const SIGNALS: [libc::c_int; 3] = [libc::SIGINT, libc::SIGTERM, libc::SIGHUP];

impl SignalGuard {
    fn install(pgid: i32) -> Self {
        CHILD_PGID.store(pgid, Ordering::SeqCst);
        let mut previous = [unsafe { std::mem::zeroed::<libc::sigaction>() }; SIGNALS.len()];
        for (slot, &signal) in previous.iter_mut().zip(SIGNALS.iter()) {
            let mut action: libc::sigaction = unsafe { std::mem::zeroed() };
            action.sa_sigaction = handle_signal as *const () as usize;
            action.sa_flags = 0;
            unsafe {
                libc::sigemptyset(&mut action.sa_mask);
                libc::sigaction(signal, &action, slot);
            }
        }
        SignalGuard { previous }
    }
}

impl Drop for SignalGuard {
    fn drop(&mut self) {
        for (&signal, previous) in SIGNALS.iter().zip(self.previous.iter()) {
            unsafe {
                libc::sigaction(signal, previous, std::ptr::null_mut());
            }
        }
        CHILD_PGID.store(0, Ordering::SeqCst);
    }
}

/// Async-signal-safe handler: kill the tracked child group, restore the
/// signal's default disposition, and re-raise it so the process exits the
/// way it would have without this handler installed.
extern "C" fn handle_signal(signal: libc::c_int) {
    let pgid = CHILD_PGID.load(Ordering::SeqCst);
    if pgid != 0 {
        unsafe {
            libc::killpg(pgid, libc::SIGKILL);
        }
    }
    unsafe {
        libc::signal(signal, libc::SIG_DFL);
        libc::raise(signal);
    }
}
