use crate::cli::RecoverArgs;
use crate::commands::error::{InternalError, report_error};
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;

pub fn run(args: RecoverArgs) -> Result<()> {
    let recovered = match crate::journal::recover(&args.root) {
        Ok(recovered) => recovered,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if args.json {
        print_success(json!({ "recovered": recovered, "root": args.root }))
    } else if recovered {
        println!("recovered staged workflow write");
        Ok(())
    } else {
        println!("no staged workflow write found");
        Ok(())
    }
}
