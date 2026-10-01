//! Output post-processing applied at the single query/scan serialization
//! boundary, after a mode has produced its payload but before it becomes the
//! versioned `{schema_version, ok, outcome, data, meta}` envelope.
//!
//! Two token-efficiency transforms (audit F5 + F6), both keyed off the mode's
//! own input object so no signature threading is needed:
//!
//! - **F5 repo-relative paths.** The MCP schema requires an absolute
//!   `repoRoot`, and the index stores each file as the walker yielded it —
//!   literally `{repoRoot}{sep}{relative}` (walkdir preserves the exact root
//!   prefix). So every emitted path re-states the absolute prefix (~200×/nav_map).
//!   We strip that prefix from every string value in the payload, turning
//!   `/abs/repo/src/main.rs` into `src/main.rs`. Only known repository-path
//!   fields are transformed, so source text and external paths stay verbatim.
//!   Round-trips: query inputs
//!   resolve a relative `filePath` against the stored path via a suffix match
//!   (`simple::file_id`), so a relative path fed back in still matches.
//!   Opt out with `absolutePaths: true`.
//!
//! - **F6 line-only spans.** A `span` object carries six fields
//!   (start/end × byte/line/col) where the line pair usually suffices for
//!   navigation. We drop the byte and column fields, keeping `start_line` /
//!   `end_line`. The byte offsets an `--apply` rewrite needs are read from the
//!   in-memory `Finding` before this runs, so trimming the JSON never affects
//!   splicing. Opt in to the full span with `includeSpanDetail: true`.
//!
//! Both transforms are idempotent, so the double pass a `batch` payload sees
//! (once per sub-call, once for the aggregate) is harmless.

use serde::Serialize;
use serde_json::Value;
use std::collections::{HashMap, HashSet};

/// Machine-output metadata supplied with every envelope.
#[derive(Clone, Debug, Default, Serialize)]
pub struct OutputMeta {
    /// Whether the compact path/span output policy was applied.
    pub compact: bool,
    /// Whether a mode reported omitted results.
    pub truncated: bool,
    /// Recovery details for a bounded query response.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pagination: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub toz: Option<serde_json::Value>,
}

/// Render a result with the output policy derived from its input.
///
/// Errors have no payload to compact, so they retain default metadata. This
/// avoids reporting a policy that could not have run.
pub fn render_with_input(result: Result<Value, super::ApiError>, input: &Value) -> String {
    render_value_with_input(result, input).to_string()
}

/// Build a result envelope with the output policy derived from its input.
pub fn render_value_with_input(result: Result<Value, super::ApiError>, input: &Value) -> Value {
    match result {
        Ok(mut data) => {
            let meta = postprocess(&mut data, input);
            super::render_value_with_meta(Ok(data), meta)
        }
        Err(error) => super::render_value_with_meta(Err(error), OutputMeta::default()),
    }
}

/// Build an envelope for a payload already processed by a producer.
///
/// Scan payloads apply path and span policy inside `scan_repo`. This helper
/// records the corresponding metadata without applying those transforms again.
pub fn render_value_with_preprocessed_input(
    result: Result<Value, super::ApiError>,
    input: &Value,
) -> Value {
    match result {
        Ok(data) => {
            let meta = metadata_for(input, &data);
            super::render_value_with_meta(Ok(data), meta)
        }
        Err(error) => super::render_value_with_meta(Err(error), OutputMeta::default()),
    }
}

/// Apply the F5 (relativize) and F6 (span trim) transforms to a mode payload
/// in place, reading the opt-out/opt-in flags and path root from `input`.
pub(crate) fn postprocess(data: &mut Value, input: &Value) -> OutputMeta {
    let keep_absolute = input
        .get("absolutePaths")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let root = input
        .get("repoRoot")
        .or_else(|| input.get("rulesDir"))
        .and_then(Value::as_str)
        .map(|root| root.trim_end_matches(std::path::MAIN_SEPARATOR))
        .filter(|root| !root.is_empty());
    if !keep_absolute && let Some(root) = root {
        let prefix = format!("{root}{}", std::path::MAIN_SEPARATOR);
        relativize(data, &prefix);
    }

    let keep_span_detail = input
        .get("includeSpanDetail")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    if !keep_span_detail {
        trim_spans(data);
    }

    metadata_for(input, data)
}

/// Assemble the metadata attached by dispatch after query-specific pagination.
/// Context-pack budgeting uses the same path to measure its final envelope.
pub(crate) fn assemble_metadata(
    data: &mut Value,
    input: &Value,
    mut pagination: Option<Value>,
) -> OutputMeta {
    let mut meta = postprocess(data, input);
    if let Some(sections) = pagination.as_mut().and_then(Value::as_object_mut) {
        meta.toz = sections.remove("__toz");
    }
    if pagination.is_some() {
        meta.truncated = true;
        meta.pagination = pagination;
    }
    meta
}

fn metadata_for(input: &Value, data: &Value) -> OutputMeta {
    let root = input
        .get("repoRoot")
        .or_else(|| input.get("rulesDir"))
        .and_then(Value::as_str)
        .filter(|root| !root.trim_end_matches(std::path::MAIN_SEPARATOR).is_empty());
    let keep_absolute = input
        .get("absolutePaths")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let keep_span_detail = input
        .get("includeSpanDetail")
        .and_then(Value::as_bool)
        .unwrap_or(false);

    OutputMeta {
        compact: root.is_some() && (!keep_absolute || !keep_span_detail),
        truncated: is_truncated(data),
        pagination: None,
        toz: data.pointer("/guide/toz").cloned(),
    }
}

fn is_truncated(data: &Value) -> bool {
    data.pointer("/guide/truncated")
        .and_then(Value::as_object)
        .is_some_and(|sections| !sections.is_empty())
        || data.as_array().is_some_and(|results| {
            results.iter().any(|result| {
                result
                    .pointer("/meta/truncated")
                    .and_then(Value::as_bool)
                    .unwrap_or(false)
            })
        })
}

