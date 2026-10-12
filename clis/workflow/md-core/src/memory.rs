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
use std::fs;
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{Duration, SystemTime};
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
/// Directory containing current session notes under the working store.
pub const SESSION_NOTES_DIR: &str = "session-notes";
/// Filename for a current session note.
pub const NOTES_FILE: &str = "notes.md";
/// Legacy directory containing session handoffs.
pub const LEGACY_HANDOFFS_DIR: &str = "handoffs";
/// Legacy session-note file name (`handoff.md`).
pub const LEGACY_HANDOFF_FILE: &str = "handoff.md";
const CONFIG_FILE: &str = "config.toml";
const LEGACY_CONFIG_FILE: &str = "paths.toml";
const LIVE_SESSION_WINDOW: Duration = Duration::from_secs(10 * 60);

/// One note path planned or completed by the session-notes migration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SessionNotesMove {
    pub from: PathBuf,
    pub to: PathBuf,
}

/// A session directory left in place by the migration.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SessionNotesSkip {
    pub path: PathBuf,
    pub reason: String,
}

/// A legacy note whose destination already exists.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct SessionNotesConflict {
    pub from: PathBuf,
    pub to: PathBuf,
}

/// Results from a dry-run or an applied session-notes migration.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize)]
pub struct SessionNotesMigration {
    pub moved: Vec<SessionNotesMove>,
    pub skipped: Vec<SessionNotesSkip>,
    pub conflicts: Vec<SessionNotesConflict>,
}

/// Move legacy session directories from `handoffs/` into `session-notes/`.
///
/// A dry-run reports the paths that would move without writing anything.
/// Recent notes are skipped as live unless `include_live` is true. Existing
/// destination directories are always reported as conflicts and preserved.
pub fn migrate_session_notes(
    working: &Path,
    dry_run: bool,
    include_live: bool,
) -> io::Result<SessionNotesMigration> {
    let legacy_root = working.join(LEGACY_HANDOFFS_DIR);
    let destination_root = working.join(SESSION_NOTES_DIR);
    let mut result = SessionNotesMigration::default();

    if !path_exists(&legacy_root)? {
        return Ok(result);
    }
    if !fs::symlink_metadata(&legacy_root)?.file_type().is_dir() {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            format!(
                "legacy handoffs path is not a directory: {}",
                legacy_root.display()
            ),
        ));
    }

    migrate_session_scope(
        &legacy_root,
        &destination_root,
        dry_run,
        include_live,
        &mut result,
    )?;
    if !dry_run {
        remove_dir_if_empty(&legacy_root)?;
    }
    Ok(result)
}

fn migrate_session_scope(
    legacy_parent: &Path,
    destination_parent: &Path,
    dry_run: bool,
    include_live: bool,
    result: &mut SessionNotesMigration,
) -> io::Result<()> {
    let mut entries = fs::read_dir(legacy_parent)?.collect::<Result<Vec<_>, _>>()?;
    entries.sort_by_key(|entry| entry.file_name());

    for entry in entries {
        if !entry.file_type()?.is_dir() {
            continue;
        }

        let legacy_dir = entry.path();
        let destination_dir = destination_parent.join(entry.file_name());
        if entry.file_name() == "archive" {
            migrate_session_scope(&legacy_dir, &destination_dir, dry_run, include_live, result)?;
            if !dry_run {
                remove_dir_if_empty(&legacy_dir)?;
            }
            continue;
        }

        let from = legacy_dir.join(LEGACY_HANDOFF_FILE);
        let source_metadata = match fs::symlink_metadata(&from) {
            Ok(metadata) if metadata.file_type().is_file() => metadata,
            Ok(_) => continue,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error),
        };
        let to = destination_dir.join(NOTES_FILE);

        if path_exists(&destination_dir)? || path_exists(&legacy_dir.join(NOTES_FILE))? {
            result.conflicts.push(SessionNotesConflict { from, to });
            continue;
        }
        if !include_live && is_recent(source_metadata.modified()?) {
            result.skipped.push(SessionNotesSkip {
                path: legacy_dir,
                reason: "live".to_owned(),
            });
            continue;
        }

        result.moved.push(SessionNotesMove {
            from: from.clone(),
            to: to.clone(),
        });
        if !dry_run {
            fs::create_dir_all(destination_parent)?;
            let renamed = legacy_dir.join(NOTES_FILE);
            fs::rename(&from, &renamed)?;
            if let Err(error) = fs::rename(&legacy_dir, &destination_dir) {
                let _ = fs::rename(&renamed, &from);
                return Err(error);
            }
        }
    }

    if !dry_run {
        remove_dir_if_empty(legacy_parent)?;
    }
    Ok(())
}

