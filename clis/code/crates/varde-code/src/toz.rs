//! Shared toz (tool-output-zone) capture helper.
//!
//! Centralizes the "shell out to `toz capture`, any failure -> `None`"
//! contract, mirroring `git.rs`'s spawn-and-check convention. `run_nav_map`
//! (`main.rs`) uses this to offload the full, unbudgeted `nav_map` text
//! render behind a toz handle; truncated JSON result lists use `capture_items`.

use serde_json::{Value, json};
use std::io::{self, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};

pub const PAGE_LIMIT: usize = 20;
const INPUT_CHUNK_SIZE: usize = 8 * 1024;
// A small queue keeps backpressure bounded while the child consumes stdin.
const INPUT_QUEUE_CHUNKS: usize = 4;
const WORKER_CLEANUP_GRACE: Duration = Duration::from_millis(50);

/// A reference to a complete JSONL result set stored in toz.
pub fn capture_items(mode: &str, items: &[Value]) -> Option<Value> {
    if !available() {
        return None;
    }
    let source = format!("varde-code results {mode}");
    let mut args = vec![
        "--json", "capture", "--force", "--source", &source, "--label", mode,
    ];
    if mode == "find_pattern" {
        args.push("--defer-index");
    }
    let stdout = capture_with_args(
        &args,
        |input| {
            for item in items {
                serde_json::to_writer(&mut *input, item)
                    .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))?;
                input.write_all(b"\n")?;
            }
            Ok(())
        },
        CAPTURE_TIMEOUT,
    )?;
    let response: Value = serde_json::from_str(&stdout).ok()?;
    let handle = response.get("handle")?.as_str()?;
    Some(
        json!({"handle": handle, "items": items.len(), "format": "jsonl", "toc": compact_toc(&response)}),
    )
}

/// Bound the inline TOC even when a result spans hundreds of files.
fn compact_toc(response: &Value) -> Value {
    let Some(entries) = response.get("toc").and_then(Value::as_array) else {
        return response.get("preview").cloned().unwrap_or(Value::Null);
    };
    let mut out = String::new();
    for (index, entry) in entries.iter().enumerate() {
        let title = entry["title"].as_str().unwrap_or("other");
        let items = entry["items"].as_u64().unwrap_or(0);
        let start = entry["line_start"].as_u64().unwrap_or(0);
        let end = entry["line_end"].as_u64().unwrap_or(0);
        let line = format!("{title}: {items} items (L{start}-L{end})\n");
        if out.len() + line.len() > 3_800 {
            out.push_str(&format!(
                "... {} more file sections; query the handle for all results",
                entries.len() - index
            ));
            break;
        }
        out.push_str(&line);
    }
    Value::String(out)
}

pub fn add_guide(guide: &mut Value, reference: &Value, start: usize, end: usize) {
    let Some(handle) = reference["handle"].as_str() else {
        return;
    };
    if start < end {
        guide["toz_read"] = json!(format!(
            "toz query --handle {handle} --lines {}:{}",
            start + 1,
            end
        ));
    }
    guide["toz_search"] = json!(format!("toz query --handle {handle} \"<term>\""));
}

/// How long [`capture_text`] waits for `toz capture` to exit before killing
/// it and falling back to `None`. A stalled toz (e.g. a store lock's
/// `busy_timeout`) must never hang the caller — most callers run inside a
/// session-start hook.
const CAPTURE_TIMEOUT: Duration = Duration::from_secs(5);

/// Capture `text` to toz via `toz capture --force --source <source> --label
/// <label>`, with `text` written to stdin.
///
/// Returns toz's stdout (its TOC preview) when the spawn succeeds and that
/// stdout contains `"handle"` — evidence toz actually stored the capture
/// rather than, say, exiting 0 with a bare usage message. Any other outcome
/// (missing binary, non-zero exit, no `"handle"` in stdout, or the process
/// running past [`CAPTURE_TIMEOUT`]) returns `None` so the caller falls back
/// to its own rendering.
///
/// `VARDE_CODE_TOZ=0` skips the spawn entirely, so callers that don't want
/// the process cost (tests, environments without toz) can opt out without
/// relying on the binary being absent from `PATH`.
pub fn capture_text(source: &str, label: &str, text: &str) -> Option<String> {
    capture_text_with_timeout(source, label, text, CAPTURE_TIMEOUT)
}

