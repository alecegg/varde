//! Compare one source commit with paths declared by its task and owning plan.
use crate::execution_wave_paths::{
    canonical_declaration, declarations_overlap, matches_declaration, matching_paths,
};
use anyhow::Result;
use serde::Serialize;
use serde_yaml::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
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
impl std::error::Error for OwnershipError {}

#[derive(Serialize)]
pub struct OwnershipAudit {
    pub status: &'static str,
    pub stray: Vec<String>,
    pub declared: Vec<String>,
    pub changed: Vec<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub blockers: Vec<String>,
}

#[derive(Debug, Default, Clone)]
pub(crate) struct OwnershipDeclarations {
    /// Legacy `modifies` paths and rename sources; a missing literal path blocks.
    pub owned: BTreeSet<String>,
    /// `owns` declarations; a path may name a file the task creates.
    pub owns: BTreeSet<String>,
    pub creates: BTreeSet<String>,
    pub generated: BTreeSet<String>,
}

#[derive(Debug, Default)]
pub(crate) struct OwnershipResolution {
    pub declared: Vec<String>,
    pub blockers: Vec<String>,
    excludes: Vec<String>,
}

impl OwnershipResolution {
    fn owns(&self, path: &str) -> bool {
        self.declared
            .iter()
            .any(|declaration| matches_declaration(declaration, path))
            && !self
                .excludes
                .iter()
                .any(|exclude| matches_declaration(exclude, path))
    }
}

/// Resolve ownership declarations once for validation and commit audits.
/// Literal modifications must exist unless they appear in the checked diff;
/// created, generated, and widened paths may be new, but must still resolve
/// safely inside the repository.
pub(crate) fn resolve(
    root: &Path,
    declarations: &OwnershipDeclarations,
    excludes: &[String],
    widened: Option<&[String]>,
    changed: &BTreeSet<String>,
) -> OwnershipResolution {
    let mut blockers = BTreeSet::new();
    let mut canonical_excludes = Vec::new();
    for exclude in excludes {
        match canonical_declaration(root, exclude) {
            Ok(canonical) => canonical_excludes.push((exclude.clone(), canonical)),
            Err(error) => {
                blockers.insert(format!("{exclude}: {error}"));
            }
        }
    }

    let mut paths = BTreeMap::<String, bool>::new();
    for path in &declarations.owned {
        paths.insert(path.clone(), false);
    }
    for path in declarations
        .owns
        .iter()
        .chain(&declarations.creates)
        .chain(&declarations.generated)
        .chain(widened.unwrap_or_default())
    {
        paths.entry(path.clone()).or_insert(true);
    }

    let mut resolved = BTreeSet::new();
    for (path, may_be_missing) in paths {
        let canonical = match canonical_declaration(root, &path) {
            Ok(canonical) => canonical,
            Err(error) => {
                blockers.insert(format!("{path}: {error}"));
                continue;
            }
        };
        resolved.insert(path.clone());
        for (exclude, canonical_exclude) in &canonical_excludes {
            if declarations_overlap(&canonical, canonical_exclude) {
                blockers.insert(format!("{path}: overlaps excluded path {exclude}"));
            }
        }

        let matches = match matching_paths(root, &canonical) {
            Ok(matches) => matches,
            Err(error) => {
                blockers.insert(format!("{path}: {error}"));
                continue;
            }
        };
        let changed_match = changed
            .iter()
            .any(|changed_path| matches_declaration(&path, changed_path));
        if matches.is_empty() && !may_be_missing && !changed_match {
            let reason = if path.contains('*') {
                "matches no repository paths"
            } else if path.ends_with('/') {
                "directory does not exist"
            } else {
                "path does not exist"
            };
            blockers.insert(format!("{path}: {reason}"));
        }
    }

    OwnershipResolution {
        declared: resolved.into_iter().collect(),
        blockers: blockers.into_iter().collect(),
        excludes: excludes.to_vec(),
    }
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

fn declared_paths(fm: &Value) -> Result<OwnershipDeclarations, OwnershipError> {
    let mut owned: BTreeSet<String> = list(fm, "modifies")?.into_iter().collect();
    let owns: BTreeSet<String> = list(fm, "owns")?.into_iter().collect();
    let mut creates: BTreeSet<_> = list(fm, "creates")?.into_iter().collect();
    for rename in list(fm, "renames")? {
        let parts: Vec<_> = rename.split("->").collect();
        if parts.len() != 2 || parts.iter().any(|part| part.trim().is_empty()) {
            return Err(OwnershipError::task(format!(
                "invalid rename entry: {rename}"
            )));
        }
        owned.insert(parts[0].trim().to_owned());
        creates.insert(parts[1].trim().to_owned());
    }
    Ok(OwnershipDeclarations {
        owned,
        owns,
        creates,
        generated: BTreeSet::new(),
    })
}

fn plan_generated_paths(task: &Path) -> Result<Vec<String>, OwnershipError> {
    let Some(tasks_dir) = task
        .parent()
        .filter(|path| path.file_name().and_then(|name| name.to_str()) == Some("tasks"))
    else {
        return Ok(Vec::new());
    };
    let Some(plan_dir) = tasks_dir.parent() else {
        return Ok(Vec::new());
    };
    let plan = plan_dir.join("plan.md");
    let bytes = match fs::read(&plan) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(Vec::new()),
        Err(error) => {
            return Err(OwnershipError::task(format!("{}: {error}", plan.display())));
        }
    };
    let (frontmatter, _) = frontmatter::parse(&bytes)
        .map_err(|error| OwnershipError::task(format!("{}: {error}", plan.display())))?;
    let mut declared = list(&frontmatter, "generated")
        .map_err(|error| OwnershipError::task(format!("{}: {error}", plan.display())))?;
    declared.extend(
        list(&frontmatter, "shared")
            .map_err(|error| OwnershipError::task(format!("{}: {error}", plan.display())))?,
    );
    Ok(declared)
}

