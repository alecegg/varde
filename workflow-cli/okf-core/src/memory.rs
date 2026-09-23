//! Memory-bank location resolution: where a project's working memory
//! (`memory-bank/working/`) and knowledge memory (`memory-bank/knowledge/`)
//! live.
//!
//! Both default to the project tree. A user-scoped config file at
//! `$XDG_CONFIG_HOME/varde/paths.toml` (falling back to
//! `~/.config/varde/paths.toml`) can redirect either one, per project or
//! for every project, and `VARDE_WORKING_DIR` / `VARDE_KNOWLEDGE_DIR`
//! override everything for one process.
//!
//! The config deliberately lives outside any repository: which folder holds
//! a user's memory is a machine-scoped choice, so it never enters git
//! history the way a `memory-bank/config/` file would.
//!
//! ```toml
//! [default]                       # optional; applies to every project
//! working = "~/varde-memory/{project}/working"
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
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

/// Per-process override for the working-memory directory.
pub const WORKING_ENV: &str = "VARDE_WORKING_DIR";
/// Per-process override for the knowledge-memory directory.
pub const KNOWLEDGE_ENV: &str = "VARDE_KNOWLEDGE_DIR";
/// Overrides the directory holding `paths.toml` (tests and unusual setups).
pub const CONFIG_DIR_ENV: &str = "VARDE_CONFIG_DIR";
/// Built-in working-memory location, relative to the project root.
pub const DEFAULT_WORKING: &str = "memory-bank/working";
/// Built-in knowledge-memory location, relative to the project root.
pub const DEFAULT_KNOWLEDGE: &str = "memory-bank/knowledge";
const CONFIG_FILE: &str = "paths.toml";

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
    #[error("failed to serialize memory path config: {0}")]
    SerializeFailed(#[from] toml::ser::Error),
    #[error("{kind} directory `{value}` needs a home directory to expand `~`")]
    NoHome { kind: MemoryKind, value: String },
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
        self.working.is_none() && self.knowledge.is_none()
    }
}

/// The whole `paths.toml`.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Config {
    #[serde(default, skip_serializing_if = "Entry::is_empty")]
    pub default: Entry,
    #[serde(default, skip_serializing_if = "BTreeMap::is_empty")]
    pub project: BTreeMap<String, Entry>,
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
    /// A `[project."…"]` table in `paths.toml`.
    Project,
    /// The `[default]` table in `paths.toml`.
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
    pub working: Resolved,
    pub knowledge: Resolved,
    /// The config file consulted (whether or not it exists).
    pub config: PathBuf,
}

impl MemoryPaths {
    /// Resolve both memories for `root` using env → project → default →
    /// built-in precedence. A missing config file is not an error.
    pub fn resolve(root: &Path) -> Result<Self, MemoryError> {
        let config = load_config()?;
        Self::resolve_with(root, &config)
    }

    pub fn resolve_with(root: &Path, config: &Config) -> Result<Self, MemoryError> {
        let root = canonical_or_lexical(root);
        let project = config.project_entry(&root);
        let resolve_kind = |kind: MemoryKind| -> Result<Resolved, MemoryError> {
            if let Some(value) = env::var_os(kind.env_var()).filter(|value| !value.is_empty()) {
                let value = value.to_string_lossy().into_owned();
                return Ok(Resolved {
                    path: expand(&root, kind, &value)?,
                    source: Source::Env,
                });
            }
            if let Some(value) = project.and_then(|entry| entry.get(kind)) {
                return Ok(Resolved {
                    path: expand(&root, kind, value)?,
                    source: Source::Project,
                });
            }
            if let Some(value) = config.default.get(kind) {
                return Ok(Resolved {
                    path: expand(&root, kind, value)?,
                    source: Source::Default,
                });
            }
            Ok(Resolved {
                path: root.join(kind.default_relative()),
                source: Source::Builtin,
            })
        };
        Ok(Self {
            working: resolve_kind(MemoryKind::Working)?,
            knowledge: resolve_kind(MemoryKind::Knowledge)?,
            config: config_path(),
            root,
        })
    }

    pub fn get(&self, kind: MemoryKind) -> &Resolved {
        match kind {
            MemoryKind::Working => &self.working,
            MemoryKind::Knowledge => &self.knowledge,
        }
    }