fn capture_text_with_timeout(
    source: &str,
    label: &str,
    text: &str,
    timeout: Duration,
) -> Option<String> {
    capture_with_args(
        &["capture", "--force", "--source", source, "--label", label],
        |input| input.write_all(text.as_bytes()),
        timeout,
    )
}

fn capture_with_args<F>(args: &[&str], write_input: F, timeout: Duration) -> Option<String>
where
    F: FnOnce(&mut BoundedInputWriter) -> io::Result<()>,
{
    if !enabled() {
        return None;
    }
    let mut command = Command::new("toz");
    command
        .args(args)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }
    let mut child = command.spawn().ok()?;

    // Keep input writes off the polling thread and drain stdout concurrently:
    // either pipe can fill while the child is using the other one.
    let mut stdin = child.stdin.take().expect("stdin was piped");
    let mut stdout = child.stdout.take().expect("stdout was piped");
    let (input_tx, input_rx) = mpsc::sync_channel::<Vec<u8>>(INPUT_QUEUE_CHUNKS);
    let writer_thread = std::thread::spawn(move || {
        while let Ok(chunk) = input_rx.recv() {
            if stdin.write_all(&chunk).is_err() {
                break;
            }
        }
    });
    let (tx, rx) = mpsc::channel();
    let reader_thread = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.read_to_end(&mut buf);
        let _ = tx.send(buf);
    });

    let deadline = Instant::now() + timeout;
    let input_result = {
        let mut input = BoundedInputWriter::new(input_tx, deadline);
        write_input(&mut input).and_then(|()| input.flush())
    };
    if input_result.is_err() {
        cleanup_capture(&mut child, writer_thread, reader_thread);
        return None;
    }

    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() >= deadline => {
                cleanup_capture(&mut child, writer_thread, reader_thread);
                return None;
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(1)),
            Err(_) => {
                cleanup_capture(&mut child, writer_thread, reader_thread);
                return None;
            }
        }
    };
    if !status.success() {
        cleanup_capture(&mut child, writer_thread, reader_thread);
        return None;
    }
    terminate_process_group(&child);
    if !join_worker(writer_thread) {
        let _ = join_worker(reader_thread);
        return None;
    }
    let remaining = deadline.saturating_duration_since(Instant::now());
    let stdout_buf = match rx.recv_timeout(remaining) {
        Ok(stdout) => stdout,
        Err(_) => {
            let _ = join_worker(reader_thread);
            return None;
        }
    };
    if !join_worker(reader_thread) {
        return None;
    }
    let stdout = String::from_utf8_lossy(&stdout_buf).into_owned();
    stdout.contains("handle").then_some(stdout)
}

struct BoundedInputWriter {
    sender: mpsc::SyncSender<Vec<u8>>,
    buffer: Vec<u8>,
    deadline: Instant,
}

impl BoundedInputWriter {
    fn new(sender: mpsc::SyncSender<Vec<u8>>, deadline: Instant) -> Self {
        Self {
            sender,
            buffer: Vec::with_capacity(INPUT_CHUNK_SIZE),
            deadline,
        }
    }

