//! User configuration: `~/.config/tool-output-zone/config.toml`.
//!
//! Every field has a default so a missing file is fine. `TOZ_CONFIG_DIR` overrides the
//! directory (used by tests and by harness shims that want isolation).

use anyhow::{Context, Result};
use serde::Deserialize;
use std::path::{Path, PathBuf};

pub const DEFAULT_THRESHOLD: usize = 4096;

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Byte threshold (stdout + stderr) above which output is captured instead of passed through.
    pub threshold: usize,
    /// Optional per-tool overrides for hook captures, keyed by tool name.
    /// Tools not listed use `threshold`.
    pub thresholds: std::collections::BTreeMap<String, usize>,
    /// Lines shown at the top of an overflow preview.
    pub preview_head: usize,
    /// Lines shown at the bottom of an overflow preview.
    pub preview_tail: usize,
    /// Max section titles listed in a preview.
    pub preview_sections: usize,
    /// Append every raw hook payload here (shape discovery / debugging). `TOZ_HOOK_LOG` overrides.
    pub hook_log: Option<PathBuf>,
    pub retention: Retention,
    /// Optional exact stdout/stderr retention for commands that need later replay.
    pub raw: RawOutputConfig,
    pub redact: Redact,
    pub capture: CaptureRules,
    pub script: Script,
    /// Optional OS restrictions for agent-written scripts and the commands they start.
    pub sandbox: Sandbox,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Sandbox {
    /// Apply Seatbelt or Bubblewrap to the script and its child commands.
    pub enabled: bool,
    /// Access to the detected project root: none | read-only | read-write.
    pub workspace: WorkspaceAccess,
    /// Additional absolute directories visible to sandboxed commands.
    pub read_roots: Vec<PathBuf>,
    /// Additional absolute directories writable by sandboxed commands.
    pub write_roots: Vec<PathBuf>,
    /// Allow outbound and inbound networking from sandboxed commands.
    pub network: bool,
    /// Additional inherited environment variable names available inside the sandbox.
    pub env_allow: Vec<String>,
}

#[derive(Debug, Clone, Copy, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "kebab-case")]
pub enum WorkspaceAccess {
    None,
    ReadOnly,
    ReadWrite,
}

impl Default for Sandbox {
    fn default() -> Self {
        Self {
            // An existing [sandbox] section without this new key remains enforced.
            enabled: true,
            workspace: WorkspaceAccess::ReadWrite,
            read_roots: Vec::new(),
            write_roots: Vec::new(),
            network: false,
            env_allow: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Retention {
    pub days: u64,
    pub superseded_days: u64,
    pub max_mb: u64,
}

/// Controls opt-in exact output storage. Raw bytes are kept apart from searchable captures.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct RawOutputConfig {
    /// Exact output storage is disabled unless explicitly enabled.
    pub enabled: bool,
    /// Maximum combined stdout and stderr size for one command, in bytes.
    pub max_bytes: usize,
    /// Lifetime of a raw output handle, in seconds.
    pub ttl_secs: u64,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Redact {
    /// Extra regex patterns; matches are replaced with `[redacted:user]`.
    pub patterns: Vec<String>,
    /// Set to false to disable the built-in pattern set.
    pub builtin: bool,
}

/// Bounds for `toz run` scripts. Time and memory are overridable per invocation.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Script {
    pub enabled: bool,
    pub timeout_ms: u64,
    pub memory_mb: usize,
    pub max_output_bytes: usize,
    pub max_text_bytes: usize,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct CaptureRules {
    /// Glob-ish patterns (`*` wildcard) matched against the source key. Matching captures are
    /// never stored.
    pub never: Vec<String>,
    pub builtin_never: bool,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            threshold: DEFAULT_THRESHOLD,
            thresholds: std::collections::BTreeMap::new(),
            preview_head: 20,
            preview_tail: 10,
            preview_sections: 25,
            hook_log: None,
            retention: Retention::default(),
            raw: RawOutputConfig::default(),
            redact: Redact::default(),
            capture: CaptureRules::default(),
            script: Script::default(),
            // No [sandbox] section means the harness owns OS permissions.
            sandbox: Sandbox {
                enabled: false,
                ..Sandbox::default()
            },
        }
    }
}

impl Default for Script {
    fn default() -> Self {
        Self {
            enabled: true,
            timeout_ms: 5_000,
            memory_mb: 64,
            max_output_bytes: 1024 * 1024,
            max_text_bytes: 16 * 1024 * 1024,
        }
    }
}

impl Default for Retention {
    fn default() -> Self {
        Self {
            days: 14,
            superseded_days: 2,
            max_mb: 500,
        }
    }
}

impl Default for RawOutputConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            max_bytes: 20 * 1024 * 1024,
            ttl_secs: 60 * 60,
        }
    }
}