const DEFAULT_QUERY_LIMIT: usize = 100;

#[derive(Clone, Copy, Debug)]
struct PaginationOptions {
    full: bool,
    limit: usize,
    offset: usize,
}

fn pagination_options(input: &Value) -> Result<PaginationOptions, super::ApiError> {
    let full = match input.get("fullResults") {
        None => false,
        Some(value) => value.as_bool().ok_or_else(|| {
            super::ApiError::new("invalid_input", "fullResults must be a boolean")
        })?,
    };
    let number = |name: &str| -> Result<Option<usize>, super::ApiError> {
        let Some(value) = input.get(name) else {
            return Ok(None);
        };
        let number = value.as_u64().ok_or_else(|| {
            super::ApiError::new(
                "invalid_input",
                format!("{name} must be a nonnegative integer"),
            )
        })?;
        usize::try_from(number).map(Some).map_err(|_| {
            super::ApiError::new(
                "invalid_input",
                format!("{name} is too large for this platform"),
            )
        })
    };
    let limit = number("resultsLimit")?.unwrap_or(DEFAULT_QUERY_LIMIT);
    if limit == 0 {
        return Err(super::ApiError::new(
            "invalid_input",
            "resultsLimit must be greater than zero",
        ));
    }
    Ok(PaginationOptions {
        full,
        limit,
        offset: number("resultsOffset")?.unwrap_or(0),
    })
}

fn paginate_slice(values: &mut Vec<Value>, options: PaginationOptions) -> Option<Value> {
    let total = values.len();
    let start = options.offset.min(total);
    let end = if options.full {
        total
    } else {
        start.saturating_add(options.limit).min(total)
    };
    let truncated = start > 0 || end < total;
    if !truncated {
        return None;
    }
    *values = values[start..end].to_vec();
    Some(pagination_meta(total, start, end, options))
}

fn pagination_meta(total: usize, start: usize, end: usize, options: PaginationOptions) -> Value {
    serde_json::json!({
        "shown": end.saturating_sub(start),
        "total": total,
        "offset": start,
        "limit": if options.full { Value::Null } else { serde_json::json!(options.limit) },
        "next_offset": if end < total { serde_json::json!(end) } else { Value::Null },
        "request": if end < total {
            "set resultsOffset to next_offset, or set fullResults to true"
        } else {
            "set fullResults to true for all results"
        },
    })
}

/// Bound query result arrays at one output boundary.
///
/// Query handlers retain their established payload shapes. Array modes stay
/// arrays, while pagination details travel in the envelope's `meta` object.
#[cfg(test)]
pub(crate) fn paginate_query(
    mode: &str,
    input: &Value,
    data: &mut Value,
) -> Result<Option<Value>, super::ApiError> {
    paginate_query_with_mode_tag(mode, input, data, None)
}

pub(crate) fn paginate_query_with_mode_tag(
    mode: &str,
    input: &Value,
    data: &mut Value,
    mode_tag: Option<&str>,
) -> Result<Option<Value>, super::ApiError> {
    // `maxSymbols` is the legacy explicit cap. Keep its old behavior and
    // avoid claiming a total that the handler intentionally did not load.
    if uses_legacy_symbol_limit(mode, input) {
        return Ok(None);
    }

    let mut options = pagination_options(input)?;
    // Store the same compact representation that a paged call returns.
    // This transform is idempotent at the later envelope boundary.
    if !options.full && crate::toz::available() {
        postprocess(data, input);
    }
    match mode {
        "context_pack" => paginate_context_pack(input, data, options, mode_tag),
        "symbols_in_files" => Ok(data
            .as_object_mut()
            .and_then(|map| paginate_symbols_in_files(map, input, mode, &mut options))),
        "symbol_blast_radius" => Ok(data["blast_radius"]
            .as_array_mut()
            .and_then(|values| paginate_array(values, "blast_radius", input, mode, &mut options))),
        _ => Ok(data
            .as_array_mut()
            .and_then(|values| paginate_array(values, "results", input, mode, &mut options))),
    }
}

fn uses_legacy_symbol_limit(mode: &str, input: &Value) -> bool {
    mode == "filter_symbols"
        && input.get("maxSymbols").is_some()
        && input.get("resultsLimit").is_none()
        && input.get("resultsOffset").is_none()
        && input.get("fullResults").is_none()
}

fn capture_page(mode: &str, values: &[Value], options: PaginationOptions) -> Option<Value> {
    (!options.full && (options.offset > 0 || values.len() > options.limit))
        .then(|| crate::toz::capture_items(mode, values))
        .flatten()
}

fn add_page_guide(meta: &mut Value, reference: &Value, end: usize, options: PaginationOptions) {
    let total = reference["items"].as_u64().unwrap_or(0) as usize;
    crate::toz::add_guide(
        meta,
        reference,
        end,
        end.saturating_add(options.limit).min(total),
    );
}

fn paginate_array(
    values: &mut Vec<Value>,
    name: &str,
    input: &Value,
    mode: &str,
    options: &mut PaginationOptions,
) -> Option<Value> {
    let reference = capture_page(mode, values, *options);
    if reference.is_some() && input.get("resultsLimit").is_none() {
        options.limit = crate::toz::PAGE_LIMIT;
    }
    let mut meta = paginate_slice(values, *options)?;
    let mut sections = serde_json::Map::new();
    if let Some(reference) = reference {
        let end = meta["next_offset"].as_u64().map_or_else(
            || reference["items"].as_u64().unwrap_or(0) as usize,
            |n| n as usize,
        );
        add_page_guide(&mut meta, &reference, end, *options);
        sections.insert("__toz".into(), reference);
    }
    sections.insert(name.to_string(), meta);
    Some(Value::Object(sections))
}

