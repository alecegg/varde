//! launchd plist generation and process-supervision plumbing.
//!
//! Plist string generation is a pure function ([`generate_plist`]) so it's
//! unit-testable without invoking `launchctl`. The `launchctl`-invoking
//! functions ([`bootstrap`], `bootout`, [`is_running`]) shell out via
//! `std::process::Command` and are not covered by automated tests — see the
//! task's Progress entry for manual verification notes.

use anyhow::{Context, Result};
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::process::Command;

/// launchd label for a given watcher id, e.g. `com.docwatch.abc123def456`.
pub fn label_for_id(id: &str) -> String {
    format!("com.docwatch.{id}")
}

/// Default plist path: `~/Library/LaunchAgents/com.docwatch.<id>.plist`.
pub fn default_plist_path(id: &str) -> Result<PathBuf> {
    let home = std::env::var_os("HOME").context("HOME environment variable is not set")?;
    Ok(PathBuf::from(home)
        .join("Library")
        .join("LaunchAgents")
        .join(format!("{}.plist", label_for_id(id))))
}

/// Default log directory: `~/Library/Logs/docwatch/<id>/`.
pub fn default_log_dir(id: &str) -> Result<PathBuf> {
    let home = std::env::var_os("HOME").context("HOME environment variable is not set")?;
    Ok(PathBuf::from(home)
        .join("Library")
        .join("Logs")
        .join("docwatch")
        .join(id))
}

fn xml_escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
}

/// Generate the plist XML for a watcher. Pure function — no filesystem
/// access, no launchctl invocation.
pub fn generate_plist(id: &str, exe_path: &Path, folder: &Path, log_dir: &Path) -> String {
    let label = label_for_id(id);
    let exe = xml_escape(&exe_path.to_string_lossy());
    let folder_str = xml_escape(&folder.to_string_lossy());
    let out_log = xml_escape(&log_dir.join("watcher.log").to_string_lossy());
    let err_log = xml_escape(&log_dir.join("watcher.err.log").to_string_lossy());

    format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exe}</string>
        <string>_run-watcher</string>
        <string>--folder</string>
        <string>{folder_str}</string>
        <string>--id</string>
        <string>{id}</string>
    </array>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{out_log}</string>
    <key>StandardErrorPath</key>
    <string>{err_log}</string>
</dict>
</plist>
"#
    )
}

/// Write `contents` to `plist_path`, creating parent directories as needed.
pub fn write_plist(plist_path: &Path, contents: &str) -> Result<()> {
    if let Some(parent) = plist_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("creating plist directory {}", parent.display()))?;
    }
    fs::write(plist_path, contents)
        .with_context(|| format!("writing plist at {}", plist_path.display()))?;
    Ok(())
}

/// Remove the plist file if present. Not an error if it's already gone.
pub fn remove_plist(plist_path: &Path) -> Result<()> {
    match fs::remove_file(plist_path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e).with_context(|| format!("removing plist at {}", plist_path.display())),
    }
}

fn gui_domain() -> String {
    // SAFETY: `id -u` is used rather than a libc call to avoid an extra
    // dependency; this mirrors the plan's `gui/$(id -u)` domain target.
    let uid = Command::new("id")
        .arg("-u")
        .output()
        .ok()
        .and_then(|o| String::from_utf8(o.stdout).ok())
        .map(|s| s.trim().to_string())
        .unwrap_or_else(|| "0".to_string());
    format!("gui/{uid}")
}

/// Load the job into launchd. Tries the modern `launchctl bootstrap`
/// subcommand first, falling back to `load` if `bootstrap` isn't available
/// or fails (older macOS).
pub fn bootstrap(plist_path: &Path) -> Result<()> {
    let domain = gui_domain();
    let status = Command::new("launchctl")
        .args(["bootstrap", &domain])
        .arg(plist_path)
        .status();

    let bootstrap_ok = matches!(status, Ok(s) if s.success());
    if bootstrap_ok {
        return Ok(());
    }

    let status = Command::new("launchctl")
        .arg("load")
        .arg(plist_path)
        .status()
        .context("running launchctl load")?;
    if !status.success() {
        anyhow::bail!(
            "launchctl bootstrap/load failed for {}",
            plist_path.display()
        );
    }
    Ok(())
}

