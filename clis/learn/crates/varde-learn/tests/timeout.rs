//! Tests for `varde_learn_core::run_with_timeout`, porting the process-group
//! and deadline behavior of `skills/eval-tools/claude-timeout.pl`.

use std::path::Path;
use std::time::Duration;

use tempfile::{TempDir, tempdir};
use varde_learn_core::{ExitResult, RunOutcome, RunRequest, run_with_timeout};

/// POSIX `SIGTERM`, stable across every Unix this crate targets.
const SIGTERM: i32 = 15;

/// Runs `script` under `sh -c`, writing stdout/stderr into `dir`.
fn run_sh(dir: &Path, script: &str, timeout: Duration) -> RunOutcome {
    run_sh_with_input(dir, script, timeout, &[])
}

fn run_sh_with_input(dir: &Path, script: &str, timeout: Duration, stdin: &[u8]) -> RunOutcome {
    let stdout_path = dir.join("stdout");
    let stderr_path = dir.join("stderr");
    let args = vec!["-c".to_string(), script.to_string()];
    let req = RunRequest {
        program: "sh",
        args: &args,
        cwd: None,
        env: &[],
        stdin,
        stdout_path: &stdout_path,
        stderr_path: &stderr_path,
        timeout,
    };
    run_with_timeout(&req).expect("run_with_timeout")
}

/// Whether any process remains in process group `pgid`, probed with the
/// `kill` shell builtin (`-0` sends no signal, just checks existence) so
/// this test crate does not need a direct `libc` dependency of its own.
fn group_alive(pgid: i32) -> bool {
    std::process::Command::new("sh")
        .arg("-c")
        .arg(format!("kill -0 -{pgid} 2>/dev/null"))
        .status()
        .map(|status| status.success())
        .unwrap_or(false)
}

#[test]
fn timeout_kills_group_with_no_survivor() {
    let dir: TempDir = tempdir().expect("tempdir");
    let pgid_path = dir.path().join("pgid");

    // The child writes its own pid (== its process group id, since it is
    // the group leader under `process_group(0)`) before backgrounding two
    // descendants that would otherwise outlive a 150 ms deadline by ~30s.
    let script = format!(
        "echo $$ > {pgid} && sleep 30 & sleep 30",
        pgid = pgid_path.display()
    );

    let start = std::time::Instant::now();
    let outcome = run_sh(dir.path(), &script, Duration::from_millis(150));
    let elapsed = start.elapsed();

    assert_eq!(outcome, RunOutcome::TimedOut);
    assert!(
        elapsed < Duration::from_secs(2),
        "expected the group to be killed well before the 30s sleeps finished, took {elapsed:?}"
    );

    let pgid: i32 = std::fs::read_to_string(&pgid_path)
        .expect("pgid file")
        .trim()
        .parse()
        .expect("pgid is a number");
    assert!(
        !group_alive(pgid),
        "process group {pgid} still has a live member after timeout"
    );
}

#[test]
fn successful_leader_exit_kills_remaining_group_members() {
    let dir: TempDir = tempdir().expect("tempdir");
    let pgid_path = dir.path().join("pgid");
    let script = format!(
        "echo $$ > {pgid}; sleep 30 & exit 0",
        pgid = pgid_path.display()
    );

    let start = std::time::Instant::now();
    let outcome = run_sh(dir.path(), &script, Duration::from_secs(5));
    let elapsed = start.elapsed();

    assert_eq!(outcome, RunOutcome::Completed(ExitResult::Code(0)));
    assert!(
        elapsed < Duration::from_secs(2),
        "successful leader cleanup took unexpectedly long: {elapsed:?}"
    );
    let pgid: i32 = std::fs::read_to_string(&pgid_path)
        .expect("pgid file")
        .trim()
        .parse()
        .expect("pgid is a number");
    assert!(
        !group_alive(pgid),
        "process group {pgid} still has a member after successful leader exit"
    );
}

#[test]
fn timeout_covers_large_stdin_to_nonreader() {
    let dir = tempdir().unwrap();
    let pgid_path = dir.path().join("pgid");
    let script = format!("echo $$ > {}; sleep 3", pgid_path.display());
    let start = std::time::Instant::now();
    let outcome = run_sh_with_input(
        dir.path(),
        &script,
        Duration::from_millis(150),
        &vec![b'x'; 1024 * 1024],
    );
    let elapsed = start.elapsed();
    let pgid: i32 = std::fs::read_to_string(&pgid_path)
        .unwrap()
        .trim()
        .parse()
        .unwrap();
    assert_eq!(outcome, RunOutcome::TimedOut);
    assert!(
        elapsed < Duration::from_secs(2),
        "blocked input exceeded deadline: {elapsed:?}"
    );
    assert!(!group_alive(pgid), "nonreader group survived timeout");
}

