//! Stable machine-readable output for every CLI command.

use anyhow::Result;
use serde_json::{Value, json};

pub const ENVELOPE_VERSION: u64 = 1;

pub fn page_bounds(total: usize, offset: usize, limit: usize, all: bool) -> (usize, usize) {
    let start = offset.min(total);
    let end = if all {
        total
    } else {
        start.saturating_add(limit).min(total)
    };
    (start, end)
}

pub fn pagination_meta(total: usize, start: usize, end: usize, limit: usize, all: bool) -> Value {
    json!({
        "truncated": end < total,
        "pagination": {
            "total": total,
            "returned": end.saturating_sub(start),
            "offset": start,
            "limit": if all { Value::Null } else { json!(limit) },
            "truncated": end < total,
            "next_offset": if end < total { json!(end) } else { Value::Null },
        }
    })
}

pub fn print_success(data: Value) -> Result<()> {
    print_success_with_meta(data, json!({ "truncated": false }))
}

pub fn print_success_with_meta(data: Value, meta: Value) -> Result<()> {
    println!(
        "{}",
        json!({
            "schema_version": ENVELOPE_VERSION,
            "envelope_version": ENVELOPE_VERSION,
            "ok": true,
            "outcome": "success",
            "data": data,
            "meta": meta,
        })
    );
    Ok(())
}

pub fn print_error(code: &str, message: String) {
    eprintln!(
        "{}",
        json!({
            "schema_version": ENVELOPE_VERSION,
            "envelope_version": ENVELOPE_VERSION,
            "ok": false,
            "outcome": "tool-error",
            "data": {
                "error": {
                    "code": code,
                    "message": message,
                },
            },
            "meta": { "truncated": false },
        })
    );
}

pub fn print_failure(code: &str, message: &str, details: Value) {
    print_failure_with_meta(code, message, details, json!({ "truncated": false }));
}

pub fn print_failure_with_meta(code: &str, message: &str, details: Value, meta: Value) {
    println!(
        "{}",
        json!({
            "schema_version": ENVELOPE_VERSION,
            "envelope_version": ENVELOPE_VERSION,
            "ok": false,
            "outcome": "negative-result",
            "data": {
                "error": {
                    "code": code,
                    "message": message,
                    "details": details,
                },
            },
            "meta": meta,
        })
    );
}
