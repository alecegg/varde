//! Shared checkpoint decisions for workflow state mutations.

use crate::review_gates::{self, CheckReport};
use anyhow::{Context, Result, bail};
use serde_yaml::{Mapping, Value as YamlValue};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;
use varde_workflow_core::memory::{self, MemoryPaths};

pub fn repository_for(path: &Path) -> Result<PathBuf> {
    let path = memory::canonical_or_lexical(path);
    let start = if path.is_dir() {
        path.clone()
    } else {
        path.parent().unwrap_or(Path::new(".")).to_path_buf()
    };
    if let Some(root) = git_root(&start) {
        return Ok(root);
    }

    let cwd = std::env::current_dir()?;
    if let Some(root) = git_root(&cwd) {
        let paths = MemoryPaths::resolve(&root)?;
        if is_memory_path(&path, &paths) {
            return Ok(root);
        }
    }

    let config = memory::load_config()?;
    let mut candidates = BTreeMap::new();
    for configured_root in config.project.keys() {
        let root = PathBuf::from(configured_root);
        let Ok(paths) = MemoryPaths::resolve_with(&root, &config) else {
            continue;
        };
        if is_memory_path(&path, &paths) || path.starts_with(&paths.root) {
            candidates.insert(memory::canonical_or_lexical(&paths.root), ());
        }
    }
    match candidates.len() {
        1 => return Ok(candidates.into_keys().next().expect("one candidate")),
        n if n > 1 => bail!("redirected workflow store matches {n} configured projects"),
        _ => {}
    }

    if let Some(root) = memory::find_root(&path) {
        return root
            .canonicalize()
            .context("failed to resolve project root");
    }
    start
        .canonicalize()
        .context("failed to resolve repository root")
}

fn is_memory_path(path: &Path, memory: &MemoryPaths) -> bool {
    path.starts_with(memory::canonical_or_lexical(&memory.working.path))
        || path.starts_with(memory::canonical_or_lexical(&memory.knowledge.path))
}

fn git_root(start: &Path) -> Option<PathBuf> {
    let output = Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(start)
        .output();
    if let Ok(output) = output
        && output.status.success()
    {
        let root = PathBuf::from(String::from_utf8_lossy(&output.stdout).trim());
        return root.canonicalize().ok();
    }
    None
}

pub fn report_if_blocked(report: CheckReport, json_output: bool) -> Result<()> {
    if report.ready {
        return Ok(());
    }
    let first = report.blockers.first().cloned().unwrap_or_else(|| {
        serde_json::json!({ "code": "review_blocked", "message": "review checkpoint is blocked" })
    });
    let code = first["code"].as_str().unwrap_or("review_blocked");
    let code = match code {
        "review_missing" | "review_stale_contract" | "review_stale_changes" | "review_invalid" => {
            code
        }
        _ => "review_blocked",
    };
    let message = first["message"]
        .as_str()
        .unwrap_or("review checkpoint is blocked");
    if json_output {
        crate::output::print_failure(
            code,
            message,
            serde_json::json!({ "blockers": report.blockers, "consumed": report.consumed }),
        );
    } else {
        eprintln!("error: {message}");
    }
    std::process::exit(4)
}

pub fn checkpoint_for_transition(
    repository: &Path,
    artifact: &Path,
    artifact_type: &str,
    requested_state: &str,
) -> Result<Option<CheckReport>> {
    let memory = MemoryPaths::resolve(repository)?;
    let path = artifact.canonicalize()?;
    let managed_root = memory::canonical_or_lexical(&memory.working.path.join("plans"));
    let bytes = fs::read(&path)?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)?;
    let mapping = frontmatter
        .as_mapping()
        .context("workflow artifact frontmatter must be a mapping")?;
    if artifact_type == "plan" {
        if requested_state == "active" {
            return Ok(Some(review_gates::check_plan(repository, &path, "start")?));
        }
        if requested_state == "completed" {
            return Ok(Some(review_gates::check_plan(
                repository, &path, "complete",
            )?));
        }
        return Ok(None);
    }
    if artifact_type != "task" || !matches!(requested_state, "in_progress" | "done") {
        return Ok(None);
    }
    let ownership_root = if path.starts_with(&managed_root) {
        managed_root.as_path()
    } else {
        repository
    };
    let parent_plan = nearest_plan(ownership_root, &path)
        .ok_or_else(|| review_gates::invalid("managed task has no containing plan.md"))?;
    let report = review_gates::check_plan(repository, &parent_plan, "start")?;
    if !report.ready {
        return Ok(Some(report));
    }
    validate_task_ownership(repository, mapping, &parent_plan)
        .map_err(|error| review_gates::invalid(error.to_string()))?;
    Ok(Some(report))
}

