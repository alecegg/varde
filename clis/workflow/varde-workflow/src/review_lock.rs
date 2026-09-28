//! Persistent cooperative lock for workflow state and review evidence.

use anyhow::{Context, Result};
use fs4::FileExt;
use std::fs::{File, OpenOptions};
use std::path::{Path, PathBuf};
use std::process::Command;

const LOCK_NAME: &str = ".varde-workflow.lock";

pub struct ProjectLock {
    file: File,
    root: PathBuf,
}

impl ProjectLock {
    pub fn acquire(root: &Path) -> Result<Self> {
        let root = root
            .canonicalize()
            .with_context(|| format!("failed to resolve workflow repository {}", root.display()))?;
        if root.join(".git").is_file() {
            return Self::acquire_worktree(&root);
        }
        Self::acquire_at(root.clone(), root.join(LOCK_NAME))
    }

    /// Keep binding-worker locks in Git metadata so checking authorization
    /// does not create untracked files that prevent ordinary worktree cleanup.
    pub fn acquire_worktree(root: &Path) -> Result<Self> {
        let root = root.canonicalize()?;
        let output = Command::new("git")
            .args(["rev-parse", "--absolute-git-dir"])
            .current_dir(&root)
            .output()?;
        if !output.status.success() {
            anyhow::bail!("could not resolve worktree Git lock directory");
        }
        let git_dir = PathBuf::from(String::from_utf8(output.stdout)?.trim()).canonicalize()?;
        Self::acquire_at(root, git_dir.join(LOCK_NAME))
    }

    fn acquire_at(root: PathBuf, lock_path: PathBuf) -> Result<Self> {
        let file = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .with_context(|| format!("failed to open workflow lock {}", lock_path.display()))?;
        FileExt::lock(&file)
            .with_context(|| format!("failed to lock workflow project {}", root.display()))?;
        Ok(Self { file, root })
    }

    pub fn root(&self) -> &Path {
        &self.root
    }
}

impl Drop for ProjectLock {
    fn drop(&mut self) {
        let _ = FileExt::unlock(&self.file);
    }
}
