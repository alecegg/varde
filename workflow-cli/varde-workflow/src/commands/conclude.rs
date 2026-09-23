use crate::cli::ConcludeArgs;
use crate::commands::error::{InternalError, report_error};
use crate::conclusion;
use crate::output::{print_failure, print_success};
use anyhow::Result;
use serde_json::json;

pub fn run(args: ConcludeArgs) -> Result<()> {
    let prepared = match conclusion::prepare(&args.plan) {
        Ok(prepared) => prepared,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if let Err(error) = crate::journal::commit_many(&prepared.memory, &prepared.writes) {
        return report_error(&InternalError(error.to_string()), args.json);
    }
    let data = prepared.to_json();
    if let Some(action) = std::env::var_os("VARDE_WORKFLOW_FAIL_POST_ACTION") {
        let action = action.to_string_lossy().to_string();
        if let Err(error) =
            conclusion::mark_post_failure(&prepared.memory, &prepared.plan_id, &action)
        {
            return report_error(&InternalError(error.to_string()), args.json);
        }
        if args.json {
            print_failure(
                "post_conclusion_failed",
                "core conclusion committed; qualitative enrichment failed",
                json!({ "conclusion": data, "failed_action": action }),
            );
        } else {
            eprintln!("core conclusion committed; qualitative enrichment failed: {action}");
        }
        std::process::exit(1);
    }
    if args.json {
        print_success(data)
    } else {
        println!("concluded {}", prepared.plan_id);
        Ok(())
    }
}
