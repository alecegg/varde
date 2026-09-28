use crate::cli::ConclusionRetryArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;

pub fn run(args: ConclusionRetryArgs) -> Result<()> {
    let data = match crate::conclusion::retry(&args.plan) {
        Ok(result) => result,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if args.json {
        print_success(data)
    } else {
        println!("post-conclusion actions are pending retry");
        Ok(())
    }
}
