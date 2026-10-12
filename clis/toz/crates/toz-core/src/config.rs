//! User configuration: `<varde config>/toz/config.toml` after migration.
//!
//! Every field has a default so a missing file is fine. `TOZ_CONFIG_DIR` overrides the
//! directory (used by tests and by harness shims that want isolation).

use anyhow::{Context, Result};
use serde::Deserialize;
use std::path::{Path, PathBuf};

pub const DEFAULT_THRESHOLD: usize = 4096;
/// Floor for file-read tool output, which agents rarely want summarized.
pub const READ_THRESHOLD: usize = 16384;
/// Calibrated default for shell tools (2026-10-10 calibration over session transcripts and
/// stored captures): 8 KiB keeps the share of ordinary Bash calls behind handles near 2% (target
/// under 10%) while retaining ~80% of the bytes currently captured (the next band, 16 KiB,
/// drops to ~56%). Outputs of 4-8 KiB made up half of Bash captures while saving little.
pub const BASH_THRESHOLD: usize = 8192;

#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Config {
    /// Byte threshold (stdout + stderr) above which output is captured instead of passed through.
    pub threshold: usize,
    /// True when `threshold` was set explicitly (config file key or `TOZ_THRESHOLD`), so an
    /// explicit user value wins over the calibrated per-tool default in `threshold_for`.
    #[serde(skip)]
    pub threshold_explicit: bool,
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

/// Redaction behavior: extra patterns, the built-in set, and value sources.
///
/// With `values` enabled, secret-named environment variables and the `.env` and
/// `.env.*` files in the project root are redacted. Relative `dotenv` paths
/// resolve against the project root too (the git root of the current directory),
/// not the process working directory when that is a subdirectory.
#[derive(Debug, Clone, Deserialize)]
#[serde(default)]
pub struct Redact {
    /// Extra regex patterns; matches are replaced with `[redacted:user]`.
    pub patterns: Vec<String>,
    /// Set to false to disable the built-in pattern set.
    pub builtin: bool,
    /// Redact the values of secret-named environment variables and `.env` files.
    pub values: bool,
    /// Extra `.env`-style files to read, besides `.env`/`.env.*` in the project root.
    pub dotenv: Vec<String>,
    /// Characters of a long value shown at each end; 0 hides it fully.
    pub reveal: usize,
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
            threshold_explicit: false,
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
            values: true,
            dotenv: Vec::new(),
            reveal: 2,
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
    /// Threshold for a hook capture from `tool`. Order: exact tool key, then (file reads only)
    /// the `read` key, then `max(READ_THRESHOLD, threshold)`; shell tools otherwise use the
    /// calibrated `BASH_THRESHOLD` unless an explicit global `threshold` (config file or
    /// `TOZ_THRESHOLD`) is set, which wins; all other tools use the global threshold.
    pub fn threshold_for(&self, tool: &str, is_file_read: bool) -> usize {
        if let Some(&limit) = self.thresholds.get(tool) {
            return limit;
        }
        if is_file_read {
            let read_default = READ_THRESHOLD.max(self.threshold);
            return self.thresholds.get("read").copied().unwrap_or(read_default);
        }
        if is_shell_tool(tool) {
            return if self.threshold_explicit {
                self.threshold
            } else {
                BASH_THRESHOLD
            };
        }
        self.threshold
    }
}

/// Shell tools that carry command text; they default to the calibrated `BASH_THRESHOLD`.
fn is_shell_tool(tool: &str) -> bool {
    matches!(
        tool.to_ascii_lowercase().as_str(),
        "bash" | "cmd" | "command" | "shell"
    )
}

/// Root directory for all toz state: `$VARDE_TOZ_CONFIG_DIR` (or `$TOZ_CONFIG_DIR`), else
/// `<varde config>/toz`. Before its migration marker exists, existing legacy roots under
/// `$XDG_CONFIG_HOME` (or `~/.config`) remain authoritative in their historical precedence.
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
    Ok(resolve_config_dir(
        None,
        &base,
        &varde_core::paths::varde_config_dir(),
    ))
}

