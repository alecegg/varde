//! `concept list` command handler.

use crate::cli::ListArgs;
use crate::commands::common::vault_and_bundle;
use crate::commands::error::finish;
use anyhow::Result;
use okf_core::vault::list_filtered;

pub fn run(args: ListArgs) -> Result<()> {
    let (vault, bundle) = vault_and_bundle(&args);
    finish(
        list_filtered(vault, bundle, args.include_deprecated),
        args.json,
        |concepts| {
            println!("{}", serde_json::to_string(concepts)?);
            Ok(())
        },
        |concepts| {
            if concepts.is_empty() {
                println!("no concepts in bundle");
            } else {
                for c in concepts {
                    println!("{}\t{}", c.slug, c.type_.as_deref().unwrap_or(""));
                }
            }
            Ok(())
        },
    )
}
