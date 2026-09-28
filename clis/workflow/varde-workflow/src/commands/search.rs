//! `concept search` command handler.
//!
//! Two composable modes:
//! - `--field key=value` (repeatable): exact-value AND-matching over
//!   frontmatter, unchanged from before `--text` existed.
//! - `--text <QUERY>`: ranked lexical full-text search across bodies and
//!   frontmatter values.
//!
//! Both may be passed together. Field matching and text scoring share one
//! traversal, then `--limit` applies to the filtered, ranked results.

use crate::cli::SearchArgs;
use crate::commands::common::resolve_bundle;
use crate::commands::error::{CliError, InternalError, finish, report_error};
use crate::output::print_success;
use anyhow::Result;
use std::path::Path;
use varde_workflow_core::crud::search::search_text_matching;
use varde_workflow_core::registry;

pub fn run(args: SearchArgs) -> Result<()> {
    let filters = match parse_filters(&args.field) {
        Ok(f) => f,
        Err(err) => return report_error(&err, args.json),
    };
    let bundle = match resolve_bundle(args.bundle.as_deref()) {
        Ok(bundle) => bundle,
        Err(err) => return report_error(&InternalError(err.to_string()), args.json),
    };
    match &args.text {
        Some(query) => run_text(&args, &bundle, query, &filters),
        None => run_field(&args, &bundle, &filters),
    }
}

fn run_field(args: &SearchArgs, bundle: &Path, filters: &[(String, String)]) -> Result<()> {
    let bundles = [bundle.to_path_buf()];
    finish(
        registry::search(&bundles, filters),
        args.json,
        |entries| print_success(serde_json::to_value(entries)?),
        |entries| {
            if entries.is_empty() {
                println!("no concepts match");
            } else {
                for entry in entries {
                    println!("{}\t{}", entry.slug, entry.type_.as_deref().unwrap_or(""));
                }
            }
            Ok(())
        },
    )
}

fn run_text(
    args: &SearchArgs,
    bundle: &Path,
    query: &str,
    filters: &[(String, String)],
) -> Result<()> {
    let bundles = [bundle.to_path_buf()];
    let results = match search_text_matching(&bundles, query, filters, args.limit) {
        Ok(results) => results,
        Err(err) => return report_error(&err, args.json),
    };

    if args.json {
        print_success(serde_json::to_value(&results)?)?;
    } else if results.is_empty() {
        println!("no concepts match");
    } else {
        for result in &results {
            println!(
                "{}\t{}\t{}\t{}",
                result.slug,
                result.type_.as_deref().unwrap_or(""),
                result.score,
                result.preview
            );
        }
    }
    Ok(())
}

/// Parse repeatable `--field key=value` flags into `(key, value)` filter
/// pairs. A flag without `=` is rejected — there is no meaningful way to
/// interpret it as an exact-value filter.
fn parse_filters(fields: &[String]) -> Result<Vec<(String, String)>, CliError> {
    fields
        .iter()
        .map(|field| {
            let (key, value) = field.split_once('=').ok_or_else(|| {
                CliError(format!("invalid --field `{field}`: expected `key=value`"))
            })?;
            if key.is_empty() {
                return Err(CliError(format!(
                    "invalid --field `{field}`: expected `key=value`"
                )));
            }
            Ok((key.to_string(), value.to_string()))
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_filters_splits_key_and_value() {
        let parsed = parse_filters(&["type=decision".into(), "tags=a=b".into()]).unwrap();
        assert_eq!(
            parsed,
            vec![
                ("type".to_string(), "decision".to_string()),
                // Only the first `=` splits; the rest is the value.
                ("tags".to_string(), "a=b".to_string()),
            ]
        );
    }

    #[test]
    fn parse_filters_empty_is_empty() {
        assert_eq!(parse_filters(&[]).unwrap(), Vec::<(String, String)>::new());
    }

    #[test]
    fn parse_filters_rejects_flag_without_equals() {
        let err = parse_filters(&["type".into()]).unwrap_err();
        assert!(err.to_string().contains("expected `key=value`"), "{err}");
    }

    #[test]
    fn parse_filters_rejects_empty_key() {
        // An empty key can never match a real frontmatter field; reject it
        // early rather than silently querying nothing.
        let err = parse_filters(&["=value".into()]).unwrap_err();
        assert!(err.to_string().contains("expected `key=value`"), "{err}");
    }
}
