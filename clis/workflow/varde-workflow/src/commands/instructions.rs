//! Manage the marker-delimited Varde instruction block in user-selected files.

use super::hook::{SPAWN_ERROR_PREFIX, capture};
use crate::cli::{InstructionsArgs, InstructionsCommand, InstructionsInstallArgs};
use anyhow::{Context, Result};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::ops::Range;
use std::path::{Component, Path, PathBuf};
use varde_workflow_core::memory::{load_config, save_config};

const START_MARKER: &[u8] = b"<!-- varde:start -->";
const END_MARKER: &[u8] = b"<!-- varde:end -->";
const LEGACY_TOZ_MARKER: &[u8] = b"<!-- varde-toz:start -->";

/// Shared warning for commands that need an instruction target before Varde can work as designed.
pub const SETUP_WARNING: &str = "Varde will not work as designed until its instruction block is installed: agents will not delegate as designed or use toz captures. Install it with `varde-workflow instructions install --target <file>`. Use one canonical `AGENTS.md` symlinked into each harness.";

pub fn run(args: InstructionsArgs) -> Result<()> {
    match args.command {
        InstructionsCommand::Install(args) => install(args),
        InstructionsCommand::Remove(args) => remove(args.dry_run),
        InstructionsCommand::Targets => targets(),
    }
}

fn install(args: InstructionsInstallArgs) -> Result<()> {
    let mut config = load_config().context("could not load Varde config")?;
    let supplied_targets = !args.targets.is_empty();
    if let Some(max_agents) = args.max_agents {
        config.orchestration.set_max_agents(max_agents);
    }

    let target_paths = if supplied_targets {
        let paths = unique_targets(&args.targets)?;
        config.instructions.targets = paths
            .iter()
            .map(|path| {
                path.to_str()
                    .map(str::to_owned)
                    .with_context(|| format!("target path is not valid UTF-8: {}", path.display()))
            })
            .collect::<Result<Vec<_>>>()?;
        paths
    } else {
        unique_targets(
            &config
                .instructions
                .targets
                .iter()
                .map(PathBuf::from)
                .collect::<Vec<_>>(),
        )?
    };

    if !args.dry_run && (supplied_targets || args.max_agents.is_some()) {
        save_config(&config).context("could not save Varde config")?;
    }

    if target_paths.is_empty() {
        println!("{SETUP_WARNING}");
        return Ok(());
    }

    let max_agents = if let Some(max_agents) = args.max_agents {
        max_agents
    } else {
        let (max_agents, invalid) = config.orchestration.max_agents();
        if let Some(reason) = invalid {
            eprintln!(
                "varde-workflow instructions: orchestration max_agents ignored ({reason}); using {max_agents}"
            );
        }
        max_agents
    };
    let block = render_block(max_agents);
    for path in target_paths {
        install_target(&path, &block, args.dry_run);
    }
    Ok(())
}

fn targets() -> Result<()> {
    let config = load_config().context("could not load Varde config")?;
    for target in config.instructions.targets {
        println!("{target}");
    }
    Ok(())
}

fn remove(dry_run: bool) -> Result<()> {
    let mut config = load_config().context("could not load Varde config")?;
    for path in unique_targets(
        &config
            .instructions
            .targets
            .iter()
            .map(PathBuf::from)
            .collect::<Vec<_>>(),
    )? {
        let content = match fs::read(&path) {
            Ok(content) => content,
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => {
                eprintln!(
                    "varde-workflow instructions: cannot read {}: {error}",
                    path.display()
                );
                continue;
            }
        };
        let updated = remove_blocks(&content);
        if updated == content {
            continue;
        }
        if dry_run {
            println!(
                "would remove the Varde instruction block from {}",
                path.display()
            );
        } else {
            fs::write(&path, updated)
                .with_context(|| format!("could not update {}", path.display()))?;
        }
    }
    if !dry_run && !config.instructions.targets.is_empty() {
        config.instructions.targets.clear();
        save_config(&config).context("could not save Varde config")?;
    }
    Ok(())
}

fn unique_targets(paths: &[PathBuf]) -> Result<Vec<PathBuf>> {
    let mut seen = HashSet::new();
    let mut targets = Vec::new();
    for path in paths {
        let absolute = absolute_path(path)?;
        if seen.insert(real_path_key(&absolute)) {
            targets.push(absolute);
        }
    }
    Ok(targets)
}

fn absolute_path(path: &Path) -> Result<PathBuf> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()?.join(path)
    };
    Ok(normalize_path(&absolute))
}

fn normalize_path(path: &Path) -> PathBuf {
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Prefix(_) | Component::RootDir => normalized.push(component.as_os_str()),
            Component::CurDir => {}
            Component::ParentDir => {
                if !normalized.pop() {
                    normalized.push(component.as_os_str());
                }
            }
            Component::Normal(part) => normalized.push(part),
        }
    }
    normalized
}

fn real_path_key(path: &Path) -> PathBuf {
    if let Ok(real) = fs::canonicalize(path) {
        return real;
    }
    match (path.parent(), path.file_name()) {
        (Some(parent), Some(name)) => fs::canonicalize(parent)
            .map(|real_parent| real_parent.join(name))
            .unwrap_or_else(|_| path.to_path_buf()),
        _ => path.to_path_buf(),
    }
}