pub struct CrudReviewGuard {
    _lock: Option<crate::review_lock::ProjectLock>,
    repository: PathBuf,
    target: PathBuf,
    original: Option<Vec<u8>>,
    managed: bool,
}

impl CrudReviewGuard {
    pub fn original_bytes(&self) -> Option<&[u8]> {
        self.original.as_deref()
    }
}

pub fn begin_crud(bundle: &Path, slug: &str) -> Result<CrudReviewGuard> {
    let repository = repository_for(bundle)?;
    let memory = MemoryPaths::resolve(&repository)?;
    let relative = Path::new(slug);
    let safe_slug = !slug.trim().is_empty()
        && !relative.is_absolute()
        && relative
            .components()
            .all(|component| matches!(component, std::path::Component::Normal(_)));
    let target = if safe_slug {
        memory::canonical_or_lexical(&bundle.join(relative).with_extension("md"))
    } else {
        bundle.join("__invalid_slug__.md")
    };
    let managed_root = memory::canonical_or_lexical(&memory.working.path.join("plans"));
    let managed = safe_slug && target.starts_with(&managed_root);
    let lock = if managed {
        Some(crate::review_lock::ProjectLock::acquire(&repository)?)
    } else {
        None
    };
    let original = if managed {
        match fs::read(&target) {
            Ok(bytes) => Some(bytes),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
            Err(error) => return Err(error.into()),
        }
    } else {
        None
    };
    Ok(CrudReviewGuard {
        _lock: lock,
        repository,
        target,
        original,
        managed,
    })
}

pub fn authorize_crud(guard: &CrudReviewGuard, proposed: &[u8], json_output: bool) -> Result<()> {
    if !guard.managed {
        return Ok(());
    }
    let old = guard
        .original
        .as_deref()
        .map(classify_core)
        .transpose()?
        .flatten();
    let new = classify_core(proposed)?;
    if authorize_initial_core(guard, new.as_ref(), proposed, json_output)? {
        return Ok(());
    }

    if let (Some(old), Some(new)) = (&old, &new)
        && old.artifact_type != new.artifact_type
        && matches!(old.status.as_str(), "active" | "in_progress")
    {
        return Err(review_gates::invalid(
            "an active plan or task cannot change its core type; move it to blocked before changing type",
        ));
    }

    let Some(state) = transition_for_core(old.as_ref(), new.as_ref()) else {
        return Ok(());
    };
    let artifact_type = old
        .as_ref()
        .filter(|old| matches!(old.status.as_str(), "active" | "in_progress"))
        .or(new.as_ref())
        .or(old.as_ref())
        .expect("transition comes from a core document")
        .artifact_type
        .as_str();
    let report = checkpoint_for_transition(&guard.repository, &guard.target, artifact_type, state)?
        .context("managed core mutation did not resolve a review checkpoint")?;
    report_if_blocked(report, json_output)?;
    validate_after_checkpoint(guard, proposed, artifact_type)
}

fn authorize_initial_core(
    guard: &CrudReviewGuard,
    new: Option<&CoreDocument>,
    proposed: &[u8],
    json_output: bool,
) -> Result<bool> {
    let Some(new) = new else {
        return Ok(false);
    };
    let allowed = match new.artifact_type.as_str() {
        "plan" => ["backlog", "active", "blocked", "completed"].as_slice(),
        "task" => ["todo", "in_progress", "blocked", "done"].as_slice(),
        _ => unreachable!("core classifier only returns plan or task"),
    };
    if !allowed.contains(&new.status.as_str()) {
        return Err(review_gates::invalid(format!(
            "invalid `{}` workflow state `{}`",
            new.artifact_type, new.status
        )));
    }
    if guard.original.is_some() {
        return Ok(false);
    }
    let initial = if new.artifact_type == "plan" {
        "backlog"
    } else {
        "todo"
    };
    if new.status == initial {
        return Ok(true);
    }
    if new.artifact_type == "plan" {
        return Err(review_gates::missing_approval(format!(
            "managed plan cannot be created in `{}` without an associated review subject; create it in `{initial}`, then start it through the workflow transition",
            new.status
        )));
    }
    validate_proposed_task(&guard.repository, &guard.target, proposed)?;
    let memory = MemoryPaths::resolve(&guard.repository)?;
    let managed_root = memory::canonical_or_lexical(&memory.working.path.join("plans"));
    let search_root = if guard.target.starts_with(&managed_root) {
        managed_root.as_path()
    } else {
        guard.repository.as_path()
    };
    let parent_plan = nearest_plan(search_root, &guard.target)
        .context("managed task has no containing plan.md")?;
    let report = review_gates::check_plan(&guard.repository, &parent_plan, "start")?;
    report_if_blocked(report, json_output)?;
    Ok(true)
}

