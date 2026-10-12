use crate::artifact::{self, ArtifactEnvelope, Diagnostic};
use crate::cli::ValidateArgs;
use crate::execution_wave;
use crate::execution_wave_tools;
use crate::output::{print_failure, print_success};
use crate::task_ownership;
use anyhow::Result;
use serde_json::json;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};
use varde_core::text_audit::{self, Finding, Severity};

const PLAN_STATUSES: &[&str] = &["active", "backlog", "blocked", "cancelled", "completed"];
/// Legacy terminal statuses `status_bucket` (status.rs) still treats as
/// terminal; tolerated so old plans keep validating without migration.
const LEGACY_PLAN_STATUSES: &[&str] = &["archived", "complete", "dismissed", "stale"];
const TASK_STATUSES: &[&str] = &["blocked", "done", "in_progress", "todo"];

/// Task frontmatter keys validate accepts; legacy ownership and test-profile
/// keys stay tolerated.
const TASK_KEYS: &[&str] = &[
    "artifact_type",
    "creates",
    "depends_on",
    "generated",
    "id",
    "kind",
    "modifies",
    "owns",
    "posture",
    "provenance",
    "relationships",
    "renames",
    "schema_version",
    "status",
    "title",
    "type",
    "verification_resources",
];

pub fn run(args: ValidateArgs) -> Result<()> {
    let target = match resolve_target(&args.artifact) {
        Ok(target) => target,
        Err(diagnostics) => return report_invalid(&args, &diagnostics, &[]),
    };
    let (diagnostics, warnings) = match artifact::inspect(&target) {
        Ok(envelope) => {
            let (mut errors, warnings) = text_findings(&envelope, &target)?;
            if envelope.artifact_type == "plan" {
                errors.extend(ownership_findings(&target));
            }
            errors.extend(status_and_key_findings(&target, &envelope));
            if errors.is_empty() {
                return print_valid(&args, &envelope, &warnings);
            }
            (errors, warnings)
        }
        Err(diagnostics) => (diagnostics, Vec::new()),
    };
    report_invalid(&args, &diagnostics, &warnings)
}

/// A single-change directory holds `task.md` without `plan.md`.
fn resolve_target(path: &Path) -> Result<PathBuf, Vec<Diagnostic>> {
    if !path.is_dir() {
        return Ok(path.to_path_buf());
    }
    for name in ["plan.md", "task.md"] {
        let candidate = path.join(name);
        if candidate.is_file() {
            return Ok(candidate);
        }
    }
    Err(vec![Diagnostic {
        field: "document".into(),
        message: format!("{} has no plan.md or task.md", path.display()),
    }])
}

fn report_invalid(
    args: &ValidateArgs,
    diagnostics: &[Diagnostic],
    warnings: &[Finding],
) -> Result<()> {
    if args.json {
        // Warnings stay out of the JSON failure details, which list errors only.
        let details = diagnostics.iter().map(Diagnostic::to_json).collect();
        print_failure(
            "validation_failed",
            "artifact validation failed",
            serde_json::Value::Array(details),
        );
    } else {
        for diagnostic in diagnostics {
            eprintln!("{}: {}", diagnostic.field, diagnostic.message);
        }
        for finding in warnings {
            eprintln!("{}", warning_line(finding));
        }
    }
    std::process::exit(4);
}

/// Status values are checked against the legal set for the artifact type;
/// unknown task frontmatter keys are rejected while legacy keys are tolerated.
/// For a plan, every `tasks/*.md` file is checked too, with its findings
/// reported under `tasks.<id>.<field>`.
fn status_and_key_findings(path: &Path, envelope: &ArtifactEnvelope) -> Vec<Diagnostic> {
    let mut findings = artifact_status_and_key_findings(path, envelope, "");
    if envelope.artifact_type == "plan" {
        let Some(plan_dir) = path.parent() else {
            return findings;
        };
        let Ok(entries) = std::fs::read_dir(plan_dir.join("tasks")) else {
            return findings;
        };
        for entry in entries.flatten() {
            let task_path = entry.path();
            if task_path
                .extension()
                .and_then(|extension| extension.to_str())
                != Some("md")
            {
                continue;
            }
            let Some(id) = task_path.file_stem().and_then(|stem| stem.to_str()) else {
                continue;
            };
            let Ok(task_envelope) = crate::artifact::inspect(&task_path) else {
                continue;
            };
            let prefix = format!("tasks.{id}");
            findings.extend(artifact_status_and_key_findings(
                &task_path,
                &task_envelope,
                &prefix,
            ));
        }
    }
    findings
}