fn render_block(max_agents: u32) -> String {
    let mut body = orchestration_brief(max_agents);
    if let Some(note) = toz_note() {
        body.push_str("\n\n");
        body.push_str(&note);
    }
    format!(
        "{}\n{}\n{}",
        String::from_utf8_lossy(START_MARKER),
        body,
        String::from_utf8_lossy(END_MARKER)
    )
}

fn toz_note() -> Option<String> {
    let argv = ["note", "--block"].map(String::from);
    match capture("varde-toz", &argv, Path::new(".")) {
        Ok(note) => (!note.is_empty()).then_some(note),
        // `cannot run` means varde-toz is not installed; omit its section.
        Err(reason) if reason.starts_with(SPAWN_ERROR_PREFIX) => None,
        Err(reason) => {
            eprintln!("varde-workflow instructions: `varde-toz note --block` failed: {reason}");
            None
        }
    }
}

fn install_target(path: &Path, block: &str, dry_run: bool) {
    let existing = match fs::read(path) {
        Ok(content) => Some(content),
        Err(error) if error.kind() == io::ErrorKind::NotFound => None,
        Err(error) => {
            write_failure(path, block, error);
            return;
        }
    };
    if existing
        .as_deref()
        .is_some_and(|content| find_bytes(content, LEGACY_TOZ_MARKER, 0).is_some())
    {
        eprintln!(
            "varde-workflow instructions: {} contains a legacy varde-toz block; run `varde-toz install codex` to remove it",
            path.display()
        );
    }
    let updated = install_block(existing.as_deref().unwrap_or_default(), block.as_bytes());
    if existing.as_deref() == Some(updated.as_slice()) {
        return;
    }
    if dry_run {
        println!(
            "would write the Varde instruction block to {}:\n{}",
            path.display(),
            block
        );
    } else if let Err(error) = fs::write(path, updated) {
        write_failure(path, block, error);
    }
}

fn write_failure(path: &Path, block: &str, error: io::Error) {
    eprintln!(
        "varde-workflow instructions: could not write {}: {error}",
        path.display()
    );
    println!("{block}");
}

fn install_block(existing: &[u8], block: &[u8]) -> Vec<u8> {
    let ranges = block_ranges(existing);
    if ranges.is_empty() {
        if existing.is_empty() {
            let mut updated = Vec::with_capacity(block.len() + 1);
            updated.extend_from_slice(block);
            updated.push(b'\n');
            return updated;
        }
        let mut updated = Vec::with_capacity(existing.len() + 3 + block.len());
        updated.extend_from_slice(existing);
        updated.extend_from_slice(b"\n\n");
        updated.extend_from_slice(block);
        updated.push(b'\n');
        return updated;
    }

    let mut updated = Vec::with_capacity(existing.len() + block.len());
    let mut cursor = 0;
    for (index, range) in ranges.iter().enumerate() {
        updated.extend_from_slice(&existing[cursor..range.start]);
        if index == 0 {
            updated.extend_from_slice(block);
        }
        cursor = range.end;
    }
    updated.extend_from_slice(&existing[cursor..]);
    updated
}

fn remove_blocks(existing: &[u8]) -> Vec<u8> {
    let ranges = block_ranges(existing);
    if ranges.is_empty() {
        return existing.to_vec();
    }

    if ranges.len() == 1 {
        let range = &ranges[0];
        let trailing_bytes = &existing[range.end..];
        if range.start == 0 && trailing_bytes == b"\n" {
            return Vec::new();
        }
        if range.start >= 2
            && &existing[range.start - 2..range.start] == b"\n\n"
            && (trailing_bytes.is_empty() || trailing_bytes == b"\n")
        {
            return existing[..range.start - 2].to_vec();
        }
    }

    let mut updated = Vec::with_capacity(existing.len());
    let mut cursor = 0;
    for range in &ranges {
        updated.extend_from_slice(&existing[cursor..range.start]);
        cursor = range.end;
    }
    updated.extend_from_slice(&existing[cursor..]);
    updated
}

fn block_ranges(content: &[u8]) -> Vec<Range<usize>> {
    let mut ranges = Vec::new();
    let mut cursor = 0;
    while let Some(start) = find_bytes(content, START_MARKER, cursor) {
        let body_start = start + START_MARKER.len();
        let Some(end) = find_bytes(content, END_MARKER, body_start) else {
            break;
        };
        let block_end = end + END_MARKER.len();
        ranges.push(start..block_end);
        cursor = block_end;
    }
    ranges
}

fn find_bytes(haystack: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    haystack
        .get(from..)?
        .windows(needle.len())
        .position(|window| window == needle)
        .map(|offset| from + offset)
}

/// The orchestration brief; every instruction file pays for it, so keep it short.
pub(super) fn orchestration_brief(max_agents: u32) -> String {
    format!(
        "Orchestration: you are the main agent. Stay available to the user and delegate bounded tasks to background `varde-*` agents.\n\
         Keep responding to the user while commands and agents run; say when you become busy and when you are free again.\n\
         Run at most {max_agents} subagents at once; `varde-explorer` runs are not counted.\n\
         Subagents spawn nothing, except OpenCode and Pi planners, executors, and reviewers, which may run up to 2 `varde-explorer`. On other harnesses, first run up to 2 `varde-explorer` over the task's areas and put their notes in the brief.\n\
         Review each result before integrating it.\n\
         If you were launched with a bounded task, follow that brief instead.\n\
         This standing user request to delegate overrides any built-in default to spawn subagents only on request.\n\
         Details: varde-change `references/orchestration.md`."
    )
}
