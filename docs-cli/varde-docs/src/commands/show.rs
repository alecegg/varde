//! `concept show` command handler.

use crate::cli::ShowArgs;
use crate::commands::error::report_error;
use anyhow::Result;
use okf_core::crud::show::ShownConcept;
use okf_core::vault::show_merged;
use serde_json::json;

pub fn run(args: ShowArgs) -> Result<()> {
    // `vault::show_merged` owns the Project → Personal Vault fallback and
    // reports which bundle actually served the Concept, so git-derived
    // timestamps are computed against the bundle that owns the file, not
    // always the project bundle.
    let shown = match show_merged(&args.bundle, &args.slug) {
        Ok(shown) => shown,
        Err(err) => return report_error(&err, args.json),
    };
    let concept = &shown.concept;
    let served_bundle = &shown.bundle;
    // Git-derived read-time metadata (never frontmatter): computed against
    // the bundle that served the Concept.
    let (created, updated) =
        okf_core::crud::timestamps::git_created_updated(served_bundle, &args.slug);
    // `--frontmatter-only` takes precedence over `--json`.
    if args.frontmatter_only {
        return render_frontmatter_only(&concept.frontmatter);
    }
    if args.json {
        render_json(concept, &created, &updated)
    } else {
        render_text(concept, &created, &updated)
    }
}

/// `--frontmatter-only` renderer: the parsed frontmatter as structured
/// JSON, no body text. `serde_yaml::Value` serializes losslessly to JSON
/// for the string-keyed frontmatter this codebase writes (OKF §4); the
/// body is intentionally omitted.
fn render_frontmatter_only(frontmatter: &serde_yaml::Value) -> Result<()> {
    println!("{}", serde_json::to_string(frontmatter)?);
    Ok(())
}

/// `--json` renderer: slug, version, frontmatter, body, and the
/// git-derived timestamps (`null` when no history exists).
fn render_json(
    concept: &ShownConcept,
    created: &Option<String>,
    updated: &Option<String>,
) -> Result<()> {
    println!(
        "{}",
        json!({
            "slug": concept.slug,
            "version": concept.version,
            "frontmatter": concept.frontmatter,
            "body": concept.body,
            "created": created,
            "updated": updated,
        })
    );
    Ok(())
}

/// Text renderer: frontmatter block, body, then the version and any
/// git-derived timestamps.
fn render_text(
    concept: &ShownConcept,
    created: &Option<String>,
    updated: &Option<String>,
) -> Result<()> {
    let yaml = serde_yaml::to_string(&concept.frontmatter)?;
    println!("---");
    print!("{yaml}");
    println!("---");
    print!("{}", concept.body);
    if !concept.body.ends_with('\n') {
        println!();
    }
    println!();
    println!("version: {}", concept.version);
    if let Some(created) = created {
        println!("created: {created}");
    }
    if let Some(updated) = updated {
        println!("updated: {updated}");
    }
    Ok(())
}
