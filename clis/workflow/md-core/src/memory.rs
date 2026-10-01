//! Memory-location resolution: where a project's working memory and
//! knowledge memory live, alongside the global friction store.
//!
//! Both default to the project tree. A user-scoped config file at
//! `$XDG_CONFIG_HOME/varde/config.toml` (falling back to
//! `~/.config/varde/config.toml`) can redirect either one, per project or
//! for every project, and `VARDE_WORKING_DIR` / `VARDE_KNOWLEDGE_DIR`
//! override everything for one process. The global friction store follows
//! `VARDE_LEARN_STORE` → `[default].learn` → `learn/` beside this config.
//!
//! `config.toml` deliberately lives outside the repository: memory locations
//! are a machine-scoped choice. The tracked `memory-bank/config/type-config/`
//! holds workflow artifact type configuration; it does not select paths.
//!
//! ```toml
//! [default]                       # optional; applies to every project
//! working = "~/varde-memory/{project}/working"
//! learn = "~/varde-memory/learn"
//!
//! [project."/Users/me/src/app"]   # keyed by canonical project root
//! working = "/Volumes/notes/app/working"
//! knowledge = "/Volumes/notes/app/knowledge"
//! ```
//!
//! Values expand a leading `~` to the home directory and `{project}` to the
//! project root's directory name; relative values resolve against the
//! project root.

use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::env;
use std::ffi::OsStr;
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use thiserror::Error;

/// Per-process override for the working-memory directory.
pub const WORKING_ENV: &str = "VARDE_WORKING_DIR";
/// Per-process override for the knowledge-memory directory.
pub const KNOWLEDGE_ENV: &str = "VARDE_KNOWLEDGE_DIR";
/// Per-process override for the global friction store directory.
pub const LEARN_ENV: &str = "VARDE_LEARN_STORE";
/// Overrides the directory holding `config.toml` (tests and unusual setups).
pub const CONFIG_DIR_ENV: &str = "VARDE_CONFIG_DIR";
/// Built-in working-memory location, relative to the project root.
pub const DEFAULT_WORKING: &str = "memory-bank/working";
/// Built-in knowledge-memory location, relative to the project root.
pub const DEFAULT_KNOWLEDGE: &str = "memory-bank/knowledge";
const CONFIG_FILE: &str = "config.toml";
const LEGACY_CONFIG_FILE: &str = "paths.toml";

#[derive(Debug, Error)]
pub enum MemoryError {
    #[error("failed to read memory path config {path}: {source}")]
    ReadFailed { path: PathBuf, source: io::Error },
    #[error("failed to write memory path config {path}: {source}")]
    WriteFailed { path: PathBuf, source: io::Error },
    #[error("failed to parse memory path config {path}: {source}")]
    ParseFailed {
        path: PathBuf,
        source: toml::de::Error,
    },
    #[error("failed to resolve relative {label} path `{path}`: {source}")]
    ResolveRelative {
        label: String,
        path: PathBuf,
        source: io::Error,
    },
    #[error(
        "invalid learn store configuration at {path}: `default.learn` must be a non-empty path string"
    )]
    InvalidLearnPath { path: PathBuf },
    #[error("failed to serialize memory path config: {0}")]
    SerializeFailed(#[from] toml::ser::Error),
    #[error("{label} directory `{value}` needs a home directory to expand `~`")]
    NoHome { label: String, value: String },
}

/// Which memory a setting addresses.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum MemoryKind {
    Working,
    Knowledge,
}

impl MemoryKind {
    pub fn env_var(self) -> &'static str {
        match self {
            MemoryKind::Working => WORKING_ENV,
            MemoryKind::Knowledge => KNOWLEDGE_ENV,
        }
    }

    pub fn default_relative(self) -> &'static str {
        match self {
            MemoryKind::Working => DEFAULT_WORKING,
            MemoryKind::Knowledge => DEFAULT_KNOWLEDGE,
        }
    }
}

impl std::fmt::Display for MemoryKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            MemoryKind::Working => "working",
            MemoryKind::Knowledge => "knowledge",
        })
    }
}

