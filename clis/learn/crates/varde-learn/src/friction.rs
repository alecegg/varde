use std::collections::HashSet;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use anyhow::Result;
use serde_json::json;
use varde_learn_core::{
    AdoptionRecordRequest, FrictionAddMode, FrictionAddRequest, FrictionExportItem,
    FrictionImportFile, FrictionImportSummary, FrictionListRequest, FrictionStatus, LearnError,
    MAX_PAGE_LIMIT, PageRequest, Store, read_import_files,
};

use crate::cli::{
    AdoptionRecordArgs, AdoptionRecurrenceArgs, FrictionAddArgs, FrictionExportArgs,
    FrictionImportArgs, FrictionListArgs, FrictionSetStatusArgs, FrictionShowArgs,
};

pub fn run_list_command(args: FrictionListArgs) -> Result<()> {
    if args.global && args.repo.is_some() {
        return Err(invalid_add("--repo and --global cannot be combined").into());
    }
    let status = args
        .status
        .as_deref()
        .map(|value| {
            FrictionStatus::parse(value)
                .ok_or_else(|| invalid_add(format!("unknown friction status `{value}`")))
        })
        .transpose()?;
    let cwd = std::env::current_dir()
        .map_err(|error| invalid_add(format!("could not read current directory: {error}")))?;
    let mut store = Store::open_global()?;
    let page = store.list_items(&FrictionListRequest {
        status,
        source: args.source,
        repo_root: args.repo,
        global: args.global,
        text: args.text,
        cwd,
        page: PageRequest {
            offset: args.offset,
            limit: args.limit,
        },
    })?;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": { "items": page.items },
                "meta": {
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                    "next_offset": page.next_offset,
                    "truncated": page.truncated,
                },
            })
        );
    } else if page.items.is_empty() {
        println!("No friction items found.");
    } else {
        for item in page.items {
            println!(
                "{} {} [{}] {} ({})",
                item.id, item.slug, item.status, item.title, item.source
            );
        }
        if page.truncated {
            println!(
                "Showing {} of {}; continue with --offset {} --limit {}.",
                page.offset + page.limit,
                page.total,
                page.next_offset.unwrap_or(page.offset + page.limit),
                page.limit
            );
        }
    }
    Ok(())
}

pub fn run_show_command(args: FrictionShowArgs) -> Result<()> {
    let mut store = Store::open_global()?;
    let show = store.show_friction(
        &args.identifier,
        PageRequest {
            offset: args.offset,
            limit: args.limit,
        },
    )?;
    let truncated = show.occurrences.truncated || show.status_changes.truncated;
    let next_offset = show
        .occurrences
        .next_offset
        .or(show.status_changes.next_offset);
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": {
                    "item": show.item,
                    "occurrences": show.occurrences.items,
                    "status_changes": show.status_changes.items,
                },
                "meta": {
                    "total": {
                        "occurrences": show.occurrences.total,
                        "status_changes": show.status_changes.total,
                    },
                    "offset": args.offset,
                    "limit": args.limit,
                    "next_offset": next_offset,
                    "truncated": truncated,
                },
            })
        );
    } else {
        println!(
            "{} {} [{}] {} ({})",
            show.item.id, show.item.slug, show.item.status, show.item.title, show.item.source
        );
        if let Some(target) = &show.item.target {
            println!("Target: {target}");
        }
        if let Some(repo_root) = &show.item.repo_root {
            println!("Repository: {repo_root}");
        } else {
            println!("Repository: global");
        }
        println!("Occurrences ({}/{})", args.offset, show.occurrences.total);
        for occurrence in show.occurrences.items {
            println!(
                "- {} at {}: {}",
                occurrence.id, occurrence.at, occurrence.evidence
            );
            if let Some(provenance) = occurrence.provenance {
                println!("  Incident: {}", provenance.incident_key);
            }
        }
        println!(
            "Status history ({}/{})",
            args.offset, show.status_changes.total
        );
        for change in show.status_changes.items {
            println!(
                "- {} {} -> {} at {}: {}",
                change.id, change.from_status, change.to_status, change.at, change.reason
            );
        }
        if truncated {
            println!(
                "Continue with --offset {} --limit {}.",
                next_offset.unwrap_or(args.offset + args.limit),
                args.limit
            );
        }
    }
    Ok(())
}

