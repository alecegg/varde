use crate::cli::ConcludeArgs;
use crate::commands::error::report_error;
use crate::conclusion;
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;

pub fn run(args: ConcludeArgs) -> Result<()> {
    match conclusion::conclude(&args.plan, args.merged.as_deref(), args.repo.as_deref()) {
        Ok(result) => {
            if args.json {
                print_success(json!({
                    "plan_id": result.id,
                    "reviewed_head": result.head,
                }))
            } else {
                println!("concluded {}", result.id);
                Ok(())
            }
        }
        Err(error) => report_error(&error, args.json),
    }
}
