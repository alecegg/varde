//! `concept update` command handler.

use crate::cli::UpdateArgs;
use crate::commands::error::{finish, report_error, CliError};
use crate::commands::input::read_input;
use anyhow::Result;
use okf_core::crud::update::update;
use serde_json::json;

pub fn run(args: UpdateArgs) -> Result<()> {
    let bytes = match read_input(args.file.as_deref()) {
        Ok(v) => v,
        Err(err) => return report_error(&CliError(err.to_string()), args.json),
    };
    finish(
        update(&args.bundle, &args.slug, &args.expected_version, &bytes),
        args.json,
        |updated| {
            println!(
                "{}",
                json!({
                    "slug": updated.slug,
                    "old_version": updated.old_version,
                    "new_version": updated.new_version,
                })
            );
            Ok(())
        },
        |updated| {
            println!(
                "updated {} (version {} -> {})",
                updated.slug, updated.old_version, updated.new_version
            );
            Ok(())
        },
    )
}