pub fn run_set_status_command(args: FrictionSetStatusArgs) -> Result<()> {
    let status = FrictionStatus::parse(&args.status)
        .ok_or_else(|| invalid_add(format!("unknown friction status `{}`", args.status)))?;
    let mut store = Store::open_global()?;
    let item = store.set_friction_status(args.id, status, &args.reason)?;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": { "id": item.id, "status": item.status },
                "meta": { "truncated": false },
            })
        );
    } else {
        println!("{} [{}]", item.id, item.status);
    }
    Ok(())
}

pub fn run_export_command(args: FrictionExportArgs) -> Result<()> {
    let mut store = Store::open_global()?;
    let items = store.export_items()?;
    let directory = prepare_export_directory(&args.directory)?;
    let filenames = preflight_export_paths(&directory, &items)?;

    for (item, filename) in items.iter().zip(&filenames) {
        let content = render_friction_markdown(item);
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(directory.join(filename))?;
        file.write_all(content.as_bytes())?;
    }

    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": { "exported": items.len() },
                "meta": { "truncated": false },
            })
        );
    } else {
        println!(
            "Exported {} friction items to {}.",
            items.len(),
            directory.display()
        );
    }
    Ok(())
}

pub fn run_import_command(args: FrictionImportArgs) -> Result<()> {
    if args.limit == 0 || args.limit > MAX_PAGE_LIMIT {
        return Err(
            invalid_add(format!("page limit must be between 1 and {MAX_PAGE_LIMIT}")).into(),
        );
    }
    if args.dry_run {
        Store::validate_global_path()?;
    }
    let files = read_import_files(&args.directory, &args.repo)?;
    let mut store = if args.dry_run {
        None
    } else {
        Some(Store::open_global()?)
    };
    let mut results = Vec::with_capacity(files.len());
    let mut summary = FrictionImportSummary {
        total: files.len(),
        ..FrictionImportSummary::default()
    };

    for file in files {
        match file {
            FrictionImportFile::Skipped { file, reason } => {
                summary.skipped += 1;
                results.push(ImportResult {
                    file,
                    outcome: "skipped".to_owned(),
                    reason: Some(reason),
                    id: None,
                    slug: None,
                    title: None,
                    source: None,
                    status: None,
                });
            }
            FrictionImportFile::Ready { file, entry } => {
                if args.dry_run {
                    summary.would_import += 1;
                    results.push(ImportResult {
                        file,
                        outcome: "would_import".to_owned(),
                        reason: None,
                        id: entry.id,
                        slug: Some(entry.slug),
                        title: Some(entry.title),
                        source: Some(entry.source),
                        status: Some(entry.status.as_str().to_owned()),
                    });
                } else {
                    let imported = store
                        .as_mut()
                        .expect("store is open for non-dry-run import")
                        .import_friction(&entry)?;
                    if let Some(item) = imported {
                        summary.imported += 1;
                        results.push(ImportResult {
                            file,
                            outcome: "imported".to_owned(),
                            reason: None,
                            id: Some(item.id),
                            slug: Some(item.slug),
                            title: Some(item.title),
                            source: Some(item.source),
                            status: Some(item.status),
                        });
                    } else {
                        summary.skipped += 1;
                        results.push(ImportResult {
                            file,
                            outcome: "skipped".to_owned(),
                            reason: Some("slug already exists".to_owned()),
                            id: None,
                            slug: Some(entry.slug),
                            title: Some(entry.title),
                            source: Some(entry.source),
                            status: Some(entry.status.as_str().to_owned()),
                        });
                    }
                }
            }
        }
    }

    let start = args.offset.min(results.len());
    let end = start.saturating_add(args.limit).min(results.len());
    let page = &results[start..end];
    let next_offset = (end < results.len()).then_some(end);
    if args.json {
        crate::print_success_envelope(
            json!({
                "summary": summary,
                "results": page.iter().map(ImportResult::to_json).collect::<Vec<_>>(),
            }),
            json!({
                "total": results.len(),
                "offset": args.offset,
                "limit": args.limit,
                "next_offset": next_offset,
                "truncated": next_offset.is_some(),
            }),
        );
    } else {
        for result in page {
            if let Some(reason) = result.reason.as_deref() {
                println!("{}: {} ({reason})", result.outcome, result.file);
            } else {
                println!(
                    "{}: {}{}",
                    result.outcome,
                    result.file,
                    result
                        .title
                        .as_deref()
                        .map(|title| format!(" - {title}"))
                        .unwrap_or_default()
                );
            }
        }
        println!(
            "Import report: {} total, {} imported, {} would import, {} skipped.",
            summary.total, summary.imported, summary.would_import, summary.skipped
        );
        if let Some(next_offset) = next_offset {
            println!(
                "Continue the report with --offset {next_offset} --limit {}.",
                args.limit
            );
        }
    }
    Ok(())
}

