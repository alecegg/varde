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
pub(crate) fn paginate_query(
    mode: &str,
    input: &Value,
    data: &mut Value,
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
        "context_pack" => paginate_context_pack(input, data, options),
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
) -> Result<Option<Value>, super::ApiError> {
    // Measure the same compact representation the caller receives. The normal
    // output pass is idempotent and runs again after pagination.
    postprocess(data, input);
    let files = data["files"].as_array().cloned().unwrap_or_default();
    let mut reference = capture_page("context_pack", &files, options);
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
    let selection = select_context_window(
        &files,
        &symbols,
        &tests,
        start,
        end,
        max_tokens,
        options.full,
        include_reading_order,
    )?;
    if reference.is_none() && !options.full && selection.end < total {
        reference = crate::toz::capture_items("context_pack", &files);
    }
    let unchanged = start == 0
        && selection.end == total
        && !selection.budget_trimmed
        && selection.symbol_shown == selection.symbol_total;
    let sections = (!unchanged)
        .then(|| context_sections(total, start, &selection, options, max_tokens, reference));
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
}

#[allow(clippy::too_many_arguments)] // Existing compact pagination boundary; preserve its call contract.
fn select_context_window(
    files: &[Value],
    symbols: &[Value],
    tests: &[Value],
    start: usize,
    mut end: usize,
    max_tokens: usize,
    full: bool,
    include_reading_order: bool,
) -> Result<ContextSelection, super::ApiError> {
    let mut budget_trimmed = false;
    let symbols_per_file = (max_tokens / 800).max(1);
    loop {
        let (mut candidate, symbol_total) = context_candidate(
            &files[start..end],
            symbols,
            tests,
            symbols_per_file,
            full,
            include_reading_order,
        );
        if !full && end == start + 1 {
            budget_trimmed |= trim_single_file(&mut candidate, max_tokens)?;
        }
        if full || estimated_tokens(&candidate) <= max_tokens {
            return Ok(ContextSelection {
                symbol_shown: candidate["symbols"].as_array().map_or(0, Vec::len),
                data: candidate,
                end,
                budget_trimmed,
                symbol_total,
            });
        }
        if end == start {
            return Err(super::ApiError::new(
                "invalid_input",
                "maxTokensEstimate cannot hold an empty context pack",
            ));
        }
        end -= 1;
        budget_trimmed = true;
    }
}

fn context_candidate(
    selected: &[Value],
    symbols: &[Value],
    tests: &[Value],
    symbols_per_file: usize,
    full: bool,
    include_reading_order: bool,
) -> (Value, usize) {
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
    )
}

fn estimated_tokens(candidate: &Value) -> usize {
    serde_json::to_string(candidate)
        .map(|text| text.len() / 4)
        .unwrap_or(0)
}

fn trim_single_file(candidate: &mut Value, max_tokens: usize) -> Result<bool, super::ApiError> {
    let mut trimmed = false;
    while estimated_tokens(candidate) > max_tokens {
        let removed = candidate["symbols"]
            .as_array_mut()
            .and_then(Vec::pop)
            .or_else(|| candidate["tests"].as_array_mut().and_then(Vec::pop));
        if removed.is_none() {
            return Err(super::ApiError::new(
                "invalid_input",
                "maxTokensEstimate cannot hold one context file",
            ));
        }
        trimmed = true;
    }
    Ok(trimmed)
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
        let input = json!({ "maxTokensEstimate": 40 });
        let mut data = json!({
            "files": [
                {"path": "a.rs", "relevance": "seed"},
                {"path": "b.rs", "relevance": "neighbor"},
                {"path": "c.rs", "relevance": "neighbor"}
            ],
            "symbols": [],
            "tests": [],
            "readingOrder": ["a.rs", "b.rs", "c.rs"]
        });
        let pagination = paginate_query("context_pack", &input, &mut data)
            .expect("budget is valid")
            .expect("budget truncates the pack");
        assert!(data["files"].as_array().unwrap().len() < 3);
        assert_eq!(
            data["readingOrder"].as_array().unwrap().len(),
            data["files"].as_array().unwrap().len()
        );
        assert!(serde_json::to_string(&data).unwrap().len() / 4 <= 40);
        assert!(pagination.get("budget").is_some());
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