fn paginate_symbols_in_files(
    map: &mut serde_json::Map<String, Value>,
    input: &Value,
    mode: &str,
    options: &mut PaginationOptions,
) -> Option<Value> {
    let total = map
        .values()
        .filter_map(Value::as_array)
        .map(Vec::len)
        .sum::<usize>();
    let reference = if crate::toz::available()
        && !options.full
        && (options.offset > 0 || total > options.limit)
    {
        let all: Vec<Value> = map
            .values()
            .filter_map(Value::as_array)
            .flatten()
            .cloned()
            .collect();
        crate::toz::capture_items(mode, &all)
    } else {
        None
    };
    if reference.is_some() && input.get("resultsLimit").is_none() {
        options.limit = crate::toz::PAGE_LIMIT;
    }
    let start = options.offset.min(total);
    let end = if options.full {
        total
    } else {
        start.saturating_add(options.limit).min(total)
    };
    if start == 0 && end == total {
        return None;
    }
    retain_file_window(map, start, end);
    let mut meta = pagination_meta(total, start, end, *options);
    let mut sections = serde_json::Map::new();
    if let Some(reference) = reference {
        add_page_guide(&mut meta, &reference, end, *options);
        sections.insert("__toz".into(), reference);
    }
    sections.insert("results".into(), meta);
    Some(Value::Object(sections))
}

fn retain_file_window(map: &mut serde_json::Map<String, Value>, start: usize, end: usize) {
    let mut cursor = 0;
    for value in map.values_mut() {
        let Some(values) = value.as_array_mut() else {
            continue;
        };
        let length = values.len();
        let local_start = start.saturating_sub(cursor).min(length);
        let local_end = end.saturating_sub(cursor).min(length);
        *values = values[local_start..local_end].to_vec();
        cursor += length;
    }
}

fn paginate_context_pack(
    input: &Value,
    data: &mut Value,
    mut options: PaginationOptions,
    mode_tag: Option<&str>,
) -> Result<Option<Value>, super::ApiError> {
    // Paths must be compacted before both candidate sizing and Toz capture.
    postprocess(data, input);
    let files = data["files"].as_array().cloned().unwrap_or_default();
    let capture_page = !options.full && (options.offset > 0 || files.len() > options.limit);
    let mut reference = capture_page
        .then(|| crate::toz::capture_items("context_pack", &files))
        .flatten();
    if reference.is_some() && input.get("resultsLimit").is_none() {
        options.limit = crate::toz::PAGE_LIMIT;
    }
    let symbols = data["symbols"].as_array().cloned().unwrap_or_default();
    let tests = data["tests"].as_array().cloned().unwrap_or_default();
    let total = files.len();
    let start = options.offset.min(total);
    let end = if options.full {
        total
    } else {
        start.saturating_add(options.limit).min(total)
    };
    let max_tokens = context_token_limit(input)?;
    let include_reading_order = context_reading_order(input)?;
    let mut selection = select_context_window(
        &files,
        &symbols,
        &tests,
        start,
        end,
        input,
        options,
        max_tokens,
        options.full,
        include_reading_order,
        &mut reference,
        mode_tag,
    )?;

    // A budget may shorten the window even when the caller's page controls do
    // not. Capture the original rows once so the final guide can recover them,
    // then remeasure with that reference in metadata.
    if reference.is_none() && !options.full && selection.end < total && !capture_page {
        reference = crate::toz::capture_items("context_pack", &files);
        if reference.is_some() {
            selection = select_context_window(
                &files,
                &symbols,
                &tests,
                start,
                end,
                input,
                options,
                max_tokens,
                options.full,
                include_reading_order,
                &mut reference,
                mode_tag,
            )?;
        }
    }
    let sections = context_pagination(total, start, &selection, options, max_tokens, reference);
    *data = selection.data;
    Ok(sections)
}

fn context_token_limit(input: &Value) -> Result<usize, super::ApiError> {
    match input.get("maxTokensEstimate") {
        None => Ok(4_000),
        Some(value) => value
            .as_u64()
            .and_then(|number| usize::try_from(number).ok())
            .filter(|number| *number > 0)
            .ok_or_else(|| {
                super::ApiError::new(
                    "invalid_input",
                    "maxTokensEstimate must be a positive integer",
                )
            }),
    }
}

fn context_reading_order(input: &Value) -> Result<bool, super::ApiError> {
    match input.get("includeReadingOrder") {
        None => Ok(true),
        Some(value) => value.as_bool().ok_or_else(|| {
            super::ApiError::new("invalid_input", "includeReadingOrder must be a boolean")
        }),
    }
}

struct ContextSelection {
    data: Value,
    end: usize,
    budget_trimmed: bool,
    symbol_total: usize,
    symbol_shown: usize,
    test_total: usize,
    test_shown: usize,
}

#[allow(clippy::too_many_arguments)] // The candidate must include the exact output policy and recovery metadata.
fn select_context_window(
    files: &[Value],
    symbols: &[Value],
    tests: &[Value],
    start: usize,
    mut end: usize,
    input: &Value,
    options: PaginationOptions,
    max_tokens: usize,
    full: bool,
    include_reading_order: bool,
    reference: &mut Option<Value>,
    mode_tag: Option<&str>,
) -> Result<ContextSelection, super::ApiError> {
    let mut budget_trimmed = false;
    let symbols_per_file = (max_tokens / 800).max(1);
    loop {
        let (mut candidate, symbol_total, test_total) = context_candidate(
            &files[start..end],
            symbols,
            tests,
            symbols_per_file,
            full,
            include_reading_order,
        );
        let mut symbol_shown = candidate["symbols"].as_array().map_or(0, Vec::len);
        let mut test_shown = candidate["tests"].as_array().map_or(0, Vec::len);
        if full {
            return Ok(ContextSelection {
                data: candidate,
                end,
                budget_trimmed,
                symbol_total,
                symbol_shown,
                test_total,
                test_shown,
            });
        }

        loop {
            let selection = ContextSelection {
                data: candidate.clone(),
                end,
                budget_trimmed,
                symbol_total,
                symbol_shown,
                test_total,
                test_shown,
            };
            let pagination = context_pagination(
                files.len(),
                start,
                &selection,
                options,
                max_tokens,
                reference.clone(),
            );
            if estimated_context_envelope_tokens(&candidate, input, pagination, mode_tag)
                <= max_tokens
            {
                return Ok(selection);
            }

            if trim_context_preview(reference) {
                budget_trimmed = true;
                continue;
            }

            if end == start + 1 {
                let removed = candidate["symbols"]
                    .as_array_mut()
                    .and_then(Vec::pop)
                    .map(|_| {
                        symbol_shown = symbol_shown.saturating_sub(1);
                    })
                    .or_else(|| {
                        candidate["tests"]
                            .as_array_mut()
                            .and_then(Vec::pop)
                            .map(|_| {
                                test_shown = test_shown.saturating_sub(1);
                            })
                    });
                if removed.is_some() {
                    budget_trimmed = true;
                    continue;
                }
                return Err(super::ApiError::new(
                    "invalid_input",
                    "maxTokensEstimate cannot hold one context file",
                ));
            }

            if end == start {
                return Err(super::ApiError::new(
                    "invalid_input",
                    "maxTokensEstimate cannot hold an empty context pack",
                ));
            }
            end -= 1;
            budget_trimmed = true;
            break;
        }
    }
}