struct ImportResult {
    file: String,
    outcome: String,
    reason: Option<String>,
    id: Option<i64>,
    slug: Option<String>,
    title: Option<String>,
    source: Option<String>,
    status: Option<String>,
}

impl ImportResult {
    fn to_json(&self) -> serde_json::Value {
        json!({
            "file": self.file,
            "outcome": self.outcome,
            "reason": self.reason,
            "id": self.id,
            "slug": self.slug,
            "title": self.title,
            "source": self.source,
            "status": self.status,
        })
    }
}

fn prepare_export_directory(path: &Path) -> Result<PathBuf> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err(invalid_add(format!(
                "refusing to export through symlinked directory `{}`",
                path.display()
            ))
            .into());
        }
        Ok(metadata) if !metadata.is_dir() => {
            return Err(invalid_add(format!(
                "export destination `{}` is not a directory",
                path.display()
            ))
            .into());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => fs::create_dir_all(path)?,
        Err(error) => return Err(error.into()),
    }
    Ok(fs::canonicalize(path)?)
}

fn preflight_export_paths(directory: &Path, items: &[FrictionExportItem]) -> Result<Vec<String>> {
    let mut filenames = Vec::with_capacity(items.len());
    let mut unique = HashSet::with_capacity(items.len());
    for item in items {
        let filename = format!("{}.md", safe_export_slug(&item.item.slug, item.item.id));
        if !unique.insert(filename.clone()) {
            return Err(invalid_add(format!(
                "multiple friction items map to export file `{filename}`"
            ))
            .into());
        }
        let destination = directory.join(&filename);
        match fs::symlink_metadata(&destination) {
            Ok(_) => {
                return Err(invalid_add(format!(
                    "refusing to overwrite existing export path `{}`",
                    destination.display()
                ))
                .into());
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        filenames.push(filename);
    }
    Ok(filenames)
}

fn safe_export_slug(slug: &str, item_id: i64) -> String {
    if !slug.is_empty()
        && slug
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return slug.to_owned();
    }

    let mut safe = String::new();
    let mut separator = false;
    for byte in slug.bytes() {
        if byte.is_ascii_alphanumeric() {
            if separator && !safe.is_empty() {
                safe.push('-');
            }
            safe.push((byte as char).to_ascii_lowercase());
            separator = false;
        } else {
            separator = true;
        }
    }
    if safe.is_empty() {
        safe.push_str("friction");
    }
    format!("{safe}-{item_id}")
}

fn render_friction_markdown(export: &FrictionExportItem) -> String {
    let item = &export.item;
    let occurrences = &export.occurrences;
    let status_changes = &export.status_changes;
    let mut output = String::from("---\nformat: \"varde-friction-item\"\nversion: 1\n");
    output.push_str(&format!("id: {}\n", item.id));
    yaml_string(&mut output, "slug", &item.slug, "");
    yaml_string(&mut output, "title", &item.title, "");
    yaml_string(&mut output, "source", &item.source, "");
    yaml_optional_string(&mut output, "repo_root", item.repo_root.as_deref(), "");
    yaml_string(&mut output, "status", &item.status, "");
    yaml_optional_string(&mut output, "target", item.target.as_deref(), "");
    yaml_string(&mut output, "created_at", &item.created_at, "");

    if occurrences.is_empty() {
        output.push_str("occurrences: []\n");
    } else {
        output.push_str("occurrences:\n");
        for occurrence in occurrences {
            output.push_str(&format!(
                "  - id: {}\n    item_id: {}\n",
                occurrence.id, occurrence.item_id
            ));
            yaml_string(&mut output, "at", &occurrence.at, "    ");
            yaml_string(&mut output, "cwd", &occurrence.cwd, "    ");
            yaml_optional_string(
                &mut output,
                "repo_root",
                occurrence.repo_root.as_deref(),
                "    ",
            );
            yaml_optional_string(
                &mut output,
                "head_sha",
                occurrence.head_sha.as_deref(),
                "    ",
            );
            yaml_string(&mut output, "evidence", &occurrence.evidence, "    ");
            yaml_optional_string(&mut output, "cost", occurrence.cost.as_deref(), "    ");
            if let Some(provenance) = &occurrence.provenance {
                render_incident_provenance(&mut output, provenance);
            }
        }
    }
    if status_changes.is_empty() {
        output.push_str("status_changes: []\n");
    } else {
        output.push_str("status_changes:\n");
        for change in status_changes {
            output.push_str(&format!(
                "  - id: {}\n    item_id: {}\n",
                change.id, change.item_id
            ));
            yaml_string(&mut output, "at", &change.at, "    ");
            yaml_string(&mut output, "from_status", &change.from_status, "    ");
            yaml_string(&mut output, "to_status", &change.to_status, "    ");
            yaml_string(&mut output, "reason", &change.reason, "    ");
        }
    }

    output.push_str("---\n\n");
    output.push_str(&format!("# Friction item {}\n\n", item.id));
    output.push_str("## Title\n\n");
    markdown_text_block(&mut output, &item.title);
    output.push_str("## Occurrences\n\n");
    for occurrence in occurrences {
        output.push_str(&format!("### Occurrence {}\n\n", occurrence.id));
        output.push_str(&format!("- Recorded: {}\n", occurrence.at));
        output.push_str(&format!(
            "- Repository: {}\n",
            occurrence.repo_root.as_deref().unwrap_or("global")
        ));
        output.push_str("- Evidence:\n\n");
        markdown_text_block(&mut output, &occurrence.evidence);
    }
    output.push_str("## Status history\n\n");
    for change in status_changes {
        output.push_str(&format!(
            "### Change {}: {} → {}\n\n- Recorded: {}\n- Reason:\n\n",
            change.id, change.from_status, change.to_status, change.at
        ));
        markdown_text_block(&mut output, &change.reason);
    }
    output
}

fn yaml_string(output: &mut String, key: &str, value: &str, indent: &str) {
    output.push_str(indent);
    output.push_str(key);
    output.push_str(": ");
    let encoded = serde_json::to_string(value)
        .expect("JSON string serialization succeeds")
        // YAML treats a raw NEL as a line break even in a quoted scalar.
        .replace('\u{0085}', "\\u0085");
    output.push_str(&encoded);
    output.push('\n');
}

fn yaml_optional_string(output: &mut String, key: &str, value: Option<&str>, indent: &str) {
    if let Some(value) = value {
        yaml_string(output, key, value, indent);
    } else {
        output.push_str(indent);
        output.push_str(key);
        output.push_str(": null\n");
    }
}

fn render_incident_provenance(
    output: &mut String,
    provenance: &varde_learn_core::FrictionIncidentProvenance,
) {
    output.push_str("    provenance:\n");
    output.push_str(&format!(
        "      identity_version: {}\n",
        provenance.identity_version
    ));
    yaml_string(output, "incident_key", &provenance.incident_key, "      ");
    yaml_string(output, "harness", &provenance.harness, "      ");
    yaml_string(output, "thread_id", &provenance.thread_id, "      ");
    yaml_string(output, "incident_kind", &provenance.incident_kind, "      ");
    yaml_optional_string(
        output,
        "witness_id",
        provenance.witness_id.as_deref(),
        "      ",
    );
    yaml_string(output, "source_id", &provenance.source_id, "      ");
    output.push_str(&format!(
        "      record_index: {}\n      byte_start: {}\n      byte_end: {}\n",
        provenance.record_index, provenance.byte_start, provenance.byte_end
    ));
    yaml_string(output, "record_digest", &provenance.record_digest, "      ");
    yaml_string(
        output,
        "payload_digest",
        &provenance.payload_digest,
        "      ",
    );
}

fn markdown_text_block(output: &mut String, value: &str) {
    let mut longest_backtick_run = 0;
    let mut current_backtick_run = 0;
    for character in value.chars() {
        if character == '`' {
            current_backtick_run += 1;
            longest_backtick_run = longest_backtick_run.max(current_backtick_run);
        } else {
            current_backtick_run = 0;
        }
    }
    let fence = "`".repeat(longest_backtick_run.max(2) + 1);
    output.push_str(&fence);
    output.push_str("text\n");
    output.push_str(value);
    if !value.ends_with('\n') {
        output.push('\n');
    }
    output.push_str(&fence);
    output.push_str("\n\n");
}

pub fn run_add_command(args: FrictionAddArgs) -> Result<()> {
    let mode = match args.item {
        Some(item_id) => {
            if args.source.is_some() || args.title.is_some() || args.target.is_some() || args.global
            {
                return Err(invalid_add(
                    "--item cannot be combined with --source, --title, --target, or --global",
                )
                .into());
            }
            FrictionAddMode::Append { item_id }
        }
        None => {
            let (Some(source), Some(title)) = (args.source, args.title) else {
                return Err(invalid_add("provide --item, or both --source and --title").into());
            };
            FrictionAddMode::Create {
                source,
                title,
                target: args.target,
                global: args.global,
            }
        }
    };

    match &mode {
        FrictionAddMode::Create {
            source,
            title,
            target,
            ..
        } => {
            for (field, value) in [("source", source), ("title", title)] {
                if value.trim().is_empty() {
                    return Err(invalid_add(format!("{field} must not be blank")).into());
                }
            }
            if target.as_ref().is_some_and(|value| value.trim().is_empty()) {
                return Err(invalid_add("target must not be blank").into());
            }
        }
        FrictionAddMode::Append { item_id } if *item_id <= 0 => {
            return Err(invalid_add("item ID must be a positive integer").into());
        }
        FrictionAddMode::Append { .. } => {}
    }

    let mut evidence = String::new();
    std::io::Read::read_to_string(&mut std::io::stdin(), &mut evidence)?;
    if evidence.trim().is_empty() {
        return Err(invalid_add("evidence from stdin must not be blank").into());
    }
    let cwd = std::env::current_dir()
        .map_err(|error| invalid_add(format!("could not read current directory: {error}")))?;
    let mut store = Store::open_global()?;
    let item = store.add_friction(FrictionAddRequest {
        mode,
        evidence,
        cwd,
    })?;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": { "id": item.id, "slug": item.slug },
                "meta": { "truncated": false },
            })
        );
    } else {
        println!("{}", item.id);
    }
    Ok(())
}

