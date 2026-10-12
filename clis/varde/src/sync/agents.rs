use std::env;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;

use super::embedded::{Agent, AgentVariant, agents as embedded_agents};
use super::fsops;
use super::harness::{Harness, HarnessId};
use super::preserve;
use super::{LinkMode, SyncContext};

const MARKDOWN_MARKER: &[u8] = b"\n<!-- varde-managed-agent -->\n";
const TOML_MARKER: &[u8] = b"\n# varde-managed-agent\n";

#[derive(Clone, Copy, PartialEq, Eq)]
enum DirectoryState {
    Missing,
    Real,
    Foreign,
}

enum CanonicalFile {
    Missing,
    Managed(String),
    Foreign,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum HarnessEntry {
    Missing,
    Managed,
    CanonicalLink,
    Foreign,
}

#[derive(Default)]
struct SyncReport {
    unowned: Vec<PathBuf>,
    preserved_models: Vec<(String, PathBuf)>,
}

struct ProbeHome(PathBuf);

impl ProbeHome {
    fn create() -> io::Result<Self> {
        static NEXT_ID: AtomicU64 = AtomicU64::new(0);

        for _ in 0..10 {
            let path = env::temp_dir().join(format!(
                "varde-opencode-probe-{}-{}",
                std::process::id(),
                NEXT_ID.fetch_add(1, Ordering::Relaxed)
            ));
            match fs::create_dir(&path) {
                Ok(()) => {
                    let home = Self(path);
                    #[cfg(unix)]
                    fs::set_permissions(&home.0, fs::Permissions::from_mode(0o700))?;
                    return Ok(home);
                }
                Err(error) if error.kind() == io::ErrorKind::AlreadyExists => continue,
                Err(error) => return Err(error),
            }
        }

        Err(io::Error::new(
            io::ErrorKind::AlreadyExists,
            "could not create an isolated OpenCode probe home",
        ))
    }
}

impl Drop for ProbeHome {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn directory_state(path: &Path) -> io::Result<DirectoryState> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(DirectoryState::Missing);
        }
        Err(error) => return Err(error),
    };
    if metadata.file_type().is_dir() {
        Ok(DirectoryState::Real)
    } else {
        Ok(DirectoryState::Foreign)
    }
}

fn has_marker(contents: &[u8]) -> bool {
    contents
        .split(|byte| *byte == b'\n')
        .any(|line| line == b"<!-- varde-managed-agent -->" || line == b"# varde-managed-agent")
}

fn canonical_file(path: &Path) -> io::Result<CanonicalFile> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(CanonicalFile::Missing);
        }
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_file() {
        return Ok(CanonicalFile::Foreign);
    }

    let contents = fs::read(path)?;
    if !has_marker(&contents) {
        return Ok(CanonicalFile::Foreign);
    }
    String::from_utf8(contents)
        .map(CanonicalFile::Managed)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

fn managed_file(path: &Path) -> io::Result<Option<String>> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_file() {
        return Ok(None);
    }

    let contents = fs::read(path)?;
    if !has_marker(&contents) {
        return Ok(None);
    }
    String::from_utf8(contents)
        .map(Some)
        .map_err(|error| io::Error::new(io::ErrorKind::InvalidData, error))
}

fn path_exists(path: &Path) -> io::Result<bool> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(error),
    }
}

fn first_major(version: &str) -> Option<u64> {
    let bytes = version.as_bytes();
    let start = bytes.iter().position(u8::is_ascii_digit)?;
    let end = bytes[start..]
        .iter()
        .position(|byte| !byte.is_ascii_digit())
        .map_or(bytes.len(), |offset| start + offset);
    version[start..end].parse().ok()
}

