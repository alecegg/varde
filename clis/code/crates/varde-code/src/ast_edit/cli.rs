//! Command-line interface for AST edit proposals.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use anyhow::{Context, Result};
use clap::{ArgGroup, Args, CommandFactory, Parser, Subcommand};
use serde_json::{Value, json};
use varde_contracts::Io;
use varde_core::envelope;

use super::{
    ApplyOptions, ApplyStatus, PreviewOptions, PreviewResult, Proposal, RewriteRule, apply, preview,
};

/// App-resolved paths needed by preview and apply.
#[derive(Debug, Clone)]
pub struct Options {
    pub repository_root: PathBuf,
    pub store_dir: PathBuf,
}

#[derive(Debug, Parser)]
#[command(
    name = "varde edit",
    bin_name = "varde edit",
    about = "Preview and apply AST edits",
    arg_required_else_help = true
)]
struct Cli {
    #[command(subcommand)]
    command: EditCommand,
}

#[derive(Debug, Subcommand)]
enum EditCommand {
    /// Build a rewrite proposal without changing source files.
    ///
    /// Directory scopes skip gitignored files; a symlink in a directory scope blocks the preview.
    /// JSON output includes complete, applicable, proposal_id, files,
    /// diagnostics, and paths to the proposal and diff. Apply validates source snapshots before writing.
    /// Failures
    /// are reported per file, so other files can still yield a proposal.
    /// Example: `varde edit preview --language typescript --pattern 'oldCall($ARG)' --replacement 'newCall($ARG)' --path src/ --json`.
    Preview(PreviewArgs),
    /// Apply a saved proposal after validating its source snapshots.
    ///
    /// Example: `varde edit apply --proposal <proposal_path> --json`.
    /// Changed snapshots or symlinked paths fail validation; inspect per-file
    /// diagnostics and preview again against current files. Apply continues
    /// past a failed file and reports each file's outcome.
    Apply(ApplyArgs),
}

#[derive(Debug, Args)]
#[command(group(
    ArgGroup::new("rule_source")
        .args(["rules", "language"])
        .required(true)
        .multiple(false)
))]
struct PreviewArgs {
    /// JSON file containing rewrite rules.
    #[arg(long, value_name = "FILE", conflicts_with_all = ["language", "pattern", "replacement"])]
    rules: Option<PathBuf>,
    /// Language for one inline rewrite rule.
    #[arg(long, value_name = "LANGUAGE", requires_all = ["pattern", "replacement"], conflicts_with = "rules")]
    language: Option<String>,
    /// ast-grep pattern for the inline rule.
    #[arg(
        long,
        value_name = "PATTERN",
        requires = "language",
        conflicts_with = "rules"
    )]
    pattern: Option<String>,
    /// Replacement template for the inline rule.
    #[arg(
        long,
        value_name = "TEXT",
        requires = "language",
        conflicts_with = "rules"
    )]
    replacement: Option<String>,
    /// File or directory to include. Relative paths start at the invoking directory.
    #[arg(long, value_name = "PATH", required = true)]
    path: Vec<PathBuf>,
    /// Directory for the saved proposal and unified diff; defaults to the working store.
    #[arg(long, value_name = "DIR")]
    out: Option<PathBuf>,
    /// Print the versioned JSON envelope.
    #[arg(long)]
    json: bool,
}

#[derive(Debug, Args)]
struct ApplyArgs {
    /// Proposal JSON to validate and apply.
    #[arg(long, value_name = "FILE", required = true)]
    proposal: PathBuf,
    /// Print the versioned JSON envelope.
    #[arg(long)]
    json: bool,
}

/// The command tree for `varde edit`.
pub fn cli_command() -> clap::Command {
    Cli::command()
}

/// Run the `varde edit` command. `args` includes argv0 (`varde edit`).
pub fn run(args: Vec<std::ffi::OsString>, options: &Options, io: &Io<'static>) -> ExitCode {
    if io.capture.is_some() {
        crate::toz::install_capture(io.capture);
    }
    match Cli::parse_from(args).command {
        EditCommand::Preview(args) => run_preview(args, options),
        EditCommand::Apply(args) => run_apply(args, options),
    }
}

