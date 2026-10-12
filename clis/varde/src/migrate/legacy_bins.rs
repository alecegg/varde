//! Remove legacy Varde executables from the Cargo install root.

use super::{MigrateEnv, Report, ReportEntry};
use std::collections::HashMap;
use std::fs;
use std::io;
use std::path::Path;
use std::process::Command;

const LEGACY_BINARIES: [&str; 5] = [
    "varde-code",
    "varde-workflow",
    "varde-toz",
    "toz",
    "varde-learn",
];
const VARDE_VERSION_NAMES: [&str; 4] = ["varde-code", "varde-workflow", "varde-toz", "varde-learn"];

/// Remove Varde-owned legacy executables from `<cargo install root>/bin`.
/// Skipped or unrewritable hook commands protect the binary they still use.
pub fn run(env: &MigrateEnv, report: &mut Report) -> io::Result<()> {
    let bin_dir = env.cargo_install_root.join("bin");
    let protected = protected_references(report);
    report.skipped.push(ReportEntry::new(
        &bin_dir,
        "checked this Cargo install directory for legacy Varde binaries",
    ));

    for name in LEGACY_BINARIES {
        let path = bin_dir.join(name);
        match fs::symlink_metadata(&path) {
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => {
                report.unrewritable.push(
                    ReportEntry::new(&path, format!("could not inspect the binary: {error}"))
                        .with_command(probe_command(&path)),
                );
                continue;
            }
        };
        let metadata = match fs::metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) => {
                report.unrewritable.push(
                    ReportEntry::new(
                        &path,
                        format!("could not inspect the binary target: {error}"),
                    )
                    .with_command(probe_command(&path)),
                );
                continue;
            }
        };
        if !metadata.is_file() {
            report.skipped.push(
                ReportEntry::new(&path, "kept because it is not a regular executable file")
                    .with_command(probe_command(&path)),
            );
            continue;
        }
        if !is_executable(&metadata) {
            report.skipped.push(
                ReportEntry::new(&path, "kept because it is not executable")
                    .with_command(probe_command(&path)),
            );
            continue;
        }

        let output = match Command::new(&path).arg("--version").output() {
            Ok(output) => output,
            Err(error) => {
                report.unrewritable.push(
                    ReportEntry::new(&path, format!("could not run the version probe: {error}"))
                        .with_command(probe_command(&path)),
                );
                continue;
            }
        };
        if !output.status.success() {
            report.unrewritable.push(
                ReportEntry::new(
                    &path,
                    format!("version probe exited with status {}", output.status),
                )
                .with_command(probe_command(&path)),
            );
            continue;
        }
        if !has_varde_version(&output.stdout) {
            report.skipped.push(
                ReportEntry::new(
                    &path,
                    "kept because the first version line is not a recognized Varde identity",
                )
                .with_command(probe_command(&path)),
            );
            continue;
        }

        if let Some(reference) = protected.get(name) {
            let original_command = reference
                .command
                .clone()
                .unwrap_or_else(|| reference.path.display().to_string());
            report.skipped.push(
                ReportEntry::new(
                    &path,
                    format!(
                        "kept because a reported skipped or unrewritable entry at {} still refers to it",
                        reference.path.display()
                    ),
                )
                .with_command(original_command),
            );
            continue;
        }

        if env.dry_run {
            report.would.push(
                ReportEntry::new(&path, "would remove the Varde legacy executable")
                    .with_command(probe_command(&path)),
            );
            continue;
        }
        match fs::remove_file(&path) {
            Ok(()) => report.moved.push(ReportEntry::new(
                &path,
                "removed the Varde legacy executable from the Cargo install root",
            )),
            Err(error) => report.unrewritable.push(
                ReportEntry::new(&path, format!("could not remove the binary: {error}"))
                    .with_command(probe_command(&path)),
            ),
        }
    }
    Ok(())
}

fn has_varde_version(stdout: &[u8]) -> bool {
    let first_line = String::from_utf8_lossy(
        stdout
            .split(|byte| *byte == b'\n')
            .next()
            .unwrap_or_default(),
    );
    let Some((name, version)) = first_line.split_once(' ') else {
        return false;
    };
    VARDE_VERSION_NAMES.contains(&name) && is_version_number(version)
}

fn is_version_number(value: &str) -> bool {
    let core = value
        .split_whitespace()
        .next()
        .unwrap_or_default()
        .split(['-', '+'])
        .next()
        .unwrap_or_default();
    let mut components = core.split('.');
    [components.next(), components.next(), components.next()]
        .into_iter()
        .all(|component| {
            component
                .is_some_and(|part| !part.is_empty() && part.bytes().all(|b| b.is_ascii_digit()))
        })
        && components.next().is_none()
}

fn probe_command(path: &Path) -> String {
    format!("{} --version", path.display())
}

fn protected_references(report: &Report) -> HashMap<&'static str, ReportEntry> {
    let mut protected = HashMap::new();
    for entry in report.skipped.iter().chain(&report.unrewritable) {
        for name in LEGACY_BINARIES {
            if entry_mentions(entry, name) {
                protected.entry(name).or_insert_with(|| entry.clone());
            }
        }
    }
    protected
}

fn entry_mentions(entry: &ReportEntry, name: &str) -> bool {
    entry
        .command
        .as_deref()
        .is_some_and(|command| text_mentions(command, name))
}

fn text_mentions(text: &str, name: &str) -> bool {
    text.match_indices(name).any(|(start, _)| {
        let before = text[..start].chars().next_back();
        let end = start + name.len();
        let after = text[end..].chars().next();
        let is_name_character = |character: char| {
            character.is_ascii_alphanumeric() || character == '_' || character == '-'
        };
        !before.is_some_and(is_name_character) && !after.is_some_and(is_name_character)
    })
}

#[cfg(unix)]
fn is_executable(metadata: &fs::Metadata) -> bool {
    use std::os::unix::fs::PermissionsExt;

    metadata.permissions().mode() & 0o111 != 0
}

#[cfg(not(unix))]
fn is_executable(_metadata: &fs::Metadata) -> bool {
    true
}