fn path_exists(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

fn is_recent(modified: SystemTime) -> bool {
    modified
        .elapsed()
        .map(|age| age < LIVE_SESSION_WINDOW)
        .unwrap_or(true)
}

fn remove_dir_if_empty(path: &Path) -> io::Result<()> {
    match fs::remove_dir(path) {
        Ok(()) => Ok(()),
        Err(error)
            if matches!(
                error.kind(),
                io::ErrorKind::NotFound | io::ErrorKind::DirectoryNotEmpty
            ) =>
        {
            Ok(())
        }
        Err(error) => Err(error),
    }
}

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
    #[serde(default, skip_serializing_if = "Hooks::is_empty")]
    pub hooks: Hooks,
    #[serde(
        default,
        deserialize_with = "lenient_orchestration",
        skip_serializing_if = "Orchestration::is_empty"
    )]
    pub orchestration: Orchestration,
    #[serde(
        default,
        deserialize_with = "lenient_instructions",
        skip_serializing_if = "Instructions::is_empty"
    )]
    pub instructions: Instructions,
    /// Preserve unrelated top-level tables.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

/// Background plan orchestrators allowed session-wide by default.
pub const DEFAULT_ORCHESTRATORS: u32 = 4;
/// Builders per orchestrator by default; also the `execution-wave` width.
pub const DEFAULT_BUILDERS: u32 = 4;
/// Planners per orchestrator by default.
pub const DEFAULT_PLANNERS: u32 = 2;
/// Reviewers per orchestrator by default.
pub const DEFAULT_REVIEWERS: u32 = 2;
/// Explorers per orchestrator by default.
pub const DEFAULT_EXPLORERS: u32 = 4;
/// Minutes without verified task activity before status marks it stalled.
pub const DEFAULT_STALL_MINUTES: u64 = 20;
/// Seconds allowed for a configured agent wake command.
pub const DEFAULT_WAKE_TIMEOUT_SECONDS: u64 = 10;
/// Consecutive wake failures before a watcher disables wake attempts.
pub const DEFAULT_WAKE_MAX_FAILURES: u32 = 3;

/// Per-role agent caps from `[orchestration]`, with their defaults.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RoleCaps {
    pub orchestrators: u32,
    pub builders: u32,
    pub planners: u32,
    pub reviewers: u32,
    pub explorers: u32,
}

impl Default for RoleCaps {
    fn default() -> Self {
        Self {
            orchestrators: DEFAULT_ORCHESTRATORS,
            builders: DEFAULT_BUILDERS,
            planners: DEFAULT_PLANNERS,
            reviewers: DEFAULT_REVIEWERS,
            explorers: DEFAULT_EXPLORERS,
        }
    }
}

/// The `[orchestration]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Orchestration {
    /// Kept untyped so an invalid value never makes the whole config unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub orchestrators: Option<toml::Value>,
    /// Kept untyped so an invalid value never makes the whole config unreadable.
    #[serde(default, alias = "executors", skip_serializing_if = "Option::is_none")]
    pub builders: Option<toml::Value>,
    /// Kept untyped so an invalid value never makes the whole config unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub planners: Option<toml::Value>,
    /// Kept untyped so an invalid value never makes the whole config unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub reviewers: Option<toml::Value>,
    /// Kept untyped so an invalid value never makes the whole config unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub explorers: Option<toml::Value>,
    /// Legacy direct-agent cap, read as `builders` when that key is absent.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub max_agents: Option<toml::Value>,
    /// Kept untyped so invalid input does not make the whole config unreadable.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stall_minutes: Option<toml::Value>,
    /// Kept untyped so malformed commands can fall back without rejecting config.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wake_command: Option<toml::Value>,
    /// Kept untyped so malformed values can fall back without rejecting config.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wake_timeout_seconds: Option<toml::Value>,
    /// Kept untyped so malformed values can fall back without rejecting config.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub wake_max_failures: Option<toml::Value>,
    /// Unknown keys under `[orchestration]`, kept on rewrite.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
    /// Set when `orchestration` was not a table; the value is dropped on rewrite.
    #[serde(skip)]
    not_a_table: bool,
}

/// Read `orchestration` without failing the whole config when it is not a table.
fn lenient_orchestration<'de, D>(deserializer: D) -> Result<Orchestration, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = toml::Value::deserialize(deserializer)?;
    Ok(match value {
        toml::Value::Table(table) => {
            Orchestration::deserialize(table).map_err(serde::de::Error::custom)?
        }
        _ => Orchestration {
            not_a_table: true,
            ..Orchestration::default()
        },
    })
}

impl Orchestration {
    pub fn is_empty(&self) -> bool {
        self.orchestrators.is_none()
            && self.builders.is_none()
            && self.planners.is_none()
            && self.reviewers.is_none()
            && self.explorers.is_none()
            && self.max_agents.is_none()
            && self.stall_minutes.is_none()
            && self.wake_command.is_none()
            && self.wake_timeout_seconds.is_none()
            && self.wake_max_failures.is_none()
            && self.unknown.is_empty()
    }

    /// One positive-integer cap, or `default` plus a reason when the value is
    /// not a positive integer.
    fn positive(&self, value: Option<&toml::Value>, default: u32) -> (u32, Option<String>) {
        if self.not_a_table {
            return (default, Some("`orchestration` is not a table".to_string()));
        }
        match value {
            None => (default, None),
            Some(toml::Value::Integer(n)) if *n > 0 => match u32::try_from(*n) {
                Ok(n) => (n, None),
                Err(_) => (default, Some(format!("{n} is too large"))),
            },
            Some(value) => (default, Some(format!("{value} is not a positive integer"))),
        }
    }

