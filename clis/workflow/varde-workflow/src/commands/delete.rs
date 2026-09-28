//! `concept delete` command handler.

use crate::cli::DeleteArgs;
use crate::commands::error::finish;
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::crud::delete::delete;

pub fn run(args: DeleteArgs) -> Result<()> {
    finish(
        delete(&args.bundle, &args.slug),
        args.json,
        |slug| print_success(json!({ "slug": slug, "deleted": true })),
        |slug| {
            println!("deleted {slug}");
            Ok(())
        },
    )
}