fn transition_for_core<'a>(
    old: Option<&'a CoreDocument>,
    new: Option<&'a CoreDocument>,
) -> Option<&'a str> {
    match (old, new) {
        (Some(old), Some(new)) if old.artifact_type == new.artifact_type => {
            match (
                new.artifact_type.as_str(),
                old.status.as_str(),
                new.status.as_str(),
            ) {
                ("plan", old, "active") if old != "active" => Some("active"),
                ("plan", old, "completed") if old != "completed" => Some("completed"),
                ("task", old, "in_progress") if old != "in_progress" => Some("in_progress"),
                ("task", old, "done") if old != "done" => Some("done"),
                ("task", _, "in_progress" | "done") => Some(new.status.as_str()),
                _ => None,
            }
        }
        (Some(old), _) if matches!(old.status.as_str(), "active" | "in_progress") => {
            Some(if old.artifact_type == "plan" {
                "active"
            } else {
                "in_progress"
            })
        }
        (_, Some(new))
            if matches!(
                new.status.as_str(),
                "active" | "in_progress" | "completed" | "done"
            ) =>
        {
            Some(new.status.as_str())
        }
        _ => None,
    }
}

fn validate_after_checkpoint(
    guard: &CrudReviewGuard,
    proposed: &[u8],
    artifact_type: &str,
) -> Result<()> {
    if artifact_type == "plan"
        && let Some(approved) =
            review_gates::approved_contract_fingerprint_for_plan(&guard.repository, &guard.target)?
        && let Some(proposed_contract) = guard
            .original
            .as_deref()
            .and_then(|_| crate::review_contract::contract_fingerprint(proposed).ok())
        && approved != proposed_contract
    {
        return Err(review_gates::stale_contract(
            "proposed plan content differs from its independent pre-edit approval",
        ));
    }
    if artifact_type == "task" {
        validate_proposed_task(&guard.repository, &guard.target, proposed)?;
    }
    Ok(())
}

pub fn preview_set_field(original: &[u8], field: &str, value: &str) -> Result<Vec<u8>> {
    let (mut frontmatter, body) = varde_workflow_core::frontmatter::parse(original)?;
    let mapping = frontmatter
        .as_mapping_mut()
        .context("concept frontmatter must be a mapping")?;
    mapping.insert(
        YamlValue::String(field.to_string()),
        YamlValue::String(value.to_string()),
    );
    Ok(varde_workflow_core::frontmatter::serialize(&frontmatter, &body)?.into_bytes())
}

pub fn report_anyhow(error: &anyhow::Error, json_output: bool) -> Result<()> {
    if let Some((code, exit_code, message, details)) = review_gates::failure_details(error) {
        if json_output {
            crate::output::print_failure(code, message, details.clone());
        } else {
            eprintln!("error: {message}");
        }
        std::process::exit(exit_code);
    }
    crate::commands::error::report_error(
        &crate::commands::error::InternalError(error.to_string()),
        json_output,
    )
}

#[derive(Debug)]
struct CoreDocument {
    artifact_type: String,
    status: String,
}

fn classify_core(bytes: &[u8]) -> Result<Option<CoreDocument>> {
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(bytes)?;
    let mapping = frontmatter
        .as_mapping()
        .context("concept frontmatter must be a mapping")?;
    let artifact_type = mapping
        .get(YamlValue::String("artifact_type".to_string()))
        .and_then(YamlValue::as_str)
        .or_else(|| {
            mapping
                .get(YamlValue::String("type".to_string()))
                .and_then(YamlValue::as_str)
        });
    let Some(artifact_type @ ("plan" | "task")) = artifact_type else {
        return Ok(None);
    };
    let status = mapping
        .get(YamlValue::String("status".to_string()))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
        .unwrap_or_else(|| {
            if artifact_type == "plan" {
                "backlog"
            } else {
                "todo"
            }
            .to_string()
        });
    Ok(Some(CoreDocument {
        artifact_type: artifact_type.to_string(),
        status,
    }))
}

