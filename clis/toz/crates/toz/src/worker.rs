//! The parent owns captures; the worker owns QuickJS and child processes.
//! They exchange bounded JSON frames over stdio. Large command output crosses the boundary
//! through named files in a private scratch directory, then the parent indexes it.

use crate::{machine, sandbox};
use anyhow::{bail, ensure, Context, Result};
use serde_json::{json, Value};
use std::cell::{Cell, RefCell};
use std::ffi::OsString;
use std::fs::{File, OpenOptions};
use std::io::{self, BufRead, BufReader, BufWriter, Read, Seek, Write};
use std::path::{Path, PathBuf};
use std::process::{ChildStdin, ChildStdout, Stdio};
use std::rc::Rc;
use std::time::Duration;
use toz_core::capture::{self, CaptureInput, Outcome as CaptureOutcome};
use toz_core::raw::{RawError, RawStore};
use toz_core::script::{CommandCaller, Limits, LineSource, Meta, Outcome};
use toz_core::streaming;
use toz_core::{Config, Project, Store};

const MAX_FRAME: usize = 20 * 1024 * 1024;
const PREVIEW_BYTES: u64 = 64 * 1024;

pub(crate) struct Launch<'a> {
    pub scratch: &'a Path,
    pub policy: Option<&'a sandbox::Policy>,
}

pub(crate) fn run_script(
    cfg: &Config,
    project: &Project,
    source: &str,
    meta: &Meta,
    src: Rc<dyn LineSource>,
    limits: &Limits,
    launch: Launch<'_>,
) -> Result<(Outcome, bool)> {
    let Launch { scratch, policy } = launch;
    write_script_inputs(scratch, src)?;
    let initial = script_initial(source, meta, limits, scratch);
    let mut command = worker_command(project, scratch, policy)?;
    let mut child = command.spawn().context("starting toz worker")?;
    let result = run_parent_protocol(cfg, project, scratch, initial, &mut child);
    if result.is_err() {
        let _ = child.kill();
        let _ = child.wait();
    }
    result
}

fn write_script_inputs(scratch: &Path, src: Rc<dyn LineSource>) -> Result<()> {
    for stream in ["stdout", "stderr"] {
        let path = scratch.join(format!("input-{stream}"));
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)?;
        src.for_each_line(stream, &mut |line| {
            writeln!(file, "{line}")?;
            Ok(())
        })?;
    }
    Ok(())
}

fn script_initial(source: &str, meta: &Meta, limits: &Limits, scratch: &Path) -> Value {
    json!({
        "source": source,
        "meta": {"handle":meta.handle,"label":meta.label,"bytes":meta.bytes,
                 "lines":meta.lines,"exit_code":meta.exit_code,"stream":meta.stream},
        "limits": {"timeout_ms":limits.timeout_ms,"memory_bytes":limits.memory_bytes,
                   "max_output_bytes":limits.max_output_bytes,
                   "max_text_bytes":limits.max_text_bytes,"max_stack_bytes":limits.max_stack_bytes},
        "scratch": scratch,
    })
}

fn worker_command(
    project: &Project,
    scratch: &Path,
    policy: Option<&sandbox::Policy>,
) -> Result<std::process::Command> {
    let exe = std::env::current_exe()?;
    let root = project.root.canonicalize()?;
    let mut command = if let Some(policy) = policy {
        let workspace_allowed = policy
            .read_roots
            .iter()
            .chain(&policy.write_roots)
            .filter_map(|path| path.canonicalize().ok())
            .any(|path| root.starts_with(path));
        let cwd = if workspace_allowed { &root } else { scratch };
        sandbox::sandboxed_command(&exe, &[OsString::from("__worker")], policy, cwd)?
    } else {
        let mut command = std::process::Command::new(&exe);
        command.arg("__worker").current_dir(&root);
        command
    };
    command
        .env("TMPDIR", scratch)
        .env("TMP", scratch)
        .env("TEMP", scratch)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());
    Ok(command)
}

fn run_parent_protocol(
    cfg: &Config,
    project: &Project,
    scratch: &Path,
    initial: Value,
    child: &mut std::process::Child,
) -> Result<(Outcome, bool)> {
    let input = child.stdin.take().context("worker stdin unavailable")?;
    let output = child.stdout.take().context("worker stdout unavailable")?;
    let mut protocol = ParentProtocol {
        input: BufWriter::new(input),
        output: BufReader::new(output),
    };
    protocol.send(&initial)?;
    let mut sequence = 0u64;
    let result = loop {
        let frame = match protocol.recv()? {
            Some(frame) => frame,
            None => {
                drop(protocol);
                let status = child.wait()?;
                bail!("worker closed before returning a result ({status})");
            }
        };
        match frame.get("type").and_then(Value::as_str) {
            Some("exec") => {
                sequence += 1;
                ensure!(
                    frame["sequence"].as_u64() == Some(sequence),
                    "worker command sequence mismatch"
                );
                let reply = capture_command(cfg, project, scratch, sequence, &frame)?;
                protocol.send(&reply)?;
            }
            Some("result") => break parse_outcome(&frame)?,
            _ => bail!("invalid worker protocol frame"),
        }
    };
    drop(protocol);
    let status = child.wait()?;
    ensure!(status.success(), "toz worker exited with {status}");
    Ok(result)
}

