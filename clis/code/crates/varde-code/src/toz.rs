//! Shared toz (tool-output-zone) capture helper.
//!
//! Centralizes the "hand text to the toz capture contract, any failure ->
//! `None`" convention. `run_nav_map` (`lib.rs`) uses this to offload the full,
//! unbudgeted `nav_map` text render behind a toz handle; truncated JSON result
//! lists use `capture_items`. The capture implementation is process-scoped:
//! the app crate installs it with [`install_capture`] before any query runs.

use serde_json::{Value, json};
use std::sync::{Mutex, mpsc};
use std::time::Duration;
use varde_contracts::{CaptureInput, OutputCapture};

pub const PAGE_LIMIT: usize = 20;

/// The installed capture implementation; `None` means toz capture is unavailable.
static CAPTURE: Mutex<Option<&'static dyn OutputCapture>> = Mutex::new(None);

/// Install the process-scoped capture implementation (`None` removes it).
pub fn install_capture(capture: Option<&'static dyn OutputCapture>) {
    *CAPTURE.lock().unwrap_or_else(|poison| poison.into_inner()) = capture;
}

pub(crate) fn installed() -> Option<&'static dyn OutputCapture> {
    *CAPTURE.lock().unwrap_or_else(|poison| poison.into_inner())
}

/// A reference to a complete JSONL result set stored in toz.
pub fn capture_items(mode: &str, items: &[Value]) -> Option<Value> {
    if !available() {
        return None;
    }
    let source = format!("varde map results {mode}");
    let lines: Vec<String> = items.iter().map(Value::to_string).collect();
    let stdout = capture_bounded(CaptureRequest::Items(lines), source, mode.to_string())?;
    let response: Value = serde_json::from_str(&stdout).ok()?;
    let handle = response.get("handle")?.as_str()?;
    Some(
        json!({"handle": handle, "items": items.len(), "format": "jsonl", "toc": compact_toc(&response)}),
    )
}

/// Bound the inline TOC even when a result spans hundreds of files.
fn compact_toc(response: &Value) -> Value {
    let Some(entries) = response.get("toc").and_then(Value::as_array) else {
        return response.get("preview").cloned().unwrap_or(Value::Null);
    };
    let mut out = String::new();
    for (index, entry) in entries.iter().enumerate() {
        let title = entry["title"].as_str().unwrap_or("other");
        let items = entry["items"].as_u64().unwrap_or(0);
        let start = entry["line_start"].as_u64().unwrap_or(0);
        let end = entry["line_end"].as_u64().unwrap_or(0);
        let line = format!("{title}: {items} items (L{start}-L{end})\n");
        if out.len() + line.len() > 3_800 {
            out.push_str(&format!(
                "... {} more file sections; query the handle for all results",
                entries.len() - index
            ));
            break;
        }
        out.push_str(&line);
    }
    Value::String(out)
}

pub fn add_guide(guide: &mut Value, reference: &Value, start: usize, end: usize) {
    let Some(handle) = reference["handle"].as_str() else {
        return;
    };
    if start < end {
        guide["toz_read"] = json!(format!(
            "varde run query --handle {handle} --lines {}:{}",
            start + 1,
            end
        ));
    }
    guide["toz_search"] = json!(format!("varde run query --handle {handle} \"<term>\""));
}

/// How long [`capture_text`] waits for the capture to finish before giving up
/// and falling back to `None`. A stalled toz (e.g. a store lock's
/// `busy_timeout`) must never hang the caller — most callers run inside a
/// session-start hook.
const CAPTURE_TIMEOUT: Duration = Duration::from_secs(5);

/// Capture `text` to toz through the installed [`OutputCapture`].
///
/// Returns toz's preview text when the capture succeeds and that text
/// contains `"handle"` — evidence toz actually stored the capture. Any other
/// outcome (no capture installed, a failed capture, no `"handle"` in the
/// preview, or the capture running past [`CAPTURE_TIMEOUT`]) returns `None` so
/// the caller falls back to its own rendering.
///
/// `VARDE_CODE_TOZ=0` skips the capture entirely, so callers that don't want
/// the cost (tests, environments without toz) can opt out.
pub fn capture_text(source: &str, label: &str, text: &str) -> Option<String> {
    capture_text_with_timeout(source, label, text, CAPTURE_TIMEOUT)
}

fn capture_text_with_timeout(
    source: &str,
    label: &str,
    text: &str,
    timeout: Duration,
) -> Option<String> {
    capture_with_timeout(
        CaptureRequest::Text(text.to_string()),
        source.to_string(),
        label.to_string(),
        timeout,
    )
}

fn capture_bounded(request: CaptureRequest, source: String, label: String) -> Option<String> {
    capture_with_timeout(request, source, label, CAPTURE_TIMEOUT)
}

enum CaptureRequest {
    Text(String),
    Items(Vec<String>),
}

/// Run the installed capture on a worker thread and wait at most `timeout`.
/// A late result is dropped; the worker finishes on its own.
fn capture_with_timeout(
    request: CaptureRequest,
    source: String,
    label: String,
    timeout: Duration,
) -> Option<String> {
    if !enabled() {
        return None;
    }
    let capture = installed()?;
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let input = match &request {
            CaptureRequest::Text(text) => CaptureInput::Text(text),
            CaptureRequest::Items(items) => CaptureInput::Items(items),
        };
        let _ = tx.send(capture.capture(input, &source, &label));
    });
    let stdout = rx.recv_timeout(timeout).ok()??;
    stdout.contains("handle").then_some(stdout)
}

