use crate::cli::ConclusionActionArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;

pub fn run(args: ConclusionActionArgs) -> Result<()> {
    let (path, content, data) = match crate::conclusion::update_action(
        &args.plan,
        &args.action,
        args.failed,
        args.output.as_deref(),
    ) {
        Ok(result) => result,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if let Err(error) = crate::journal::commit(&path, &content) {
        return report_error(&InternalError(error.to_string()), args.json);
    }
    if args.json {
        print_success(data)
    } else {
        println!("recorded post-conclusion action {}", args.action);
        Ok(())
    }
}