fn validate_proposed_task(repository: &Path, target: &Path, bytes: &[u8]) -> Result<()> {
    let memory = MemoryPaths::resolve(repository)?;
    let managed_root = memory::canonical_or_lexical(&memory.working.path.join("plans"));
    let search_root = if target.starts_with(&managed_root) {
        managed_root
    } else {
        repository.to_path_buf()
    };
    let plan =
        nearest_plan(&search_root, target).context("managed task has no containing plan.md")?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(bytes)?;
    let mapping = frontmatter
        .as_mapping()
        .context("task frontmatter must be a mapping")?;
    validate_task_ownership(repository, mapping, &plan)
        .map_err(|error| review_gates::invalid(error.to_string()))
}

pub fn nearest_plan(managed_root: &Path, task: &Path) -> Option<PathBuf> {
    let mut directory = task.parent()?;
    while directory.starts_with(managed_root) {
        let candidate = directory.join("plan.md");
        if candidate.is_file() {
            return candidate.canonicalize().ok();
        }
        if directory == managed_root {
            break;
        }
        directory = directory.parent()?;
    }
    None
}

fn validate_task_ownership(repository: &Path, mapping: &Mapping, plan_path: &Path) -> Result<()> {
    let fields = ["modifies", "creates", "renames"];
    let mut declared = Vec::new();
    for field in fields {
        let Some(value) = mapping.get(YamlValue::String(field.to_string())) else {
            continue;
        };
        let values = value
            .as_sequence()
            .with_context(|| format!("task `{field}` ownership must be a sequence"))?;
        for value in values {
            let value = value
                .as_str()
                .with_context(|| format!("task `{field}` entries must be strings"))?;
            if field == "renames" {
                let (old, new) = value
                    .split_once(" -> ")
                    .context("task rename ownership must use `old/path -> new/path`")?;
                declared.push(validate_owned_path(repository, old, field)?);
                declared.push(validate_owned_path(repository, new, field)?);
            } else {
                declared.push(validate_owned_path(repository, value, field)?);
            }
        }
    }
    if declared.is_empty() {
        bail!("managed task must declare non-empty modifies, creates, or renames ownership");
    }
    if let Some(declared_plan) = mapping
        .get(YamlValue::String("plan".to_string()))
        .and_then(YamlValue::as_str)
    {
        let (plan_frontmatter, _) = varde_workflow_core::frontmatter::parse(&fs::read(plan_path)?)?;
        let plan_mapping = plan_frontmatter
            .as_mapping()
            .context("containing plan frontmatter must be a mapping")?;
        let plan_id = plan_mapping
            .get(YamlValue::String("id".to_string()))
            .and_then(YamlValue::as_str)
            .map(str::to_string)
            .or_else(|| {
                plan_path
                    .parent()
                    .and_then(Path::file_name)
                    .and_then(|name| name.to_str())
                    .map(str::to_string)
            });
        if Some(declared_plan) != plan_id.as_deref() && Some(declared_plan) != plan_path.to_str() {
            bail!("task parent plan does not match its containing plan.md");
        }
    }
    let approved_scope = review_gates::scope_for_plan(repository, plan_path)?
        .context("parent plan has no review subject scope")?;
    for path in declared {
        if !approved_scope
            .iter()
            .any(|root| root == "." || Path::new(&path).starts_with(Path::new(root)))
        {
            bail!("task ownership `{path}` falls outside its parent plan's approved scope");
        }
    }
    Ok(())
}

fn validate_owned_path(repository: &Path, raw: &str, field: &str) -> Result<String> {
    let value = raw.trim();
    let relative = Path::new(value);
    if value.is_empty()
        || relative.is_absolute()
        || relative
            .components()
            .any(|component| !matches!(component, std::path::Component::Normal(_)))
    {
        bail!("task `{field}` contains an invalid repository-relative path `{raw}`");
    }
    let normalized = memory::canonical_or_lexical(&repository.join(relative));
    if !normalized.starts_with(repository) {
        bail!("task `{field}` path escapes the repository: `{raw}`");
    }
    Ok(value.trim_end_matches('/').to_string())
}
