use crate::cli::MigrateArgs;
use crate::commands::error::{InternalError, report_error};
use crate::migration;
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;

pub fn run(args: MigrateArgs) -> Result<()> {
    let preview = match migration::preview(&args.artifact) {
        Ok(preview) => preview,
        Err(error) => return report_error(&InternalError(error.to_string()), args.json),
    };
    if args.apply
        && let Err(error) = migration::apply(&preview)
    {
        return report_error(&InternalError(error.to_string()), args.json);
    }
    if args.json {
        let mut data = preview.to_json();
        data["applied"] = json!(args.apply);
        print_success(data)
    } else if args.apply {
        println!("migrated {}", args.artifact.display());
        Ok(())
    } else {
        print!("{}", preview.content);
        Ok(())
    }
}
