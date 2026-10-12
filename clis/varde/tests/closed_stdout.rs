//! A closed stdout (`varde ... | head`) must end quietly with status 0.

use std::process::{Command, Stdio};

fn assert_quiet_exit_with_closed_stdout(args: &[&str]) {
    let (reader, writer) = std::io::pipe().expect("pipe");
    drop(reader); // closed before the child writes its first byte
    let output = Command::new(env!("CARGO_BIN_EXE_varde"))
        .args(args)
        .stdout(Stdio::from(writer))
        .stderr(Stdio::piped())
        .output()
        .expect("spawn varde");
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(!stderr.contains("panicked"), "{args:?}: {stderr}");
    assert_eq!(output.status.code(), Some(0), "{args:?}: {stderr}");
}

#[test]
fn routed_help_exits_quietly() {
    assert_quiet_exit_with_closed_stdout(&["map", "--help"]);
}

#[test]
fn json_output_exits_quietly() {
    assert_quiet_exit_with_closed_stdout(&["setup", "paths", "--json"]);
}