impl Default for Redact {
    fn default() -> Self {
        Self {
            patterns: Vec::new(),
            builtin: true,
        }
    }
}

impl Default for CaptureRules {
    fn default() -> Self {
        Self {
            never: Vec::new(),
            builtin_never: true,
        }
    }
}

impl Config {
    /// Threshold for a hook capture from `tool`. User-listed tools override; then default.
    pub fn threshold_for(&self, tool: &str) -> usize {
        self.thresholds.get(tool).copied().unwrap_or(self.threshold)
    }
}

/// Root directory for all toz state: `$VARDE_TOZ_CONFIG_DIR` (or `$TOZ_CONFIG_DIR`), else `$XDG_CONFIG_HOME/varde-toz`,
/// else `~/.config/varde-toz`. Existing legacy roots remain authoritative until migrated.
///
/// Deliberately not `dirs::config_dir()`: on macOS that resolves to `~/Library/Application Support`,
/// which is neither where the docs say the store lives nor readable from inside the Claude Code
/// bash sandbox (so the hook could write captures the agent then couldn't `toz query`).
/// Canonical environment inputs take precedence over compatibility aliases.
pub fn env_os(name: &str) -> Option<std::ffi::OsString> {
    std::env::var_os(format!("VARDE_{name}")).or_else(|| std::env::var_os(name))
}

pub fn env(name: &str) -> Result<String, std::env::VarError> {
    env_os(name)
        .ok_or(std::env::VarError::NotPresent)?
        .into_string()
        .map_err(std::env::VarError::NotUnicode)
}

pub fn config_dir() -> Result<PathBuf> {
    if let Ok(dir) = env("TOZ_CONFIG_DIR") {
        return Ok(PathBuf::from(dir));
    }
    let base = match std::env::var_os("XDG_CONFIG_HOME") {
        Some(x) if !x.is_empty() => PathBuf::from(x),
        _ => dirs::home_dir()
            .context("could not determine home directory")?
            .join(".config"),
    };
    let canonical = base.join("varde-toz");
    let legacy = base.join("tool-output-zone");
    let same_root = canonical
        .canonicalize()
        .ok()
        .zip(legacy.canonicalize().ok())
        .is_some_and(|(canonical, legacy)| canonical == legacy);
    Ok(if legacy.exists() && !same_root {
        legacy
    } else {
        canonical
    })
}

impl Config {
    pub fn load() -> Result<Self> {
        let path = config_dir()?.join("config.toml");
        Self::load_from(&path)
    }

    pub fn load_from(path: &Path) -> Result<Self> {
        match std::fs::read_to_string(path) {
            Ok(text) => {
                let mut cfg: Config =
                    toml::from_str(&text).with_context(|| format!("parsing {}", path.display()))?;
                if let Ok(t) = env("TOZ_THRESHOLD") {
                    if let Ok(t) = t.parse() {
                        cfg.threshold = t;
                    }
                }
                Ok(cfg)
            }
            // No config, or a config we can't read (sandboxed harness, odd permissions):
            // defaults. A present-but-malformed config is still an error above, since
            // silently ignoring a typo'd never-capture list would be worse.
            Err(e) => {
                if e.kind() != std::io::ErrorKind::NotFound {
                    eprintln!(
                        "varde-toz: cannot read {} ({e}); using defaults",
                        path.display()
                    );
                }
                let mut cfg = Config::default();
                if let Ok(t) = env("TOZ_THRESHOLD") {
                    if let Ok(t) = t.parse() {
                        cfg.threshold = t;
                    }
                }
                Ok(cfg)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Config;

    #[test]
    fn sandbox_is_opt_in_but_existing_section_remains_enabled() {
        let no_section: Config = toml::from_str("").unwrap();
        assert!(!no_section.sandbox.enabled);

        let legacy_section: Config = toml::from_str("[sandbox]\nnetwork = true\n").unwrap();
        assert!(legacy_section.sandbox.enabled);
        assert!(legacy_section.sandbox.network);

        let disabled_section: Config = toml::from_str("[sandbox]\nenabled = false\n").unwrap();
        assert!(!disabled_section.sandbox.enabled);
    }
}