    /// Background plan orchestrators allowed session-wide.
    pub fn orchestrators(&self) -> (u32, Option<String>) {
        self.positive(self.orchestrators.as_ref(), DEFAULT_ORCHESTRATORS)
    }

    /// Builders per orchestrator; legacy `max_agents` when `builders` is absent.
    pub fn builders(&self) -> (u32, Option<String>) {
        self.positive(
            self.builders.as_ref().or(self.max_agents.as_ref()),
            DEFAULT_BUILDERS,
        )
    }

    /// Planners per orchestrator.
    pub fn planners(&self) -> (u32, Option<String>) {
        self.positive(self.planners.as_ref(), DEFAULT_PLANNERS)
    }

    /// Reviewers per orchestrator.
    pub fn reviewers(&self) -> (u32, Option<String>) {
        self.positive(self.reviewers.as_ref(), DEFAULT_REVIEWERS)
    }

    /// Explorers per orchestrator.
    pub fn explorers(&self) -> (u32, Option<String>) {
        self.positive(self.explorers.as_ref(), DEFAULT_EXPLORERS)
    }

    /// Set the builder cap while retaining unknown keys in the table. The
    /// legacy `max_agents` key is superseded and dropped.
    pub fn set_builders(&mut self, builders: u32) {
        self.builders = Some(toml::Value::Integer(i64::from(builders)));
        self.max_agents = None;
        self.not_a_table = false;
    }

    /// The configured stall threshold, or `DEFAULT_STALL_MINUTES` plus a
    /// reason when the value is not a positive integer.
    pub fn stall_minutes(&self) -> (u64, Option<String>) {
        if self.not_a_table {
            return (
                DEFAULT_STALL_MINUTES,
                Some("`orchestration` is not a table".to_string()),
            );
        }
        match &self.stall_minutes {
            None => (DEFAULT_STALL_MINUTES, None),
            Some(toml::Value::Integer(minutes)) if *minutes > 0 => (
                u64::try_from(*minutes).expect("positive i64 fits u64"),
                None,
            ),
            Some(value) => (
                DEFAULT_STALL_MINUTES,
                Some(format!("{value} is not a positive integer")),
            ),
        }
    }

    /// The configured wake argv, or an empty command plus a reason if invalid.
    pub fn wake_command(&self) -> (Vec<String>, Option<String>) {
        if self.not_a_table {
            return (
                Vec::new(),
                Some("`orchestration` is not a table".to_string()),
            );
        }
        match &self.wake_command {
            None => (Vec::new(), None),
            Some(toml::Value::Array(values)) => {
                let command = values
                    .iter()
                    .map(|value| value.as_str().map(str::to_owned))
                    .collect::<Option<Vec<_>>>();
                match command {
                    Some(command) => (command, None),
                    None => (
                        Vec::new(),
                        Some("array contains a non-string value".to_string()),
                    ),
                }
            }
            Some(value) => (
                Vec::new(),
                Some(format!("{value} is not an array of strings")),
            ),
        }
    }

    /// The configured wake timeout, or `DEFAULT_WAKE_TIMEOUT_SECONDS` plus a reason.
    pub fn wake_timeout_seconds(&self) -> (u64, Option<String>) {
        self.positive_u64(&self.wake_timeout_seconds, DEFAULT_WAKE_TIMEOUT_SECONDS)
    }

    /// The configured wake failure limit, or `DEFAULT_WAKE_MAX_FAILURES` plus a reason.
    pub fn wake_max_failures(&self) -> (u32, Option<String>) {
        if self.not_a_table {
            return (
                DEFAULT_WAKE_MAX_FAILURES,
                Some("`orchestration` is not a table".to_string()),
            );
        }
        match &self.wake_max_failures {
            None => (DEFAULT_WAKE_MAX_FAILURES, None),
            Some(toml::Value::Integer(n)) if *n > 0 => match u32::try_from(*n) {
                Ok(n) => (n, None),
                Err(_) => (DEFAULT_WAKE_MAX_FAILURES, Some(format!("{n} is too large"))),
            },
            Some(value) => (
                DEFAULT_WAKE_MAX_FAILURES,
                Some(format!("{value} is not a positive integer")),
            ),
        }
    }

    fn positive_u64(&self, value: &Option<toml::Value>, default: u64) -> (u64, Option<String>) {
        if self.not_a_table {
            return (default, Some("`orchestration` is not a table".to_string()));
        }
        match value {
            None => (default, None),
            Some(toml::Value::Integer(n)) if *n > 0 => {
                (u64::try_from(*n).expect("positive i64 fits u64"), None)
            }
            Some(value) => (default, Some(format!("{value} is not a positive integer"))),
        }
    }
}

/// The `[instructions]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Instructions {
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub targets: Vec<String>,
    /// Unknown keys under `[instructions]`, kept on rewrite.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl Instructions {
    pub fn is_empty(&self) -> bool {
        self.targets.is_empty() && self.unknown.is_empty()
    }
}

