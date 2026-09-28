//! `concept update` command handler.

use crate::cli::UpdateArgs;
use crate::commands::error::{CliError, finish, report_error};
use crate::commands::input::read_input;
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::crud::update::update;

pub fn run(args: UpdateArgs) -> Result<()> {
    let bytes = match read_input(args.file.as_deref()) {
        Ok(v) => v,
        Err(err) => return report_error(&CliError(err.to_string()), args.json),
    };
    let guard = match crate::review_checkpoints::begin_crud(&args.bundle, &args.slug) {
        Ok(guard) => guard,
        Err(error) => return crate::review_checkpoints::report_anyhow(&error, args.json),
    };
    if let Err(error) = crate::review_checkpoints::authorize_crud(&guard, &bytes, args.json) {
        return crate::review_checkpoints::report_anyhow(&error, args.json);
    }
    finish(
        update(&args.bundle, &args.slug, &args.expected_version, &bytes),
        args.json,
        |updated| {
            print_success(json!({
                "slug": updated.slug,
                "old_version": updated.old_version,
                "new_version": updated.new_version,
            }))
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
