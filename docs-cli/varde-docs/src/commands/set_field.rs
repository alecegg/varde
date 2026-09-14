//! `concept set-field` command handler.

use crate::cli::SetFieldArgs;
use crate::commands::error::finish;
use anyhow::Result;
use okf_core::crud::set_field;
use serde_json::json;

pub fn run(args: SetFieldArgs) -> Result<()> {
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
            println!(
                "{}",
                json!({
                    "slug": args.slug,
                    "key": args.key,
                    "value": args.value,
                    "old_version": old_version,
                    "new_version": new_version,
                })
            );
            Ok(())
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