fn resolve_config_dir(explicit: Option<PathBuf>, base: &Path, varde_config_dir: &Path) -> PathBuf {
    if let Some(explicit) = explicit {
        return explicit;
    }

    let new = varde_config_dir.join("toz");
    if new.join(".varde-migration-complete").exists() {
        return new;
    }

    let canonical = base.join("varde-toz");
    let legacy = base.join("tool-output-zone");
    let same_root = canonical
        .canonicalize()
        .ok()
        .zip(legacy.canonicalize().ok())
        .is_some_and(|(canonical, legacy)| canonical == legacy);
    if legacy.exists() && !same_root {
        legacy
    } else if canonical.exists() {
        canonical
    } else {
        new
    }
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
                // A bare `threshold` key marks the value as explicit so per-tool defaults
                // (the calibrated Bash threshold) do not override a user's global choice.
                let mut explicit = toml::from_str::<toml::Value>(&text)
                    .ok()
                    .is_some_and(|table| table.get("threshold").is_some());
                if let Ok(t) = env("TOZ_THRESHOLD") {
                    if let Ok(t) = t.parse() {
                        cfg.threshold = t;
                        explicit = true;
                    }
                }
                cfg.threshold_explicit = explicit;
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
                        cfg.threshold_explicit = true;
                    }
                }
                Ok(cfg)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{resolve_config_dir, Config};
    use std::path::PathBuf;

    struct TestRoots {
        _fixture: tempfile::TempDir,
        base: PathBuf,
        config_root: PathBuf,
        new: PathBuf,
        varde_toz: PathBuf,
        tool_output_zone: PathBuf,
    }

    fn test_roots() -> TestRoots {
        let fixture = tempfile::tempdir().unwrap();
        TestRoots {
            base: fixture.path().join("xdg"),
            config_root: fixture.path().join("config/varde"),
            new: fixture.path().join("config/varde/toz"),
            varde_toz: fixture.path().join("xdg/varde-toz"),
            tool_output_zone: fixture.path().join("xdg/tool-output-zone"),
            _fixture: fixture,
        }
    }

    fn resolve(roots: &TestRoots, explicit: Option<PathBuf>) -> PathBuf {
        resolve_config_dir(explicit, &roots.base, &roots.config_root)
    }

    #[test]
    fn explicit_config_dir_wins_unchanged() {
        let roots = test_roots();
        let explicit = PathBuf::from("relative/toz/../store");

        assert_eq!(resolve(&roots, Some(explicit.clone())), explicit);
    }

    #[test]
    fn varde_toz_is_selected_when_it_is_the_only_legacy_root() {
        let roots = test_roots();
        std::fs::create_dir_all(&roots.varde_toz).unwrap();

        assert_eq!(resolve(&roots, None), roots.varde_toz);
    }

    #[test]
    fn tool_output_zone_is_selected_when_it_is_the_only_legacy_root() {
        let roots = test_roots();
        std::fs::create_dir_all(&roots.tool_output_zone).unwrap();

        assert_eq!(resolve(&roots, None), roots.tool_output_zone);
    }

    #[test]
    fn legacy_root_wins_when_new_root_exists_before_marker() {
        let roots = test_roots();
        std::fs::create_dir_all(&roots.varde_toz).unwrap();
        std::fs::create_dir_all(&roots.new).unwrap();

        assert_eq!(resolve(&roots, None), roots.varde_toz);
    }

    #[test]
    fn tool_output_zone_wins_when_both_distinct_legacy_roots_exist() {
        let roots = test_roots();
        std::fs::create_dir_all(&roots.varde_toz).unwrap();
        std::fs::create_dir_all(&roots.tool_output_zone).unwrap();
        std::fs::create_dir_all(&roots.new).unwrap();

        assert_eq!(resolve(&roots, None), roots.tool_output_zone);
    }

    #[test]
    fn migration_marker_keeps_new_root_authoritative_after_legacy_reappears() {
        let roots = test_roots();
        std::fs::create_dir_all(&roots.new).unwrap();
        std::fs::write(roots.new.join(".varde-migration-complete"), "").unwrap();
        std::fs::create_dir_all(&roots.tool_output_zone).unwrap();

        assert_eq!(resolve(&roots, None), roots.new);
    }

    #[cfg(unix)]
    #[test]
    fn tool_output_zone_symlink_to_varde_toz_is_not_a_distinct_root() {
        use std::os::unix::fs::symlink;

        let roots = test_roots();
        std::fs::create_dir_all(&roots.varde_toz).unwrap();
        symlink(&roots.varde_toz, &roots.tool_output_zone).unwrap();

        assert_eq!(resolve(&roots, None), roots.varde_toz);
    }

    #[test]
    fn new_root_is_selected_when_neither_legacy_root_exists() {
        let roots = test_roots();

        assert_eq!(resolve(&roots, None), roots.new);
    }

    #[test]
    fn redact_defaults_enable_values_and_reveal_two() {
        let redact = super::Redact::default();
        assert!(redact.builtin);
        assert!(redact.values);
        assert!(redact.dotenv.is_empty());
        assert_eq!(redact.reveal, 2);

        let no_section: Config = toml::from_str("").unwrap();
        assert!(no_section.redact.values);
        assert_eq!(no_section.redact.reveal, 2);

        let configured: Config =
            toml::from_str("[redact]\nvalues = false\ndotenv = [\"secrets.env\"]\nreveal = 0\n")
                .unwrap();
        assert!(!configured.redact.values);
        assert_eq!(configured.redact.dotenv, vec!["secrets.env".to_string()]);
        assert_eq!(configured.redact.reveal, 0);
    }

    #[test]
    fn shell_tools_default_to_calibrated_bash_threshold() {
        let cfg = Config::default();
        for tool in ["Bash", "bash", "cmd", "command", "shell"] {
            assert_eq!(
                cfg.threshold_for(tool, false),
                super::BASH_THRESHOLD,
                "{tool}"
            );
        }
    }

    #[test]
    fn per_tool_thresholds_key_overrides_shell_default() {
        let cfg = Config {
            thresholds: [("Bash".to_string(), 4096)].into_iter().collect(),
            ..Default::default()
        };
        assert_eq!(cfg.threshold_for("Bash", false), 4096);
        // Sibling shell names without an exact key still get the calibrated default.
        assert_eq!(cfg.threshold_for("bash", false), super::BASH_THRESHOLD);
    }

    #[test]
    fn explicit_config_threshold_wins_for_shell_tools() {
        let _guard = crate::test_support::env_lock();
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("config.toml");
        std::fs::write(&path, "threshold = 2048\n").unwrap();
        let cfg = Config::load_from(&path).unwrap();
        assert_eq!(cfg.threshold_for("Bash", false), 2048);
    }

    #[test]
    fn toz_threshold_env_wins_for_shell_tools() {
        let _guard = crate::test_support::env_lock();
        std::env::set_var("TOZ_THRESHOLD", "4096");
        let cfg = Config::load_from(&PathBuf::from("/nonexistent/toz-config.toml")).unwrap();
        std::env::remove_var("TOZ_THRESHOLD");
        assert_eq!(cfg.threshold_for("Bash", false), 4096);
    }

    #[test]
    fn read_tools_keep_read_threshold_and_other_tools_the_global_default() {
        let cfg = Config::default();
        assert_eq!(cfg.threshold_for("Read", true), super::READ_THRESHOLD);
        assert_eq!(cfg.threshold_for("Write", false), super::DEFAULT_THRESHOLD);

        let read_key = Config {
            thresholds: [("read".to_string(), 32768)].into_iter().collect(),
            ..Default::default()
        };
        assert_eq!(read_key.threshold_for("Read", true), 32768);
    }

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