struct ParentProtocol {
    input: BufWriter<ChildStdin>,
    output: BufReader<ChildStdout>,
}

impl ParentProtocol {
    fn send(&mut self, value: &Value) -> Result<()> {
        send_frame(&mut self.input, value)
    }
    fn recv(&mut self) -> Result<Option<Value>> {
        read_frame(&mut self.output)
    }
}

fn capture_command(
    cfg: &Config,
    project: &Project,
    scratch: &Path,
    sequence: u64,
    frame: &Value,
) -> Result<Value> {
    let source = frame["source"]
        .as_str()
        .context("worker command source missing")?;
    let exit_code = frame["exitCode"].as_i64().map(|n| n as i32);
    let mut stdout = open_worker_output(&scratch.join(format!("exec-{sequence}.stdout")))?;
    let mut stderr = open_worker_output(&scratch.join(format!("exec-{sequence}.stderr")))?;
    let stdout_bytes = stdout.metadata()?.len();
    let stderr_bytes = stderr.metadata()?.len();
    let (out, err, truncated) =
        read_command_preview(&mut stdout, &mut stderr, stdout_bytes, stderr_bytes)?;
    stdout.rewind()?;
    stderr.rewind()?;
    let raw = if frame["raw"].as_bool().unwrap_or(false) {
        store_raw(
            cfg,
            project,
            source,
            &mut stdout,
            &mut stderr,
            stdout_bytes,
            stderr_bytes,
        )
    } else {
        json!({"state":"not_requested"})
    };
    stdout.rewind()?;
    stderr.rewind()?;
    let capture = capture_worker_output(
        cfg,
        project,
        source,
        exit_code,
        &mut stdout,
        &mut stderr,
        stdout_bytes,
        stderr_bytes,
    )?;
    Ok(json!({
        "exitCode": frame["exitCode"], "signal": frame["signal"],
        "timedOut": frame["timedOut"], "interrupted": frame["interrupted"],
        "stdout": String::from_utf8_lossy(&out), "stderr": String::from_utf8_lossy(&err),
        "truncated": truncated, "capture": capture, "raw": raw,
    }))
}

fn read_command_preview(
    stdout: &mut File,
    stderr: &mut File,
    stdout_bytes: u64,
    stderr_bytes: u64,
) -> Result<(Vec<u8>, Vec<u8>, bool)> {
    let mut out = Vec::new();
    let mut err = Vec::new();
    stdout.take(PREVIEW_BYTES).read_to_end(&mut out)?;
    stderr.take(PREVIEW_BYTES).read_to_end(&mut err)?;
    let truncated = stdout_bytes > out.len() as u64 || stderr_bytes > err.len() as u64;
    Ok((out, err, truncated))
}

fn capture_worker_output(
    cfg: &Config,
    project: &Project,
    source: &str,
    exit_code: Option<i32>,
    stdout: &mut File,
    stderr: &mut File,
    stdout_bytes: u64,
    stderr_bytes: u64,
) -> Result<Value> {
    let mut store = open_store(cfg, project)?;
    let session = toz_core::config::env("TOZ_SESSION").ok();
    let outcome = streaming::run(
        cfg,
        &mut store,
        CaptureInput {
            stdout: &[],
            stderr: &[],
            label: None,
            source,
            kind: "exec",
            exit_code,
            session: session.as_deref(),
            force: true,
            defer_index: false,
            threshold: None,
            file_mtime: None,
            file_hash: None,
        },
        stdout,
        stderr,
        usize::try_from(stdout_bytes.saturating_add(stderr_bytes)).unwrap_or(usize::MAX),
    )?;
    Ok(match outcome {
        CaptureOutcome::Captured(preview) => json!({"state":"captured","handle":preview.handle}),
        CaptureOutcome::Skipped { rule } => json!({"state":"excluded","rule":rule}),
        CaptureOutcome::PassThrough => json!({"state":"unavailable"}),
    })
}