fn opencode_major() -> u64 {
    if let Some(version) = env::var("VARDE_AGENTS_OPENCODE_VERSION")
        .ok()
        .filter(|version| !version.is_empty())
    {
        return first_major(&version).unwrap_or(1);
    }

    let Ok(probe_home) = ProbeHome::create() else {
        return 1;
    };

    Command::new("opencode")
        .arg("--version")
        .env("HOME", &probe_home.0)
        .env("XDG_CONFIG_HOME", probe_home.0.join(".config"))
        .env("XDG_CACHE_HOME", probe_home.0.join(".cache"))
        .env("XDG_DATA_HOME", probe_home.0.join(".local/share"))
        .env("XDG_STATE_HOME", probe_home.0.join(".local/state"))
        .output()
        .ok()
        .and_then(|output| first_major(&String::from_utf8_lossy(&output.stdout)))
        .unwrap_or(1)
}

fn variant_for(agent: &Agent, harness: HarnessId, opencode_major: u64) -> Option<&AgentVariant> {
    let file_name = match harness {
        HarnessId::Claude => "claude.md",
        HarnessId::Codex => "codex.toml",
        HarnessId::OpenCode if opencode_major >= 2 => "opencode-v2.md",
        HarnessId::OpenCode => "opencode.md",
        HarnessId::Pi => "pi.md",
    };
    agent
        .variants
        .iter()
        .find(|variant| variant.file_name == file_name)
}

fn extension(file_name: &str) -> &str {
    file_name
        .rsplit_once('.')
        .map_or("md", |(_, extension)| extension)
}

fn marker(file_name: &str) -> &'static [u8] {
    if file_name.ends_with(".toml") {
        TOML_MARKER
    } else {
        MARKDOWN_MARKER
    }
}

fn old_name(agent: &str) -> &'static [&'static str] {
    match agent {
        "varde-explorer" => &["explore"],
        "varde-planner" => &["plan"],
        "varde-reviewer" => &["review"],
        "varde-builder" => &["varde-executor", "executor", "build"],
        _ => &[],
    }
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            std::path::Component::CurDir => {}
            std::path::Component::ParentDir => {
                if normalized.file_name().is_some_and(|name| name != "..") {
                    normalized.pop();
                } else if !normalized.has_root() {
                    normalized.push("..");
                }
            }
            component => normalized.push(component.as_os_str()),
        }
    }
    normalized
}

fn is_within(path: &Path, directory: &Path) -> bool {
    normalize_path(path).starts_with(normalize_path(directory))
}

fn managed_canonical_source(path: &Path, canonical_directory: &Path) -> io::Result<Option<String>> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error),
    };
    if !metadata.file_type().is_symlink() {
        return managed_file(path);
    }

    let target = fs::read_link(path)?;
    let target = if target.is_absolute() {
        target
    } else {
        path.parent().unwrap_or_else(|| Path::new(".")).join(target)
    };
    if is_within(&target, canonical_directory) {
        managed_file(&target)
    } else {
        Ok(None)
    }
}

fn migration_source(
    context: &SyncContext,
    harness: &Harness,
    agent: &Agent,
    file_name: &str,
) -> Result<Option<String>, String> {
    let extension = extension(file_name);
    let destination = harness
        .agents_dir
        .join(format!("{}.{}", agent.name, extension));
    let canonical_directory = context.agents_dir.join(harness.id.as_str());
    if let Some(contents) =
        managed_canonical_source(&destination, &canonical_directory).map_err(|error| {
            format!(
                "could not inspect migration source {}: {error}",
                destination.display()
            )
        })?
    {
        return Ok(Some(contents));
    }
    if path_exists(&destination).map_err(|error| {
        format!(
            "could not inspect migration destination {}: {error}",
            destination.display()
        )
    })? {
        return Ok(None);
    }

    let mut candidates = Vec::new();
    for old in old_name(agent.name) {
        candidates.push(harness.agents_dir.join(format!("{old}.{extension}")));
        candidates.push(canonical_directory.join(format!("{old}.{extension}")));
    }

    if harness.id == HarnessId::OpenCode {
        let legacy = context.home.join(".config/opencode/agent");
        let state = directory_state(&legacy).map_err(|error| {
            format!(
                "could not inspect legacy OpenCode agent directory {}: {error}",
                legacy.display()
            )
        })?;
        if state == DirectoryState::Real {
            candidates.push(legacy.join(format!("{}.md", agent.name)));
            for old in old_name(agent.name) {
                candidates.push(legacy.join(format!("{old}.md")));
            }
        }
    }

    for candidate in candidates {
        if let Some(contents) =
            managed_canonical_source(&candidate, &canonical_directory).map_err(|error| {
                format!(
                    "could not inspect migration source {}: {error}",
                    candidate.display()
                )
            })?
        {
            return Ok(Some(contents));
        }
    }
    Ok(None)
}