/// Status and key checks for one artifact; `prefix` names the owning task for
/// plan-level findings (for example `tasks.alpha`) or is empty for the
/// validated artifact itself.
fn artifact_status_and_key_findings(
    path: &Path,
    envelope: &ArtifactEnvelope,
    prefix: &str,
) -> Vec<Diagnostic> {
    let mut findings = Vec::new();
    let field = |name: &str| {
        if prefix.is_empty() {
            name.to_string()
        } else {
            format!("{prefix}.{name}")
        }
    };
    let Ok(bytes) = std::fs::read(path) else {
        return findings;
    };
    let Ok((frontmatter, _)) = varde_workflow_core::frontmatter::parse(&bytes) else {
        return findings;
    };
    let Some(mapping) = frontmatter.as_mapping() else {
        return findings;
    };
    let legal: &[&str] = match envelope.artifact_type.as_str() {
        "plan" => PLAN_STATUSES,
        "task" => TASK_STATUSES,
        _ => return findings,
    };
    if let Some(status) = envelope.status.as_deref()
        && !legal.contains(&status)
        && !(envelope.artifact_type == "plan" && LEGACY_PLAN_STATUSES.contains(&status))
    {
        findings.push(Diagnostic {
            field: field("status"),
            message: format!(
                "`{status}` is not a legal {} status ({})",
                envelope.artifact_type,
                legal.join(", ")
            ),
        });
    }
    if envelope.artifact_type == "task" {
        for key in mapping.keys() {
            let Some(key) = key.as_str() else {
                continue;
            };
            if !TASK_KEYS.contains(&key) {
                findings.push(Diagnostic {
                    field: field(key),
                    message: "unknown task frontmatter key".into(),
                });
            }
        }
    }
    findings
}

fn ownership_findings(plan: &Path) -> Vec<Diagnostic> {
    let Some(plan_dir) = plan.parent() else {
        return vec![Diagnostic {
            field: "ownership".into(),
            message: "cannot locate the plan directory".into(),
        }];
    };
    let tasks = match execution_wave::ownership_declarations(plan_dir) {
        Ok(tasks) => tasks,
        Err(error) => {
            return vec![Diagnostic {
                field: "ownership".into(),
                message: error,
            }];
        }
    };
    if !tasks.iter().any(|(_, _, paths)| {
        !paths.owned.is_empty()
            || !paths.owns.is_empty()
            || !paths.creates.is_empty()
            || !paths.generated.is_empty()
    }) {
        return Vec::new();
    }
    let root = match ownership_repository_root(plan_dir) {
        Some(root) => root,
        None => {
            return vec![Diagnostic {
                field: "ownership".into(),
                message: "cannot discover repository root for task ownership".into(),
            }];
        }
    };

    // Created paths and the legacy `modifies` of a done task (which may name a
    // file the task deleted) may be missing from the working copy.
    let permitted_missing: BTreeSet<String> = tasks
        .iter()
        .filter(|(_, status, _)| status == "done")
        .flat_map(|(_, _, paths)| paths.owned.iter().cloned())
        .chain(
            tasks
                .iter()
                .flat_map(|(_, _, paths)| paths.creates.iter().cloned()),
        )
        .collect();

    let mut findings = Vec::new();
    for (task_id, _, paths) in tasks {
        let resolution = task_ownership::resolve(&root, &paths, &[], None, &permitted_missing);
        findings.extend(resolution.blockers.into_iter().map(|message| Diagnostic {
            field: format!("tasks.{task_id}.ownership"),
            message,
        }));
    }
    findings
}

