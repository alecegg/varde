//! `concept set-field` command handler.

use crate::cli::SetFieldArgs;
use crate::commands::error::finish;
use crate::output::print_success;
use anyhow::Result;
use serde_json::json;
use varde_workflow_core::crud::set_field;

pub fn run(args: SetFieldArgs) -> Result<()> {
    let guard = match crate::review_checkpoints::begin_crud(&args.bundle, &args.slug) {
        Ok(guard) => guard,
        Err(error) => return crate::review_checkpoints::report_anyhow(&error, args.json),
    };
    if let Some(original) = guard.original_bytes() {
        let proposed =
            match crate::review_checkpoints::preview_set_field(original, &args.key, &args.value) {
                Ok(proposed) => proposed,
                Err(error) => return crate::review_checkpoints::report_anyhow(&error, args.json),
            };
        if let Err(error) = crate::review_checkpoints::authorize_crud(&guard, &proposed, args.json)
        {
            return crate::review_checkpoints::report_anyhow(&error, args.json);
        }
    }
    finish(
        set_field(
            &args.bundle,
            &args.slug,
            &args.expected_version,
            &args.key,
            Some(&args.value),
        ),
        args.json,
        |(old_version, new_version)| {
            print_success(json!({
                "slug": args.slug,
                "key": args.key,
                "value": args.value,
                "old_version": old_version,
                "new_version": new_version,
            }))
        },
        |(old_version, new_version)| {
            println!(
                "set {}={} on {} (version {} -> {})",
                args.key, args.value, args.slug, old_version, new_version
            );
            Ok(())
        },
    )
}