/// Whether toz capture should be attempted at all. Callers that also need to
/// skip the (potentially expensive) work of building the text to capture
/// check this before doing that work, rather than only inside
/// [`capture_text`].
pub fn enabled() -> bool {
    std::env::var("VARDE_CODE_TOZ").as_deref() != Ok("0")
}

/// Cheap preflight for call sites that would otherwise retain an unbounded
/// result set during a search. Called once per query, never once per file.
pub fn available() -> bool {
    enabled() && installed().is_some()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::CaptureOverride;
    use std::sync::{Arc, Mutex};

    #[test]
    fn capture_items_sends_jsonl_lines_and_labels_the_capture() {
        let seen = Arc::new(Mutex::new(None));
        let sink = Arc::clone(&seen);
        let _override = CaptureOverride::with(move |input, source, label| {
            let CaptureInput::Items(lines) = input else {
                return None;
            };
            *sink.lock().unwrap() = Some((lines.to_vec(), source.to_string(), label.to_string()));
            Some("{\"handle\":\"ab12\",\"toc\":[]}".to_string())
        });
        let payload = "x".repeat(256 * 1024);
        let items = vec![json!({"payload": payload})];

        let result = capture_items("query", &items).expect("capture returns a handle");

        assert_eq!(result["handle"], "ab12");
        assert_eq!(result["items"], 1);
        let (lines, source, label) = seen.lock().unwrap().take().expect("fake was called");
        assert_eq!(
            lines,
            vec![format!("{{\"payload\":\"{}\"}}", "x".repeat(256 * 1024))]
        );
        assert_eq!(source, "varde map results query");
        assert_eq!(label, "query");
    }

    #[test]
    fn capture_items_returns_none_on_capture_failure() {
        let _override = CaptureOverride::with(|_, _, _| None);
        let items = vec![json!({"payload": "x".repeat(256 * 1024)})];

        assert_eq!(capture_items("query", &items), None);
    }

    #[test]
    fn toc_summary_is_bounded_for_many_files() {
        let entries: Vec<Value> = (0..200).map(|i| json!({"title": format!("src/very-long-module-{i}.rs"), "items": 7, "line_start": i*7+1, "line_end": (i+1)*7})).collect();
        let toc = compact_toc(&json!({"toc": entries}));
        let text = toc.as_str().unwrap();
        assert!(text.len() <= 4_000, "{} bytes", text.len());
        assert!(text.contains("src/very-long-module-0.rs: 7 items"));
        assert!(text.contains("more file sections"));
    }

    /// A capture that succeeds (preview contains `"handle"`) returns that
    /// preview and receives the given text.
    #[test]
    fn capture_text_returns_preview_on_success_and_passes_the_text() {
        let seen = Arc::new(Mutex::new(String::new()));
        let sink = Arc::clone(&seen);
        let _override = CaptureOverride::with(move |input, _, _| {
            if let CaptureInput::Text(text) = input {
                *sink.lock().unwrap() = text.to_string();
            }
            Some("toz: captured 12 bytes -> handle ab12\n".to_string())
        });

        let result = capture_text("varde map nav_map /repo", "nav_map", "## entrypoints\n");

        assert_eq!(
            result.as_deref(),
            Some("toz: captured 12 bytes -> handle ab12\n")
        );
        assert_eq!(*seen.lock().unwrap(), "## entrypoints\n");
    }

    #[test]
    fn capture_text_returns_none_on_failed_capture() {
        let _override = CaptureOverride::with(|_, _, _| None);

        assert_eq!(capture_text("src", "nav_map", "text"), None);
    }

    /// A successful-looking preview without `"handle"` is treated as no capture.
    #[test]
    fn capture_text_returns_none_without_handle_in_preview() {
        let _override = CaptureOverride::with(|_, _, _| Some("ok\n".to_string()));

        assert_eq!(capture_text("src", "nav_map", "text"), None);
    }

    /// `VARDE_CODE_TOZ=0` skips the capture entirely: the fake is never called.
    #[test]
    fn capture_text_skips_capture_when_disabled_by_env() {
        let called = Arc::new(Mutex::new(false));
        let sink = Arc::clone(&called);
        let _override = CaptureOverride::with(move |_, _, _| {
            *sink.lock().unwrap() = true;
            Some("handle\n".to_string())
        });
        unsafe { std::env::set_var("VARDE_CODE_TOZ", "0") };

        assert_eq!(capture_text("src", "nav_map", "text"), None);
        assert!(!*called.lock().unwrap());
    }

    /// No capture implementation installed returns `None` rather than panicking.
    #[test]
    fn capture_text_returns_none_when_no_capture_is_installed() {
        let _override = CaptureOverride::none();

        assert_eq!(capture_text("src", "nav_map", "text"), None);
        assert!(!available());
    }

    /// A capture that stalls past the timeout yields `None`, without the test
    /// itself waiting anywhere near the stall duration.
    #[test]
    fn capture_text_returns_none_when_capture_stalls_past_timeout() {
        let _override = CaptureOverride::with(|_, _, _| {
            std::thread::sleep(Duration::from_secs(3));
            Some("handle\n".to_string())
        });

        let start = std::time::Instant::now();
        let result =
            capture_text_with_timeout("src", "nav_map", "text", Duration::from_millis(200));
        assert_eq!(result, None);
        assert!(
            start.elapsed() < Duration::from_secs(2),
            "took {:?}",
            start.elapsed()
        );
    }
}