fn canonicalize_path_or_parent(path: &Path) -> Result<PathBuf, OwnershipError> {
    if let Ok(canonical) = path.canonicalize() {
        return Ok(canonical);
    }
    let parent = path
        .parent()
        .ok_or_else(|| OwnershipError::task("ownership input has no parent directory"))?
        .canonicalize()
        .map_err(|error| OwnershipError::task(format!("{}: {error}", path.display())))?;
    let name = path
        .file_name()
        .ok_or_else(|| OwnershipError::task("ownership input has no filename"))?;
    Ok(parent.join(name))
}

fn git(root: &Path, args: &[&str]) -> Result<String, OwnershipError> {
    git_response(root, args, false)
}

fn git_response(root: &Path, args: &[&str], reject_stderr: bool) -> Result<String, OwnershipError> {
    let output = Command::new("git")
        .arg("-C")
        .arg(root)
        .args(args)
        .env("GIT_NO_REPLACE_OBJECTS", "1")
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

fn resolve_commit(root: &Path, reference: &str) -> Result<String, OwnershipError> {
    if reference.is_empty() || reference.starts_with('-') {
        return Err(OwnershipError::git(
            "commit reference must be a nonempty revision, not an option",
        ));
    }
    let commit = git_response(
        root,
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
    Ok(commit.to_owned())
}

fn validate_trusted_tips(root: &Path, tips: &[String]) -> Result<(), OwnershipError> {
    for tip in tips {
        let commit = resolve_commit(root, tip)?;
        let output = Command::new("git")
            .arg("-C")
            .arg(root)
            .args(["merge-base", "--is-ancestor", &commit, "HEAD"])
            .output()
            .map_err(|error| OwnershipError::git(error.to_string()))?;
        if !output.status.success() {
            return Err(OwnershipError::git(format!(
                "trusted tip {commit} is not an ancestor of integration branch HEAD"
            )));
        }
    }
    Ok(())
}

fn changed_paths(root: &Path, commit: &str) -> Result<BTreeSet<String>, OwnershipError> {
    let ancestry = git(root, &["rev-list", "--parents", "-n", "1", commit])?;
    let parents: Vec<_> = ancestry.split_whitespace().skip(1).collect();
    if parents.len() <= 1 {
        let diff = git(
            root,
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
        return Ok(diff
            .split('\0')
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
            .collect());
    }

    // A merge contributes only paths whose result differs from every parent.
    let mut common: Option<BTreeSet<String>> = None;
    for parent in parents {
        let diff = git(
            root,
            &[
                "diff",
                "--name-only",
                "--no-renames",
                "-z",
                parent,
                commit,
                "--",
            ],
        )?;
        let changed: BTreeSet<String> = diff
            .split('\0')
            .filter(|path| !path.is_empty())
            .map(str::to_owned)
            .collect();
        common = Some(match common {
            None => changed,
            Some(previous) => previous.intersection(&changed).cloned().collect(),
        });
    }
    Ok(common.unwrap_or_default())
}

pub fn check(
    task: &Path,
    reference: &str,
    root: &Path,
    trusted_tips: &[String],
) -> Result<OwnershipAudit, OwnershipError> {
    let task = canonicalize_path_or_parent(task)?;
    let bytes = fs::read(&task)
        .map_err(|error| OwnershipError::task(format!("{}: {error}", task.display())))?;
    let (fm, _) =
        frontmatter::parse(&bytes).map_err(|error| OwnershipError::task(error.to_string()))?;
    let mut declarations = declared_paths(&fm)?;
    declarations.generated = plan_generated_paths(&task)?.into_iter().collect();
    let kind = match fm.get("kind") {
        None | Some(Value::Null) => "",
        Some(value) => value
            .as_str()
            .ok_or_else(|| OwnershipError::task("kind must be a string"))?,
    };
    if kind == "spike"
        || (declarations.generated.is_empty()
            && !["owns", "modifies", "creates", "renames"]
                .iter()
                .any(|key| fm.get(*key).is_some()))
    {
        let declared: BTreeSet<String> = declarations
            .owned
            .iter()
            .chain(&declarations.owns)
            .chain(&declarations.creates)
            .chain(&declarations.generated)
            .cloned()
            .collect();
        return Ok(OwnershipAudit {
            status: "skipped",
            stray: Vec::new(),
            declared: declared.into_iter().collect(),
            changed: Vec::new(),
            blockers: Vec::new(),
        });
    }
    let root = root
        .canonicalize()
        .map_err(|error| OwnershipError::git(error.to_string()))?;
    validate_trusted_tips(&root, trusted_tips)?;
    let commit = resolve_commit(&root, reference)?;
    let changed = changed_paths(&root, &commit)?;
    let task_relative = task.strip_prefix(&root).ok().and_then(Path::to_str);
    let changed: BTreeSet<_> = changed
        .into_iter()
        .filter(|path| Some(path.as_str()) != task_relative)
        .collect();
    let resolution = resolve(&root, &declarations, &[], None, &changed);
    if !resolution.blockers.is_empty() {
        return Ok(OwnershipAudit {
            status: "invalid",
            stray: Vec::new(),
            declared: resolution.declared,
            changed: changed.into_iter().collect(),
            blockers: resolution.blockers,
        });
    }
    let stray: Vec<_> = changed
        .iter()
        .filter(|path| !resolution.owns(path))
        .cloned()
        .collect();
    Ok(OwnershipAudit {
        status: if stray.is_empty() { "ok" } else { "stray" },
        stray,
        declared: resolution.declared,
        changed: changed.into_iter().collect(),
        blockers: Vec::new(),
    })
}

// Ownership checks read task and plan files from the working copy only;
// artifact pins and their Git object verification were removed with the
// independent review gates.
