use crate::cli::ConclusionStatusArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;

pub fn run(args: ConclusionStatusArgs) -> Result<()> {
    let data = match crate::conclusion::status(&args.plan) {
        Ok(data) => data,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if args.json {
        print_success(data)
    } else {
        println!("{}", serde_json::to_string_pretty(&data)?);
        Ok(())
    }
}
