//! The versioned machine-output envelope shared by the workflow and learn CLIs.

use serde_json::{Value, json};

/// Value of both `schema_version` and `envelope_version`.
pub const ENVELOPE_VERSION: u64 = 1;

fn envelope(ok: bool, outcome: &str, data: Value, meta: Value) -> Value {
    json!({
        "schema_version": ENVELOPE_VERSION,
        "envelope_version": ENVELOPE_VERSION,
        "ok": ok,
        "outcome": outcome,
        "data": data,
        "meta": meta,
    })
}

/// A successful result carrying `data` and `meta`.
pub fn success(data: Value, meta: Value) -> Value {
    envelope(true, "success", data, meta)
}

/// A negative result (`ok: false`) whose error carries structured `details`.
pub fn negative_result(code: &str, message: &str, details: Value, meta: Value) -> Value {
    let error = json!({ "code": code, "message": message, "details": details });
    envelope(false, "negative-result", json!({ "error": error }), meta)
}

/// A tool error with the default `meta` of `{"truncated": false}`.
pub fn tool_error(code: &str, message: &str) -> Value {
    let error = json!({ "code": code, "message": message });
    envelope(
        false,
        "tool-error",
        json!({ "error": error }),
        json!({ "truncated": false }),
    )
}
