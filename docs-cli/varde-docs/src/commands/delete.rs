//! `concept delete` command handler.

use crate::cli::DeleteArgs;
use crate::commands::error::finish;
use anyhow::Result;
use okf_core::crud::delete::delete;
use serde_json::json;

pub fn run(args: DeleteArgs) -> Result<()> {
    finish(
        delete(&args.bundle, &args.slug),
        args.json,
        |slug| {
            println!("{}", json!({ "slug": slug, "deleted": true }));
            Ok(())
        },
        |slug| {
            println!("deleted {slug}");
            Ok(())
        },
    )
}