    fn send_buffer(&mut self) -> io::Result<()> {
        if self.buffer.is_empty() {
            return Ok(());
        }
        let mut chunk = std::mem::replace(&mut self.buffer, Vec::with_capacity(INPUT_CHUNK_SIZE));
        loop {
            if Instant::now() >= self.deadline {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "toz input timed out",
                ));
            }
            match self.sender.try_send(chunk) {
                Ok(()) => return Ok(()),
                Err(mpsc::TrySendError::Full(returned)) => {
                    chunk = returned;
                    std::thread::sleep(Duration::from_millis(1));
                }
                Err(mpsc::TrySendError::Disconnected(_)) => {
                    return Err(io::Error::new(
                        io::ErrorKind::BrokenPipe,
                        "toz closed stdin",
                    ));
                }
            }
        }
    }
}

impl Write for BoundedInputWriter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        if bytes.is_empty() {
            return Ok(0);
        }
        if Instant::now() >= self.deadline {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "toz input timed out",
            ));
        }
        let remaining = INPUT_CHUNK_SIZE - self.buffer.len();
        let written = bytes.len().min(remaining);
        self.buffer.extend_from_slice(&bytes[..written]);
        if self.buffer.len() == INPUT_CHUNK_SIZE {
            self.send_buffer()?;
        }
        Ok(written)
    }

    fn flush(&mut self) -> io::Result<()> {
        self.send_buffer()
    }
}

fn terminate_and_wait(child: &mut Child) {
    terminate_process_group(child);
    let _ = child.kill();
    let _ = child.wait();
}

fn terminate_process_group(child: &Child) {
    #[cfg(unix)]
    {
        // The child is the group leader. Killing the group also closes pipes
        // inherited by descendants that would otherwise strand reader threads.
        let pgid = child.id() as libc::pid_t;
        unsafe {
            libc::killpg(pgid, libc::SIGKILL);
        }
    }
    #[cfg(not(unix))]
    {
        let _ = child;
    }
}

fn cleanup_capture(
    child: &mut Child,
    writer_thread: std::thread::JoinHandle<()>,
    reader_thread: std::thread::JoinHandle<()>,
) {
    terminate_and_wait(child);
    let _ = join_worker(writer_thread);
    let _ = join_worker(reader_thread);
}

fn join_worker(handle: std::thread::JoinHandle<()>) -> bool {
    let deadline = Instant::now() + WORKER_CLEANUP_GRACE;
    while !handle.is_finished() && Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(1));
    }
    if handle.is_finished() {
        handle.join().is_ok()
    } else {
        false
    }
}

/// Whether toz capture should be attempted at all. Callers that also need to
/// skip the (potentially expensive) work of building the text to capture
/// check this before doing that work, rather than only inside
/// [`capture_text`].
pub fn enabled() -> bool {
    std::env::var("VARDE_CODE_TOZ").as_deref() != Ok("0")
}