fn add_unowned(report: &mut SyncReport, path: &Path) {
    if !report.unowned.iter().any(|existing| existing == path) {
        report.unowned.push(path.to_path_buf());
    }
}

fn report_preserved(report: &SyncReport, dry_run: bool) {
    for (key, path) in &report.preserved_models {
        if dry_run {
            println!(
                "would preserve user model setting {key} in {}",
                path.display()
            );
        } else {
            println!("Preserved user model setting {key} in {}", path.display());
        }
    }
    for path in &report.unowned {
        if dry_run {
            println!("would preserve unowned {}", path.display());
        } else {
            println!("Preserved unowned {}", path.display());
        }
    }
}

fn install_harness(
    context: &SyncContext,
    harness: HarnessId,
    opencode_major: u64,
    report: &mut SyncReport,
) -> Result<(), String> {
    let directory = context.agents_dir.join(harness.as_str());
    let state = directory_state(&directory).map_err(|error| {
        format!(
            "could not inspect canonical agent directory {}: {error}",
            directory.display()
        )
    })?;
    if state == DirectoryState::Foreign {
        add_unowned(report, &directory);
        return Ok(());
    }
    if state == DirectoryState::Missing && !context.dry_run {
        fs::create_dir_all(&directory).map_err(|error| {
            format!(
                "could not create canonical agent directory {}: {error}",
                directory.display()
            )
        })?;
        if directory_state(&directory).map_err(|error| {
            format!(
                "could not inspect canonical agent directory {}: {error}",
                directory.display()
            )
        })? != DirectoryState::Real
        {
            add_unowned(report, &directory);
            return Ok(());
        }
    }

    let selected_harness = context
        .harnesses
        .iter()
        .find(|selected| selected.id == harness);
    for agent in embedded_agents() {
        let variant = variant_for(agent, harness, opencode_major).ok_or_else(|| {
            format!(
                "agent {} has no embedded {} variant",
                agent.name,
                harness.as_str()
            )
        })?;
        let destination =
            directory.join(format!("{}.{}", agent.name, extension(variant.file_name)));
        let existing = canonical_file(&destination).map_err(|error| {
            format!(
                "could not inspect canonical agent file {}: {error}",
                destination.display()
            )
        })?;
        if matches!(&existing, CanonicalFile::Foreign) {
            add_unowned(report, &destination);
            continue;
        }

        let migrated = selected_harness
            .map(|selected| migration_source(context, selected, agent, variant.file_name))
            .transpose()?
            .flatten();
        let installed = migrated.or_else(|| match &existing {
            CanonicalFile::Managed(contents) => Some(contents.clone()),
            CanonicalFile::Missing | CanonicalFile::Foreign => None,
        });
        let staged = std::str::from_utf8(variant.bytes)
            .map_err(|error| format!("embedded agent {} is not UTF-8: {error}", agent.name))?;

        if context.dry_run {
            let preserved = preserve::dry_run(harness, agent.name, staged, installed.as_deref());
            let action = if matches!(&existing, CanonicalFile::Managed(_)) {
                "replace"
            } else {
                "install"
            };
            println!(
                "would {action} agent {} -> {}",
                agent.name,
                destination.display()
            );
            report
                .preserved_models
                .extend(preserved.into_iter().map(|key| (key, destination.clone())));
            continue;
        }

        let (contents, preserved) =
            preserve::preserve_models(harness, agent.name, staged, installed.as_deref());
        let mut marked = contents.into_bytes();
        marked.extend_from_slice(marker(variant.file_name));
        fsops::replace_file(&destination, &marked).map_err(|error| {
            format!(
                "could not install agent {} at {}: {error}",
                agent.name,
                destination.display()
            )
        })?;
        let action = if matches!(&existing, CanonicalFile::Managed(_)) {
            "Replaced"
        } else {
            "Installed"
        };
        println!("{action} agent {} -> {}", agent.name, destination.display());
        report
            .preserved_models
            .extend(preserved.into_iter().map(|key| (key, destination.clone())));
    }
    Ok(())
}

