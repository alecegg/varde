//! `concept search` command handler.
//!
//! Two composable modes:
//! - `--field key=value` (repeatable): exact-value AND-matching over
//!   frontmatter, unchanged from before `--text` existed.
//! - `--text <QUERY>`: ranked lexical full-text search across bodies and
//!   frontmatter values.
//!
//! Both may be passed together: `--field` narrows to exact matches first
//! (via [`search_filtered`]), then `--text` ranks/filters that narrowed set
//! (via [`search_text_filtered`]) — the full-text ranking still runs over
//! every Concept so relative scores are meaningful, but only slugs also
//! present in the `--field` match set are kept, and `--limit` is applied to
//! that final, filtered/ranked list.

use crate::cli::SearchArgs;
use crate::commands::common::vault_and_bundle;
use crate::commands::error::{CliError, finish, report_error};
use anyhow::Result;
use okf_core::vault::{VaultSelector, search_filtered, search_text_filtered};
use std::path::Path;

pub fn run(args: SearchArgs) -> Result<()> {
    let filters = match parse_filters(&args.field) {
        Ok(f) => f,
        Err(err) => return report_error(&err, args.json),
    };
    let (vault, bundle) = vault_and_bundle(&args);
    match &args.text {
        Some(query) => run_text(&args, vault, bundle, query, &filters),
        None => run_field(&args, vault, bundle, &filters),
    }
}

fn run_field(
    args: &SearchArgs,
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    filters: &[(String, String)],
) -> Result<()> {
    finish(
        search_filtered(vault, bundle, filters),
        args.json,
        |entries| {
            println!("{}", serde_json::to_string(entries)?);
            Ok(())
        },
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
    vault: Option<VaultSelector>,
    bundle: Option<&Path>,
    query: &str,
    filters: &[(String, String)],
) -> Result<()> {
    // Rank over every Concept first (unlimited), so `--field` narrowing
    // never distorts relative scores, then narrow to the `--field` match
    // set (if any) before applying `--limit`.
    let ranked = search_text_filtered(vault, bundle, query, usize::MAX);
    let mut results = match ranked {
        Ok(results) => results,
        Err(err) => return report_error(&err, args.json),
    };

    if !filters.is_empty() {
        let field_matches = match search_filtered(vault, bundle, filters) {
            Ok(entries) => entries,
            Err(err) => return report_error(&err, args.json),
        };
        let allowed: std::collections::HashSet<String> =
            field_matches.into_iter().map(|entry| entry.slug).collect();
        results.retain(|result| allowed.contains(&result.slug));
    }
    results.truncate(args.limit);

    if args.json {
        println!("{}", serde_json::to_string(&results)?);
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
        assert!(
            err.to_string().contains("expected `key=value`"),
            "{err}"
        );
    }

    #[test]
    fn parse_filters_rejects_empty_key() {
        // An empty key can never match a real frontmatter field; reject it
        // early rather than silently querying nothing.
        let err = parse_filters(&["=value".into()]).unwrap_err();
        assert!(err.to_string().contains("expected `key=value`"), "{err}");
    }
}
