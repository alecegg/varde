//! Bounded read-only queries (git subprocesses and the impact contract). Failure remains unknown reach.
use crate::commands::hook::within;
use crate::execution_wave_paths::canonical_path;
use std::collections::BTreeSet;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc;
use std::time::{Duration, Instant};
use varde_contracts::ImpactQuery;

const TIMEOUT: Duration = Duration::from_secs(120);
const OUTPUT_LIMIT: u64 = 16 * 1024 * 1024;

fn run_timeout(command: &mut Command, timeout: Duration) -> Option<(i32, String)> {
    let mut child = command
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let stdout = child.stdout.take()?;
    let (sender, receiver) = mpsc::channel();
    std::thread::spawn(move || {
        let mut bytes = Vec::new();
        let result = stdout.take(OUTPUT_LIMIT + 1).read_to_end(&mut bytes);
        let value = result
            .ok()
            .filter(|_| bytes.len() as u64 <= OUTPUT_LIMIT)
            .and_then(|_| String::from_utf8(bytes).ok());
        let _ = sender.send(value);
    });
    let deadline = Instant::now() + timeout;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if Instant::now() < deadline => std::thread::sleep(Duration::from_millis(10)),
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                return None;
            }
        }
    };
    let remaining = deadline.saturating_duration_since(Instant::now());
    let output = receiver.recv_timeout(remaining).ok()??;
    Some((status.code()?, output))
}

pub fn git(root: &Path, args: &[&str]) -> Option<(i32, String)> {
    run_timeout(Command::new("git").arg("-C").arg(root).args(args), TIMEOUT)
}

pub fn blast_radius(
    impact: &'static dyn ImpactQuery,
    root: &Path,
    path: &str,
) -> Option<Vec<String>> {
    let (query_root, file) = (root.to_path_buf(), PathBuf::from(path));
    let found = within(TIMEOUT, move || impact.dependents(&query_root, &file)).ok()??;
    found
        .iter()
        .map(|value| canonical_path(root, value.to_str()?).ok())
        .collect()
}

fn grep(root: &Path, pattern: &str) -> Option<Vec<String>> {
    let (status, stdout) = git(root, &["grep", "-l", "-F", "--", pattern])?;
    match status {
        1 => Some(Vec::new()),
        0 => stdout
            .lines()
            .filter(|line| !line.is_empty())
            .map(|line| canonical_path(root, line).ok())
            .collect(),
        _ => None,
    }
}

pub fn basename_references(root: &Path, path: &str) -> Option<Vec<String>> {
    let basename = Path::new(path).file_name()?.to_str()?;
    let (status, tracked) = git(root, &["ls-files", "-z"])?;
    if status != 0 {
        return None;
    }
    let duplicates = tracked
        .split('\0')
        .filter(|file| Path::new(file).file_name().and_then(|name| name.to_str()) == Some(basename))
        .count()
        > 1;
    let references = grep(root, basename)?;
    if !duplicates {
        return Some(references);
    }
    let mut exact: BTreeSet<String> = grep(root, path)?.into_iter().collect();
    if let Some(parent) = Path::new(path)
        .parent()
        .and_then(Path::parent)
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        let prefix = format!("{}/", parent.to_str()?);
        exact.extend(
            references
                .into_iter()
                .filter(|file| file.starts_with(&prefix)),
        );
    }
    Some(exact.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn timeout_kills_child_without_waiting_for_inherited_pipe() {
        let started = Instant::now();
        assert!(
            run_timeout(
                Command::new("sh").args(["-c", "sleep 2"]),
                Duration::from_millis(30)
            )
            .is_none()
        );
        assert!(started.elapsed() < Duration::from_secs(1));
    }
}
