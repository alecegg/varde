//! Native `varde edit` command setup.

use std::ffi::OsString;
use std::fs;
use std::path::PathBuf;
use std::process::ExitCode;

use toz_core::project::Project;
use varde_code::ast_edit::{Options, cli_command, run as run_ast_edit};
use varde_contracts::Io;
use varde_workflow_core::memory::{MemoryPaths, Source};

pub fn run(mut args: Vec<OsString>, io: &Io<'static>) -> ExitCode {
    if let Some(argv0) = args.first_mut() {
        *argv0 = OsString::from("varde edit");
    }
    let matches = match cli_command().try_get_matches_from(args.clone()) {
        Ok(matches) => matches,
        Err(error) => error.exit(),
    };
    let is_preview = matches.subcommand_name() == Some("preview");
    let output_directory = matches
        .subcommand_matches("preview")
        .and_then(|preview| preview.get_one::<PathBuf>("out"))
        .cloned();

    let project = match Project::resolve(None) {
        Ok(project) => project,
        Err(error) => {
            return report_error(&args, "repository_resolution_failed", &error.to_string());
        }
    };
    let repository_root = match fs::canonicalize(&project.root) {
        Ok(root) => root,
        Err(error) => {
            return report_error(
                &args,
                "repository_resolution_failed",
                &format!(
                    "cannot resolve repository root {}: {error}",
                    project.root.display()
                ),
            );
        }
    };
    let store_dir = if let Some(path) = output_directory {
        path
    } else if is_preview {
        match MemoryPaths::resolve(&repository_root) {
            Ok(paths) => proposal_store(&paths),
            Err(error) => {
                return report_error(
                    &args,
                    "working_store_resolution_failed",
                    &format!("cannot resolve proposal working store: {error}"),
                );
            }
        }
    } else {
        PathBuf::new()
    };
    run_ast_edit(
        args,
        &Options {
            repository_root,
            store_dir,
        },
        io,
    )
}

/// Proposals stay out of the repository: an unconfigured (builtin) working
/// store falls back to the varde config root.
fn proposal_store(paths: &MemoryPaths) -> PathBuf {
    if paths.working.source == Source::Builtin
        && let Some(config_root) = paths.config.parent()
    {
        return config_root.join("ast-edit");
    }
    paths.working.path.join("ast-edit")
}

fn report_error(args: &[OsString], code: &str, message: &str) -> ExitCode {
    if args.iter().any(|arg| arg == "--json") {
        println!("{}", varde_core::envelope::tool_error(code, message));
    } else {
        eprintln!("varde edit: {message}");
    }
    ExitCode::FAILURE
}