fn store_raw(
    cfg: &Config,
    project: &Project,
    source: &str,
    stdout: &mut File,
    stderr: &mut File,
    stdout_bytes: u64,
    stderr_bytes: u64,
) -> Value {
    if !cfg.raw.enabled {
        return json!({"state":"disabled"});
    }
    if stdout_bytes.saturating_add(stderr_bytes) > cfg.raw.max_bytes as u64 {
        return json!({"state":"cap_reached"});
    }
    let result = (|| -> Result<_> {
        let dir = project.store_dir()?.join("raw");
        let raw = RawStore::open(&dir, &cfg.raw, &cfg.capture)?;
        stdout.rewind()?;
        stderr.rewind()?;
        let mut out = Vec::with_capacity(stdout_bytes as usize);
        let mut err = Vec::with_capacity(stderr_bytes as usize);
        stdout.read_to_end(&mut out)?;
        stderr.read_to_end(&mut err)?;
        Ok(raw.store_with_source(source, &capture::source_key(source), &out, &err)?)
    })();
    match result {
        Ok(handle) => json!({"state":"stored","handle":handle.as_str(),"fidelity":"exact_bytes",
                             "ttl_secs":cfg.raw.ttl_secs}),
        Err(error) => match error.downcast_ref::<RawError>() {
            Some(RawError::Disabled) => json!({"state":"disabled"}),
            Some(RawError::Excluded { .. }) => json!({"state":"excluded"}),
            Some(RawError::TooLarge { .. }) => json!({"state":"cap_reached"}),
            _ => {
                eprintln!("toz worker: raw capture unavailable: {error:#}");
                json!({"state":"unavailable"})
            }
        },
    }
}

fn open_store(cfg: &Config, project: &Project) -> Result<Store> {
    let path = project.db_path()?;
    let mut store = match Store::open(&path) {
        Ok(store) => store,
        Err(error) if Store::access_error(&error) => {
            let fallback = project
                .fallback_db_path()
                .filter(|candidate| candidate != &path)
                .context("default store unavailable and no fallback is configured")?;
            Store::open(&fallback)?
        }
        Err(error) => return Err(error),
    };
    store.maybe_prune(&cfg.retention)?;
    Ok(store)
}

fn open_worker_output(path: &Path) -> Result<File> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        let file = OpenOptions::new()
            .read(true)
            .custom_flags(libc::O_NOFOLLOW)
            .open(path)?;
        ensure!(
            file.metadata()?.is_file(),
            "worker output is not a regular file"
        );
        Ok(file)
    }
    #[cfg(not(unix))]
    {
        let file = File::open(path)?;
        ensure!(
            file.metadata()?.is_file(),
            "worker output is not a regular file"
        );
        Ok(file)
    }
}

struct FileLines {
    scratch: PathBuf,
}

impl LineSource for FileLines {
    fn for_each_line(&self, stream: &str, f: &mut dyn FnMut(&str) -> Result<()>) -> Result<()> {
        ensure!(stream == "stdout" || stream == "stderr", "invalid stream");
        let file = File::open(self.scratch.join(format!("input-{stream}")))?;
        for line in BufReader::new(file).lines() {
            f(&line?)?;
        }
        Ok(())
    }
}

struct WorkerCommands {
    scratch: PathBuf,
    protocol: RefCell<WorkerProtocol>,
    sequence: Cell<u64>,
    used: Cell<bool>,
}

struct WorkerProtocol {
    input: BufReader<io::Stdin>,
    output: BufWriter<io::Stdout>,
}

impl CommandCaller for WorkerCommands {
    fn exec(&self, request: Value, timeout: Duration) -> Result<Value> {
        self.used.set(true);
        let sequence = self.sequence.get() + 1;
        self.sequence.set(sequence);
        let source = request
            .get("shell")
            .and_then(Value::as_str)
            .map(str::to_string)
            .or_else(|| {
                request.get("argv").and_then(Value::as_array).map(|parts| {
                    parts
                        .iter()
                        .filter_map(Value::as_str)
                        .collect::<Vec<_>>()
                        .join(" ")
                })
            })
            .unwrap_or_else(|| "exec".into());
        let out_path = self.scratch.join(format!("exec-{sequence}.stdout"));
        let err_path = self.scratch.join(format!("exec-{sequence}.stderr"));
        let mut stdout = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&out_path)?;
        let mut stderr = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&err_path)?;
        let raw = request.get("raw").and_then(Value::as_bool).unwrap_or(false);
        let result = machine::execute_script(request, timeout, &mut |stream, bytes| {
            if stream == "stderr" {
                stderr.write_all(bytes)?;
            } else {
                stdout.write_all(bytes)?;
            }
            Ok(())
        })?;
        stdout.flush()?;
        stderr.flush()?;
        let frame = json!({"type":"exec","sequence":sequence,"source":source,
            "exitCode":result.exit_code,"signal":result.signal,
            "timedOut":result.timed_out,"interrupted":result.interrupted,"raw":raw});
        let mut protocol = self.protocol.borrow_mut();
        send_frame(&mut protocol.output, &frame)?;
        let reply =
            read_frame(&mut protocol.input)?.context("parent closed during command capture")?;
        std::fs::remove_file(out_path)?;
        std::fs::remove_file(err_path)?;
        if let Some(error) = reply.get("error").and_then(Value::as_str) {
            bail!("{error}");
        }
        Ok(reply)
    }
}