/// Unload the job from launchd. Tries `launchctl bootout` first, falling
/// back to `unload`.
pub fn bootout(id: &str, plist_path: &Path) -> Result<()> {
    let domain = gui_domain();
    let label = label_for_id(id);
    let status = Command::new("launchctl")
        .args(["bootout", &format!("{domain}/{label}")])
        .status();

    let bootout_ok = matches!(status, Ok(s) if s.success());
    if bootout_ok {
        return Ok(());
    }

    let status = Command::new("launchctl")
        .arg("unload")
        .arg(plist_path)
        .status()
        .context("running launchctl unload")?;
    if !status.success() {
        // Not fatal: the job may simply not be currently loaded (e.g. after
        // logout/login or a crash) — the plist/registry cleanup should still
        // proceed.
    }
    Ok(())
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JobStatus {
    Running { pid: u32 },
    Stopped,
}

/// Query `launchctl list <label>` and parse whether the job is running and
/// its PID. Parsing is exercised via [`parse_launchctl_list_output`]; this
/// wrapper is the only part that shells out.
pub fn is_running(id: &str) -> Result<JobStatus> {
    let label = label_for_id(id);
    let output = Command::new("launchctl")
        .args(["list", &label])
        .output()
        .context("running launchctl list")?;
    if !output.status.success() {
        return Ok(JobStatus::Stopped);
    }
    let text = String::from_utf8_lossy(&output.stdout);
    Ok(parse_launchctl_list_output(&text))
}

/// Parse the plist-ish key/value output of `launchctl list <label>` (single
/// job form) to find the `"PID" = <n>;` entry. Pure function, unit-tested.
pub fn parse_launchctl_list_output(text: &str) -> JobStatus {
    for line in text.lines() {
        let trimmed = line.trim().trim_end_matches(';');
        if let Some(rest) = trimmed.strip_prefix("\"PID\" = ")
            && let Ok(pid) = rest.trim().parse::<u32>()
        {
            return JobStatus::Running { pid };
        }
    }
    JobStatus::Stopped
}

/// Return the last `n` lines of `log_path`, or an empty vec if the file
/// doesn't exist yet.
pub fn tail_log(log_path: &Path, n: usize) -> Result<Vec<String>> {
    if n == 0 {
        return Ok(Vec::new());
    }
    let mut file = match fs::File::open(log_path) {
        Ok(file) => file,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(error).with_context(|| format!("opening log at {}", log_path.display()));
        }
    };
    let length = file
        .metadata()
        .with_context(|| format!("reading log metadata at {}", log_path.display()))?
        .len();
    if length == 0 {
        return Ok(Vec::new());
    }

    file.seek(SeekFrom::End(-1))?;
    let mut final_byte = [0_u8; 1];
    file.read_exact(&mut final_byte)?;
    let required_newlines = n.saturating_add(usize::from(final_byte[0] == b'\n'));
    let (mut bytes, newline_count) = read_log_tail(&mut file, length, required_newlines)?;
    trim_log_prefix(&mut bytes, newline_count, required_newlines);
    let contents = String::from_utf8(bytes)
        .with_context(|| format!("reading UTF-8 log at {}", log_path.display()))?;
    let line_count = contents.lines().count();
    Ok(contents
        .lines()
        .skip(line_count.saturating_sub(n))
        .map(str::to_string)
        .collect())
}

fn read_log_tail(
    file: &mut fs::File,
    length: u64,
    required_newlines: usize,
) -> Result<(Vec<u8>, usize)> {
    const BLOCK_SIZE: u64 = 8 * 1024;
    let mut chunks = Vec::new();
    let mut position = length;
    let mut newline_count = 0;
    while position > 0 && newline_count < required_newlines {
        let start = position.saturating_sub(BLOCK_SIZE);
        let mut chunk = vec![0; (position - start) as usize];
        file.seek(SeekFrom::Start(start))?;
        file.read_exact(&mut chunk)?;
        newline_count += chunk.iter().filter(|byte| **byte == b'\n').count();
        chunks.push(chunk);
        position = start;
    }
    let retained = chunks.iter().map(Vec::len).sum();
    let mut bytes = Vec::with_capacity(retained);
    for chunk in chunks.iter().rev() {
        bytes.extend_from_slice(chunk);
    }
    Ok((bytes, newline_count))
}