fn harness_entry(path: &Path, canonical: &Path) -> io::Result<HarnessEntry> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Ok(HarnessEntry::Missing);
        }
        Err(error) => return Err(error),
    };
    if metadata.file_type().is_symlink() {
        return if fs::read_link(path)? == canonical {
            Ok(HarnessEntry::CanonicalLink)
        } else {
            Ok(HarnessEntry::Foreign)
        };
    }
    if !metadata.file_type().is_file() {
        return Ok(HarnessEntry::Foreign);
    }
    if has_marker(&fs::read(path)?) {
        Ok(HarnessEntry::Managed)
    } else {
        Ok(HarnessEntry::Foreign)
    }
}

fn sync_entry(
    context: &SyncContext,
    harness: &Harness,
    agent: &Agent,
    variant: &AgentVariant,
    canonical: &Path,
    canonical_contents: Option<&str>,
    report: &mut SyncReport,
) -> Result<bool, String> {
    let extension = extension(variant.file_name);
    let destination = harness
        .agents_dir
        .join(format!("{}.{}", agent.name, extension));
    let state = harness_entry(&destination, canonical).map_err(|error| {
        format!(
            "could not inspect harness agent {}: {error}",
            destination.display()
        )
    })?;
    if state == HarnessEntry::Foreign {
        add_unowned(report, &destination);
        return Ok(false);
    }

    match context.link_mode {
        LinkMode::Symlink if state == HarnessEntry::CanonicalLink => {
            if context.dry_run {
                println!(
                    "would keep already linked {} -> {}",
                    destination.display(),
                    canonical.display()
                );
            } else {
                println!(
                    "Already linked harness agent {} -> {}",
                    destination.display(),
                    canonical.display()
                );
            }
        }
        LinkMode::Symlink if context.dry_run => {
            println!(
                "would link {} -> {}",
                destination.display(),
                canonical.display()
            );
        }
        LinkMode::Symlink => {
            fsops::replace_with_file_symlink(&destination, canonical).map_err(|error| {
                format!(
                    "could not link harness agent {} to {}: {error}",
                    destination.display(),
                    canonical.display()
                )
            })?;
            println!(
                "Linked harness agent {} -> {}",
                destination.display(),
                canonical.display()
            );
        }
        LinkMode::Copy if context.dry_run => {
            println!(
                "would install copy agent {} -> {}",
                agent.name,
                destination.display()
            );
        }
        LinkMode::Copy => {
            let contents = canonical_contents.ok_or_else(|| {
                format!(
                    "canonical agent file is missing for {}",
                    destination.display()
                )
            })?;
            fsops::replace_file(&destination, contents.as_bytes()).map_err(|error| {
                format!(
                    "could not copy canonical agent {} to {}: {error}",
                    canonical.display(),
                    destination.display()
                )
            })?;
            println!(
                "Installed harness agent copy {} -> {}",
                destination.display(),
                canonical.display()
            );
        }
    }
    Ok(true)
}