/// One `[default]` or `[project."…"]` table.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Entry {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub working: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub knowledge: Option<String>,
    /// The `toz` output-capture store directory. Not part of `MemoryKind`:
    /// toz has no env override and no built-in fallback in this crate.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub toz: Option<String>,
    /// Global friction store setting. Project entries are preserved but ignored.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub learn: Option<String>,
}

impl Entry {
    pub fn get(&self, kind: MemoryKind) -> Option<&str> {
        match kind {
            MemoryKind::Working => self.working.as_deref(),
            MemoryKind::Knowledge => self.knowledge.as_deref(),
        }
    }

    pub fn set(&mut self, kind: MemoryKind, value: Option<String>) {
        match kind {
            MemoryKind::Working => self.working = value,
            MemoryKind::Knowledge => self.knowledge = value,
        }
    }

    pub fn is_empty(&self) -> bool {
        self.working.is_none()
            && self.knowledge.is_none()
            && self.toz.is_none()
            && self.learn.is_none()
    }
}

/// User-wide settings stored alongside memory paths.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Settings {
    /// Preserve hand-edited keys so a path edit cannot silently erase them.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl Settings {
    pub fn is_empty(&self) -> bool {
        self.unknown.is_empty()
    }
}

/// The whole `config.toml`.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Config {
    #[serde(default, skip_serializing_if = "Entry::is_empty")]
    pub default: Entry,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub project: BTreeMap<String, Entry>,
    #[serde(default, skip_serializing_if = "Settings::is_empty")]
    pub settings: Settings,
}

impl Config {
    /// The entry for `root`, matched on the canonical root path so
    /// `/a/b/../c` and `/a/c` address the same table.
    pub fn project_entry(&self, root: &Path) -> Option<&Entry> {
        let root = canonical_or_lexical(root);
        self.project
            .iter()
            .find(|(key, _)| canonical_or_lexical(Path::new(key)) == root)
            .map(|(_, entry)| entry)
    }

    pub fn project_entry_mut(&mut self, root: &Path) -> &mut Entry {
        let canonical = canonical_or_lexical(root);
        let key = self
            .project
            .keys()
            .find(|key| canonical_or_lexical(Path::new(key)) == canonical)
            .cloned()
            .unwrap_or_else(|| canonical.to_string_lossy().into_owned());
        self.project.entry(key).or_default()
    }

    /// Drop project tables that no longer set anything.
    pub fn prune(&mut self) {
        self.project.retain(|_, entry| !entry.is_empty());
    }
}

/// Where a resolved path came from, highest precedence first.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Source {
    /// `VARDE_WORKING_DIR` / `VARDE_KNOWLEDGE_DIR`.
    Env,
    /// A `[project."…"]` table in `config.toml`.
    Project,
    /// The `[default]` table in `config.toml`.
    Default,
    /// `memory-bank/{working,knowledge}` under the project root.
    Builtin,
}

