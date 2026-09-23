//! `concept list` command handler.

use crate::cli::ListArgs;
use crate::commands::common::vault_and_bundle;
use crate::commands::error::finish;
use crate::output::{page_bounds, pagination_meta, print_success_with_meta};
use anyhow::Result;
use okf_core::vault::list_filtered;

pub fn run(args: ListArgs) -> Result<()> {
    let (vault, bundle) = vault_and_bundle(&args);
    finish(
        list_filtered(vault, bundle, args.include_deprecated),
        args.json,
        |concepts| {
            let (start, end) = page_bounds(
                concepts.len(),
                args.page.offset,
                args.page.limit,
                args.page.all,
            );
            print_success_with_meta(
                serde_json::to_value(&concepts[start..end])?,
                pagination_meta(concepts.len(), start, end, args.page.limit, args.page.all),
            )
        },
        |concepts| {
            let (start, end) = page_bounds(
                concepts.len(),
                args.page.offset,
                args.page.limit,
                args.page.all,
            );
            if concepts.is_empty() {
                println!("no concepts in bundle");
            } else {
                for c in &concepts[start..end] {
                    println!("{}\t{}", c.slug, c.type_.as_deref().unwrap_or(""));
                }
                if end < concepts.len() {
                    eprintln!(
                        "showing {} of {} concepts; continue with --offset {}",
                        end - start,
                        concepts.len(),
                        end
                    );
                }
            }
            Ok(())
        },
    )
}