fn sync_harness_entries(
    context: &SyncContext,
    harness: &Harness,
    opencode_major: u64,
    report: &mut SyncReport,
) -> Result<(), String> {
    let state = directory_state(&harness.agents_dir).map_err(|error| {
        format!(
            "could not inspect harness agents directory {}: {error}",
            harness.agents_dir.display()
        )
    })?;
    if state == DirectoryState::Foreign {
        add_unowned(report, &harness.agents_dir);
        return Ok(());
    }
    if state == DirectoryState::Missing && !context.dry_run {
        fs::create_dir_all(&harness.agents_dir).map_err(|error| {
            format!(
                "could not create harness agents directory {}: {error}",
                harness.agents_dir.display()
            )
        })?;
        if directory_state(&harness.agents_dir).map_err(|error| {
            format!(
                "could not inspect harness agents directory {}: {error}",
                harness.agents_dir.display()
            )
        })? != DirectoryState::Real
        {
            add_unowned(report, &harness.agents_dir);
            return Ok(());
        }
    }

    let canonical_directory = context.agents_dir.join(harness.id.as_str());
    let canonical_state = directory_state(&canonical_directory).map_err(|error| {
        format!(
            "could not inspect canonical agent directory {}: {error}",
            canonical_directory.display()
        )
    })?;
    if canonical_state == DirectoryState::Foreign {
        return Ok(());
    }
    if canonical_state == DirectoryState::Missing && !context.dry_run {
        return Err(format!(
            "canonical agent directory {} is missing",
            canonical_directory.display()
        ));
    }

    for agent in embedded_agents() {
        let variant = variant_for(agent, harness.id, opencode_major).ok_or_else(|| {
            format!(
                "agent {} has no embedded {} variant",
                agent.name,
                harness.id.as_str()
            )
        })?;
        let canonical =
            canonical_directory.join(format!("{}.{}", agent.name, extension(variant.file_name)));
        let contents = match canonical_file(&canonical).map_err(|error| {
            format!(
                "could not inspect canonical agent file {}: {error}",
                canonical.display()
            )
        })? {
            CanonicalFile::Managed(contents) => Some(contents),
            CanonicalFile::Missing if context.dry_run => None,
            CanonicalFile::Missing => {
                return Err(format!(
                    "canonical agent file {} is missing",
                    canonical.display()
                ));
            }
            CanonicalFile::Foreign => {
                add_unowned(report, &canonical);
                continue;
            }
        };
        sync_entry(
            context,
            harness,
            agent,
            variant,
            &canonical,
            contents.as_deref(),
            report,
        )?;
    }
    Ok(())
}

fn remove_managed(path: &Path, context: &SyncContext) -> Result<(), String> {
    if managed_file(path)
        .map_err(|error| {
            format!(
                "could not inspect stale agent file {}: {error}",
                path.display()
            )
        })?
        .is_none()
    {
        return Ok(());
    }
    if context.dry_run {
        println!("would remove {}", path.display());
    } else {
        fs::remove_file(path).map_err(|error| {
            format!(
                "could not remove stale agent file {}: {error}",
                path.display()
            )
        })?;
        println!("Removed {}", path.display());
    }
    Ok(())
}

fn remove_retired(
    path: &Path,
    canonical_directory: &Path,
    context: &SyncContext,
) -> Result<(), String> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(()),
        Err(error) => {
            return Err(format!(
                "could not inspect retired agent file {}: {error}",
                path.display()
            ));
        }
    };
    if metadata.file_type().is_symlink() {
        let target = fs::read_link(path).map_err(|error| {
            format!(
                "could not inspect retired agent link {}: {error}",
                path.display()
            )
        })?;
        let target = if target.is_absolute() {
            target
        } else {
            path.parent().unwrap_or_else(|| Path::new(".")).join(target)
        };
        if !is_within(&target, canonical_directory) {
            return Ok(());
        }
        if context.dry_run {
            println!("would remove {}", path.display());
        } else {
            fs::remove_file(path).map_err(|error| {
                format!(
                    "could not remove retired agent link {}: {error}",
                    path.display()
                )
            })?;
            println!("Removed {}", path.display());
        }
        return Ok(());
    }
    remove_managed(path, context)
}