impl std::fmt::Display for Source {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(match self {
            Source::Env => "env",
            Source::Project => "project",
            Source::Default => "default",
            Source::Builtin => "builtin",
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Resolved {
    pub path: PathBuf,
    pub source: Source,
}

/// The resolved memory locations for one project root.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MemoryPaths {
    pub root: PathBuf,
    /// The caller checkout remains a valid workflow write destination.
    checkout_root: PathBuf,
    pub working: Resolved,
    pub knowledge: Resolved,
    /// The `toz` output-capture store directory, when `config.toml` redirects
    /// it. `None` when unset — toz resolves its own default outside this
    /// crate.
    pub toz: Option<Resolved>,
    /// Global friction store location, independent of the project root.
    pub learn: Resolved,
    /// The config file consulted (whether or not it exists).
    pub config: PathBuf,
}

impl MemoryPaths {
    /// Resolve project memories and the global friction store. A missing
    /// config file is not an error.
    pub fn resolve(root: &Path) -> Result<Self, MemoryError> {
        let config = load_config()?;
        Self::resolve_with(root, &config)
    }

    pub fn resolve_with(root: &Path, config: &Config) -> Result<Self, MemoryError> {
        let checkout_root = canonical_or_lexical(root);
        let root = repository_memory_root(&checkout_root);
        let project = config.project_entry(&root);
        let resolve_kind = |kind: MemoryKind| -> Result<Resolved, MemoryError> {
            if let Some(value) = env::var_os(kind.env_var()).filter(|value| !value.is_empty()) {
                let value = value.to_string_lossy().into_owned();
                return Ok(Resolved {
                    path: expand(&root, &kind.to_string(), &value)?,
                    source: Source::Env,
                });
            }
            if let Some(value) = project.and_then(|entry| entry.get(kind)) {
                return Ok(Resolved {
                    path: expand(&root, &kind.to_string(), value)?,
                    source: Source::Project,
                });
            }
            if let Some(value) = config.default.get(kind) {
                return Ok(Resolved {
                    path: expand(&root, &kind.to_string(), value)?,
                    source: Source::Default,
                });
            }
            Ok(Resolved {
                path: root.join(kind.default_relative()),
                source: Source::Builtin,
            })
        };
        // toz has no env override and no built-in fallback: it is `None`
        // unless a config entry sets it. toz supplies its own default
        // elsewhere; this crate only stores and reports the redirect.
        let toz = if let Some(value) = project.and_then(|entry| entry.toz.as_deref()) {
            Some(Resolved {
                path: expand(&root, "toz", value)?,
                source: Source::Project,
            })
        } else if let Some(value) = config.default.toz.as_deref() {
            Some(Resolved {
                path: expand(&root, "toz", value)?,
                source: Source::Default,
            })
        } else {
            None
        };
        let learn = if let Some(value) = env::var_os(LEARN_ENV).filter(|value| !value.is_empty()) {
            Resolved {
                path: expand_global(Path::new(&value), "learn")?,
                source: Source::Env,
            }
        } else if let Some(value) = config.default.learn.as_deref() {
            if value.trim().is_empty() {
                return Err(MemoryError::InvalidLearnPath {
                    path: config_path(),
                });
            }
            Resolved {
                path: expand_global(Path::new(value), "learn")?,
                source: Source::Default,
            }
        } else {
            let fallback = config_path()
                .parent()
                .unwrap_or_else(|| Path::new("."))
                .join("learn");
            Resolved {
                path: expand_global(&fallback, "learn")?,
                source: Source::Builtin,
            }
        };
        Ok(Self {
            working: resolve_kind(MemoryKind::Working)?,
            knowledge: resolve_kind(MemoryKind::Knowledge)?,
            toz,
            learn,
            config: config_path(),
            checkout_root,
            root,
        })
    }

    pub fn get(&self, kind: MemoryKind) -> &Resolved {
        match kind {
            MemoryKind::Working => &self.working,
            MemoryKind::Knowledge => &self.knowledge,
        }
    }

    /// Every directory a workflow write may land in: the caller checkout,
    /// repository memory root, and any redirected memory. Canonical where the directory exists, so
    /// callers can compare against canonicalized paths.
    pub fn write_roots(&self) -> Vec<PathBuf> {
        let mut roots = Vec::new();
        for candidate in [
            &self.checkout_root,
            &self.root,
            &self.working.path,
            &self.knowledge.path,
        ] {
            let candidate = canonical_or_lexical(candidate);
            if !roots.iter().any(|root| candidate.starts_with(root)) {
                roots.retain(|root: &PathBuf| !root.starts_with(&candidate));
                roots.push(candidate);
            }
        }
        roots
    }

    /// Whether `path` (already canonical, or lexical if it does not exist
    /// yet) lies under one of [`Self::write_roots`].
    pub fn contains(&self, path: &Path) -> bool {
        let path = canonical_or_lexical(path);
        self.write_roots().iter().any(|root| path.starts_with(root))
    }
}

/// The user-scoped config file: `$VARDE_CONFIG_DIR/config.toml`, else
/// `$XDG_CONFIG_HOME/varde/config.toml`, else `~/.config/varde/config.toml`.
/// With no home directory at all, a relative `.config/varde/config.toml`.
pub fn config_path() -> PathBuf {
    config_dir().join(CONFIG_FILE)
}

pub fn legacy_config_path() -> PathBuf {
    config_dir().join(LEGACY_CONFIG_FILE)
}

fn config_dir() -> PathBuf {
    if let Some(dir) = env::var_os(CONFIG_DIR_ENV).filter(|value| !value.is_empty()) {
        return PathBuf::from(dir);
    }
    if let Some(dir) = env::var_os("XDG_CONFIG_HOME").filter(|value| !value.is_empty()) {
        return PathBuf::from(dir).join("varde");
    }
    dirs::home_dir()
        .map(|home| home.join(".config"))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("varde")
}

/// Load `config.toml`, falling back to legacy `paths.toml` when absent.
pub fn load_config() -> Result<Config, MemoryError> {
    let path = if config_path().exists() {
        config_path()
    } else {
        legacy_config_path()
    };
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(Config::default()),
        Err(source) => return Err(MemoryError::ReadFailed { path, source }),
    };
    toml::from_str(&text).map_err(|source| MemoryError::ParseFailed { path, source })
}

/// Write `config.toml`, creating its directory. A successful write removes the
/// legacy file; an empty config leaves neither file behind.
pub fn save_config(config: &Config) -> Result<PathBuf, MemoryError> {
    let path = config_path();
    save_config_at(config, &path, &legacy_config_path(), |from, to| {
        std::fs::rename(from, to)
    })
}

fn save_config_at(
    config: &Config,
    path: &Path,
    legacy: &Path,
    publish: impl FnOnce(&Path, &Path) -> io::Result<()>,
) -> Result<PathBuf, MemoryError> {
    if config.default.is_empty() && config.project.is_empty() && config.settings.is_empty() {
        remove_if_present(path)?;
        remove_if_present(legacy)?;
        return Ok(path.to_path_buf());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|source| MemoryError::WriteFailed {
            path: path.to_path_buf(),
            source,
        })?;
    }
    let text = toml::to_string_pretty(config)?;
    let temp = unique_config_temp_path(path);
    let mut created = false;
    let result = (|| -> io::Result<()> {
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temp)?;
        created = true;
        file.write_all(text.as_bytes())?;
        file.flush()?;
        file.sync_all()?;
        drop(file);
        publish(&temp, path)
    })();
    if created && result.is_err() {
        let _ = std::fs::remove_file(&temp);
    }
    result.map_err(|source| MemoryError::WriteFailed {
        path: path.to_path_buf(),
        source,
    })?;
    remove_if_present(legacy)?;
    Ok(path.to_path_buf())
}

