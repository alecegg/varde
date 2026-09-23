//! `concept update` command handler.

use crate::cli::UpdateArgs;
use crate::commands::error::{CliError, finish, report_error};
use crate::commands::input::read_input;
use crate::output::print_success;
use anyhow::Result;
use okf_core::crud::update::update;
use serde_json::json;

pub fn run(args: UpdateArgs) -> Result<()> {
    crate::migration::enforce_concept_migration(&args.bundle, &args.slug, args.json)?;
    let bytes = match read_input(args.file.as_deref()) {
        Ok(v) => v,
        Err(err) => return report_error(&CliError(err.to_string()), args.json),
    };
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
