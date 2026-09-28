//! Build child commands inside the sandboxed QuickJS worker.

use std::process::Command;

pub fn build_argv_command(argv: &[String]) -> Command {
    let mut command = Command::new(&argv[0]);
    command.args(&argv[1..]);
    command
}

pub fn build_shell_command(script: &str) -> Command {
    let shell = std::env::var("SHELL").unwrap_or_else(|_| "/bin/sh".into());
    let mut command = Command::new(shell);
    command.arg("-c").arg(script);
    command
}
