use crate::cli::CheckTaskOwnershipArgs;
use crate::commands::error::{ExitCode, report_error, report_failure_with_fix};
use crate::output::{Fix, print_success};
use crate::task_ownership::{self, OwnershipError};
use anyhow::Result;

impl ExitCode for OwnershipError {
    fn error_code(&self) -> &'static str {
        self.code
    }
}

pub fn run(args: CheckTaskOwnershipArgs) -> Result<()> {
    let audit = match task_ownership::check(
        &args.task,
        &args.commit,
        &args.repo_root,
        &args.trusted_tips,
    ) {
        Ok(audit) => audit,
        Err(error) => return report_error(&error, args.json),
    };
    if audit.status == "stray" {
        let message = format!(
            "task ownership found stray paths: {}",
            audit.stray.join(", ")
        );
        let fix = Fix::no_command(
            "add each stray path to the task's `owns:` or the plan's `shared:`, then rerun check-task-ownership",
        );
        return report_failure_with_fix(
            "ownership_stray",
            2,
            &message,
            serde_json::to_value(&audit)?,
            &fix,
            args.json,
        );
    }
    if audit.status == "invalid" {
        let message = format!(
            "task ownership has invalid paths: {}",
            audit.blockers.join(", ")
        );
        let fix = Fix::no_command(
            "correct each invalid path or ownership declaration, then rerun plan validate and check-task-ownership",
        );
        return report_failure_with_fix(
            "ownership_invalid",
            2,
            &message,
            serde_json::to_value(&audit)?,
            &fix,
            args.json,
        );
    }
    if args.json {
        print_success(serde_json::to_value(&audit)?)?;
    } else {
        println!("{}", serde_json::to_string_pretty(&audit)?);
    }
    Ok(())
}
