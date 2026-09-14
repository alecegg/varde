//! CLI argument parsing (clap derive).

use clap::{Args, Parser, Subcommand};
use std::path::PathBuf;

#[derive(Debug, Parser)]
#[command(
    name = "docwatch",
    version,
    about = "In-doc agent orchestrator: watches documents and dispatches agents on change"
)]
pub struct Cli {
    #[command(subcommand)]
    pub command: Command,
}

#[derive(Debug, Subcommand)]
pub enum Command {
    /// Register a document (or watch target) for watching
    Add(AddArgs),
    /// Stop watching a previously registered document
    Remove(RemoveArgs),
    /// List currently watched documents
    List(ListArgs),
    /// Show watcher status
    Status(StatusArgs),
    /// Tail the watcher's log file
    Logs(LogsArgs),
    /// Internal: run the background watcher loop (not for direct use)
    #[command(name = "_run-watcher", hide = true)]
    RunWatcher(RunWatcherArgs),
}

#[derive(Debug, Args)]
pub struct AddArgs {
    /// Path to the document to watch
    pub path: PathBuf,
}

#[derive(Debug, Args)]
pub struct RemoveArgs {
    /// Path to the document to stop watching
    pub path: PathBuf,
}

#[derive(Debug, Args)]
pub struct ListArgs {
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct StatusArgs {
    /// Path to the watched folder, or a registered watcher id
    pub path: PathBuf,
    /// Machine-readable JSON output
    #[arg(long)]
    pub json: bool,
}

#[derive(Debug, Args)]
pub struct LogsArgs {
    /// Path to the watched folder, or a registered watcher id
    pub path: PathBuf,
    /// Number of trailing log lines to print
    #[arg(short = 'n', long, default_value_t = 50)]
    pub lines: usize,
}

#[derive(Debug, Args)]
pub struct RunWatcherArgs {
    /// Folder to watch (matches the `add`ed folder)
    #[arg(long)]
    pub folder: PathBuf,
    /// Registered watcher id (used for the log directory / lock namespace)
    #[arg(long)]
    pub id: String,
}

#[cfg(test)]
mod tests {
    use super::*;
    use clap::Parser;

    fn parse_cli(args: &[&str]) -> Cli {
        Cli::try_parse_from(args).unwrap()
    }

    #[test]
    fn add_parses_path() {
        let cli = parse_cli(&["docwatch", "add", "docs/foo.md"]);
        let Command::Add(args) = cli.command else {
            panic!("expected add");
        };
        assert_eq!(args.path, PathBuf::from("docs/foo.md"));
    }

    #[test]
    fn remove_parses_path() {
        let cli = parse_cli(&["docwatch", "remove", "docs/foo.md"]);
        let Command::Remove(args) = cli.command else {
            panic!("expected remove");
        };
        assert_eq!(args.path, PathBuf::from("docs/foo.md"));
    }

    #[test]
    fn list_parses() {
        let cli = parse_cli(&["docwatch", "list"]);
        assert!(matches!(cli.command, Command::List(_)));
    }

    #[test]
    fn status_parses() {
        let cli = parse_cli(&["docwatch", "status", "docs/foo.md"]);
        let Command::Status(args) = cli.command else {
            panic!("expected status");
        };
        assert_eq!(args.path, PathBuf::from("docs/foo.md"));
    }

    #[test]
    fn logs_parses_with_default_lines() {
        let cli = parse_cli(&["docwatch", "logs", "docs/foo.md"]);
        let Command::Logs(args) = cli.command else {
            panic!("expected logs");
        };
        assert_eq!(args.path, PathBuf::from("docs/foo.md"));
        assert_eq!(args.lines, 50);
    }

    #[test]
    fn logs_parses_custom_line_count() {
        let cli = parse_cli(&["docwatch", "logs", "docs/foo.md", "-n", "10"]);
        let Command::Logs(args) = cli.command else {
            panic!("expected logs");
        };
        assert_eq!(args.lines, 10);
    }

    #[test]
    fn run_watcher_parses_and_is_hidden() {
        let cli = parse_cli(&["docwatch", "_run-watcher", "--folder", "docs", "--id", "abc123"]);
        let Command::RunWatcher(args) = cli.command else {
            panic!("expected _run-watcher");
        };
        assert_eq!(args.folder, PathBuf::from("docs"));
        assert_eq!(args.id, "abc123");
    }
}
