//! Implementations of the `varde-contracts` traits over the module crates.
//! This is the only place the modules meet; each module sees only the traits.

use serde_json::{Value, json};
use std::collections::HashSet;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use varde_contracts::{CaptureInput, ContractError, ImpactQuery, Io, OutputCapture, RepoMap};

/// Session-start repo map from `varde map nav_map --format text`.
struct CodeRepoMap;

impl RepoMap for CodeRepoMap {
    fn repo_map_text(&self, repo_root: &Path) -> Result<String, ContractError> {
        let input = json!({"repoRoot": repo_root}).to_string();
        let text = varde_code::nav_map_text(&input, true);
        match error_envelope_code(&text) {
            Some(code) => Err(ContractError {
                code: Some(code),
                message: text,
            }),
            None => Ok(text),
        }
    }
}

/// The error code (or "error") when `text` is a JSON object with `"ok": false`.
fn error_envelope_code(text: &str) -> Option<String> {
    let value: Value = serde_json::from_str(text.trim()).ok()?;
    if value.get("ok") != Some(&json!(false)) {
        return None;
    }
    let code = value["data"]["error"]["code"].as_str();
    Some(code.unwrap_or("error").to_string())
}

/// File dependents from `varde map blast_radius`.
struct CodeImpact;

impl ImpactQuery for CodeImpact {
    fn dependents(&self, repo_root: &Path, file: &Path) -> Option<Vec<PathBuf>> {
        let payload = json!({"repoRoot": repo_root, "filePath": file, "fullResults": true});
        let input = payload.to_string();
        dependents_with_retry(
            &repo_root.to_string_lossy(),
            || varde_code::query::run_mode("blast_radius", &input),
            |root| varde_code::build::run(root).map(|_| ()).map_err(|_| ()),
        )
    }
}

static INDEX_BUILD_ATTEMPTS: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();

/// Query dependents, building a missing index at most once per repository.
fn dependents_with_retry(
    repo_root: &str,
    mut query: impl FnMut() -> String,
    build: impl FnOnce(&str) -> Result<(), ()>,
) -> Option<Vec<PathBuf>> {
    let envelope = query();
    if error_envelope_code(&envelope).as_deref() != Some("index_missing") {
        return dependents_from_envelope(&envelope);
    }

    let attempts = INDEX_BUILD_ATTEMPTS.get_or_init(|| Mutex::new(HashSet::new()));
    let first_attempt = attempts
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .insert(repo_root.to_owned());
    if !first_attempt || build(repo_root).is_err() {
        return None;
    }

    dependents_from_envelope(&query())
}

/// The dependent paths in a `blast_radius` envelope; `None` for anything that
/// is not a complete, successful result (an error, a truncated list, bad JSON).
fn dependents_from_envelope(envelope: &str) -> Option<Vec<PathBuf>> {
    let result: Value = serde_json::from_str(envelope).ok()?;
    if result["ok"] != true
        || result["data"].get("error").is_some()
        || result.pointer("/meta/truncated").and_then(Value::as_bool) == Some(true)
    {
        return None;
    }
    result["data"]
        .as_array()?
        .iter()
        .map(|value| value.as_str().map(PathBuf::from))
        .collect()
}

/// `find_pattern` results defer full-text indexing until first search.
fn defers_index(label: &str) -> bool {
    label == "find_pattern"
}

/// Stores output in toz, as `varde run capture --force` does.
struct TozCapture;

impl OutputCapture for TozCapture {
    fn capture(&self, input: CaptureInput<'_>, source: &str, label: &str) -> Option<String> {
        let stored = match input {
            CaptureInput::Text(text) => {
                varde_toz::capture_forced(&mut text.as_bytes(), source, label, false, false)
            }
            CaptureInput::Items(items) => {
                let jsonl: String = items.iter().map(|item| format!("{item}\n")).collect();
                let defer_index = defers_index(label);
                varde_toz::capture_forced(&mut jsonl.as_bytes(), source, label, true, defer_index)
            }
        };
        stored.ok().flatten()
    }
}

static REPO_MAP: CodeRepoMap = CodeRepoMap;
static IMPACT: CodeImpact = CodeImpact;
static CAPTURE: TozCapture = TozCapture;

