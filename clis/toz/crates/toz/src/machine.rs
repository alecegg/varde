//! Command execution inside the sandboxed QuickJS worker.

use crate::exec;
use anyhow::{Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{self, Read};
use std::os::fd::AsRawFd;
use std::os::unix::process::{CommandExt, ExitStatusExt};
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

const VERSION: u32 = 1;
const OUTPUT_CHUNK_BYTES: usize = 9 * 1024;
const TERMINATE_GRACE: Duration = Duration::from_millis(300);

#[derive(Debug, Deserialize)]
pub(crate) struct Request {
    pub(crate) version: u32,
    #[serde(rename = "type")]
    frame_type: Option<String>,
    pub(crate) argv: Option<Vec<String>>,
    pub(crate) shell: Option<String>,
    pub(crate) cwd: Option<String>,
    #[serde(default)]
    pub(crate) env: BTreeMap<String, Option<String>>,
    pub(crate) timeout_ms: Option<u64>,
}

#[derive(Debug)]
pub(crate) struct ExecutionResult {
    pub(crate) exit_code: Option<i32>,
    pub(crate) signal: Option<i32>,
    pub(crate) timed_out: bool,
    pub(crate) interrupted: bool,
}

impl Request {
    fn validate(&self) -> std::result::Result<(), String> {
        if self.version != VERSION {
            return Err(format!(
                "unsupported protocol version {}; expected {VERSION}",
                self.version
            ));
        }
        if self.frame_type.as_deref().is_some_and(|t| t != "exec") {
            return Err("initial request type must be `exec`".into());
        }
        if self.argv.is_some() == self.shell.is_some() {
            return Err("provide exactly one of `argv` or `shell`".into());
        }
        if let Some(argv) = &self.argv {
            if argv.is_empty() || argv[0].is_empty() {
                return Err("`argv` must contain a non-empty executable".into());
            }
        }
        if self.shell.as_ref().is_some_and(String::is_empty) {
            return Err("`shell` must not be empty".into());
        }
        if self.timeout_ms == Some(0) {
            return Err("`timeout_ms` must be greater than zero".into());
        }
        Ok(())
    }
}

/// Run one script command through the same pipe executor used by the JSONL interface.
pub(crate) fn execute_script(
    request: Value,
    timeout: Duration,
    on_output: &mut impl FnMut(&str, &[u8]) -> Result<()>,
) -> Result<ExecutionResult> {
    let mut request = request
        .as_object()
        .cloned()
        .context("exec request must be an object")?;
    for key in request.keys() {
        if !matches!(
            key.as_str(),
            "argv" | "shell" | "cwd" | "env" | "timeoutMs" | "raw"
        ) {
            anyhow::bail!("unknown exec option {key:?}");
        }
    }
    if let Some(raw) = request.remove("raw") {
        raw.as_bool().context("raw must be a boolean")?;
    }
    let requested = request
        .remove("timeoutMs")
        .map(|value| {
            value
                .as_u64()
                .context("timeoutMs must be a positive integer")
        })
        .transpose()?
        .unwrap_or(u64::MAX);
    if requested == 0 {
        anyhow::bail!("timeoutMs must be greater than zero");
    }
    let remaining = u64::try_from(timeout.as_millis()).unwrap_or(u64::MAX);
    if remaining == 0 {
        anyhow::bail!("script timeout exceeded");
    }
    request.insert("version".into(), json!(VERSION));
    request.insert("timeout_ms".into(), json!(requested.min(remaining)));
    let request: Request = serde_json::from_value(Value::Object(request))?;
    request.validate().map_err(anyhow::Error::msg)?;
    run_piped(&request, on_output).map_err(|failure| match failure {
        Failure::Spawn(error) => anyhow::anyhow!("could not start command: {error}"),
        Failure::Infrastructure(message) => anyhow::anyhow!(message),
    })
}

enum OutputEvent {
    Data(&'static str, Vec<u8>),
    End(&'static str),
    Error(&'static str, String),
}

struct SignalForwarder {
    interrupted: Arc<AtomicBool>,
    handle: signal_hook::iterator::Handle,
    thread: Option<JoinHandle<()>>,
}

impl SignalForwarder {
    fn start(pgid: libc::pid_t) -> Result<Self> {
        use signal_hook::consts::{SIGHUP, SIGINT, SIGTERM};
        let interrupted = Arc::new(AtomicBool::new(false));
        let flag = interrupted.clone();
        let mut signals = signal_hook::iterator::Signals::new([SIGINT, SIGTERM, SIGHUP])?;
        let handle = signals.handle();
        let thread = thread::spawn(move || {
            for signal in signals.forever() {
                flag.store(true, Ordering::SeqCst);
                unsafe {
                    libc::killpg(pgid, signal);
                }
            }
        });
        Ok(Self {
            interrupted,
            handle,
            thread: Some(thread),
        })
    }

    fn close(mut self) -> bool {
        self.stop();
        self.interrupted.load(Ordering::SeqCst)
    }

    fn stop(&mut self) {
        self.handle.close();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

impl Drop for SignalForwarder {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Reap a child on every early return after spawn, including a closed JSONL consumer.
struct ChildReaper {
    pid: libc::pid_t,
    armed: bool,
    reaped: bool,
}

impl ChildReaper {
    fn new(pid: libc::pid_t) -> Self {
        Self {
            pid,
            armed: true,
            reaped: false,
        }
    }

    fn mark_reaped(&mut self) {
        self.reaped = true;
    }

    fn disarm(&mut self) {
        self.armed = false;
    }
}

impl Drop for ChildReaper {
    fn drop(&mut self) {
        if !self.armed {
            return;
        }
        unsafe {
            libc::killpg(self.pid, libc::SIGKILL);
            if !self.reaped {
                let mut status = 0;
                while libc::waitpid(self.pid, &mut status, 0) == -1 {
                    if io::Error::last_os_error().kind() != io::ErrorKind::Interrupted {
                        break;
                    }
                }
            }
        }
    }
}

/// Execute a request while handing each bounded output chunk to an integration callback.
/// The final callback runs after the child has been reaped and before its result frame is emitted.
/// Callbacks can spool data without retaining command output in memory.
#[derive(Debug)]
enum Failure {
    Spawn(io::Error),
    Infrastructure(String),
}

fn base_command(request: &Request) -> Command {
    let mut command = if let Some(argv) = &request.argv {
        exec::build_argv_command(argv)
    } else {
        exec::build_shell_command(request.shell.as_deref().unwrap_or_default())
    };
    if let Some(cwd) = &request.cwd {
        command.current_dir(cwd);
    }
    for (key, value) in &request.env {
        match value {
            Some(value) => {
                command.env(key, value);
            }
            None => {
                command.env_remove(key);
            }
        }
    }
    command
}

fn run_piped(
    request: &Request,
    on_output: &mut impl FnMut(&str, &[u8]) -> Result<()>,
) -> std::result::Result<ExecutionResult, Failure> {
    let start = Instant::now();
    let mut child = spawn_piped_child(request)?;
    let pgid = child.id() as libc::pid_t;
    let mut reaper = ChildReaper::new(pgid);
    let signals = SignalForwarder::start(pgid)
        .map_err(|error| Failure::Infrastructure(format!("registering signals: {error:#}")))?;
    let mut readers = PipedReaders::new(&mut child)
        .map_err(|error| Failure::Infrastructure(format!("configuring output pipes: {error}")))?;

    let progress = drain_pipes(
        &mut child,
        pgid,
        request,
        &signals,
        &mut reaper,
        &mut readers,
        start,
        on_output,
    )?;
    drop(readers);
    let status = progress
        .status
        .or_else(|| child.wait().ok())
        .ok_or_else(|| Failure::Infrastructure("command ended without a status".into()))?;
    let interrupted = signals.close();
    if let Some(message) = progress.read_failure {
        return Err(Failure::Infrastructure(message));
    }
    if let Some(message) = progress.callback_failure {
        return Err(Failure::Infrastructure(message));
    }
    reaper.disarm();
    Ok(ExecutionResult {
        exit_code: status.code(),
        signal: status.signal(),
        timed_out: progress.timed_out,
        interrupted,
    })
}

fn spawn_piped_child(request: &Request) -> std::result::Result<Child, Failure> {
    let mut command = base_command(request);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    unsafe {
        command.pre_exec(|| {
            if libc::setpgid(0, 0) == -1 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
    command.spawn().map_err(Failure::Spawn)
}

#[derive(Default)]
struct PipeProgress {
    status: Option<ExitStatus>,
    termination_deadline: Option<Instant>,
    drain_deadline: Option<Instant>,
    timed_out: bool,
    termination_requested: bool,
    leader_exited_at: Option<Instant>,
    ended: [bool; 2],
    read_failure: Option<String>,
    callback_failure: Option<String>,
}

impl PipeProgress {
    fn terminate(&mut self, pgid: libc::pid_t) {
        if !self.termination_requested {
            begin_termination(pgid, &mut self.termination_deadline);
            self.drain_deadline = self.termination_deadline;
            self.termination_requested = true;
        }
    }

    fn poll_child(
        &mut self,
        child: &mut Child,
        pgid: libc::pid_t,
        request: &Request,
        start: Instant,
        signals: &SignalForwarder,
        reaper: &mut ChildReaper,
    ) -> std::result::Result<(), Failure> {
        update_child(
            child,
            pgid,
            request.timeout_ms,
            start,
            &mut self.timed_out,
            &mut self.termination_deadline,
            &mut self.status,
        )
        .map_err(|error| Failure::Infrastructure(format!("waiting for command: {error}")))?;
        if self.status.is_some() {
            reaper.mark_reaped();
            self.leader_exited_at.get_or_insert_with(Instant::now);
        }
        if signals.interrupted.load(Ordering::SeqCst) && !self.termination_requested {
            self.terminate(pgid);
        }
        if self.timed_out && !self.termination_requested {
            self.drain_deadline = request
                .timeout_ms
                .and_then(|ms| start.checked_add(Duration::from_millis(ms)))
                .and_then(|deadline| deadline.checked_add(TERMINATE_GRACE))
                .or(self.termination_deadline);
            self.termination_requested = true;
        }
        if self
            .leader_exited_at
            .is_some_and(|exit| exit.elapsed() >= TERMINATE_GRACE)
            && !self.termination_requested
            && self.ended != [true, true]
        {
            self.terminate(pgid);
        }
        Ok(())
    }

    fn receive(
        &mut self,
        event: OutputEvent,
        pgid: libc::pid_t,
        on_output: &mut impl FnMut(&str, &[u8]) -> Result<()>,
    ) -> std::result::Result<(), Failure> {
        match event {
            OutputEvent::Data(stream, bytes) => {
                if let Err(error) = on_output(stream, &bytes) {
                    self.callback_failure = Some(format!("output callback failed: {error:#}"));
                    self.terminate(pgid);
                }
            }
            OutputEvent::End(stream) => self.ended[stream_index(stream)] = true,
            OutputEvent::Error(stream, message) => {
                self.read_failure = Some(format!("reading {stream}: {message}"));
                self.terminate(pgid);
            }
        }
        Ok(())
    }
}

struct PipedReaders {
    stdout: Option<std::process::ChildStdout>,
    stderr: Option<std::process::ChildStderr>,
    buffer: Vec<u8>,
}

impl PipedReaders {
    fn new(child: &mut Child) -> io::Result<Self> {
        let stdout = child.stdout.take().expect("stdout pipe enabled");
        let stderr = child.stderr.take().expect("stderr pipe enabled");
        for fd in [stdout.as_raw_fd(), stderr.as_raw_fd()] {
            let flags = unsafe { libc::fcntl(fd, libc::F_GETFL) };
            if flags == -1
                || unsafe { libc::fcntl(fd, libc::F_SETFL, flags | libc::O_NONBLOCK) } == -1
            {
                return Err(io::Error::last_os_error());
            }
        }
        Ok(Self {
            stdout: Some(stdout),
            stderr: Some(stderr),
            buffer: vec![0; OUTPUT_CHUNK_BYTES],
        })
    }

    fn read_once<R: Read>(
        reader: &mut Option<R>,
        stream: &'static str,
        buffer: &mut [u8],
    ) -> Option<OutputEvent> {
        let result = reader.as_mut()?.read(buffer);
        match result {
            Ok(0) => {
                *reader = None;
                Some(OutputEvent::End(stream))
            }
            Ok(size) => Some(OutputEvent::Data(stream, buffer[..size].to_vec())),
            Err(error)
                if matches!(
                    error.kind(),
                    io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                ) =>
            {
                None
            }
            Err(error) => {
                *reader = None;
                Some(OutputEvent::Error(stream, error.to_string()))
            }
        }
    }
}

fn drain_pipes(
    child: &mut Child,
    pgid: libc::pid_t,
    request: &Request,
    signals: &SignalForwarder,
    reaper: &mut ChildReaper,
    readers: &mut PipedReaders,
    start: Instant,
    on_output: &mut impl FnMut(&str, &[u8]) -> Result<()>,
) -> std::result::Result<PipeProgress, Failure> {
    let mut progress = PipeProgress::default();
    while progress.status.is_none() || progress.ended != [true, true] {
        progress.poll_child(child, pgid, request, start, signals, reaper)?;
        // Check even when a descendant continuously writes. EOF is not required
        // once termination grace expires: a detached descendant can retain pipes.
        if progress
            .drain_deadline
            .is_some_and(|deadline| Instant::now() >= deadline)
        {
            unsafe {
                libc::killpg(pgid, libc::SIGKILL);
            }
            readers.stdout = None;
            readers.stderr = None;
            if progress.status.is_none() {
                progress.status = Some(child.wait().map_err(|error| {
                    Failure::Infrastructure(format!("waiting for command: {error}"))
                })?);
                reaper.mark_reaped();
            }
            if progress.ended != [true, true]
                && !progress.timed_out
                && !signals.interrupted.load(Ordering::SeqCst)
            {
                progress.read_failure.get_or_insert_with(|| {
                    "output pipes remained open after command termination".into()
                });
            }
            break;
        }
        let mut received = false;
        for event in [
            PipedReaders::read_once(&mut readers.stdout, "stdout", &mut readers.buffer),
            PipedReaders::read_once(&mut readers.stderr, "stderr", &mut readers.buffer),
        ]
        .into_iter()
        .flatten()
        {
            received = true;
            if let OutputEvent::Error(stream, _) = &event {
                progress.ended[stream_index(stream)] = true;
            }
            progress.receive(event, pgid, on_output)?;
        }
        if !received && (progress.status.is_none() || progress.ended != [true, true]) {
            thread::sleep(Duration::from_millis(20));
        }
    }
    Ok(progress)
}

fn stream_index(stream: &str) -> usize {
    if stream == "stdout" {
        0
    } else {
        1
    }
}

fn update_child(
    child: &mut Child,
    pgid: libc::pid_t,
    timeout_ms: Option<u64>,
    start: Instant,
    timed_out: &mut bool,
    termination_deadline: &mut Option<Instant>,
    status: &mut Option<ExitStatus>,
) -> io::Result<()> {
    if status.is_none() {
        *status = child.try_wait()?;
    }
    if let Some(timeout) = timeout_ms {
        if !*timed_out && start.elapsed() >= Duration::from_millis(timeout) {
            *timed_out = true;
            begin_termination(pgid, termination_deadline);
        }
    }
    if termination_deadline.is_some_and(|deadline| Instant::now() >= deadline) {
        unsafe {
            libc::killpg(pgid, libc::SIGKILL);
        }
        *termination_deadline = None;
    }
    Ok(())
}

fn begin_termination(pgid: libc::pid_t, deadline: &mut Option<Instant>) {
    unsafe {
        libc::killpg(pgid, libc::SIGTERM);
    }
    *deadline = Some(Instant::now() + TERMINATE_GRACE);
}