/// Ownership paths belong to the code checkout that invoked validation. The
/// plan may be stored in a separate Git repository, such as the agent-memory
/// working store, so use its Git root only when the caller is outside a repo.
fn ownership_repository_root(plan_dir: &Path) -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok();
    cwd.as_deref()
        .and_then(|cwd| execution_wave_tools::git(cwd, &["rev-parse", "--show-toplevel"]))
        .filter(|(status, output)| *status == 0 && !output.trim().is_empty())
        .map(|(_, output)| PathBuf::from(output.trim()))
        .or_else(|| {
            execution_wave_tools::git(plan_dir, &["rev-parse", "--show-toplevel"])
                .filter(|(status, output)| *status == 0 && !output.trim().is_empty())
                .map(|(_, output)| PathBuf::from(output.trim()))
        })
}

/// Audits plan and task text, splitting findings into errors and warnings.
fn text_findings(
    envelope: &ArtifactEnvelope,
    path: &Path,
) -> Result<(Vec<Diagnostic>, Vec<Finding>)> {
    if !matches!(envelope.artifact_type.as_str(), "plan" | "task") {
        return Ok((Vec::new(), Vec::new()));
    }
    let text = blank_progress(&std::fs::read_to_string(path)?);
    let (errors, warnings): (Vec<_>, Vec<_>) =
        text_audit::audit(&text, &path.display().to_string())
            .into_iter()
            .partition(|finding| finding.severity == Severity::Error);
    let errors = errors
        .into_iter()
        .map(|finding| Diagnostic {
            field: "text".to_string(),
            message: format!("{}:{} {}", finding.path, finding.line, finding.message),
        })
        .collect();
    Ok((errors, warnings))
}

/// Progress is a build-appended evidence log, not instructions: replace its
/// lines with empty ones so the audit skips it and line numbers stay correct.
/// The section is a level 2-4 `Progress` heading up to the next heading of the
/// same or higher level. Fence delimiters stay so fence state remains balanced.
fn blank_progress(text: &str) -> String {
    let mut progress_level = None;
    let mut fence: Option<(char, usize)> = None;
    let lines: Vec<&str> = text
        .lines()
        .map(|line| {
            let marker = fence_marker(line);
            if let Some((open_marker, open_length)) = fence {
                if marker.is_some_and(|(marker, length, closes)| {
                    marker == open_marker && length >= open_length && closes
                }) {
                    fence = None;
                }
                if progress_level.is_some() && marker.is_none() {
                    ""
                } else {
                    line
                }
            } else if let Some((marker, length, _)) = marker {
                fence = Some((marker, length));
                line
            } else {
                if let Some((level, title)) = atx_heading(line) {
                    match progress_level {
                        Some(start) if level > start => {}
                        _ => progress_level = (title == "Progress" && level <= 4).then_some(level),
                    }
                }
                if progress_level.is_some() { "" } else { line }
            }
        })
        .collect();
    lines.join("\n")
}

fn fence_marker(line: &str) -> Option<(char, usize, bool)> {
    let trimmed = line.trim_start();
    let marker = trimmed.chars().next()?;
    if !matches!(marker, '`' | '~') {
        return None;
    }
    let length = trimmed.chars().take_while(|&char| char == marker).count();
    (length >= 3).then(|| (marker, length, trimmed[length..].trim().is_empty()))
}

/// Returns the level (2 or more) and title of an ATX heading line.
fn atx_heading(line: &str) -> Option<(usize, &str)> {
    let level = line.bytes().take_while(|&byte| byte == b'#').count();
    let title = line[level..].strip_prefix(' ')?;
    (level >= 2).then_some((level, title.trim()))
}

fn warning_line(finding: &Finding) -> String {
    format!(
        "warn: {}:{} {}",
        finding.path, finding.line, finding.message
    )
}

