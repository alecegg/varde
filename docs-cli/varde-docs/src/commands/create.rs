//! `concept create` command handler.

use crate::cli::CreateArgs;
use crate::commands::error::{CliError, finish, report_error};
use crate::commands::input::read_input;
use anyhow::Result;
use okf_core::concept::slug_from_filename;
use okf_core::crud::create::create;
use serde_json::json;

pub fn run(args: CreateArgs) -> Result<()> {
    let (slug, bytes) = match resolve_slug_and_bytes(&args) {
        Ok(v) => v,
        Err(err) => return report_error(&err, args.json),
    };
    finish(
        create(&args.bundle, &bytes, &slug),
        args.json,
        |created| {
            println!("{}", json!({ "slug": created.slug, "version": created.version }));
            Ok(())
        },
        |created| {
            println!("created {} (version {})", created.slug, created.version);
            Ok(())
        },
    )
}

/// Read the concept document from `--file` (slug derived from filename) or
/// stdin (slug passed positionally).
fn resolve_slug_and_bytes(args: &CreateArgs) -> Result<(String, Vec<u8>), CliError> {
    match (args.file.as_deref(), args.slug.as_deref()) {
        (Some(path), None) => {
            let name = path
                .file_name()
                .and_then(|n| n.to_str())
                .ok_or_else(|| CliError("input file name must be UTF-8".to_string()))?;
            let slug = slug_from_filename(name).ok_or_else(|| {
                CliError("input file must be named `<slug>.md` (kebab-case slug)".to_string())
            })?;
            let bytes = read_input(args.file.as_deref()).map_err(|e| CliError(e.to_string()))?;
            Ok((slug.to_string(), bytes))
        }
        (None, Some(slug)) => {
            let bytes = read_input(None).map_err(|e| CliError(e.to_string()))?;
            Ok((slug.to_string(), bytes))
        }
        _ => Err(CliError("concept create requires exactly one of `--file <path>` or a positional <slug> with the document on stdin".to_string())),
    }
}