fn run_preview(args: PreviewArgs, options: &Options) -> ExitCode {
    let rules = match load_rules(&args) {
        Ok(rules) => rules,
        Err(error) => return report_error("invalid_rules", &format!("{error:#}"), args.json),
    };
    let invoking_cwd = match std::env::current_dir() {
        Ok(path) => path,
        Err(error) => {
            return report_error(
                "invalid_cwd",
                &format!("cannot resolve invoking directory: {error}"),
                args.json,
            );
        }
    };
    let store_dir = args.out.unwrap_or_else(|| options.store_dir.clone());
    let result = match preview(&PreviewOptions {
        repository_root: options.repository_root.clone(),
        invoking_cwd,
        paths: args.path,
        store_dir,
        rules,
    }) {
        Ok(result) => result,
        Err(error) => return report_error("preview_failed", &format!("{error:#}"), args.json),
    };

    let complete = result.complete;
    let applicable = result.applicable;
    let message = result
        .diagnostics
        .iter()
        .find(|diagnostic| diagnostic.blocking)
        .map(|diagnostic| format!("{}: {}", diagnostic.code, diagnostic.message))
        .unwrap_or_else(|| "preview is incomplete".to_string());
    let data = preview_data(&result);
    if args.json {
        if complete {
            println!("{}", envelope::success(data, json!({ "truncated": false })));
        } else {
            println!(
                "{}",
                envelope::negative_result(
                    "preview_incomplete",
                    &message,
                    data,
                    json!({ "truncated": false })
                )
            );
        }
    } else if complete {
        print_preview(&data, result.diff.as_deref(), applicable);
    } else {
        eprintln!("varde edit: {message}");
    }

    if complete {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn load_rules(args: &PreviewArgs) -> Result<Vec<RewriteRule>> {
    if let Some(path) = &args.rules {
        let contents =
            fs::read(path).with_context(|| format!("read rules file {}", path.display()))?;
        return serde_json::from_slice(&contents)
            .with_context(|| format!("parse rules file {} as JSON", path.display()));
    }
    Ok(vec![RewriteRule {
        id: "cli-rule".to_string(),
        language: args.language.clone().unwrap_or_default(),
        pattern: args.pattern.clone().unwrap_or_default(),
        replacement: args.replacement.clone().unwrap_or_default(),
        inside: None,
        has: None,
        precedes: None,
        follows: None,
    }])
}

fn preview_data(result: &PreviewResult) -> Value {
    let files = result
        .proposal
        .as_ref()
        .map(|proposal| {
            proposal
                .files
                .iter()
                .map(|file| {
                    json!({
                        "path": file.path,
                        "replacement_count": file.replacement_count,
                    })
                })
                .collect::<Vec<_>>()
        })
        .unwrap_or_default();
    json!({
        "complete": result.complete,
        "applicable": result.applicable,
        "proposal_id": result.proposal.as_ref().map(|proposal| proposal.id.as_str()),
        "files": files,
        "diagnostics": result.diagnostics,
        "proposal_path": result
            .proposal_path
            .as_ref()
            .map(|path| path.display().to_string()),
        "diff_path": result
            .diff_path
            .as_ref()
            .map(|path| path.display().to_string()),
    })
}

fn print_preview(data: &Value, diff: Option<&str>, applicable: bool) {
    if let Some(diff) = diff {
        print!("{diff}");
    } else if !applicable {
        println!("varde edit: no applicable edits");
    }
    for diagnostic in data["diagnostics"].as_array().into_iter().flatten() {
        let level = if diagnostic["blocking"] == true {
            "error"
        } else {
            "warning"
        };
        eprintln!(
            "varde edit: {level}: {}: {}",
            diagnostic["code"].as_str().unwrap_or("diagnostic"),
            diagnostic["message"]
                .as_str()
                .unwrap_or("unknown diagnostic")
        );
    }
    if let Some(path) = data["proposal_path"].as_str() {
        println!("Proposal: {path}");
    }
}

fn run_apply(args: ApplyArgs, options: &Options) -> ExitCode {
    let proposal = match read_proposal(&args.proposal) {
        Ok(proposal) => proposal,
        Err(error) => return report_error("invalid_proposal", &format!("{error:#}"), args.json),
    };
    let result = match apply(
        &proposal,
        &ApplyOptions {
            repository_root: options.repository_root.clone(),
        },
    ) {
        Ok(result) => result,
        Err(error) => return report_error("apply_failed", &format!("{error:#}"), args.json),
    };
    let successful = result.files.iter().all(|file| file.is_applied());
    let message = result
        .files
        .iter()
        .find_map(|file| match &file.status {
            ApplyStatus::Applied => None,
            ApplyStatus::SourceChanged { message } | ApplyStatus::WriteFailed { message } => {
                Some(format!("{}: {message}", file.path))
            }
        })
        .unwrap_or_default();
    let data = json!({
        "proposal_id": result.proposal_id,
        "files": result.files.iter().map(|file| {
            let (status, detail) = match &file.status {
                ApplyStatus::Applied => ("applied", Value::Null),
                ApplyStatus::SourceChanged { message } => ("source_changed", json!(message)),
                ApplyStatus::WriteFailed { message } => ("write_failed", json!(message)),
            };
            json!({ "path": file.path, "status": status, "detail": detail })
        }).collect::<Vec<_>>(),
    });
    if args.json {
        if successful {
            println!("{}", envelope::success(data, json!({ "truncated": false })));
        } else {
            println!(
                "{}",
                envelope::negative_result(
                    "apply_incomplete",
                    &message,
                    data,
                    json!({ "truncated": false })
                )
            );
        }
    } else {
        for file in &result.files {
            match &file.status {
                ApplyStatus::Applied => println!("Applied {}", file.path),
                ApplyStatus::SourceChanged { message } | ApplyStatus::WriteFailed { message } => {
                    eprintln!("varde edit: {}: {message}", file.path);
                }
            }
        }
    }
    if successful {
        ExitCode::SUCCESS
    } else {
        ExitCode::FAILURE
    }
}

fn read_proposal(path: &Path) -> Result<Proposal> {
    let contents = fs::read(path).with_context(|| format!("read proposal {}", path.display()))?;
    serde_json::from_slice(&contents).with_context(|| format!("parse proposal {}", path.display()))
}

fn report_error(code: &str, message: &str, json_output: bool) -> ExitCode {
    if json_output {
        println!("{}", envelope::tool_error(code, message));
    } else {
        eprintln!("varde edit: {message}");
    }
    ExitCode::FAILURE
}

#[cfg(test)]
mod tests {
    use super::cli_command;

    #[test]
    fn apply_help_describes_per_file_continuation() {
        let help = cli_command()
            .find_subcommand_mut("apply")
            .expect("apply subcommand exists")
            .render_long_help()
            .to_string();
        assert!(help.contains("continues past a failed file"));
        assert!(help.contains("reports each file's outcome"));
    }

    #[test]
    fn preview_help_describes_directory_scope_behavior() {
        let help = cli_command()
            .find_subcommand_mut("preview")
            .expect("preview subcommand exists")
            .render_long_help()
            .to_string();
        assert!(help.contains("Directory scopes skip gitignored files"));
        assert!(help.contains("a symlink in a directory scope blocks the preview"));
    }

    #[test]
    fn apply_summary_stays_short() {
        let mut command = cli_command();
        let about = command
            .find_subcommand_mut("apply")
            .expect("apply subcommand exists")
            .get_about()
            .expect("apply summary exists");
        assert_eq!(about.to_string(), "Apply a saved proposal after validating its source snapshots");
    }
}