/// Cheap preflight for call sites that would otherwise retain an unbounded
/// result set during a search. Called once per query, never once per file.
pub fn available() -> bool {
    enabled()
        && std::env::split_paths(&std::env::var_os("PATH").unwrap_or_default())
            .any(|dir| dir.join("toz").is_file())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::PathOverride;

    #[test]
    fn bounded_input_writer_chunks_large_writes() {
        const CHUNK_SIZE: usize = 8 * 1024;
        let payload = vec![b'x'; CHUNK_SIZE * 6 + 17];
        let (tx, rx) = mpsc::sync_channel(2);
        let collector = std::thread::spawn(move || rx.into_iter().collect::<Vec<_>>());
        let mut writer = BoundedInputWriter::new(tx, Instant::now() + Duration::from_secs(2));

        writer.write_all(&payload).expect("large payload writes");
        writer.flush().expect("last chunk flushes");
        drop(writer);

        let chunks = collector.join().expect("collector finishes");
        assert!(!chunks.is_empty());
        assert!(
            chunks
                .iter()
                .all(|chunk| !chunk.is_empty() && chunk.len() <= CHUNK_SIZE)
        );
        assert_eq!(chunks.concat(), payload);
    }

    #[test]
    fn capture_items_streams_large_jsonl_to_child() {
        let dir = stub_bin_dir(
            "large-items",
            "#!/bin/sh\ncat > \"$0.input\"\necho '{\"handle\":\"ab12\",\"toc\":[]}'\n",
        );
        let output_path = dir.join("toz.input");
        let _override = PathOverride::new(&dir);
        let payload = "x".repeat(256 * 1024);
        let items = vec![json!({"payload": payload})];

        let result = capture_items("query", &items).expect("capture returns a handle");

        assert_eq!(result["handle"], "ab12");
        assert_eq!(result["items"], 1);
        let expected = format!("{{\"payload\":\"{}\"}}\n", "x".repeat(256 * 1024));
        assert_eq!(std::fs::read_to_string(output_path).unwrap(), expected);
    }

    #[test]
    fn capture_items_returns_none_on_child_failure() {
        let dir = stub_bin_dir("items-failure", "#!/bin/sh\nexit 1\n");
        let _override = PathOverride::new(&dir);
        let items = vec![json!({"payload": "x".repeat(256 * 1024)})];

        assert_eq!(capture_items("query", &items), None);
    }

    #[test]
    fn toc_summary_is_bounded_for_many_files() {
        let entries: Vec<Value> = (0..200).map(|i| json!({"title": format!("src/very-long-module-{i}.rs"), "items": 7, "line_start": i*7+1, "line_end": (i+1)*7})).collect();
        let toc = compact_toc(&json!({"toc": entries}));
        let text = toc.as_str().unwrap();
        assert!(text.len() <= 4_000, "{} bytes", text.len());
        assert!(text.contains("src/very-long-module-0.rs: 7 items"));
        assert!(text.contains("more file sections"));
    }

    fn stub_bin_dir(label: &str, script: &str) -> std::path::PathBuf {
        let dir = std::env::temp_dir().join(format!(
            "varde-toz-test-{label}-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .expect("clock is after epoch")
                .as_nanos()
        ));
        std::fs::create_dir_all(&dir).expect("bin dir creates");
        let script_path = dir.join("toz");
        std::fs::write(&script_path, script).expect("script writes");
        let mut perms = std::fs::metadata(&script_path)
            .expect("script metadata")
            .permissions();
        std::os::unix::fs::PermissionsExt::set_mode(&mut perms, 0o755);
        std::fs::set_permissions(&script_path, perms).expect("script perms set");
        dir
    }

    /// A `toz` on `PATH` that captures successfully (exit 0, stdout contains
    /// `"handle"`) returns that stdout, and receives the given text on stdin.
    #[test]
    fn capture_text_returns_stub_stdout_on_success() {
        let dir = stub_bin_dir(
            "success",
            "#!/bin/sh\ncat > /dev/null\necho 'toz: captured 12 bytes -> handle ab12'\n",
        );
        let _override = PathOverride::new(&dir);

        let result = capture_text("varde-code nav_map /repo", "nav_map", "## entrypoints\n");
        assert_eq!(
            result.as_deref(),
            Some("toz: captured 12 bytes -> handle ab12\n")
        );
    }

    /// The stub receives the exact text passed on stdin.
    #[test]
    fn capture_text_writes_the_given_text_to_stdin() {
        let dir = stub_bin_dir("stdin-echo", "#!/bin/sh\ncat\necho handle\n");
        let _override = PathOverride::new(&dir);

        let result = capture_text("varde-code nav_map /repo", "nav_map", "hello toz");
        let stdout = result.expect("capture succeeds");
        assert!(stdout.starts_with("hello toz"), "{stdout}");
        assert!(stdout.contains("handle"), "{stdout}");
    }

    /// A `toz` that exits non-zero yields `None`, even if it printed
    /// `"handle"` on stdout first.
    #[test]
    fn capture_text_returns_none_on_nonzero_exit() {
        let dir = stub_bin_dir(
            "failure",
            "#!/bin/sh\ncat > /dev/null\necho handle\nexit 1\n",
        );
        let _override = PathOverride::new(&dir);

        let result = capture_text("varde-code nav_map /repo", "nav_map", "text");
        assert_eq!(result, None);
    }

    /// Success without `"handle"` in stdout (e.g. a usage error printed to
    /// stdout with a stray exit 0) is treated as no capture.
    #[test]
    fn capture_text_returns_none_without_handle_in_stdout() {
        let dir = stub_bin_dir("no-handle", "#!/bin/sh\ncat > /dev/null\necho ok\n");
        let _override = PathOverride::new(&dir);

        let result = capture_text("varde-code nav_map /repo", "nav_map", "text");
        assert_eq!(result, None);
    }

    /// `VARDE_CODE_TOZ=0` skips the spawn entirely — even a stub that would
    /// otherwise succeed is never invoked.
    #[test]
    fn capture_text_skips_spawn_when_disabled_by_env() {
        let dir = stub_bin_dir("disabled", "#!/bin/sh\ncat > /dev/null\necho handle\n");
        let _override = PathOverride::new(&dir);
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "0") };

        let result = capture_text("varde-code nav_map /repo", "nav_map", "text");
        assert_eq!(result, None);
    }

    /// No `toz` on `PATH` at all returns `None` rather than panicking.
    #[test]
    fn capture_text_returns_none_when_binary_is_missing() {
        let _override = PathOverride::without_toz();

        let result = capture_text("varde-code nav_map /repo", "nav_map", "text");
        assert_eq!(result, None);
    }

    /// A `toz` that stalls past the timeout is killed and yields `None`,
    /// without the test itself waiting anywhere near the stall duration.
    #[test]
    fn capture_text_returns_none_when_child_stalls_past_timeout() {
        let dir = stub_bin_dir("stall", "#!/bin/sh\ncat > /dev/null\nexec sleep 30\n");
        let _override = PathOverride::new(&dir);

        let start = std::time::Instant::now();
        let result = capture_text_with_timeout(
            "varde-code nav_map /repo",
            "nav_map",
            "text",
            std::time::Duration::from_millis(200),
        );
        assert_eq!(result, None);
        assert!(
            start.elapsed() < std::time::Duration::from_secs(5),
            "took {:?}",
            start.elapsed()
        );
    }

    #[cfg(unix)]
    #[test]
    fn capture_text_cleans_up_descendant_after_leader_exit() {
        let dir = stub_bin_dir("descendant", "");
        let pid_path = dir.join("leader.pid");
        std::fs::write(
            dir.join("toz"),
            format!(
                "#!/bin/sh\nsleep 30 &\nprintf '%s' \"$$\" > '{}'\necho handle\n",
                pid_path.display()
            ),
        )
        .expect("write Toz stub");
        let _override = PathOverride::new(&dir);

        let start = Instant::now();
        let result = capture_text_with_timeout(
            "varde-code nav_map /repo",
            "nav_map",
            "text",
            Duration::from_secs(5),
        );
        let elapsed = start.elapsed();
        let pgid: libc::pid_t = std::fs::read_to_string(&pid_path)
            .expect("stub writes its process-group id")
            .parse()
            .expect("process-group id is numeric");
        let cleanup_deadline = Instant::now() + Duration::from_secs(1);
        while process_group_alive(pgid) && Instant::now() < cleanup_deadline {
            std::thread::sleep(Duration::from_millis(10));
        }
        let group_cleaned = !process_group_alive(pgid);
        if !group_cleaned {
            unsafe {
                libc::killpg(pgid, libc::SIGKILL);
            }
        }

        assert_eq!(result.as_deref(), Some("handle\n"));
        assert!(elapsed < Duration::from_secs(2), "capture took {elapsed:?}");
        assert!(group_cleaned, "descendant process group {pgid} survived");
    }

    #[cfg(unix)]
    fn process_group_alive(pgid: libc::pid_t) -> bool {
        unsafe { libc::kill(-pgid, 0) == 0 }
    }
}
