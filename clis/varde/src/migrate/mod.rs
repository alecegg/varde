//! Shared environment and output types for the one-time setup migrations.

pub mod config_move;
pub mod harness;
pub mod legacy_bins;
pub mod watch;

use serde_json::{Value, json};
use std::env;
use std::ffi::OsString;
use std::path::PathBuf;

/// Inputs that migrations would otherwise read from process-global state.
#[derive(Clone, Debug)]
pub struct MigrateEnv {
    pub home: PathBuf,
    /// The resolved varde config directory returned by `varde_config_dir()`.
    pub config_dir: PathBuf,
    pub xdg_config_home: Option<PathBuf>,
    pub path: OsString,
    /// Cargo's install root. The binary directory is its `bin/` child.
    pub cargo_install_root: PathBuf,
    /// The running `varde` executable, used by later steps for subcommands.
    pub exe: PathBuf,
    /// Explicit toz primary-store override, with the canonical env name first.
    pub toz_config_override: Option<PathBuf>,
    pub dry_run: bool,
}

impl MigrateEnv {
    /// Capture the current process settings once so later steps can be tested
    /// with a fully isolated environment.
    pub fn current(dry_run: bool) -> Self {
        let home = env::var_os("HOME")
            .or_else(|| env::var_os("USERPROFILE"))
            .map(PathBuf::from)
            .unwrap_or_else(|| PathBuf::from("."));
        let nonempty = |name: &str| env::var_os(name).filter(|value| !value.is_empty());
        let xdg_config_home = nonempty("XDG_CONFIG_HOME").map(PathBuf::from);
        let cargo_install_root = nonempty("CARGO_INSTALL_ROOT")
            .or_else(|| nonempty("CARGO_HOME"))
            .map(PathBuf::from)
            .unwrap_or_else(|| home.join(".cargo"));
        let toz_config_override = env::var_os("VARDE_TOZ_CONFIG_DIR")
            .or_else(|| env::var_os("TOZ_CONFIG_DIR"))
            .filter(|value| !value.is_empty())
            .map(PathBuf::from);

        Self {
            home,
            config_dir: varde_core::paths::varde_config_dir(),
            xdg_config_home,
            path: env::var_os("PATH").unwrap_or_default(),
            cargo_install_root,
            exe: env::current_exe().unwrap_or_else(|_| PathBuf::from("varde")),
            toz_config_override,
            dry_run,
        }
    }
}

/// One reported migration action or item that needs attention.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ReportEntry {
    pub path: PathBuf,
    pub reason: String,
    pub command: Option<String>,
}

impl ReportEntry {
    pub fn new(path: impl Into<PathBuf>, reason: impl Into<String>) -> Self {
        Self {
            path: path.into(),
            reason: reason.into(),
            command: None,
        }
    }

    pub fn with_command(mut self, command: impl Into<String>) -> Self {
        self.command = Some(command.into());
        self
    }
}

/// Actions gathered by the setup migration steps.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Report {
    pub moved: Vec<ReportEntry>,
    pub skipped: Vec<ReportEntry>,
    pub unrewritable: Vec<ReportEntry>,
    pub would: Vec<ReportEntry>,
}

impl Report {
    pub fn data(&self) -> Value {
        let entries = |items: &[ReportEntry]| {
            items
                .iter()
                .map(|entry| {
                    json!({
                        "path": entry.path,
                        "reason": entry.reason,
                        "command": entry.command,
                    })
                })
                .collect::<Vec<_>>()
        };
        json!({
            "moved": entries(&self.moved),
            "skipped": entries(&self.skipped),
            "unrewritable": entries(&self.unrewritable),
            "would": entries(&self.would),
        })
    }
}

impl std::fmt::Display for Report {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let mut first = true;
        for (name, entries) in [
            ("moved", &self.moved),
            ("skipped", &self.skipped),
            ("unrewritable", &self.unrewritable),
            ("would", &self.would),
        ] {
            for entry in entries {
                if !first {
                    writeln!(f)?;
                }
                first = false;
                write!(f, "{name}: {}: {}", entry.path.display(), entry.reason)?;
                if let Some(command) = &entry.command {
                    write!(f, " ({command})")?;
                }
            }
        }
        if first {
            f.write_str("no migration actions")?;
        }
        Ok(())
    }
}
