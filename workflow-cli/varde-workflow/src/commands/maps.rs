//! `concept map` command handler.

use crate::cli::MapArgs;
use crate::commands::error::finish;
use crate::output::print_success;
use anyhow::Result;
use okf_core::maps::generate;
use serde_json::to_value;

pub fn run(args: MapArgs) -> Result<()> {
    finish(
        generate(&args.bundle),
        args.json,
        |maps| print_success(to_value(maps)?),
        |maps| {
            println!(
                "generated {} entries in {} and {} type maps",
                maps.entries,
                maps.root,
                maps.type_maps.len()
            );
            Ok(())
        },
    )
}