fn cleanup_harness(
    context: &SyncContext,
    harness: &Harness,
    opencode_major: u64,
) -> Result<(), String> {
    if directory_state(&harness.agents_dir).map_err(|error| {
        format!(
            "could not inspect harness agents directory {}: {error}",
            harness.agents_dir.display()
        )
    })? != DirectoryState::Real
    {
        return Ok(());
    }

    let canonical_directory = context.agents_dir.join(harness.id.as_str());
    if directory_state(&canonical_directory).map_err(|error| {
        format!(
            "could not inspect canonical agent directory {}: {error}",
            canonical_directory.display()
        )
    })? == DirectoryState::Foreign
    {
        return Ok(());
    }

    for agent in embedded_agents() {
        let variant = variant_for(agent, harness.id, opencode_major).ok_or_else(|| {
            format!(
                "agent {} has no embedded {} variant",
                agent.name,
                harness.id.as_str()
            )
        })?;
        let extension = extension(variant.file_name);
        let canonical = canonical_directory.join(format!("{}.{}", agent.name, extension));
        match canonical_file(&canonical).map_err(|error| {
            format!(
                "could not inspect canonical agent file {}: {error}",
                canonical.display()
            )
        })? {
            CanonicalFile::Managed(_) => {}
            CanonicalFile::Missing if context.dry_run => {}
            CanonicalFile::Missing | CanonicalFile::Foreign => continue,
        }
        let destination = harness
            .agents_dir
            .join(format!("{}.{}", agent.name, extension));
        if matches!(
            harness_entry(&destination, &canonical).map_err(|error| {
                format!(
                    "could not inspect harness agent {}: {error}",
                    destination.display()
                )
            })?,
            HarnessEntry::Foreign
        ) {
            continue;
        }

        for old in old_name(agent.name) {
            remove_retired(
                &harness.agents_dir.join(format!("{old}.{extension}")),
                &canonical_directory,
                context,
            )?;
        }

        if harness.id == HarnessId::OpenCode {
            let legacy = context.home.join(".config/opencode/agent");
            if directory_state(&legacy).map_err(|error| {
                format!(
                    "could not inspect legacy OpenCode agent directory {}: {error}",
                    legacy.display()
                )
            })? == DirectoryState::Real
            {
                remove_managed(&legacy.join(format!("{}.md", agent.name)), context)?;
                for old in old_name(agent.name) {
                    remove_retired(
                        &legacy.join(format!("{old}.md")),
                        &canonical_directory,
                        context,
                    )?;
                }
            }
        }
    }
    Ok(())
}

pub fn run(context: &SyncContext) -> Result<(), String> {
    let opencode_major = opencode_major();
    let mut report = SyncReport::default();
    for harness in [
        HarnessId::Claude,
        HarnessId::Codex,
        HarnessId::OpenCode,
        HarnessId::Pi,
    ] {
        install_harness(context, harness, opencode_major, &mut report)?;
    }

    for harness in &context.harnesses {
        sync_harness_entries(context, harness, opencode_major, &mut report)?;
    }
    report_preserved(&report, context.dry_run);
    for harness in &context.harnesses {
        cleanup_harness(context, harness, opencode_major)?;
    }
    for harness in &context.harnesses {
        let canonical_directory = context.agents_dir.join(harness.id.as_str());
        if directory_state(&canonical_directory).map_err(|error| {
            format!(
                "could not inspect canonical agent directory {}: {error}",
                canonical_directory.display()
            )
        })? != DirectoryState::Foreign
        {
            let entries = match fs::read_dir(&canonical_directory) {
                Ok(entries) => entries,
                Err(error) if error.kind() == io::ErrorKind::NotFound && context.dry_run => {
                    continue;
                }
                Err(error) => {
                    return Err(format!(
                        "could not list canonical agent directory {}: {error}",
                        canonical_directory.display()
                    ));
                }
            };
            for entry in entries {
                let entry = entry.map_err(|error| {
                    format!(
                        "could not read canonical agent directory {}: {error}",
                        canonical_directory.display()
                    )
                })?;
                let retired_prefix = format!("{}.", old_name("varde-builder")[0]);
                if entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(&retired_prefix)
                {
                    remove_managed(&entry.path(), context)?;
                }
            }
        }
    }
    Ok(())
}