fn unique_config_temp_path(path: &Path) -> PathBuf {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let nonce = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    path.with_file_name(format!(
        ".{CONFIG_FILE}.tmp-{}-{now}-{nonce}",
        std::process::id()
    ))
}

fn remove_if_present(path: &Path) -> Result<(), MemoryError> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(source) if source.kind() == io::ErrorKind::NotFound => Ok(()),
        Err(source) => Err(MemoryError::WriteFailed {
            path: path.to_path_buf(),
            source,
        }),
    }
}

/// Find the project root that owns `start`, first match wins:
///
/// 1. the main Git checkout (or bare repository), shared by all linked
///    worktrees and nested modules. Legacy worktree config entries are ignored.
/// 2. a configured project whose resolved working/knowledge directory
///    contains `start` (a redirected artifact outside the tree), or whose
///    root itself is an ancestor of `start` (a project fully redirected
///    away, so no `memory-bank/` exists under its root at all).
/// 3. the nearest ancestor containing a `memory-bank/` directory for
///    projects outside git.
///
/// A caller that wants a guaranteed root (rather than "no project found")
/// falls back to `start` itself, same as `paths` with no `--project`.
pub fn find_root(start: &Path) -> Option<PathBuf> {
    let start = canonical_or_lexical(start);
    let begin = if start.is_dir() {
        start.as_path()
    } else {
        start.parent()?
    };
    let config = load_config().ok();
    if let Some(worktree) = git_top_level(begin) {
        return Some(repository_memory_root(&worktree));
    }
    config
        .as_ref()
        .and_then(|config| configured_project_root(&start, config))
        .or_else(|| memory_bank_ancestor(begin))
        .or_else(|| memory_bank_ancestor(&env::current_dir().ok()?))
}