pub(crate) fn worker_main() -> Result<i32> {
    let input = io::stdin();
    let output = io::stdout();
    let mut reader = BufReader::new(input);
    let initial = read_frame(&mut reader)?.context("missing worker request")?;
    let scratch = PathBuf::from(
        initial["scratch"]
            .as_str()
            .context("missing scratch path")?,
    );
    let meta = &initial["meta"];
    let limits = &initial["limits"];
    let meta = Meta {
        handle: meta["handle"].as_str().unwrap_or_default().into(),
        label: meta["label"].as_str().unwrap_or_default().into(),
        bytes: meta["bytes"].as_i64().unwrap_or_default(),
        lines: meta["lines"].as_i64().unwrap_or_default(),
        exit_code: meta["exit_code"].as_i64().map(|n| n as i32),
        stream: meta["stream"].as_str().unwrap_or("stdout").into(),
    };
    let limits = Limits {
        timeout_ms: limits["timeout_ms"].as_u64().context("missing timeout")?,
        memory_bytes: limits["memory_bytes"]
            .as_u64()
            .context("missing memory limit")? as usize,
        max_output_bytes: limits["max_output_bytes"]
            .as_u64()
            .context("missing output limit")? as usize,
        max_text_bytes: limits["max_text_bytes"]
            .as_u64()
            .context("missing text limit")? as usize,
        max_stack_bytes: limits["max_stack_bytes"]
            .as_u64()
            .context("missing stack limit")? as usize,
    };
    let commands = Rc::new(WorkerCommands {
        scratch: scratch.clone(),
        protocol: RefCell::new(WorkerProtocol {
            input: reader,
            output: BufWriter::new(output),
        }),
        sequence: Cell::new(0),
        used: Cell::new(false),
    });
    let source = initial["source"]
        .as_str()
        .context("missing script source")?;
    let lines: Rc<dyn LineSource> = Rc::new(FileLines { scratch });
    let (outcome, _records) =
        toz_core::script::run_with_tools(source, &meta, lines, &limits, Some(commands.clone()))?;
    let frame = outcome_frame(outcome, commands.used.get());
    send_frame(&mut commands.protocol.borrow_mut().output, &frame)?;
    Ok(0)
}

fn outcome_frame(outcome: Outcome, used: bool) -> Value {
    match outcome {
        Outcome::Ok(text) => json!({"type":"result","kind":"ok","text":text,"used":used}),
        Outcome::Exception(text) => {
            json!({"type":"result","kind":"exception","text":text,"used":used})
        }
        Outcome::Timeout => json!({"type":"result","kind":"timeout","used":used}),
        Outcome::MemoryLimit => json!({"type":"result","kind":"memory_limit","used":used}),
        Outcome::OutputLimit => json!({"type":"result","kind":"output_limit","used":used}),
    }
}

fn parse_outcome(frame: &Value) -> Result<(Outcome, bool)> {
    let text = frame["text"].as_str().unwrap_or_default().to_string();
    let outcome = match frame["kind"].as_str() {
        Some("ok") => Outcome::Ok(text),
        Some("exception") => Outcome::Exception(text),
        Some("timeout") => Outcome::Timeout,
        Some("memory_limit") => Outcome::MemoryLimit,
        Some("output_limit") => Outcome::OutputLimit,
        _ => bail!("unknown worker outcome"),
    };
    Ok((outcome, frame["used"].as_bool().unwrap_or(false)))
}

fn send_frame(writer: &mut impl Write, value: &Value) -> Result<()> {
    let bytes = serde_json::to_vec(value)?;
    ensure!(bytes.len() <= MAX_FRAME, "worker protocol frame too large");
    writer.write_all(&bytes)?;
    writer.write_all(b"\n")?;
    writer.flush()?;
    Ok(())
}

fn read_frame(reader: &mut impl BufRead) -> Result<Option<Value>> {
    let mut bytes = Vec::new();
    loop {
        let available = reader.fill_buf()?;
        if available.is_empty() {
            if bytes.is_empty() {
                return Ok(None);
            }
            bail!("incomplete worker protocol frame");
        }
        let n = available
            .iter()
            .position(|b| *b == b'\n')
            .map(|i| i + 1)
            .unwrap_or(available.len());
        ensure!(
            bytes.len() + n <= MAX_FRAME + 1,
            "worker protocol frame too large"
        );
        let ended = available[n - 1] == b'\n';
        bytes.extend_from_slice(&available[..n]);
        reader.consume(n);
        if ended {
            break;
        }
    }
    Ok(Some(serde_json::from_slice(&bytes)?))
}
