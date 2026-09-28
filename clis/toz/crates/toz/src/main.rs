#![cfg_attr(not(unix), allow(unused))]
#[cfg(not(unix))]
compile_error!("toz supports macOS and Linux only (process groups, isatty, and hook plumbing are Unix-specific)");

mod cli;
mod commands;
mod diagnostics;
mod exec;
mod install;
mod machine;
mod sandbox;
mod worker;

use clap::Parser;

fn main() {
    if std::env::args_os().nth(1).as_deref() == Some(std::ffi::OsStr::new("__worker")) {
        match worker::worker_main() {
            Ok(code) => std::process::exit(code),
            Err(error) => {
                eprintln!("toz worker: {error:#}");
                std::process::exit(2);
            }
        }
    }
    let args = cli::Cli::parse();
    // Hook mode must never fail the harness: a non-zero exit from a Claude Code PostToolUse hook
    // is reported to the model, which is worse than silently passing the original output through.
    let hook_mode = matches!(&args.cmd, cli::Command::Capture(a) if a.hook);
    let hook_harness = match &args.cmd {
        cli::Command::Capture(a) if a.hook => a.harness.clone(),
        _ => String::new(),
    };
    let result = if hook_mode {
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| commands::dispatch(args)))
            .unwrap_or_else(|_| Err(anyhow::anyhow!("panic inside hook")))
    } else {
        commands::dispatch(args)
    };
    match result {
        Ok(_) if hook_mode => std::process::exit(0),
        Ok(code) => std::process::exit(code),
        Err(e) if hook_mode => {
            commands::log_hook_error(&e, &hook_harness);
            std::process::exit(0);
        }
        Err(e) => {
            eprintln!("varde-toz: {e:#}");
            std::process::exit(2);
        }
    }
}