fn git_top_level(start: &Path) -> Option<PathBuf> {
    let output = std::process::Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .current_dir(start)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8(output.stdout).ok()?;
    Some(canonical_or_lexical(Path::new(text.trim())))
}

/// A configured project whose resolved working/knowledge directory contains
/// `start`, or whose root itself is an ancestor of `start`.
fn configured_project_root(start: &Path, config: &Config) -> Option<PathBuf> {
    for key in config.project.keys() {
        let root = PathBuf::from(key);
        let Ok(paths) = MemoryPaths::resolve_with(&root, config) else {
            continue;
        };
        let owns_memory = [&paths.working.path, &paths.knowledge.path]
            .into_iter()
            .any(|dir| start.starts_with(canonical_or_lexical(dir)));
        let owns_root = start.starts_with(canonical_or_lexical(&root));
        if owns_memory || owns_root {
            return Some(paths.root);
        }
    }
    None
}

fn memory_bank_ancestor(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .find(|ancestor| ancestor.join("memory-bank").is_dir())
        .map(Path::to_path_buf)
}

/// Normalize a linked worktree to the repository that owns its memory.
/// Ordinary checkouts and non-Git project paths keep their canonical root.
/// The common Git config or inventory identifies the repository memory root.
/// Separate metadata needs `core.worktree` to identify its checkout; for a
/// bare repository, the first inventory entry is the bare repository itself.
pub fn repository_memory_root(root: &Path) -> PathBuf {
    let root = canonical_or_lexical(root);
    git_worktree_root(&root).unwrap_or(root)
}

fn git_worktree_root(start: &Path) -> Option<PathBuf> {
    let git_dir = git_directory(start, "--git-dir")?;
    let common_dir = git_directory(start, "--git-common-dir")?;
    if git_dir == common_dir {
        return None;
    }
    // Separate Git metadata needs core.worktree to identify its checkout.
    // Query the common config, not a linked worktree's private config.
    if let Ok(output) = std::process::Command::new("git")
        .arg("--git-dir")
        .arg(&common_dir)
        .args(["config", "--null", "--get", "core.worktree"])
        .current_dir(start)
        .output()
        && output.status.success()
        && let Some(path) = git_path(output.stdout.strip_suffix(&[0]).unwrap_or(&output.stdout))
        && !path.as_os_str().is_empty()
    {
        let path = if path.is_absolute() {
            path
        } else {
            common_dir.join(path)
        };
        return Some(canonical_or_lexical(&path));
    }
    let output = std::process::Command::new("git")
        .args(["worktree", "list", "--porcelain", "-z"])
        .current_dir(start)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    // The main worktree is listed first; -z preserves whitespace in paths.
    let first = output.stdout.split(|byte| *byte == 0).next()?;
    let path = first.strip_prefix(b"worktree ")?;
    Some(canonical_or_lexical(&git_path(path)?))
}

fn git_path(bytes: &[u8]) -> Option<PathBuf> {
    #[cfg(unix)]
    {
        use std::os::unix::ffi::OsStrExt;
        Some(PathBuf::from(OsStr::from_bytes(bytes)))
    }
    #[cfg(not(unix))]
    {
        Some(PathBuf::from(std::str::from_utf8(bytes).ok()?))
    }
}

fn git_directory(start: &Path, flag: &str) -> Option<PathBuf> {
    let output = std::process::Command::new("git")
        .args(["rev-parse", flag])
        .current_dir(start)
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8(output.stdout).ok()?;
    let directory = PathBuf::from(text.trim());
    let directory = if directory.is_absolute() {
        directory
    } else {
        start.join(directory)
    };
    Some(canonical_or_lexical(&directory))
}

fn expand(root: &Path, label: &str, value: &str) -> Result<PathBuf, MemoryError> {
    let project = root
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let value = value.replace("{project}", &project);
    let expanded = if value == "~" || value.starts_with("~/") {
        let home = dirs::home_dir().ok_or_else(|| MemoryError::NoHome {
            label: label.to_string(),
            value: value.clone(),
        })?;
        home.join(value.trim_start_matches('~').trim_start_matches('/'))
    } else {
        PathBuf::from(value)
    };
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        root.join(expanded)
    };
    Ok(canonical_or_lexical(&absolute))
}

