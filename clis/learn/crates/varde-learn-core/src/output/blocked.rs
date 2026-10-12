//! Detect runs that could not produce a meaningful evaluation.

use serde_json::Value;

/// Return the first blocking condition found in setup output or the harness
/// trace. Keep the reason stable for the per-run artifact.
pub(super) fn classify(
    trace: Option<&Value>,
    trace_error: Option<&str>,
    setup_error: Option<&str>,
    stderr: Option<&str>,
) -> Option<&'static str> {
    if setup_error.is_some() {
        return Some("fixture_setup_failure");
    }

    let trace_text = trace_error.unwrap_or_default().to_lowercase();
    let stderr = stderr.unwrap_or_default().to_lowercase();
    let error_event = trace
        .and_then(|value| {
            let is_error = value.get("is_error").and_then(Value::as_bool) == Some(true)
                || value.get("type").and_then(Value::as_str) == Some("error")
                || value.get("type").and_then(Value::as_str) == Some("turn.failed");
            is_error.then(|| {
                serde_json::to_string(value)
                    .unwrap_or_default()
                    .to_lowercase()
            })
        })
        .unwrap_or_default();
    let trace = format!("{trace_text} {stderr} {error_event}");

    if contains_any(
        &trace,
        &[
            "sandbox denied",
            "sandbox denial",
            "operation not permitted",
        ],
    ) {
        Some("sandbox_denial")
    } else if contains_any(
        &trace,
        &[
            "reviewer failed to launch",
            "reviewer launch failed",
            "failed to launch reviewer",
        ],
    ) {
        Some("reviewer_launch_failure")
    } else if contains_any(
        &trace,
        &["stale approval", "approval is stale", "approval expired"],
    ) {
        Some("stale_approval")
    } else if contains_any(
        &trace,
        &[
            "tool failed to launch",
            "tool launch failed",
            "failed to launch tool",
        ],
    ) {
        Some("tool_launch_failure")
    } else if contains_any(
        &trace,
        &[
            "application unavailable",
            "app unavailable",
            "command not found",
            "failed to launch",
        ],
    ) {
        Some("unavailable_app")
    } else {
        None
    }
}

fn contains_any(text: &str, needles: &[&str]) -> bool {
    needles.iter().any(|needle| text.contains(needle))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn classifies_blocked_trace_fixtures_and_setup_results() {
        let fixtures = [
            ("sandbox denial", "sandbox_denial"),
            ("reviewer failed to launch", "reviewer_launch_failure"),
            ("tool failed to launch", "tool_launch_failure"),
            ("stale approval", "stale_approval"),
            ("application unavailable", "unavailable_app"),
        ];
        for (message, reason) in fixtures {
            assert_eq!(
                classify(
                    Some(&json!({"is_error": true, "result": message})),
                    None,
                    None,
                    None
                ),
                Some(reason),
                "fixture: {message}"
            );
        }
        assert_eq!(
            classify(None, None, Some("setup_script failed"), None),
            Some("fixture_setup_failure")
        );
        assert_eq!(
            classify(
                Some(
                    &json!({"type":"result", "is_error": false, "result": "sandbox denial operation not permitted"})
                ),
                None,
                None,
                None
            ),
            None
        );
        assert_eq!(
            classify(None, None, None, Some("operation not permitted")),
            Some("sandbox_denial")
        );
    }
}