pub fn run_adopt_record_command(args: AdoptionRecordArgs) -> Result<()> {
    if args.items.is_empty() {
        return Err(invalid_add("at least one item ID is required").into());
    }
    let mut seen = HashSet::with_capacity(args.items.len());
    for item_id in &args.items {
        if *item_id <= 0 {
            return Err(invalid_add("item IDs must be positive integers").into());
        }
        if !seen.insert(*item_id) {
            return Err(invalid_add("item IDs must not contain duplicates").into());
        }
    }
    if args.summary.trim().is_empty() {
        return Err(invalid_add("summary must not be blank").into());
    }
    if args.files.is_empty() {
        return Err(invalid_add("at least one file path is required").into());
    }
    if args.files.iter().any(|file| file.trim().is_empty()) {
        return Err(invalid_add("file paths must not be blank").into());
    }
    if args
        .commit
        .as_ref()
        .is_some_and(|commit| commit.trim().is_empty())
    {
        return Err(invalid_add("commit SHA must not be blank").into());
    }
    let eval_before = read_benchmark_json(args.eval_before, "--eval-before")?;
    let eval_after = read_benchmark_json(args.eval_after, "--eval-after")?;

    let mut store = Store::open_global()?;
    let adoption = store.record_adoption(AdoptionRecordRequest {
        item_ids: args.items,
        summary: args.summary,
        files: args.files,
        commit_sha: args.commit,
        eval_before,
        eval_after,
    })?;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": {
                    "adoption_id": adoption.id,
                    "items": adoption.item_ids,
                },
                "meta": { "truncated": false },
            })
        );
    } else {
        println!(
            "Recorded adoption {} for {} friction items.",
            adoption.id,
            adoption.item_ids.len()
        );
    }
    Ok(())
}