fn expand_global(path: &Path, label: &str) -> Result<PathBuf, MemoryError> {
    let mut components = path.components();
    let expanded = if components.next() == Some(Component::Normal(OsStr::new("~"))) {
        let home = dirs::home_dir().ok_or_else(|| MemoryError::NoHome {
            label: label.to_owned(),
            value: path.to_string_lossy().into_owned(),
        })?;
        home.join(components.as_path())
    } else {
        path.to_path_buf()
    };
    let absolute = if expanded.is_absolute() {
        expanded
    } else {
        env::current_dir()
            .map_err(|source| MemoryError::ResolveRelative {
                label: label.to_owned(),
                path: expanded.clone(),
                source,
            })?
            .join(expanded)
    };
    Ok(canonical_or_lexical(&absolute))
}

/// `canonicalize()` when the path exists. Otherwise canonicalize the
/// nearest existing ancestor and reattach the missing tail, so a
/// redirected memory directory that has not been written yet still
/// compares equal to its canonical form once created (symlinked parents
/// such as `/tmp` → `/private/tmp` would otherwise split the two).
pub fn canonical_or_lexical(path: &Path) -> PathBuf {
    if let Ok(canonical) = path.canonicalize() {
        return canonical;
    }
    let mut tail = Vec::new();
    let mut current = path;
    while let Some(parent) = current.parent() {
        if let Some(name) = current.file_name() {
            tail.push(name.to_os_string());
        }
        if let Ok(canonical) = parent.canonicalize() {
            return tail
                .iter()
                .rev()
                .fold(canonical, |acc, name| acc.join(name));
        }
        current = parent;
    }
    path.to_path_buf()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn config(text: &str) -> Config {
        toml::from_str(text).unwrap()
    }

    #[test]
    fn builtin_defaults_when_config_is_empty() {
        let root = Path::new("/srv/app");
        let paths = MemoryPaths::resolve_with(root, &Config::default()).unwrap();
        assert_eq!(paths.working.path, root.join(DEFAULT_WORKING));
        assert_eq!(paths.working.source, Source::Builtin);
        assert_eq!(paths.knowledge.path, root.join(DEFAULT_KNOWLEDGE));
        assert_eq!(paths.knowledge.source, Source::Builtin);
    }

    #[test]
    fn project_entry_beats_default_and_expands_placeholder() {
        let cfg = config(
            r#"
[default]
working = "/mem/{project}/working"
knowledge = "/mem/{project}/knowledge"

[project."/srv/app"]
working = "/fast/app-working"
"#,
        );
        let paths = MemoryPaths::resolve_with(Path::new("/srv/app"), &cfg).unwrap();
        assert_eq!(paths.working.path, PathBuf::from("/fast/app-working"));
        assert_eq!(paths.working.source, Source::Project);
        assert_eq!(paths.knowledge.path, PathBuf::from("/mem/app/knowledge"));
        assert_eq!(paths.knowledge.source, Source::Default);
    }

    #[test]
    fn relative_values_resolve_against_root() {
        let cfg = config("[default]\nworking = \".local-working\"\n");
        let paths = MemoryPaths::resolve_with(Path::new("/srv/app"), &cfg).unwrap();
        assert_eq!(paths.working.path, PathBuf::from("/srv/app/.local-working"));
    }

    #[test]
    fn write_roots_collapse_nested_directories() {
        let cfg = config("[default]\nworking = \"/elsewhere/working\"\n");
        let paths = MemoryPaths::resolve_with(Path::new("/srv/app"), &cfg).unwrap();
        let roots = paths.write_roots();
        assert_eq!(
            roots,
            vec![
                PathBuf::from("/srv/app"),
                PathBuf::from("/elsewhere/working")
            ]
        );
        assert!(paths.contains(Path::new("/elsewhere/working/plans/x/plan.md")));
        assert!(paths.contains(Path::new("/srv/app/memory-bank/knowledge/a.md")));
        assert!(!paths.contains(Path::new("/elsewhere/other")));
    }

    #[test]
    fn config_round_trips_and_prunes_empty_tables() {
        let mut cfg = Config::default();
        cfg.project_entry_mut(Path::new("/srv/app"))
            .set(MemoryKind::Knowledge, Some("/k".into()));
        cfg.project_entry_mut(Path::new("/srv/other"));
        cfg.prune();
        let text = toml::to_string_pretty(&cfg).unwrap();
        assert!(text.contains("[project.\"/srv/app\"]"), "{text}");
        assert!(!text.contains("/srv/other"), "{text}");
        assert_eq!(config(&text), cfg);
    }

    #[test]
    fn toz_key_survives_config_rewrite() {
        let mut cfg = Config::default();
        cfg.project_entry_mut(Path::new("/srv/app")).toz = Some("/srv/toz-store".into());
        cfg.default.toz = Some("~/toz/{project}".into());
        let text = toml::to_string_pretty(&cfg).unwrap();
        assert!(text.contains("toz = \"/srv/toz-store\""), "{text}");
        assert!(text.contains("toz = \"~/toz/{project}\""), "{text}");
        // Rewriting an already-loaded config (as `paths set` does when it
        // also edits working/knowledge) must not drop the `toz` key.
        let mut reloaded = config(&text);
        reloaded
            .project_entry_mut(Path::new("/srv/app"))
            .set(MemoryKind::Working, Some("/srv/working".into()));
        let rewritten = toml::to_string_pretty(&reloaded).unwrap();
        assert!(
            rewritten.contains("toz = \"/srv/toz-store\""),
            "{rewritten}"
        );
        assert!(
            rewritten.contains("toz = \"~/toz/{project}\""),
            "{rewritten}"
        );
        assert_eq!(config(&rewritten), reloaded);
    }

    #[test]
    fn toz_resolves_project_then_default_with_no_builtin_fallback() {
        let root = Path::new("/srv/app");
        let empty = MemoryPaths::resolve_with(root, &Config::default()).unwrap();
        assert_eq!(empty.toz, None);

        let cfg = config("[default]\ntoz = \"/mem/{project}/toz\"\n");
        let via_default = MemoryPaths::resolve_with(root, &cfg).unwrap();
        assert_eq!(
            via_default.toz,
            Some(Resolved {
                path: PathBuf::from("/mem/app/toz"),
                source: Source::Default,
            })
        );

        let cfg = config(
            "[default]\ntoz = \"/mem/{project}/toz\"\n\n[project.\"/srv/app\"]\ntoz = \"/fast/toz\"\n",
        );
        let via_project = MemoryPaths::resolve_with(root, &cfg).unwrap();
        assert_eq!(
            via_project.toz,
            Some(Resolved {
                path: PathBuf::from("/fast/toz"),
                source: Source::Project,
            })
        );
    }

    #[test]
    fn failed_config_publish_keeps_legacy_readable() {
        let dir = std::env::temp_dir().join(format!(
            "varde-config-publish-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        let current = dir.join(CONFIG_FILE);
        let legacy = dir.join(LEGACY_CONFIG_FILE);
        let old = "[default]\nworking = \"/old-working\"\n";
        std::fs::write(&legacy, old).unwrap();
        let new = config("[default]\nworking = \"/new-working\"\n");

        let failed = save_config_at(&new, &current, &legacy, |_, _| {
            Err(io::Error::new(io::ErrorKind::Interrupted, "before rename"))
        });
        assert!(matches!(failed, Err(MemoryError::WriteFailed { .. })));
        assert!(!current.exists());
        assert_eq!(
            config(&std::fs::read_to_string(&legacy).unwrap())
                .default
                .working,
            Some("/old-working".into())
        );

        save_config_at(&new, &current, &legacy, |from, to| {
            std::fs::rename(from, to)
        })
        .unwrap();
        assert!(!legacy.exists());
        assert_eq!(config(&std::fs::read_to_string(&current).unwrap()), new);
        assert_eq!(std::fs::read_dir(&dir).unwrap().count(), 1);
        std::fs::remove_dir_all(dir).unwrap();
    }
}
