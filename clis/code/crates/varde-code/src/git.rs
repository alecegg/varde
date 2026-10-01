//! Shared git subprocess helper.
//!
//! Centralizes the "shell out to `git`, any failure -> `None`" contract used
//! by `churn::commit_count` and `query::mapping::git_changed_files`.

use std::io::{self, BufRead, BufReader};
use std::path::Path;
use std::process::{Child, Command, ExitStatus, Stdio};

/// Run `git <args>` from `cwd`. Returns `Some(stdout)` on a successful
/// (exit-0) invocation, `None` on any failure: missing binary, non-repo,
/// or non-zero exit.
pub fn run_git(args: &[&str], cwd: &Path) -> Option<String> {
    let output = std::process::Command::new("git")
        .args(args)
        .current_dir(cwd)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).into_owned())
}

/// Stream NUL-terminated records from `git <args>` in `cwd`.
///
/// The visitor sees each record including its trailing NUL. A read or visitor
/// error aborts the stream; the child is then killed and reaped.
pub(crate) fn run_git_records<F>(args: &[&str], cwd: &Path, mut visit_record: F) -> bool
where
    F: FnMut(&[u8]) -> io::Result<()>,
{
    let mut command = Command::new("git");
    command.args(args).current_dir(cwd);
    run_command_records(&mut command, &mut visit_record).is_some()
}

fn run_command_records<F>(command: &mut Command, visit_record: &mut F) -> Option<ExitStatus>
where
    F: FnMut(&[u8]) -> io::Result<()>,
{
    let mut child = ChildGuard::new(
        command
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .ok()?,
    );
    let stdout = child.child.stdout.take()?;
    let mut reader = BufReader::new(stdout);
    let mut record = Vec::new();

    loop {
        record.clear();
        if reader.read_until(b'\0', &mut record).ok()? == 0 {
            break;
        }
        visit_record(&record).ok()?;
    }

    let status = child.wait().ok()?;
    status.success().then_some(status)
}

struct ChildGuard {
    child: Child,
    reaped: bool,
}

impl ChildGuard {
    fn new(child: Child) -> Self {
        Self {
            child,
            reaped: false,
        }
    }

    fn wait(&mut self) -> io::Result<ExitStatus> {
        let status = self.child.wait()?;
        self.reaped = true;
        Ok(status)
    }
}

impl Drop for ChildGuard {
    fn drop(&mut self) {
        if !self.reaped {
            let _ = self.child.kill();
            let _ = self.child.wait();
            self.reaped = true;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[cfg(unix)]
    unsafe extern "C" {
        fn waitpid(pid: i32, status: *mut i32, options: i32) -> i32;
    }

    #[cfg(unix)]
    #[test]
    fn churn_parse_error_kills_and_reaps_child() {
        let dir = std::env::temp_dir().join(format!("varde-git-stream-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("test dir creates");
        let pid_file = dir.join("child.pid");
        let script = "printf '%s\\n' \"$$\" > \"$1\"; printf 'malformed\\000'; exec sleep 30";
        let mut command = Command::new("sh");
        command.args(["-c", script, "stream-test", pid_file.to_str().unwrap()]);

        let result = run_command_records(&mut command, &mut |record| {
            if record.strip_suffix(b"\0") == Some(b"valid".as_slice()) {
                Ok(())
            } else {
                Err(io::Error::new(
                    io::ErrorKind::InvalidData,
                    "record content is malformed",
                ))
            }
        });

        assert!(result.is_none(), "malformed record should fail the stream");
        let pid: i32 = std::fs::read_to_string(&pid_file)
            .expect("child pid was written")
            .trim()
            .parse()
            .expect("child pid is an integer");
        let mut status = 0;
        let wait_result = unsafe { waitpid(pid, &mut status, 1) };
        assert!(
            wait_result == -1 && io::Error::last_os_error().raw_os_error() == Some(10),
            "child should already be reaped, waitpid returned {wait_result} with {:?}",
            io::Error::last_os_error()
        );
        let _ = std::fs::remove_dir_all(&dir);
    }
}