fn estimated_context_envelope_tokens(
    data: &Value,
    input: &Value,
    pagination: Option<Value>,
    mode_tag: Option<&str>,
) -> usize {
    let mut data = data.clone();
    let meta = assemble_metadata(&mut data, input, pagination);
    let envelope = match mode_tag {
        Some(mode) => super::render_batch_value(Ok(data), meta, Some(mode)),
        None => super::render_value_with_meta(Ok(data), meta),
    };
    serde_json::to_vec(&envelope)
        .map(|serialized| serialized.len() / 4)
        .unwrap_or(usize::MAX)
}

fn trim_context_preview(reference: &mut Option<Value>) -> bool {
    let Some(preview) = reference
        .as_mut()
        .and_then(|reference| reference.get_mut("toc"))
    else {
        return false;
    };
    match preview {
        Value::String(preview) if !preview.is_empty() => {
            if preview.chars().count() <= 4 {
                preview.clear();
            } else {
                let keep = preview.chars().count() / 2;
                let end = preview
                    .char_indices()
                    .nth(keep)
                    .map_or(preview.len(), |(index, _)| index);
                preview.truncate(end);
                preview.push('…');
            }
            true
        }
        Value::String(preview) if preview.is_empty() => false,
        Value::Null => false,
        _ => {
            *preview = Value::String("…".to_string());
            true
        }
    }
}

fn context_candidate(
    selected: &[Value],
    symbols: &[Value],
    tests: &[Value],
    symbols_per_file: usize,
    full: bool,
    include_reading_order: bool,
) -> (Value, usize, usize) {
    let paths: HashSet<&str> = selected
        .iter()
        .filter_map(|file| file.get("path").and_then(Value::as_str))
        .collect();
    let mut seen_per_file = HashMap::new();
    let mut matching_symbols = 0;
    let selected_symbols: Vec<Value> = symbols
        .iter()
        .filter(|symbol| {
            let Some(path) = symbol.get("filePath").and_then(Value::as_str) else {
                return false;
            };
            if !paths.contains(path) {
                return false;
            }
            matching_symbols += 1;
            let seen = seen_per_file.entry(path).or_insert(0usize);
            let keep = full || *seen < symbols_per_file;
            *seen += 1;
            keep
        })
        .cloned()
        .collect();
    let selected_tests: Vec<Value> = tests
        .iter()
        .filter(|test| {
            test.get("coversFile")
                .and_then(Value::as_str)
                .is_some_and(|path| paths.contains(path))
        })
        .cloned()
        .collect();
    let test_total = selected_tests.len();
    let reading_order: Vec<Value> = if include_reading_order {
        selected
            .iter()
            .filter_map(|file| file.get("path").cloned())
            .collect()
    } else {
        Vec::new()
    };
    (
        serde_json::json!({
            "files": selected, "symbols": selected_symbols,
            "tests": selected_tests, "readingOrder": reading_order,
        }),
        matching_symbols,
        test_total,
    )
}

fn context_pagination(
    total: usize,
    start: usize,
    selection: &ContextSelection,
    options: PaginationOptions,
    max_tokens: usize,
    reference: Option<Value>,
) -> Option<Value> {
    let unchanged = start == 0
        && selection.end == total
        && !selection.budget_trimmed
        && selection.symbol_shown == selection.symbol_total
        && selection.test_shown == selection.test_total;
    (!unchanged).then(|| context_sections(total, start, selection, options, max_tokens, reference))
}

fn context_sections(
    total: usize,
    start: usize,
    selection: &ContextSelection,
    options: PaginationOptions,
    max_tokens: usize,
    reference: Option<Value>,
) -> Value {
    let mut sections = serde_json::Map::new();
    if start > 0 || selection.end < total {
        let mut meta = pagination_meta(total, start, selection.end, options);
        if let Some(reference) = &reference {
            add_page_guide(&mut meta, reference, selection.end, options);
        }
        sections.insert("files".to_string(), meta);
    }
    if let Some(reference) = reference {
        sections.insert("__toz".into(), reference);
    }
    if selection.budget_trimmed {
        sections.insert(
            "budget".to_string(),
            serde_json::json!({
                "maxTokensEstimate": max_tokens,
                "request": "raise maxTokensEstimate for a larger file window"
            }),
        );
    }
    if selection.symbol_shown < selection.symbol_total {
        sections.insert(
            "symbols".to_string(),
            serde_json::json!({
                "shown": selection.symbol_shown,
                "total": selection.symbol_total,
                "request": "raise maxTokensEstimate or set fullResults to true for more symbols"
            }),
        );
    }
    if selection.test_shown < selection.test_total {
        sections.insert(
            "tests".to_string(),
            serde_json::json!({
                "shown": selection.test_shown,
                "total": selection.test_total,
                "request": "raise maxTokensEstimate or set fullResults to true for more tests"
            }),
        );
    }
    Value::Object(sections)
}

