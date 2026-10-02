use crate::cli::ExecutionWaveArgs;
use crate::commands::error::{CliError, ExitCode, report_error};
use crate::execution_wave::{WaveError, execution_wave};
use crate::execution_wave_tools;
use crate::output::print_success;
use anyhow::Result;
use std::path::PathBuf;

impl ExitCode for WaveError {
    fn exit_code(&self) -> i32 {
        match self {
            Self::Input(_) => 1,
            Self::Cycle => 3,
        }
    }
    fn error_code(&self) -> &'static str {
        match self {
            Self::Input(_) => "invalid_input",
            Self::Cycle => "dependency_cycle",
        }
    }
}

pub fn run(args: ExecutionWaveArgs) -> Result<()> {
    let root = match args.repo_root {
        Some(root) => root,
        None => {
            match execution_wave_tools::git(&args.plan_dir, &["rev-parse", "--show-toplevel"]) {
                Some((0, output)) if !output.trim().is_empty() => PathBuf::from(output.trim()),
                _ => {
                    return report_error(
                        &CliError("cannot discover repository root; pass --repo-root".into()),
                        args.json,
                    );
                }
            }
        }
    };
    let data = match execution_wave(&args.plan_dir, &root, args.max_workers) {
        Ok(data) => data,
        Err(error) => return report_error(&error, args.json),
    };
    if args.json {
        print_success(data)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        Ok(())
    }
}