fn print_valid(
    args: &ValidateArgs,
    envelope: &ArtifactEnvelope,
    warnings: &[Finding],
) -> Result<()> {
    if args.json {
        let mut data = json!({
            "valid": true,
            "artifact": envelope.to_json(),
            "diagnostics": [],
        });
        if !warnings.is_empty() {
            data["text_warnings"] = json!(warnings);
        }
        return print_success(data);
    }
    println!("valid: {}", args.artifact.display());
    for finding in warnings {
        println!("{}", warning_line(finding));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::time::{SystemTime, UNIX_EPOCH};

    fn temp_dir(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "varde-validate-{label}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        fs::create_dir_all(&root).unwrap();
        root
    }

    fn write(target: &Path, frontmatter: &str) {
        fs::write(target, format!("---\n{frontmatter}\n---\nbody\n")).unwrap();
    }

    fn envelope(path: &Path) -> ArtifactEnvelope {
        crate::artifact::inspect(path).unwrap()
    }

    #[test]
    fn single_change_dir_accepts_task_without_plan() {
        let root = temp_dir("single-change");
        let dir = root.join("plans/2026-10-09-change");
        fs::create_dir_all(&dir).unwrap();
        write(&dir.join("task.md"), "type: task\nstatus: todo");

        let target = resolve_target(&dir).unwrap();
        assert_eq!(target.file_name().unwrap(), "task.md");
        let findings = status_and_key_findings(&target, &envelope(&target));
        assert!(findings.is_empty(), "{findings:?}");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn cancelled_plan_status_is_legal() {
        let root = temp_dir("cancelled");
        let dir = root.join("plans/2026-10-09-dropped");
        fs::create_dir_all(&dir).unwrap();
        let plan = dir.join("plan.md");
        fs::write(
            &plan,
            "---\ntype: plan\nstatus: cancelled\n---\n## Acceptance criteria\n\n- [x] verified\n",
        )
        .unwrap();

        let findings = status_and_key_findings(&plan, &envelope(&plan));
        assert!(findings.is_empty(), "{findings:?}");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn illegal_status_and_unknown_task_keys_are_flagged() {
        let root = temp_dir("illegal-status");
        let task = root.join("task.md");
        fs::create_dir_all(&root).unwrap();
        write(&task, "type: task\nstatus: shipping\nwidgets: 3");

        let findings = status_and_key_findings(&task, &envelope(&task));
        let fields: Vec<&str> = findings.iter().map(|item| item.field.as_str()).collect();
        assert!(fields.contains(&"status"), "{findings:?}");
        assert!(fields.contains(&"widgets"), "{findings:?}");
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn plan_validation_flag_illegal_task_statuses_and_keys_per_task() {
        let root = temp_dir("plan-task-fields");
        let plan_dir = root.join("plans/2026-10-09-change");
        fs::create_dir_all(plan_dir.join("tasks")).unwrap();
        let plan = plan_dir.join("plan.md");
        fs::write(
            &plan,
            "---\ntype: plan\nstatus: active\n---\n## Acceptance criteria\n\n- [x] verified\n",
        )
        .unwrap();
        write(
            &plan_dir.join("tasks/alpha.md"),
            "type: task\nstatus: shipping\nwidgets: 3",
        );

        let findings = status_and_key_findings(&plan, &envelope(&plan));
        let fields: Vec<String> = findings.iter().map(|item| item.field.clone()).collect();
        assert!(
            fields.contains(&"tasks.alpha.status".to_string()),
            "{findings:?}"
        );
        assert!(
            fields.contains(&"tasks.alpha.widgets".to_string()),
            "{findings:?}"
        );
        fs::remove_dir_all(root).unwrap();
    }

    #[test]
    fn legacy_terminal_plan_statuses_are_tolerated() {
        for status in LEGACY_PLAN_STATUSES {
            let root = temp_dir("legacy-status");
            let plan = root.join("plan.md");
            fs::create_dir_all(&root).unwrap();
            fs::write(
                &plan,
                format!(
                    "---\ntype: plan\nstatus: {status}\n---\n## Acceptance criteria\n\n- [x] verified\n"
                ),
            )
            .unwrap();

            let findings = status_and_key_findings(&plan, &envelope(&plan));
            assert!(findings.is_empty(), "{status}: {findings:?}");
            fs::remove_dir_all(root).unwrap();
        }
    }
}
