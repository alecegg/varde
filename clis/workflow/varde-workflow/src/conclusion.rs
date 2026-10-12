//! Verify a review report and conclude a plan or single change.
//!
//! `review.md` in the concluded directory carries `verdict`, `base`, and
//! `head`. Conclusion succeeds only when the verdict is `approved` and the
//! merged commit equals the reviewed `head`.

use anyhow::Result;
use serde_yaml::{Mapping, Value as YamlValue};
use std::path::{Path, PathBuf};
use std::process::Command;

/// A successful conclusion.
#[derive(Debug)]
pub struct Conclusion {
    pub id: String,
    pub head: String,
}

/// A refused conclusion; every case exits 1.
#[derive(Debug)]
pub struct ConcludeError {
    pub code: &'static str,
    pub message: String,
}

impl ConcludeError {
    fn review(message: impl Into<String>) -> Self {
        Self {
            code: "review_invalid",
            message: message.into(),
        }
    }

    fn git(message: impl Into<String>) -> Self {
        Self {
            code: "git_error",
            message: message.into(),
        }
    }
}

impl std::fmt::Display for ConcludeError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for ConcludeError {}

impl crate::commands::error::ExitCode for ConcludeError {
    fn error_code(&self) -> &'static str {
        self.code
    }
}

/// Verify `<dir>/review.md` and conclude. A plan directory gains
/// `status: completed`; a single-change directory holding `task.md` and no
/// `plan.md` is accepted without a status write.
pub fn conclude(
    dir: &Path,
    merged: Option<&str>,
    repo: Option<&Path>,
) -> Result<Conclusion, ConcludeError> {
    let dir = dir
        .canonicalize()
        .map_err(|error| ConcludeError::review(format!("{}: {error}", dir.display())))?;
    let report = dir.join("review.md");
    let bytes = std::fs::read(&report)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", report.display())))?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", report.display())))?;
    let mapping = frontmatter.as_mapping().ok_or_else(|| {
        ConcludeError::review(format!("{}: invalid frontmatter", report.display()))
    })?;

    let verdict = string_field(mapping, "verdict");
    if verdict.as_deref() != Some("approved") {
        let verdict = verdict.unwrap_or_else(|| "missing".to_string());
        return Err(ConcludeError::review(format!(
            "review verdict is {verdict}"
        )));
    }
    let head = string_field(mapping, "head")
        .ok_or_else(|| ConcludeError::review("review report has no head"))?;

    let repository = repository_root(repo)?;
    let head_commit = resolve_commit(&repository, &head).ok_or_else(|| {
        ConcludeError::git(format!(
            "review commit {head} not found in {}",
            repository.display()
        ))
    })?;
    let merged_rev = merged.unwrap_or("HEAD");
    let merged_commit = resolve_commit(&repository, merged_rev).ok_or_else(|| {
        ConcludeError::git(format!(
            "merged commit {merged_rev} not found in {}",
            repository.display()
        ))
    })?;
    if merged_commit != head_commit {
        return Err(ConcludeError::review(format!(
            "merged commit {merged_commit} does not match reviewed head {head_commit}"
        )));
    }

    let plan = dir.join("plan.md");
    let id = if plan.is_file() {
        let id = artifact_id(&plan)?;
        write_status(&plan, "completed")?;
        id
    } else if dir.join("task.md").is_file() {
        artifact_id(&dir)?
    } else {
        return Err(ConcludeError::review(format!(
            "{} has no plan.md or task.md",
            dir.display()
        )));
    };
    Ok(Conclusion {
        id,
        head: head_commit,
    })
}

/// `None` when the plan has no `## Acceptance criteria` section, otherwise
/// whether that section still holds an unchecked criterion.
pub(crate) fn unchecked_acceptance(body: &str) -> Option<bool> {
    let mut in_acceptance = false;
    let mut found = false;
    for line in body.lines() {
        if line.trim() == "## Acceptance criteria" {
            in_acceptance = true;
            found = true;
            continue;
        }
        if in_acceptance && line.starts_with("## ") {
            break;
        }
        if in_acceptance && line.trim_start().starts_with("- [ ]") {
            return Some(true);
        }
    }
    found.then_some(false)
}

fn string_field(mapping: &Mapping, name: &str) -> Option<String> {
    mapping
        .get(YamlValue::String(name.to_string()))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
}

fn artifact_id(path: &Path) -> Result<String, ConcludeError> {
    let directory = if path.is_dir() {
        path
    } else {
        path.parent().unwrap_or(path)
    };
    if path.is_file() {
        let bytes = std::fs::read(path)
            .map_err(|error| ConcludeError::review(format!("{}: {error}", path.display())))?;
        if let Ok((frontmatter, _)) = varde_workflow_core::frontmatter::parse(&bytes)
            && let Some(mapping) = frontmatter.as_mapping()
            && let Some(id) = string_field(mapping, "id")
            && !id.is_empty()
        {
            return Ok(id);
        }
    }
    Ok(directory
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("plan")
        .to_string())
}

fn write_status(path: &Path, status: &str) -> Result<(), ConcludeError> {
    let bytes = std::fs::read(path)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", path.display())))?;
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(&bytes)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", path.display())))?;
    let mut mapping = frontmatter
        .as_mapping()
        .ok_or_else(|| ConcludeError::review(format!("{}: invalid frontmatter", path.display())))?
        .clone();
    mapping.insert(
        YamlValue::String("status".to_string()),
        YamlValue::String(status.to_string()),
    );
    let content = varde_workflow_core::frontmatter::serialize(&YamlValue::Mapping(mapping), &body)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", path.display())))?;
    std::fs::write(path, content)
        .map_err(|error| ConcludeError::review(format!("{}: {error}", path.display())))?;
    Ok(())
}

fn repository_root(repo: Option<&Path>) -> Result<PathBuf, ConcludeError> {
    match repo {
        Some(path) => path
            .canonicalize()
            .map_err(|error| ConcludeError::git(format!("{}: {error}", path.display()))),
        None => {
            let cwd =
                std::env::current_dir().map_err(|error| ConcludeError::git(error.to_string()))?;
            git_toplevel(&cwd)
        }
    }
}

fn git_toplevel(start: &Path) -> Result<PathBuf, ConcludeError> {
    let output = Command::new("git")
        .arg("-C")
        .arg(start)
        .args(["rev-parse", "--show-toplevel"])
        .output()
        .map_err(|error| ConcludeError::git(error.to_string()))?;
    if !output.status.success() {
        return Err(ConcludeError::git("not inside a Git repository"));
    }
    let root =
        String::from_utf8(output.stdout).map_err(|error| ConcludeError::git(error.to_string()))?;
    Ok(PathBuf::from(root.trim()))
}

fn resolve_commit(repository: &Path, reference: &str) -> Option<String> {
    if reference.is_empty() || reference.starts_with('-') {
        return None;
    }
    let output = Command::new("git")
        .arg("-C")
        .arg(repository)
        .args([
            "rev-parse",
            "--verify",
            "--end-of-options",
            &format!("{reference}^{{commit}}"),
        ])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let commit = String::from_utf8(output.stdout).ok()?.trim().to_owned();
    (!commit.is_empty()).then_some(commit)
}