    /// Every directory a workflow write may land in: the project root plus
    /// any redirected memory. Canonical where the directory exists, so
    /// callers can compare against canonicalized paths.
    pub fn write_roots(&self) -> Vec<PathBuf> {
        let mut roots = Vec::new();
        for candidate in [&self.root, &self.working.path, &self.knowledge.path] {
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

/// The user-scoped config file: `$VARDE_CONFIG_DIR/paths.toml`, else
/// `$XDG_CONFIG_HOME/varde/paths.toml`, else `~/.config/varde/paths.toml`.
/// With no home directory at all, a relative `.config/varde/paths.toml`.
pub fn config_path() -> PathBuf {
    if let Some(dir) = env::var_os(CONFIG_DIR_ENV).filter(|value| !value.is_empty()) {
        return PathBuf::from(dir).join(CONFIG_FILE);
    }
    if let Some(dir) = env::var_os("XDG_CONFIG_HOME").filter(|value| !value.is_empty()) {
        return PathBuf::from(dir).join("varde").join(CONFIG_FILE);
    }
    dirs::home_dir()
        .map(|home| home.join(".config"))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("varde")
        .join(CONFIG_FILE)
}

/// Load `paths.toml`; a missing file is an empty config.
pub fn load_config() -> Result<Config, MemoryError> {
    let path = config_path();
    let text = match std::fs::read_to_string(&path) {
        Ok(text) => text,
        Err(source) if source.kind() == io::ErrorKind::NotFound => return Ok(Config::default()),
        Err(source) => return Err(MemoryError::ReadFailed { path, source }),
    };
    toml::from_str(&text).map_err(|source| MemoryError::ParseFailed { path, source })
}

/// Write `paths.toml`, creating its directory. An empty config removes the
/// file so an unset leaves no trace.
pub fn save_config(config: &Config) -> Result<PathBuf, MemoryError> {
    let path = config_path();
    if *config == Config::default() {
        return match std::fs::remove_file(&path) {
            Ok(()) => Ok(path),
            Err(source) if source.kind() == io::ErrorKind::NotFound => Ok(path),
            Err(source) => Err(MemoryError::WriteFailed { path, source }),
        };
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|source| MemoryError::WriteFailed {
            path: path.clone(),
            source,
        })?;
    }
    let text = toml::to_string_pretty(config)?;
    std::fs::write(&path, text).map_err(|source| MemoryError::WriteFailed {
        path: path.clone(),
        source,
    })?;
    Ok(path)
}

/// Find the project root that owns `start`.
///
/// Walks `start`'s ancestors for a `memory-bank/` directory first (an
/// artifact inside the project tree). When the artifact lives in a
/// redirected memory outside the tree, matches it against each configured
/// project's resolved working/knowledge directories, then falls back to the
/// current directory's ancestors.
pub fn find_root(start: &Path) -> Option<PathBuf> {
    let start = canonical_or_lexical(start);
    let begin = if start.is_dir() {
        start.as_path()
    } else {
        start.parent()?
    };
    if let Some(root) = memory_bank_ancestor(begin) {
        return Some(root);
    }
    if let Ok(config) = load_config() {
        for key in config.project.keys() {
            let root = PathBuf::from(key);
            let Ok(paths) = MemoryPaths::resolve_with(&root, &config) else {
                continue;
            };
            let owns = [&paths.working.path, &paths.knowledge.path]
                .into_iter()
                .any(|dir| start.starts_with(canonical_or_lexical(dir)));
            if owns {
                return Some(paths.root);
            }
        }
    }
    let cwd = env::current_dir().ok()?;
    memory_bank_ancestor(&cwd)
}

fn memory_bank_ancestor(start: &Path) -> Option<PathBuf> {
    start
        .ancestors()
        .find(|ancestor| ancestor.join("memory-bank").is_dir())
        .map(Path::to_path_buf)
}

fn expand(root: &Path, kind: MemoryKind, value: &str) -> Result<PathBuf, MemoryError> {
    let project = root
        .file_name()
        .map(|name| name.to_string_lossy().into_owned())
        .unwrap_or_default();
    let value = value.replace("{project}", &project);
    let expanded = if value == "~" || value.starts_with("~/") {
        let home = dirs::home_dir().ok_or_else(|| MemoryError::NoHome {
            kind,
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
}