/// Read `instructions` without failing the whole config when it is not a table.
fn lenient_instructions<'de, D>(deserializer: D) -> Result<Instructions, D::Error>
where
    D: serde::Deserializer<'de>,
{
    let value = toml::Value::deserialize(deserializer)?;
    Ok(match value {
        toml::Value::Table(table) => {
            Instructions::deserialize(table).map_err(serde::de::Error::custom)?
        }
        _ => Instructions::default(),
    })
}

/// Session-start providers used when `[hooks.session_start]` omits them.
pub const DEFAULT_SESSION_START_PROVIDERS: [&str; 2] = ["nav_map", "toz_note"];
/// Every session-start provider name the dispatcher recognises.
pub const KNOWN_SESSION_START_PROVIDERS: [&str; 3] = ["nav_map", "toz_note", "orchestration"];
/// Post-tool-use providers used when `[hooks.post_tool_use]` omits them.
pub const DEFAULT_POST_TOOL_USE_PROVIDERS: [&str; 2] = ["capture", "session_notes"];
/// Every post-tool-use provider name the dispatcher recognises.
pub const KNOWN_POST_TOOL_USE_PROVIDERS: [&str; 3] =
    ["capture", "session_notes", "context_handoff"];
/// User-prompt-submit providers used when `[hooks.user_prompt_submit]` omits them.
pub const DEFAULT_USER_PROMPT_SUBMIT_PROVIDERS: [&str; 1] = ["inbox"];
/// Every user-prompt-submit provider name the dispatcher recognises.
pub const KNOWN_USER_PROMPT_SUBMIT_PROVIDERS: [&str; 1] = ["inbox"];

/// The `[hooks]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct Hooks {
    #[serde(default, skip_serializing_if = "SessionStart::is_empty")]
    pub session_start: SessionStart,
    #[serde(default, skip_serializing_if = "PostToolUse::is_empty")]
    pub post_tool_use: PostToolUse,
    #[serde(default, skip_serializing_if = "UserPromptSubmit::is_empty")]
    pub user_prompt_submit: UserPromptSubmit,
    /// Unknown keys under `[hooks]`, kept so a config rewrite never drops them.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl Hooks {
    pub fn is_empty(&self) -> bool {
        self.session_start.is_empty()
            && self.post_tool_use.is_empty()
            && self.user_prompt_submit.is_empty()
            && self.unknown.is_empty()
    }
}

/// The `[hooks.session_start]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct SessionStart {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub providers: Option<Vec<String>>,
    /// Unknown keys under `[hooks.session_start]`, kept on rewrite.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl SessionStart {
    pub fn is_empty(&self) -> bool {
        self.providers.is_none() && self.unknown.is_empty()
    }
}

/// The `[hooks.post_tool_use]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct PostToolUse {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub providers: Option<Vec<String>>,
    /// Unknown keys under `[hooks.post_tool_use]`, kept on rewrite.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl PostToolUse {
    pub fn is_empty(&self) -> bool {
        self.providers.is_none() && self.unknown.is_empty()
    }
}

/// The `[hooks.user_prompt_submit]` table.
#[derive(Debug, Clone, Default, PartialEq, Serialize, Deserialize)]
pub struct UserPromptSubmit {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub providers: Option<Vec<String>>,
    /// Unknown keys under `[hooks.user_prompt_submit]`, kept on rewrite.
    #[serde(flatten)]
    pub unknown: BTreeMap<String, toml::Value>,
}

impl UserPromptSubmit {
    pub fn is_empty(&self) -> bool {
        self.providers.is_none() && self.unknown.is_empty()
    }
}

impl Config {
    /// Configured user-prompt-submit providers, or the built-in default list.
    pub fn user_prompt_submit_providers(&self) -> Vec<String> {
        self.hooks
            .user_prompt_submit
            .providers
            .clone()
            .unwrap_or_else(|| {
                DEFAULT_USER_PROMPT_SUBMIT_PROVIDERS
                    .map(String::from)
                    .to_vec()
            })
    }
}

impl Config {
    /// Configured post-tool-use providers, or the built-in default list.
    pub fn post_tool_use_providers(&self) -> Vec<String> {
        self.hooks
            .post_tool_use
            .providers
            .clone()
            .unwrap_or_else(|| DEFAULT_POST_TOOL_USE_PROVIDERS.map(String::from).to_vec())
            .into_iter()
            .map(|provider| {
                if provider == "context_handoff" {
                    "session_notes".to_owned()
                } else {
                    provider
                }
            })
            .collect()
    }

    /// Configured session-start providers, or the built-in default list.
    pub fn session_start_providers(&self) -> Vec<String> {
        self.hooks
            .session_start
            .providers
            .clone()
            .unwrap_or_else(|| DEFAULT_SESSION_START_PROVIDERS.map(String::from).to_vec())
    }
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