#[test]
fn large_stdin_is_delivered_completely_and_closed() {
    let dir = tempdir().unwrap();
    let input = vec![b'x'; 2 * 1024 * 1024];
    let outcome = run_sh_with_input(dir.path(), "cat", Duration::from_secs(5), &input);
    assert_eq!(outcome, RunOutcome::Completed(ExitResult::Code(0)));
    assert_eq!(std::fs::read(dir.path().join("stdout")).unwrap(), input);
}

#[test]
fn early_exit_with_large_stdin_preserves_exit_status() {
    let dir = tempdir().unwrap();
    let outcome = run_sh_with_input(
        dir.path(),
        "exit 3",
        Duration::from_secs(5),
        &vec![b'x'; 1024 * 1024],
    );
    assert_eq!(outcome, RunOutcome::Completed(ExitResult::Code(3)));
}

#[test]
fn stdin_interruption_helper() {
    let Some(dir) = std::env::var_os("VARDE_TEST_STDIN_INTERRUPT") else {
        return;
    };
    let dir = std::path::PathBuf::from(dir);
    let script = format!("echo $$ > {}; sleep 30", dir.join("pgid").display());
    run_sh_with_input(
        &dir,
        &script,
        Duration::from_secs(30),
        &vec![b'x'; 1024 * 1024],
    );
}

#[test]
fn interruption_during_stdin_delivery_kills_child_group() {
    use std::os::unix::process::ExitStatusExt;
    use std::process::{Child, Command, Stdio};

    struct Helper {
        child: Child,
        pgid_path: std::path::PathBuf,
    }
    impl Drop for Helper {
        fn drop(&mut self) {
            if let Ok(pgid) = std::fs::read_to_string(&self.pgid_path)
                && let Ok(pgid) = pgid.trim().parse::<i32>()
            {
                let _ = Command::new("sh")
                    .args(["-c", &format!("kill -KILL -{pgid} 2>/dev/null")])
                    .status();
            }
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }

    let dir = tempdir().unwrap();
    let pgid_path = dir.path().join("pgid");
    let mut helper = Helper {
        child: Command::new(std::env::current_exe().unwrap())
            .args(["--exact", "stdin_interruption_helper", "--nocapture"])
            .env("VARDE_TEST_STDIN_INTERRUPT", dir.path())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .unwrap(),
        pgid_path,
    };
    let deadline = std::time::Instant::now() + Duration::from_secs(5);
    let pgid: i32 = loop {
        if let Ok(text) = std::fs::read_to_string(&helper.pgid_path)
            && let Ok(pgid) = text.trim().parse()
        {
            break pgid;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "helper did not start child"
        );
        std::thread::sleep(Duration::from_millis(20));
    };
    assert!(
        Command::new("sh")
            .args(["-c", &format!("kill -TERM {}", helper.child.id())])
            .status()
            .unwrap()
            .success()
    );
    let status = loop {
        if let Some(status) = helper.child.try_wait().unwrap() {
            break status;
        }
        assert!(
            std::time::Instant::now() < deadline,
            "interrupted helper did not exit"
        );
        std::thread::sleep(Duration::from_millis(20));
    };
    assert_eq!(status.signal(), Some(SIGTERM));
    while group_alive(pgid) && std::time::Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(20));
    }
    assert!(
        !group_alive(pgid),
        "child group survived caller interruption"
    );
}

#[test]
fn timeout_normal_exit_status_propagates() {
    let dir = tempdir().expect("tempdir");
    let outcome = run_sh(dir.path(), "exit 3", Duration::from_secs(5));
    assert_eq!(outcome, RunOutcome::Completed(ExitResult::Code(3)));
}

#[test]
fn timeout_signal_death_reports_128_plus_signal() {
    let dir = tempdir().expect("tempdir");
    let outcome = run_sh(dir.path(), "kill -TERM $$", Duration::from_secs(5));
    match outcome {
        RunOutcome::Completed(ExitResult::Signal(signal)) => {
            assert_eq!(signal, SIGTERM);
            assert_eq!(ExitResult::Signal(signal).as_shell_code(), 128 + SIGTERM);
        }
        other => panic!("expected a SIGTERM death, got {other:?}"),
    }
}
