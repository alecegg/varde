//! Fixture-backed assertions evaluated against the completed run sandbox.

use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

use serde_json::{Value, json};

/// Evaluate assertions in declaration order. Supported fields are `path` and
/// `contains` for file assertions, `exit_code` for command_exit, `events` for
/// transcript event_order, and `allowed_paths` for no_write_outside.
pub(super) fn verify(
    assertions: &[Value],
    sandbox: &Path,
    transcript: &str,
    before: &BTreeMap<PathBuf, Vec<u8>>,
) -> Vec<Value> {
    assertions
        .iter()
        .map(|assertion| {
            let kind = assertion
                .get("kind")
                .and_then(Value::as_str)
                .unwrap_or("unknown");
            let (passed, evidence) = match kind {
                "file_contains" => {
                    let path = assertion.get("path").and_then(Value::as_str).unwrap_or("");
                    let expected = assertion
                        .get("contains")
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    let result =
                        safe_path(sandbox, path).and_then(|path| fs::read_to_string(path).ok());
                    let pass = result
                        .as_deref()
                        .is_some_and(|text| text.contains(expected));
                    (
                        pass,
                        if pass {
                            "file contains expected text"
                        } else {
                            "file does not contain expected text"
                        },
                    )
                }
                "file_absent" => {
                    let path = assertion.get("path").and_then(Value::as_str).unwrap_or("");
                    let absent = safe_path(sandbox, path).is_some_and(|path| !path.exists());
                    (
                        absent,
                        if absent {
                            "file is absent"
                        } else {
                            "file exists or path is invalid"
                        },
                    )
                }
                "command_exit" => {
                    let expected = assertion
                        .get("exit_code")
                        .and_then(Value::as_i64)
                        .unwrap_or(0) as i32;
                    let command = assertion
                        .get("command")
                        .and_then(Value::as_str)
                        .unwrap_or("");
                    let actual = std::process::Command::new("sh")
                        .args(["-c", command])
                        .current_dir(sandbox)
                        .status()
                        .ok()
                        .and_then(|status| status.code());
                    let pass = !command.is_empty() && actual == Some(expected);
                    (
                        pass,
                        if pass {
                            "command exit code matched"
                        } else {
                            "command exit code differed"
                        },
                    )
                }
                "event_order" => {
                    let events = assertion
                        .get("events")
                        .and_then(Value::as_array)
                        .cloned()
                        .unwrap_or_default();
                    let mut offset = 0;
                    let pass = !events.is_empty()
                        && events.iter().all(|event| {
                            let Some(event) = event.as_str() else {
                                return false;
                            };
                            let Some(found) = transcript[offset..].find(event) else {
                                return false;
                            };
                            offset += found + event.len();
                            true
                        });
                    (
                        pass,
                        if pass {
                            "events appeared in the requested order"
                        } else {
                            "events were missing or out of order"
                        },
                    )
                }
                "no_write_outside" => {
                    let allowed: Vec<PathBuf> = assertion
                        .get("allowed_paths")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter_map(Value::as_str)
                        .map(PathBuf::from)
                        .collect();
                    let after = files_under(sandbox);
                    let mut changed: Vec<PathBuf> = after
                        .into_iter()
                        .filter(|file| {
                            fs::read(sandbox.join(file)).ok().as_ref() != before.get(file)
                        })
                        .collect();
                    changed.extend(
                        before
                            .keys()
                            .filter(|file| !sandbox.join(file).exists())
                            .cloned(),
                    );
                    let pass = changed.iter().all(|file| {
                        allowed
                            .iter()
                            .any(|path| file == path || file.starts_with(path))
                    });
                    (
                        pass,
                        if pass {
                            "sandbox files stayed within allowed paths"
                        } else {
                            "sandbox contains a file outside allowed paths"
                        },
                    )
                }
                _ => (false, "unknown assertion kind"),
            };
            json!({"kind": kind, "passed": passed, "evidence": evidence})
        })
        .collect()
}

pub(super) fn snapshot(root: &Path) -> BTreeMap<PathBuf, Vec<u8>> {
    files_under(root)
        .into_iter()
        .filter_map(|path| {
            fs::read(root.join(&path))
                .ok()
                .map(|contents| (path, contents))
        })
        .collect()
}

fn safe_path(root: &Path, relative: &str) -> Option<PathBuf> {
    let path = Path::new(relative);
    if relative.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|c| matches!(c, std::path::Component::ParentDir))
    {
        return None;
    }
    Some(root.join(path))
}

fn files_under(root: &Path) -> Vec<PathBuf> {
    fn visit(root: &Path, dir: &Path, files: &mut Vec<PathBuf>) {
        let Ok(entries) = fs::read_dir(dir) else {
            return;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                visit(root, &path, files);
            } else if let Ok(relative) = path.strip_prefix(root) {
                files.push(relative.to_path_buf());
            }
        }
    }
    let mut files = Vec::new();
    visit(root, root, &mut files);
    files
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn no_write_outside_reports_deleted_files() {
        let sandbox = tempfile::tempdir().unwrap();
        let file = sandbox.path().join("outside.txt");
        fs::write(&file, "before").unwrap();
        let before = snapshot(sandbox.path());
        fs::remove_file(file).unwrap();

        let results = verify(
            &[json!({"kind":"no_write_outside", "allowed_paths": []})],
            sandbox.path(),
            "",
            &before,
        );
        assert_eq!(results[0]["passed"], false);
    }
}