pub fn run_adopt_recurrence_command(args: AdoptionRecurrenceArgs) -> Result<()> {
    if args.limit == 0 || args.limit > MAX_PAGE_LIMIT {
        return Err(
            invalid_add(format!("page limit must be between 1 and {MAX_PAGE_LIMIT}")).into(),
        );
    }
    let mut store = Store::open_global()?;
    let report = store.list_recurrences(PageRequest {
        offset: args.offset,
        limit: args.limit,
    })?;
    let page = report.page;
    if args.json {
        println!(
            "{}",
            json!({
                "schema_version": 1,
                "envelope_version": 1,
                "ok": true,
                "outcome": "success",
                "data": { "items": page.items },
                "meta": {
                    "total": page.total,
                    "offset": page.offset,
                    "limit": page.limit,
                    "next_offset": page.next_offset,
                    "truncated": page.truncated,
                    "skipped_invalid_timestamps": report.skipped_invalid_timestamps,
                },
            })
        );
    } else {
        if page.items.is_empty() {
            println!("No adoption recurrences found.");
        } else {
            for recurrence in &page.items {
                println!(
                    "{} {} recurred after adoption {} ({}) at {}: {}",
                    recurrence.item.id,
                    recurrence.item.title,
                    recurrence.adoption_id,
                    recurrence.summary,
                    recurrence.occurrence.at,
                    recurrence.occurrence.evidence
                );
            }
            if page.truncated {
                println!(
                    "Showing {} of {}; continue with --offset {} --limit {}.",
                    page.offset + page.limit,
                    page.total,
                    page.next_offset.unwrap_or(page.offset + page.limit),
                    page.limit
                );
            }
        }
        if report.skipped_invalid_timestamps > 0 {
            println!(
                "Skipped {} linked timestamps SQLite could not parse.",
                report.skipped_invalid_timestamps
            );
        }
    }
    Ok(())
}

fn read_benchmark_json(path: Option<PathBuf>, flag: &str) -> Result<Option<String>> {
    let Some(path) = path else {
        return Ok(None);
    };
    let contents = std::fs::read_to_string(&path).map_err(|error| {
        invalid_add(format!(
            "could not read {flag} file {}: {error}",
            path.display()
        ))
    })?;
    serde_json::from_str::<serde_json::Value>(&contents)
        .map_err(|error| invalid_add(format!("{flag} file must contain valid JSON: {error}")))?;
    Ok(Some(contents))
}

fn invalid_add(message: impl Into<String>) -> LearnError {
    LearnError::StoreInvalid {
        message: message.into(),
    }
}