/// Strip `prefix` from known repository-path fields only.
fn relativize(v: &mut Value, prefix: &str) {
    match v {
        Value::Array(items) => items.iter_mut().for_each(|item| relativize(item, prefix)),
        Value::Object(map) => {
            for (key, value) in map {
                if is_repo_path_field(key) {
                    relativize_path(value, prefix);
                }
                relativize(value, prefix);
            }
        }
        _ => {}
    }
}

fn is_repo_path_field(field: &str) -> bool {
    matches!(
        field,
        "file"
            | "filePath"
            | "sourceFile"
            | "targetFile"
            | "coversFile"
            | "path"
            | "files"
            | "seedFiles"
            | "targetDir"
            | "changedFiles"
            | "changedFilesSample"
            | "reachable"
            | "readingOrder"
            | "members"
            | "from"
            | "to"
    )
}

fn relativize_path(v: &mut Value, prefix: &str) {
    match v {
        Value::String(path) => {
            if let Some(relative) = path.strip_prefix(prefix) {
                *path = relative.to_string();
            }
        }
        Value::Array(paths) => paths
            .iter_mut()
            .for_each(|path| relativize_path(path, prefix)),
        _ => {}
    }
}

/// Remove the byte/column fields from every `span` object, keeping the line
/// pair. Recurses through the whole tree so nested spans (e.g. a finding's
/// `location.span`, a symbol row's `span`) are all trimmed.
fn trim_spans(v: &mut Value) {
    match v {
        Value::Array(items) => items.iter_mut().for_each(trim_spans),
        Value::Object(map) => {
            if let Some(Value::Object(span)) = map.get_mut("span") {
                span.remove("start_byte");
                span.remove("end_byte");
                span.remove("start_col");
                span.remove("end_col");
            }
            map.values_mut().for_each(trim_spans);
        }
        _ => {}
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn context_pack_data(file_count: usize) -> Value {
        let files: Vec<Value> = (0..file_count)
            .map(|index| {
                json!({
                    "path": format!("src/module_{index}_{}", "x".repeat(48)),
                    "relevance": "neighbor"
                })
            })
            .collect();
        let reading_order: Vec<Value> = files.iter().map(|file| file["path"].clone()).collect();
        json!({
            "files": files,
            "symbols": [],
            "tests": [],
            "readingOrder": reading_order
        })
    }

    fn render_context_envelope(
        mut data: Value,
        input: &Value,
        pagination: Option<Value>,
        mode: Option<&str>,
    ) -> Value {
        let meta = assemble_metadata(&mut data, input, pagination);
        match mode {
            Some(mode) => super::super::render_batch_value(Ok(data), meta, Some(mode)),
            None => super::super::render_value_with_meta(Ok(data), meta),
        }
    }

    fn estimated_envelope_tokens(envelope: &Value) -> usize {
        serde_json::to_vec(envelope).unwrap().len() / 4
    }

    fn sep() -> char {
        std::path::MAIN_SEPARATOR
    }

    #[test]
    fn relativizes_paths_and_trims_spans_by_default() {
        let root = format!("{s}abs{s}repo", s = sep());
        let input = json!({ "repoRoot": root });
        let mut data = json!({
            "file": format!("{root}{s}src{s}main.rs", s = sep()),
            "reachable": [
                format!("{root}{s}src{s}a.rs", s = sep()),
                format!("{root}{s}src{s}b.rs", s = sep()),
            ],
            "location": {
                "span": {
                    "start_byte": 10, "end_byte": 26,
                    "start_line": 2, "start_col": 4,
                    "end_line": 3, "end_col": 20
                }
            },
            "dbPath": format!("{s}home{s}u{s}.config{s}index.db", s = sep()),
            "source": format!("{root}{s}this is source text", s = sep()),
        });

        let meta = postprocess(&mut data, &input);

        // F5: repo paths are relative; the out-of-repo dbPath is untouched.
        assert_eq!(data["file"], "src/main.rs".replace('/', &sep().to_string()));
        assert_eq!(
            data["reachable"][0],
            "src/a.rs".replace('/', &sep().to_string())
        );
        assert_eq!(
            data["dbPath"],
            format!("{s}home{s}u{s}.config{s}index.db", s = sep())
        );
        assert_eq!(
            data["source"],
            format!("{root}{s}this is source text", s = sep())
        );
        assert!(meta.compact);
        assert!(!meta.truncated);

        // F6: byte/col dropped, line pair kept.
        let span = &data["location"]["span"];
        assert_eq!(span["start_line"], 2);
        assert_eq!(span["end_line"], 3);
        assert!(span.get("start_byte").is_none());
        assert!(span.get("end_byte").is_none());
        assert!(span.get("start_col").is_none());
        assert!(span.get("end_col").is_none());
    }

    #[test]
    fn absolute_paths_opt_out_keeps_prefix() {
        let root = format!("{s}abs{s}repo", s = sep());
        let input = json!({ "repoRoot": root, "absolutePaths": true });
        let abs = format!("{root}{s}src{s}main.rs", s = sep());
        let mut data = json!({ "file": abs });
        postprocess(&mut data, &input);
        assert_eq!(data["file"], format!("{root}{s}src{s}main.rs", s = sep()));
    }

    #[test]
    fn include_span_detail_opt_in_keeps_byte_and_col() {
        let input = json!({ "includeSpanDetail": true });
        let mut data = json!({
            "span": { "start_byte": 1, "end_byte": 2, "start_line": 1, "start_col": 0, "end_line": 1, "end_col": 5 }
        });
        postprocess(&mut data, &input);
        assert_eq!(data["span"]["start_byte"], 1);
        assert_eq!(data["span"]["end_col"], 5);
    }

    #[test]
    fn relativize_is_idempotent() {
        let root = format!("{s}abs{s}repo", s = sep());
        let input = json!({ "repoRoot": root });
        let mut data = json!({ "file": format!("{root}{s}src{s}main.rs", s = sep()) });
        postprocess(&mut data, &input);
        let once = data.clone();
        postprocess(&mut data, &input);
        assert_eq!(data, once);
    }

    #[test]
    fn reports_nav_map_truncation_in_metadata() {
        let input = json!({});
        let mut data = json!({
            "guide": { "truncated": { "symbols": { "shown": 1, "total": 2 } } }
        });

        let meta = postprocess(&mut data, &input);

        assert!(meta.truncated);
    }

    #[test]
    fn reports_batch_child_truncation_in_metadata() {
        let input = json!({});
        let mut data = json!([
            { "mode": "find_pattern", "meta": { "truncated": true } }
        ]);

        let meta = postprocess(&mut data, &input);

        assert!(meta.truncated);
    }

    #[test]
    fn query_array_pagination_reports_recovery_window() {
        let input = json!({ "resultsLimit": 2, "resultsOffset": 1 });
        let mut data = json!(["a", "b", "c", "d"]);
        let pagination = paginate_query("hotspots", &input, &mut data)
            .expect("pagination options are valid")
            .expect("array is truncated");

        assert_eq!(data, json!(["b", "c"]));
        assert_eq!(pagination["results"]["shown"], 2);
        assert_eq!(pagination["results"]["total"], 4);
        assert_eq!(pagination["results"]["next_offset"], 3);
    }

    #[test]
    fn query_arrays_are_bounded_by_default() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let input = json!({});
        let mut data = Value::Array((0..105).map(Value::from).collect());
        let pagination = paginate_query("hotspots", &input, &mut data)
            .expect("default pagination is valid")
            .expect("large array is truncated");

        assert_eq!(data.as_array().unwrap().len(), DEFAULT_QUERY_LIMIT);
        assert_eq!(pagination["results"]["total"], 105);
        assert_eq!(pagination["results"]["next_offset"], 100);
    }

    #[test]
    fn captured_query_uses_short_page_and_honors_explicit_limit() {
        use std::os::unix::fs::PermissionsExt;
        let dir = std::env::temp_dir().join(format!("varde-query-toz-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let bin = dir.join("toz");
        std::fs::write(&bin, "#!/bin/sh\ncat >/dev/null\necho '{\"handle\":\"test-handle\",\"preview\":\"src/a.rs: 110 items\"}'\n").unwrap();
        std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755)).unwrap();
        let _path = crate::test_support::PathOverride::new(&dir);
        let rows: Vec<Value> = (0..110)
            .map(|i| json!({"file":"src/a.rs","id":i}))
            .collect();
        let mut default_data = Value::Array(rows.clone());
        let pagination = paginate_query("hotspots", &json!({}), &mut default_data)
            .unwrap()
            .unwrap();
        assert_eq!(default_data.as_array().unwrap().len(), 20);
        assert_eq!(pagination["results"]["next_offset"], 20);
        assert_eq!(pagination["__toz"]["items"], 110);
        assert_eq!(pagination["__toz"]["toc"], "src/a.rs: 110 items");
        let mut explicit_data = Value::Array(rows);
        let explicit = paginate_query("hotspots", &json!({"resultsLimit":50}), &mut explicit_data)
            .unwrap()
            .unwrap();
        assert_eq!(explicit_data.as_array().unwrap().len(), 50);
        assert_eq!(explicit["__toz"]["handle"], "test-handle");

        let mut final_data = Value::Array((0..110).map(Value::from).collect());
        let final_page = paginate_query(
            "hotspots",
            &json!({"resultsOffset":100,"resultsLimit":20}),
            &mut final_data,
        )
        .unwrap()
        .unwrap();
        assert_eq!(final_data.as_array().unwrap().len(), 10);
        assert!(final_page["results"].get("toz_read").is_none());
        assert_eq!(
            final_page["results"]["toz_search"],
            "toz query --handle test-handle \"<term>\""
        );

        let mut context = json!({"files":[{"path":"a.rs"},{"path":"b.rs"},{"path":"c.rs"}],"symbols":[],"tests":[]});
        let context_page = paginate_query("context_pack", &json!({"resultsLimit":1}), &mut context)
            .unwrap()
            .unwrap();
        assert_eq!(context["files"].as_array().unwrap().len(), 1);
        assert_eq!(
            context_page["files"]["toz_read"],
            "toz query --handle test-handle --lines 2:2"
        );
    }

    #[test]
    fn context_pack_pagination_keeps_sections_on_selected_files() {
        let input = json!({ "resultsLimit": 1 });
        let mut data = json!({
            "files": [
                {"path": "a", "relevance": "seed"},
                {"path": "b", "relevance": "seed"}
            ],
            "symbols": [
                {"name": "s2", "filePath": "b"},
                {"name": "s1", "filePath": "a"}
            ],
            "tests": [
                {"path": "tb", "coversFile": "b"},
                {"path": "ta", "coversFile": "a"}
            ],
            "readingOrder": ["a", "b"]
        });
        let pagination = paginate_query("context_pack", &input, &mut data)
            .expect("pagination options are valid")
            .expect("sections are truncated");

        assert_eq!(data["files"], json!([{"path": "a", "relevance": "seed"}]));
        assert_eq!(data["symbols"], json!([{"name": "s1", "filePath": "a"}]));
        assert_eq!(data["tests"], json!([{"path": "ta", "coversFile": "a"}]));
        assert_eq!(data["readingOrder"], json!(["a"]));
        assert_eq!(pagination["files"]["total"], 2);
        assert!(pagination.get("symbols").is_none());
    }

    #[test]
    fn context_pack_budget_trims_file_window() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let budget = 150;
        let input = json!({ "maxTokensEstimate": budget });
        let mut data = context_pack_data(3);
        let pagination = paginate_query("context_pack", &input, &mut data)
            .expect("budget is valid")
            .expect("budget truncates the pack");
        assert!(pagination.get("budget").is_some());
        let envelope = render_context_envelope(data, &input, Some(pagination), None);
        let files = envelope["data"]["files"].as_array().unwrap();
        assert!(files.len() < 3);
        assert_eq!(
            envelope["data"]["readingOrder"].as_array().unwrap().len(),
            files.len()
        );
        assert!(estimated_envelope_tokens(&envelope) <= budget);
    }

    #[test]
    fn context_pack_budget_covers_standalone_and_batch_child_envelopes() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let budget = 250;
        for mode in [None, Some("context_pack")] {
            let input = json!({ "maxTokensEstimate": budget });
            let mut data = context_pack_data(8);
            let pagination = paginate_query_with_mode_tag("context_pack", &input, &mut data, mode)
                .expect("budget is valid");
            let envelope = render_context_envelope(data, &input, pagination, mode);

            assert_eq!(envelope["ok"], true);
            assert_eq!(envelope.get("mode").is_some(), mode.is_some());
            assert!(
                estimated_envelope_tokens(&envelope) <= budget,
                "{} tokens exceeds budget {budget}: {envelope}",
                estimated_envelope_tokens(&envelope)
            );
        }
    }

    #[test]
    fn context_pack_toz_preview_is_trimmed_and_recovery_is_preserved() {
        use std::os::unix::fs::PermissionsExt;

        let dir =
            std::env::temp_dir().join(format!("varde-context-budget-toz-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).expect("stub directory creates");
        let count_path = dir.join("capture-count");
        let input_path = dir.join("capture-input");
        let marker = format!("varde_context_budget_toz_probe_{}.rs", std::process::id());
        let preview = "x".repeat(6_000);
        let response = json!({
            "handle": "context-pack-handle",
            "preview": preview
        })
        .to_string();
        let quote = |value: &str| format!("'{}'", value.replace('\'', "'\\''"));
        let real_toz = std::env::var_os("PATH").and_then(|path| {
            std::env::split_paths(&path)
                .map(|directory| directory.join("toz"))
                .find(|candidate| candidate.is_file())
        });
        let fallback = real_toz
            .as_deref()
            .map(|path| {
                format!(
                    "{} \"$@\" < \"$input_path\"\nexit $?",
                    quote(path.to_str().unwrap())
                )
            })
            .unwrap_or_else(|| "exit 1".to_string());
        let script = format!(
            "#!/bin/sh\ninput_path={}.$$\ntrap 'rm -f \"$input_path\"' 0\ncat > \"$input_path\"\nif grep -F -- {} \"$input_path\" >/dev/null 2>&1; then\n  printf 'capture\\n' >> {}\n  printf '%s\\n' {}\n  exit 0\nfi\n{}\n",
            quote(input_path.to_str().unwrap()),
            quote(&marker),
            quote(count_path.to_str().unwrap()),
            quote(&response),
            fallback
        );
        let bin = dir.join("toz");
        std::fs::write(&bin, script).expect("stub writes");
        std::fs::set_permissions(&bin, std::fs::Permissions::from_mode(0o755))
            .expect("stub becomes executable");
        let _path = crate::test_support::PathOverride::new(&dir);
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "1") };

        let budget = 240;
        let input = json!({ "maxTokensEstimate": budget, "resultsLimit": 30 });
        let mut data = context_pack_data(30);
        data["files"][0]["path"] = json!(marker);
        data["readingOrder"][0] = json!(marker);
        let pagination =
            paginate_query("context_pack", &input, &mut data).expect("budget is valid");
        let envelope = render_context_envelope(data, &input, pagination, None);
        let files = envelope["data"]["files"].as_array().unwrap();
        assert!(!files.is_empty(), "context pack keeps at least one file");
        assert!(
            files.len() < 30,
            "oversized captured context should shrink its file window"
        );

        assert!(
            estimated_envelope_tokens(&envelope) <= budget,
            "{} tokens exceeds budget {budget}: {envelope}",
            estimated_envelope_tokens(&envelope)
        );
        assert_eq!(envelope["meta"]["toz"]["handle"], "context-pack-handle");
        assert_eq!(envelope["meta"]["toz"]["toc"], "");
        assert_eq!(
            envelope["meta"]["pagination"]["files"]["toz_search"],
            "toz query --handle context-pack-handle \"<term>\""
        );
        assert!(
            envelope["meta"]["pagination"]["files"]["toz_read"]
                .as_str()
                .is_some()
        );
        assert_eq!(
            std::fs::read_to_string(&count_path)
                .expect("capture count exists")
                .lines()
                .count(),
            1
        );
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn context_pack_stops_trimming_an_exhausted_toz_preview() {
        let mut reference = Some(json!({ "toc": "" }));

        assert!(!trim_context_preview(&mut reference));
        assert_eq!(reference, Some(json!({ "toc": "" })));
    }

    #[test]
    fn context_pack_reports_tests_omitted_from_the_selected_file_window() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let tests: Vec<Value> = (0..4)
            .map(|index| {
                json!({
                    "name": format!("large_test_{index}"),
                    "coversFile": "src/main.rs",
                    "excerpt": "x".repeat(700)
                })
            })
            .collect();
        let mut data = json!({
            "files": [{"path":"src/main.rs", "relevance":"seed"}],
            "symbols": [],
            "tests": tests,
            "readingOrder": ["src/main.rs"]
        });
        let budget = 300;
        let input = json!({ "maxTokensEstimate": budget });
        let pagination =
            paginate_query("context_pack", &input, &mut data).expect("budget is valid");
        let envelope = render_context_envelope(data, &input, pagination, None);
        let shown = envelope["data"]["tests"].as_array().unwrap();

        assert!(shown.len() < 4);
        assert_eq!(envelope["meta"]["pagination"]["tests"]["total"], 4);
        assert_eq!(
            envelope["meta"]["pagination"]["tests"]["shown"],
            shown.len()
        );
        assert!(shown.iter().all(|test| test["coversFile"] == "src/main.rs"));
        assert!(estimated_envelope_tokens(&envelope) <= budget);
    }

    #[test]
    fn context_pack_rejects_a_file_when_its_success_envelope_cannot_fit() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let input = json!({
            "maxTokensEstimate": 20,
            "includeReadingOrder": false
        });
        let mut data = json!({
            "files": [{"path":"a"}],
            "symbols": [],
            "tests": [],
            "readingOrder": ["a"]
        });

        let error = paginate_query("context_pack", &input, &mut data)
            .expect_err("the complete success envelope cannot fit");

        assert_eq!(error.code, "invalid_input");
    }

    #[test]
    fn context_pack_full_results_bypasses_budget_and_symbol_caps_after_offset() {
        let _without_toz = crate::test_support::PathOverride::without_toz();
        let mut data = json!({
            "files": [
                {"path":"a.rs", "relevance":"seed"},
                {"path":"b.rs", "relevance":"neighbor"},
                {"path":"c.rs", "relevance":"neighbor"}
            ],
            "symbols": [
                {"name":"a1", "filePath":"a.rs"},
                {"name":"b1", "filePath":"b.rs"},
                {"name":"b2", "filePath":"b.rs"},
                {"name":"c1", "filePath":"c.rs"},
                {"name":"c2", "filePath":"c.rs"}
            ],
            "tests": [
                {"name":"test_b", "coversFile":"b.rs"},
                {"name":"test_c", "coversFile":"c.rs"}
            ],
            "readingOrder": ["a.rs", "b.rs", "c.rs"]
        });
        let input = json!({
            "fullResults": true,
            "resultsLimit": 1,
            "resultsOffset": 1,
            "maxTokensEstimate": 1
        });

        let pagination = paginate_query("context_pack", &input, &mut data)
            .expect("tiny positive budget is valid")
            .expect("nonzero offset is reported");
        let envelope = render_context_envelope(data, &input, Some(pagination), None);

        assert_eq!(envelope["data"]["files"].as_array().unwrap().len(), 2);
        assert_eq!(envelope["data"]["files"][0]["path"], "b.rs");
        assert_eq!(envelope["data"]["symbols"].as_array().unwrap().len(), 4);
        assert_eq!(envelope["data"]["tests"].as_array().unwrap().len(), 2);
        assert_eq!(envelope["meta"]["pagination"]["files"]["offset"], 1);
        assert!(estimated_envelope_tokens(&envelope) > 1);
    }

    #[test]
    fn context_pack_can_omit_redundant_reading_order() {
        let input = json!({ "includeReadingOrder": false });
        let mut data = json!({
            "files": [{"path": "a.rs", "relevance": "seed"}],
            "symbols": [],
            "tests": [],
            "readingOrder": ["a.rs"]
        });
        assert!(
            paginate_query("context_pack", &input, &mut data)
                .expect("valid option")
                .is_none()
        );
        assert_eq!(data["readingOrder"], json!([]));
        assert_eq!(data["files"][0]["path"], "a.rs");
    }

    #[test]
    fn context_pack_rejects_budget_below_minimum() {
        let input = json!({ "maxTokensEstimate": 1, "resultsOffset": 5 });
        let mut data = json!({
            "files": [],
            "symbols": [],
            "tests": [],
            "readingOrder": []
        });
        let error = paginate_query("context_pack", &input, &mut data)
            .expect_err("empty pack cannot fit the requested budget");
        assert_eq!(error.code, "invalid_input");
    }

    #[test]
    fn context_pack_bounds_symbols_per_file() {
        let input = json!({});
        let mut data = json!({
            "files": [
                {"path": "dense.rs", "relevance": "seed"},
                {"path": "other.rs", "relevance": "seed"}
            ],
            "symbols": (0..20).map(|index| json!({
                "name": format!("dense_symbol_{index}"),
                "filePath": "dense.rs"
            })).collect::<Vec<_>>(),
            "tests": [],
            "readingOrder": ["dense.rs", "other.rs"]
        });
        let pagination = paginate_query("context_pack", &input, &mut data)
            .expect("valid input")
            .expect("symbol cap is reported");
        assert_eq!(data["files"].as_array().unwrap().len(), 2);
        assert_eq!(data["symbols"].as_array().unwrap().len(), 5);
        assert_eq!(pagination["symbols"]["total"], 20);
        assert_eq!(pagination["symbols"]["shown"], 5);
    }

    #[test]
    fn symbols_in_files_pagination_bounds_the_aggregate() {
        let input = json!({ "resultsLimit": 2, "resultsOffset": 1 });
        let mut data = json!({
            "a.rs": ["a1", "a2"],
            "b.rs": ["b1", "b2"]
        });
        let pagination = paginate_query("symbols_in_files", &input, &mut data)
            .expect("pagination options are valid")
            .expect("aggregate is truncated");

        assert_eq!(data["a.rs"], json!(["a2"]));
        assert_eq!(data["b.rs"], json!(["b1"]));
        assert_eq!(pagination["results"]["shown"], 2);
        assert_eq!(pagination["results"]["total"], 4);
    }

    #[test]
    fn preprocessed_render_preserves_payload_and_reports_metadata() {
        let root = format!("{s}abs{s}repo", s = sep());
        let input = json!({ "repoRoot": root });
        let file = format!("{root}{s}src{s}main.rs", s = sep());
        let payload = json!({
            "file": file.clone(),
            "span": {
                "start_byte": 1,
                "end_byte": 2,
                "start_line": 1,
                "start_col": 0,
                "end_line": 1,
                "end_col": 5
            }
        });

        let envelope = render_value_with_preprocessed_input(Ok(payload), &input);

        assert_eq!(envelope["data"]["file"], file);
        assert_eq!(envelope["data"]["span"]["start_byte"], 1);
        assert_eq!(envelope["meta"]["compact"], true);
    }

    #[test]
    fn dbpath_only_call_without_reporoot_leaves_paths_alone() {
        // No repoRoot → we can't know the prefix, so paths pass through as-is
        // (spans still trim).
        let input = json!({ "dbPath": "/tmp/x.db" });
        let abs = format!("{s}abs{s}repo{s}src{s}main.rs", s = sep());
        let mut data = json!({ "file": abs.clone() });
        postprocess(&mut data, &input);
        assert_eq!(data["file"], abs);
    }
}