fn trim_log_prefix(bytes: &mut Vec<u8>, newline_count: usize, required_newlines: usize) {
    if newline_count < required_newlines {
        return;
    }
    let boundary = bytes
        .iter()
        .enumerate()
        .rev()
        .filter(|(_, byte)| **byte == b'\n')
        .nth(required_newlines - 1)
        .map(|(index, _)| index);
    if let Some(boundary) = boundary {
        bytes.drain(..=boundary);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn generate_plist_includes_label_and_program_arguments() {
        let xml = generate_plist(
            "abc123",
            Path::new("/usr/local/bin/docwatch"),
            Path::new("/Users/me/docs"),
            Path::new("/Users/me/Library/Logs/docwatch/abc123"),
        );
        assert!(xml.contains("<string>com.docwatch.abc123</string>"));
        assert!(xml.contains("<string>/usr/local/bin/docwatch</string>"));
        assert!(xml.contains("<string>_run-watcher</string>"));
        assert!(xml.contains("<string>--folder</string>"));
        assert!(xml.contains("<string>/Users/me/docs</string>"));
        assert!(xml.contains("<string>--id</string>"));
        assert!(xml.contains("<string>abc123</string>"));
        assert!(xml.contains("<true/>"));
        assert!(xml.contains("watcher.log"));
        assert!(xml.contains("watcher.err.log"));
    }

    #[test]
    fn generate_plist_escapes_xml_special_chars() {
        let xml = generate_plist(
            "id1",
            Path::new("/bin/docwatch"),
            Path::new("/Users/me/a & b <docs>"),
            Path::new("/logs"),
        );
        assert!(xml.contains("a &amp; b &lt;docs&gt;"));
        assert!(!xml.contains("a & b <docs>"));
    }

    #[test]
    fn label_for_id_formats_correctly() {
        assert_eq!(label_for_id("abc123"), "com.docwatch.abc123");
    }

    #[test]
    fn parse_launchctl_list_output_running_extracts_pid() {
        let text = r#"{
	"PID" = 4242;
	"Label" = "com.docwatch.abc123";
};"#;
        assert_eq!(
            parse_launchctl_list_output(text),
            JobStatus::Running { pid: 4242 }
        );
    }

    #[test]
    fn parse_launchctl_list_output_stopped_when_no_pid() {
        let text = r#"{
	"LastExitStatus" = 0;
	"Label" = "com.docwatch.abc123";
};"#;
        assert_eq!(parse_launchctl_list_output(text), JobStatus::Stopped);
    }

    #[test]
    fn parse_launchctl_list_output_stopped_on_empty() {
        assert_eq!(parse_launchctl_list_output(""), JobStatus::Stopped);
    }

    #[test]
    fn write_and_remove_plist_round_trip() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested").join("com.docwatch.x.plist");
        write_plist(&path, "<plist/>").unwrap();
        assert!(path.exists());
        remove_plist(&path).unwrap();
        assert!(!path.exists());
        // Removing again is not an error.
        remove_plist(&path).unwrap();
    }

    #[test]
    fn tail_log_returns_last_n_lines() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("watcher.log");
        fs::write(&path, "l1\nl2\nl3\nl4\nl5\n").unwrap();
        let tail = tail_log(&path, 2).unwrap();
        assert_eq!(tail, vec!["l4".to_string(), "l5".to_string()]);
    }

    #[test]
    fn tail_log_missing_file_returns_empty() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nope.log");
        assert!(tail_log(&path, 5).unwrap().is_empty());
    }

    #[test]
    fn tail_log_handles_utf8_across_block_boundaries() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("watcher.log");
        let prefix = "x".repeat(8190);
        fs::write(&path, format!("{prefix}ø\nsecond\nthird")).unwrap();
        assert_eq!(
            tail_log(&path, 2).unwrap(),
            vec!["second".to_string(), "third".to_string()]
        );
    }

    #[test]
    fn tail_log_preserves_trailing_newline_behavior() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("watcher.log");
        fs::write(&path, "first\nsecond\nthird\n").unwrap();
        assert_eq!(
            tail_log(&path, 2).unwrap(),
            vec!["second".to_string(), "third".to_string()]
        );
    }

    #[test]
    fn tail_log_zero_lines_avoids_opening_file() {
        let dir = tempfile::tempdir().unwrap();
        assert!(
            tail_log(&dir.path().join("missing.log"), 0)
                .unwrap()
                .is_empty()
        );
    }

    #[test]
    fn tail_log_does_not_decode_discarded_history() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("watcher.log");
        let mut bytes = vec![0xff; 9_000];
        bytes.extend_from_slice(b"\nfirst\nsecond\n");
        fs::write(&path, bytes).unwrap();
        assert_eq!(
            tail_log(&path, 2).unwrap(),
            vec!["first".to_string(), "second".to_string()]
        );
    }
}