    /// The checkout the caller ran from; differs from `root` in a linked worktree.
    pub fn checkout_root(&self) -> &Path {
        &self.checkout_root
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
    varde_core::paths::varde_config_dir()
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

/// Rewrite `existing` so it holds the values of `fresh`, keeping the comments
/// and formatting of every entry that did not change. Unparseable text falls
/// back to `fresh`. Empty tables under `[hooks]` survive, so seeded comments do.
pub fn merge_toml_text(existing: &str, fresh: &str) -> String {
    let (Ok(mut old), Ok(new)) = (
        existing.parse::<toml_edit::DocumentMut>(),
        fresh.parse::<toml_edit::DocumentMut>(),
    ) else {
        return fresh.to_string();
    };
    merge_tables(old.as_table_mut(), new.as_table(), false);
    old.to_string()
}

fn merge_tables(old: &mut toml_edit::Table, new: &toml_edit::Table, keep_empty: bool) {
    let stale: Vec<String> = old
        .iter()
        .filter(|(key, item)| {
            !new.contains_key(key) && !((keep_empty || *key == "hooks") && is_empty_tables(item))
        })
        .map(|(key, _)| key.to_string())
        .collect();
    for key in stale {
        old.remove(&key);
    }
    for (key, new_item) in new.iter() {
        let Some(old_item) = old.get_mut(key) else {
            old.insert(key, new_item.clone());
            continue;
        };
        if let (Some(old_table), Some(new_table)) = (old_item.as_table_mut(), new_item.as_table()) {
            merge_tables(old_table, new_table, keep_empty || key == "hooks");
        } else if item_text(old_item) != item_text(new_item) {
            let decor = old_item.as_value().map(|value| value.decor().clone());
            *old_item = new_item.clone();
            if let (Some(decor), Some(value)) = (decor, old_item.as_value_mut()) {
                *value.decor_mut() = decor;
            }
        }
    }
}

fn is_empty_tables(item: &toml_edit::Item) -> bool {
    item.as_table()
        .is_some_and(|table| table.iter().all(|(_, child)| is_empty_tables(child)))
}

fn item_text(item: &toml_edit::Item) -> String {
    match item.as_value() {
        Some(value) => {
            let mut bare = value.clone();
            bare.decor_mut().clear();
            bare.to_string()
        }
        None => item.to_string(),
    }
}

/// Whether the file at `path` has comments or `[hooks]` tables worth keeping
/// when the config itself holds no values.
fn holds_seeded_hooks_or_comments(path: &Path) -> bool {
    std::fs::read_to_string(path).is_ok_and(|text| {
        text.lines().any(|line| {
            let line = line.trim_start();
            line.starts_with('#') || line.starts_with("[hooks")
        })
    })
}

fn save_config_at(
    config: &Config,
    path: &Path,
    legacy: &Path,
    publish: impl FnOnce(&Path, &Path) -> io::Result<()>,
) -> Result<PathBuf, MemoryError> {
    if config.default.is_empty()
        && config.project.is_empty()
        && config.settings.is_empty()
        && config.hooks.is_empty()
        && config.instructions.is_empty()
        && config.unknown.is_empty()
        && !holds_seeded_hooks_or_comments(path)
    {
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
    let fresh = toml::to_string_pretty(config)?;
    let text = match std::fs::read_to_string(path) {
        Ok(existing) => merge_toml_text(&existing, &fresh),
        Err(_) => fresh,
    };
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
    use std::fs;
    use std::sync::atomic::{AtomicU64, Ordering};

    static NEXT_TEMP_DIR: AtomicU64 = AtomicU64::new(0);

    struct TestDir(PathBuf);

    impl TestDir {
        fn new() -> Self {
            let path = env::temp_dir().join(format!(
                "varde-session-notes-{}-{}",
                std::process::id(),
                NEXT_TEMP_DIR.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn config(text: &str) -> Config {
        toml::from_str(text).unwrap()
    }

    #[test]
    fn hook_providers_default_and_override_per_event() {
        let empty = Config::default();
        assert_eq!(empty.session_start_providers(), ["nav_map", "toz_note"]);
        assert_eq!(
            empty.post_tool_use_providers(),
            ["capture", "session_notes"]
        );
        assert_eq!(empty.user_prompt_submit_providers(), ["inbox"]);

        let set = config("[hooks.post_tool_use]\nproviders = []\n[hooks.session_start]\nx = 1\n");
        assert!(set.post_tool_use_providers().is_empty());
        assert_eq!(set.session_start_providers(), ["nav_map", "toz_note"]);
        assert_eq!(set.user_prompt_submit_providers(), ["inbox"]);

        let inbox_only = config("[hooks.user_prompt_submit]\nproviders = [\"inbox\"]\n");
        assert_eq!(inbox_only.user_prompt_submit_providers(), ["inbox"]);

        let legacy = config("[hooks.post_tool_use]\nproviders = [\"context_handoff\"]\n");
        assert_eq!(legacy.post_tool_use_providers(), ["session_notes"]);
        let current = config("[hooks.post_tool_use]\nproviders = [\"session_notes\"]\n");
        assert_eq!(current.post_tool_use_providers(), ["session_notes"]);
        assert!(KNOWN_POST_TOOL_USE_PROVIDERS.contains(&"session_notes"));
        assert!(KNOWN_POST_TOOL_USE_PROVIDERS.contains(&"context_handoff"));
    }

    #[test]
    fn migrate_session_notes_dry_run_reports_without_writing() {
        let temp = TestDir::new();
        let working = temp.path();
        let legacy_dir = working.join("handoffs/session-a");
        fs::create_dir_all(&legacy_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "original note\n").unwrap();
        fs::write(legacy_dir.join("index.md"), "extra file\n").unwrap();

        let result = migrate_session_notes(working, true, true).unwrap();

        assert_eq!(result.moved.len(), 1);
        assert_eq!(result.moved[0].from, legacy_dir.join("handoff.md"));
        assert_eq!(
            result.moved[0].to,
            working.join("session-notes/session-a/notes.md")
        );
        assert!(result.skipped.is_empty());
        assert!(result.conflicts.is_empty());
        assert_eq!(
            fs::read_to_string(legacy_dir.join("handoff.md")).unwrap(),
            "original note\n"
        );
        assert!(legacy_dir.join("index.md").exists());
        assert!(!working.join("session-notes").exists());
    }

    #[test]
    fn migrate_session_notes_moves_archives_and_is_idempotent() {
        let temp = TestDir::new();
        let working = temp.path();
        let live_dir = working.join("handoffs/archive/old-session");
        let regular_dir = working.join("handoffs/session-b");
        fs::create_dir_all(&live_dir).unwrap();
        fs::create_dir_all(&regular_dir).unwrap();
        fs::write(live_dir.join("handoff.md"), "archived note\n").unwrap();
        fs::write(regular_dir.join("handoff.md"), "current note\n").unwrap();
        fs::write(regular_dir.join("index.md"), "keep alongside note\n").unwrap();

        let first = migrate_session_notes(working, false, true).unwrap();

        assert_eq!(first.moved.len(), 2);
        assert!(first.skipped.is_empty());
        assert!(first.conflicts.is_empty());
        assert_eq!(
            fs::read_to_string(working.join("session-notes/archive/old-session/notes.md")).unwrap(),
            "archived note\n"
        );
        assert_eq!(
            fs::read_to_string(working.join("session-notes/session-b/notes.md")).unwrap(),
            "current note\n"
        );
        assert_eq!(
            fs::read_to_string(working.join("session-notes/session-b/index.md")).unwrap(),
            "keep alongside note\n"
        );
        assert!(!working.join("handoffs").exists());

        let second = migrate_session_notes(working, false, false).unwrap();
        assert!(second.moved.is_empty());
        assert!(second.skipped.is_empty());
        assert!(second.conflicts.is_empty());
    }

    #[test]
    fn migrate_session_notes_reports_existing_targets_without_overwriting() {
        let temp = TestDir::new();
        let working = temp.path();
        let legacy_dir = working.join("handoffs/session-c");
        let other_legacy_dir = working.join("handoffs/session-c2");
        let target_dir = working.join("session-notes/session-c");
        fs::create_dir_all(&legacy_dir).unwrap();
        fs::create_dir_all(&other_legacy_dir).unwrap();
        fs::create_dir_all(&target_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "legacy\n").unwrap();
        fs::write(other_legacy_dir.join("handoff.md"), "move this\n").unwrap();
        fs::write(target_dir.join("notes.md"), "existing\n").unwrap();

        let result = migrate_session_notes(working, false, true).unwrap();

        assert_eq!(result.moved.len(), 1);
        assert_eq!(
            result.moved[0].to,
            working.join("session-notes/session-c2/notes.md")
        );
        assert_eq!(result.conflicts.len(), 1);
        assert_eq!(result.conflicts[0].from, legacy_dir.join("handoff.md"));
        assert_eq!(result.conflicts[0].to, target_dir.join("notes.md"));
        assert_eq!(
            fs::read_to_string(legacy_dir.join("handoff.md")).unwrap(),
            "legacy\n"
        );
        assert_eq!(
            fs::read_to_string(target_dir.join("notes.md")).unwrap(),
            "existing\n"
        );
        assert_eq!(
            fs::read_to_string(working.join("session-notes/session-c2/notes.md")).unwrap(),
            "move this\n"
        );
    }

    #[test]
    fn migrate_session_notes_does_not_replace_notes_file_inside_legacy_dir() {
        let temp = TestDir::new();
        let working = temp.path();
        let legacy_dir = working.join("handoffs/session-e");
        fs::create_dir_all(&legacy_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "legacy\n").unwrap();
        fs::write(legacy_dir.join("notes.md"), "preserve this\n").unwrap();

        let result = migrate_session_notes(working, false, true).unwrap();

        assert!(result.moved.is_empty());
        assert_eq!(result.conflicts.len(), 1);
        assert_eq!(result.conflicts[0].from, legacy_dir.join("handoff.md"));
        assert_eq!(
            result.conflicts[0].to,
            working.join("session-notes/session-e/notes.md")
        );
        assert_eq!(
            fs::read_to_string(legacy_dir.join("notes.md")).unwrap(),
            "preserve this\n"
        );
        assert_eq!(
            fs::read_to_string(legacy_dir.join("handoff.md")).unwrap(),
            "legacy\n"
        );
    }

    #[test]
    fn migrate_session_notes_skips_recent_sessions_as_live() {
        let temp = TestDir::new();
        let working = temp.path();
        let legacy_dir = working.join("handoffs/session-live");
        fs::create_dir_all(&legacy_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "live note\n").unwrap();

        let result = migrate_session_notes(working, false, false).unwrap();

        assert!(result.moved.is_empty());
        assert!(result.conflicts.is_empty());
        assert_eq!(result.skipped.len(), 1);
        assert_eq!(result.skipped[0].path, legacy_dir);
        assert_eq!(result.skipped[0].reason, "live");
        assert!(!working.join("session-notes").exists());
    }

    #[test]
    fn migrate_session_notes_reports_recreated_legacy_file_as_conflict() {
        let temp = TestDir::new();
        let working = temp.path();
        let legacy_dir = working.join("handoffs/session-d");
        fs::create_dir_all(&legacy_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "first version\n").unwrap();
        migrate_session_notes(working, false, true).unwrap();

        fs::create_dir_all(&legacy_dir).unwrap();
        fs::write(legacy_dir.join("handoff.md"), "recreated version\n").unwrap();
        let result = migrate_session_notes(working, false, false).unwrap();

        assert!(result.moved.is_empty());
        assert!(result.skipped.is_empty());
        assert_eq!(result.conflicts.len(), 1);
        assert_eq!(result.conflicts[0].from, legacy_dir.join("handoff.md"));
        assert_eq!(
            result.conflicts[0].to,
            working.join("session-notes/session-d/notes.md")
        );
        assert_eq!(
            fs::read_to_string(legacy_dir.join("handoff.md")).unwrap(),
            "recreated version\n"
        );
        assert_eq!(
            fs::read_to_string(working.join("session-notes/session-d/notes.md")).unwrap(),
            "first version\n"
        );
    }

    #[test]
    fn merge_keeps_comments_order_and_drops_removed_keys() {
        let existing = "# top\nz = 1\n[a] # tail\n# why\nk = 1\ngone = 2\n";
        let fresh = "z = 1\n[a]\nk = 5\n[b]\nn = 1\n";
        let merged = merge_toml_text(existing, fresh);
        assert!(
            merged.starts_with("# top\nz = 1\n[a] # tail\n# why\nk = 5\n"),
            "{merged}"
        );
        assert!(!merged.contains("gone"), "{merged}");
        assert!(merged.contains("[b]\nn = 1"), "{merged}");
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
    fn hooks_and_unknown_tables_round_trip() {
        let text = "[hooks.session_start]\nproviders = [\"nav_map\"]\ntimeout = 10\n\n[hooks.post_tool_use]\nx = 1\n\n[hooks.user_prompt_submit]\nproviders = [\"inbox\"]\nkeep = \"yes\"\n\n[orchestration]\nmode = \"x\"\n";
        let cfg = config(text);
        assert_eq!(cfg.session_start_providers(), vec!["nav_map".to_string()]);
        assert_eq!(
            cfg.user_prompt_submit_providers(),
            vec!["inbox".to_string()]
        );
        assert!(cfg.hooks.user_prompt_submit.unknown.contains_key("keep"));
        let out = toml::to_string_pretty(&cfg).unwrap();
        let again = config(&out);
        assert_eq!(again, cfg);
        assert!(out.contains("[orchestration]"), "{out}");
        assert!(out.contains("providers"), "{out}");
        assert!(out.contains("timeout = 10"), "{out}");
        assert!(out.contains("[hooks.post_tool_use]"), "{out}");
        assert!(out.contains("[hooks.user_prompt_submit]"), "{out}");
        assert!(out.contains("keep = \"yes\""), "{out}");
    }

    #[test]
    fn orchestration_table_round_trips_with_unknown_keys() {
        let cfg = config("[orchestration]\nbuilders = 2\nmode = \"x\"\n");
        assert_eq!(cfg.orchestration.builders(), (2, None));
        let again = config(&toml::to_string_pretty(&cfg).unwrap());
        assert_eq!(again, cfg);
        assert!(again.orchestration.unknown.contains_key("mode"));
    }

    #[test]
    fn stall_minutes_default_round_trip_and_invalid_fallback() {
        assert_eq!(Config::default().orchestration.stall_minutes(), (20, None));
        let cfg = config("[orchestration]\nstall_minutes = 35\nmode = \"x\"\n");
        assert_eq!(cfg.orchestration.stall_minutes(), (35, None));
        let again = config(&toml::to_string_pretty(&cfg).unwrap());
        assert_eq!(again, cfg);
        assert_eq!(again.orchestration.stall_minutes(), (35, None));

        for bad in ["0", "-3", "\"many\"", "2.5"] {
            let cfg = config(&format!("[orchestration]\nstall_minutes = {bad}\n"));
            let (minutes, reason) = cfg.orchestration.stall_minutes();
            assert_eq!(minutes, 20, "{bad}");
            assert!(reason.is_some(), "{bad}");
        }
    }

    #[test]
    fn instructions_table_round_trips_with_unknown_keys() {
        let cfg =
            config("[instructions]\ntargets = [\"/home/user/AGENTS.md\"]\nmode = \"shared\"\n");
        let again = config(&toml::to_string_pretty(&cfg).unwrap());
        assert_eq!(again, cfg);
        assert_eq!(again.instructions.targets, vec!["/home/user/AGENTS.md"]);
        assert!(again.instructions.unknown.contains_key("mode"));
    }

    #[test]
    fn non_table_orchestration_falls_back_with_a_reason() {
        for bad in ["3", "\"x\"", "[1]"] {
            let cfg = config(&format!("orchestration = {bad}\n"));
            let (n, reason) = cfg.orchestration.builders();
            assert_eq!(n, 4, "{bad}");
            assert!(reason.is_some(), "{bad}");
        }
    }

    #[test]
    fn orchestration_role_caps_default_to_four_four_two_two_four() {
        let caps = Config::default().orchestration;
        assert_eq!(caps.orchestrators(), (4, None));
        assert_eq!(caps.builders(), (4, None));
        assert_eq!(caps.planners(), (2, None));
        assert_eq!(caps.reviewers(), (2, None));
        assert_eq!(caps.explorers(), (4, None));
        assert_eq!(
            RoleCaps::default(),
            RoleCaps {
                orchestrators: 4,
                builders: 4,
                planners: 2,
                reviewers: 2,
                explorers: 4,
            }
        );
    }

    #[test]
    fn orchestration_role_caps_read_legacy_max_agents_as_builders() {
        let cfg = config("[orchestration]\nmax_agents = 6\n");
        assert_eq!(cfg.orchestration.builders(), (6, None));
        let cfg = config("[orchestration]\nmax_agents = 6\nbuilders = 2\n");
        assert_eq!(cfg.orchestration.builders(), (2, None));
        let cfg = config("[orchestration]\nexecutors = 3\n");
        assert_eq!(cfg.orchestration.builders(), (3, None));
    }

    #[test]
    fn orchestration_role_caps_fall_back_with_a_reason_when_invalid() {
        for bad in ["0", "-3", "\"many\"", "2.5"] {
            let cfg = config(&format!("[orchestration]\nmax_agents = {bad}\n"));
            let (n, reason) = cfg.orchestration.builders();
            assert_eq!(n, 4, "{bad}");
            assert!(reason.is_some(), "{bad}");
        }
        let cases: [(&str, u32); 5] = [
            ("orchestrators", 4),
            ("builders", 4),
            ("planners", 2),
            ("reviewers", 2),
            ("explorers", 4),
        ];
        for (key, expected) in cases {
            let cfg = config(&format!("[orchestration]\n{key} = 0\n"));
            let orchestration = &cfg.orchestration;
            let (n, reason) = match key {
                "orchestrators" => orchestration.orchestrators(),
                "builders" => orchestration.builders(),
                "planners" => orchestration.planners(),
                "reviewers" => orchestration.reviewers(),
                _ => orchestration.explorers(),
            };
            assert_eq!(n, expected, "{key}");
            assert!(reason.is_some(), "{key}");
        }
    }

    #[test]
    fn orchestration_role_caps_set_builders_drops_the_legacy_key() {
        let mut cfg = config("[orchestration]\nexecutors = 6\nmode = \"x\"\n");
        cfg.orchestration.set_builders(2);
        assert_eq!(cfg.orchestration.builders(), (2, None));
        let text = toml::to_string_pretty(&cfg).unwrap();
        assert!(text.contains("builders = 2"), "{text}");
        assert!(!text.contains("max_agents"), "{text}");
        assert!(text.contains("mode = \"x\""), "{text}");
        assert_eq!(config(&text), cfg);
    }

    #[test]
    fn session_start_providers_default_when_absent() {
        assert_eq!(
            Config::default().session_start_providers(),
            vec!["nav_map", "toz_note"]
        );
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

    #[test]
    fn saving_an_empty_config_keeps_seeded_hook_comments() {
        let dir = std::env::temp_dir().join(format!(
            "varde-config-seeded-{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        std::fs::create_dir(&dir).unwrap();
        let current = dir.join(CONFIG_FILE);
        let legacy = dir.join(LEGACY_CONFIG_FILE);
        let seeded = "[hooks.session_start]\n# providers = [\"nav_map\"]\n[hooks.post_tool_use]\n# providers = [\"capture\"]\n";
        std::fs::write(&current, seeded).unwrap();

        save_config_at(&Config::default(), &current, &legacy, |from, to| {
            std::fs::rename(from, to)
        })
        .unwrap();
        assert_eq!(std::fs::read_to_string(&current).unwrap(), seeded);

        std::fs::write(&current, "[default]\nworking = \"/w\"\n").unwrap();
        save_config_at(&Config::default(), &current, &legacy, |from, to| {
            std::fs::rename(from, to)
        })
        .unwrap();
        assert!(!current.exists());
        std::fs::remove_dir_all(dir).unwrap();
    }
}
