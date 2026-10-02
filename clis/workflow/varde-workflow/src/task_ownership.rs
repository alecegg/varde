//! Compare one source commit with exact lexical paths declared by its task.
use serde::Serialize;
use serde_yaml::Value;
use std::collections::BTreeSet;
use std::fs;
use std::path::Path;
use std::process::Command;
use varde_workflow_core::frontmatter;

#[derive(Debug)]
pub struct OwnershipError {
    pub code: &'static str,
    pub message: String,
}
impl OwnershipError {
    fn task(message: impl Into<String>) -> Self {
        Self {
            code: "unreadable_task",
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
impl std::fmt::Display for OwnershipError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.message)
    }
}

#[derive(Serialize)]
pub struct OwnershipAudit {
    pub status: &'static str,
    pub stray: Vec<String>,
    pub declared: Vec<String>,
    pub changed: Vec<String>,
}

fn list(fm: &Value, key: &str) -> Result<Vec<String>, OwnershipError> {
    let Some(value) = fm.get(key) else {
        return Ok(Vec::new());
    };
    value
        .as_sequence()
        .ok_or_else(|| OwnershipError::task(format!("{key} must be a list of strings")))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| OwnershipError::task(format!("{key} must contain only strings")))
        })
        .collect()
}

fn declared_paths(fm: &Value) -> Result<BTreeSet<String>, OwnershipError> {
    let mut paths: BTreeSet<_> = list(fm, "modifies")?
        .into_iter()
        .chain(list(fm, "creates")?)
        .collect();
    for rename in list(fm, "renames")? {
        let parts: Vec<_> = rename.split("->").collect();
        if parts.len() != 2 || parts.iter().any(|part| part.trim().is_empty()) {
            return Err(OwnershipError::task(format!(
                "invalid rename entry: {rename}"
            )));
        }
        paths.extend(parts.iter().map(|part| part.trim().to_owned()));
    }
    Ok(paths)
}

fn git(root: &Path, args: &[&str]) -> Result<String, OwnershipError> {
    git_response(root, args, false)
}

fn git_response(root: &Path, args: &[&str], reject_stderr: bool) -> Result<String, OwnershipError> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .output()
        .map_err(|error| OwnershipError::git(error.to_string()))?;
    if !output.status.success() || (reject_stderr && !output.stderr.is_empty()) {
        return Err(OwnershipError::git(
            String::from_utf8_lossy(&output.stderr).trim().to_owned(),
        ));
    }
    String::from_utf8(output.stdout)
        .map_err(|_| OwnershipError::git("Git returned a non-UTF-8 path or response"))
}

pub fn check(task: &Path, reference: &str, root: &Path) -> Result<OwnershipAudit, OwnershipError> {
    let bytes = fs::read(task)
        .map_err(|error| OwnershipError::task(format!("{}: {error}", task.display())))?;
    let (fm, _) =
        frontmatter::parse(&bytes).map_err(|error| OwnershipError::task(error.to_string()))?;
    let declared = declared_paths(&fm)?;
    let kind = match fm.get("kind") {
        None | Some(Value::Null) => "",
        Some(value) => value
            .as_str()
            .ok_or_else(|| OwnershipError::task("kind must be a string"))?,
    };
    if kind == "spike"
        || !["modifies", "creates", "renames"]
            .iter()
            .any(|key| fm.get(*key).is_some())
    {
        return Ok(OwnershipAudit {
            status: "skipped",
            stray: Vec::new(),
            declared: declared.into_iter().collect(),
            changed: Vec::new(),
        });
    }
    if reference.is_empty() || reference.starts_with('-') {
        return Err(OwnershipError::git(
            "commit reference must be a nonempty revision, not an option",
        ));
    }
    let root = root
        .canonicalize()
        .map_err(|error| OwnershipError::git(error.to_string()))?;
    let task = task
        .canonicalize()
        .map_err(|error| OwnershipError::task(error.to_string()))?;
    let commit = git_response(
        &root,
        &[
            "-c",
            "core.warnAmbiguousRefs=true",
            "rev-parse",
            "--verify",
            "--end-of-options",
            &format!("{reference}^{{commit}}"),
        ],
        true,
    )?;
    let commit = commit.trim();
    if ![40, 64].contains(&commit.len()) || !commit.bytes().all(|byte| byte.is_ascii_hexdigit()) {
        return Err(OwnershipError::git("Git did not resolve one commit object"));
    }
    let ancestry = git(&root, &["rev-list", "--parents", "-n", "1", commit, "--"])?;
    let ancestry: Vec<_> = ancestry.split_whitespace().collect();
    if ancestry.first().copied() != Some(commit) {
        return Err(OwnershipError::git(
            "Git returned inconsistent commit ancestry",
        ));
    }
    let parents = ancestry.len() - 1;
    if parents > 1 {
        return Err(OwnershipError {
            code: "merge_commit",
            message: format!(
                "{reference} has {parents} parents; pass the task's own source commit"
            ),
        });
    }
    let diff = git(
        &root,
        &[
            "diff-tree",
            "-z",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            commit,
            "--",
        ],
    )?;
    let task_relative = task.strip_prefix(&root).ok().and_then(Path::to_str);
    let changed: BTreeSet<_> = diff
        .split('\0')
        .filter(|path| !path.is_empty() && Some(*path) != task_relative)
        .map(str::to_owned)
        .collect();
    let stray: Vec<_> = changed.difference(&declared).cloned().collect();
    Ok(OwnershipAudit {
        status: if stray.is_empty() { "ok" } else { "stray" },
        stray,
        declared: declared.into_iter().collect(),
        changed: changed.into_iter().collect(),
    })
}
