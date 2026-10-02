use crate::cli::CheckTaskOwnershipArgs;
use crate::commands::error::{ExitCode, report_error};
use crate::output::print_success;
use crate::task_ownership::{self, OwnershipError};
use anyhow::Result;
use std::io::Write;

impl ExitCode for OwnershipError {
    fn error_code(&self) -> &'static str {
        self.code
    }
}

pub fn run(args: CheckTaskOwnershipArgs) -> Result<()> {
    let audit = match task_ownership::check(&args.task, &args.commit, &args.repo_root) {
        Ok(audit) => audit,
        Err(error) => return report_error(&error, args.json),
    };
    if args.json {
        print_success(serde_json::to_value(&audit)?)?;
    } else {
        println!("{}", serde_json::to_string_pretty(&audit)?);
    }
    if audit.status == "stray" {
        std::io::stdout().flush()?;
        std::process::exit(2);
    }
    Ok(())
}
