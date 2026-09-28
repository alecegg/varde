//! `concept list` command handler.

use crate::cli::ListArgs;
use crate::commands::common::resolve_bundle;
use crate::commands::error::{InternalError, finish, report_error};
use crate::output::{page_bounds, pagination_meta, print_success_with_meta};
use anyhow::Result;
use varde_workflow_core::crud::list::list;

pub fn run(args: ListArgs) -> Result<()> {
    let bundle = match resolve_bundle(args.bundle.as_deref()) {
        Ok(bundle) => bundle,
        Err(err) => return report_error(&InternalError(err.to_string()), args.json),
    };
    finish(
        list(&bundle, args.include_deprecated),
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