/// The full `Io`, shared by every legacy binary. Also installs the capture
/// for `varde-code`'s result offloading, which runs below the `Io` plumbing.
pub fn io() -> Io<'static> {
    varde_code::toz::install_capture(Some(&CAPTURE));
    Io {
        repo_map: Some(&REPO_MAP),
        impact: Some(&IMPACT),
        capture: Some(&CAPTURE),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_find_pattern_captures_defer_indexing() {
        assert!(defers_index("find_pattern"));
        for label in ["blast_radius", "nav_map", "find_references", ""] {
            assert!(!defers_index(label), "{label}");
        }
    }

    #[test]
    fn dependents_are_read_from_a_successful_envelope() {
        assert_eq!(
            dependents_from_envelope(r#"{"ok":true,"data":["src/a","src/b"]}"#),
            Some(vec![PathBuf::from("src/a"), PathBuf::from("src/b")])
        );
        assert_eq!(
            dependents_from_envelope(r#"{"ok":true,"data":[]}"#),
            Some(Vec::new())
        );
    }

    #[test]
    fn malformed_failed_or_truncated_envelopes_are_unknown() {
        for envelope in [
            "broken",
            r#"{"ok":true,"data":{}}"#,
            r#"{"ok":true,"data":[42]}"#,
            r#"{"ok":true,"data":[],"meta":{"truncated":true}}"#,
            r#"{"ok":false,"data":{"error":{"code":"index_stale"}}}"#,
            r#"{"ok":true,"data":{"error":{"code":"x"}}}"#,
        ] {
            assert_eq!(dependents_from_envelope(envelope), None, "{envelope}");
        }
    }

    #[test]
    fn error_envelope_code_reads_the_code_or_falls_back_to_error() {
        assert_eq!(
            error_envelope_code(r#"{"ok":false,"data":{"error":{"code":"invalid_input"}}}"#)
                .as_deref(),
            Some("invalid_input")
        );
        assert_eq!(
            error_envelope_code(r#"{"ok":false}"#).as_deref(),
            Some("error")
        );
    }

    #[test]
    fn json_looking_text_without_ok_false_is_not_an_error() {
        assert_eq!(error_envelope_code(r#"{"note":"map"}"#), None);
        assert_eq!(error_envelope_code("## Repository outline"), None);
    }

    #[test]
    fn index_missing_retries_once_after_build() {
        let queries = std::cell::Cell::new(0);
        let builds = std::cell::Cell::new(0);
        let result = dependents_with_retry(
            "test-index-missing-success",
            || {
                if queries.replace(queries.get() + 1) == 0 {
                    r#"{"ok":false,"data":{"error":{"code":"index_missing"}}}"#.to_string()
                } else {
                    r#"{"ok":true,"data":["src/a"]}"#.to_string()
                }
            },
            |_| {
                builds.set(builds.get() + 1);
                Ok(())
            },
        );
        assert_eq!(result, Some(vec![PathBuf::from("src/a")]));
        assert_eq!(queries.get(), 2);
        assert_eq!(builds.get(), 1);
    }

    #[test]
    fn index_missing_with_failed_build_returns_none() {
        let queries = std::cell::Cell::new(0);
        let builds = std::cell::Cell::new(0);
        let result = dependents_with_retry(
            "test-index-missing-failed-build",
            || {
                queries.set(queries.get() + 1);
                r#"{"ok":false,"data":{"error":{"code":"index_missing"}}}"#.to_string()
            },
            |_| {
                builds.set(builds.get() + 1);
                Err(())
            },
        );
        assert_eq!(result, None);
        assert_eq!(queries.get(), 1);
        assert_eq!(builds.get(), 1);
    }

    #[test]
    fn other_errors_and_first_try_success_do_not_build() {
        let builds = std::cell::Cell::new(0);
        let other = dependents_with_retry(
            "test-other-error",
            || r#"{"ok":false,"data":{"error":{"code":"index_stale"}}}"#.to_string(),
            |_| {
                builds.set(builds.get() + 1);
                Ok(())
            },
        );
        assert_eq!(other, None);
        let success = dependents_with_retry(
            "test-initial-success",
            || r#"{"ok":true,"data":["src/b"]}"#.to_string(),
            |_| {
                builds.set(builds.get() + 1);
                Ok(())
            },
        );
        assert_eq!(success, Some(vec![PathBuf::from("src/b")]));
        assert_eq!(builds.get(), 0);
    }

    #[test]
    fn failed_build_is_not_repeated_for_same_repo() {
        let builds = std::cell::Cell::new(0);
        for _ in 0..2 {
            let result = dependents_with_retry(
                "test-repeat-failed-build",
                || r#"{"ok":false,"data":{"error":{"code":"index_missing"}}}"#.to_string(),
                |_| {
                    builds.set(builds.get() + 1);
                    Err(())
                },
            );
            assert_eq!(result, None);
        }
        assert_eq!(builds.get(), 1);
    }
}
