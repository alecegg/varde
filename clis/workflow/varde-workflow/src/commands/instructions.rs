//! Manage the marker-delimited Varde instruction block in user-selected files.

use crate::cli::{InstructionsArgs, InstructionsCommand, InstructionsInstallArgs};
use anyhow::{Context, Result};
use std::collections::HashSet;
use std::fs;
use std::io;
use std::ops::Range;
use std::path::{Component, Path, PathBuf};
use varde_workflow_core::memory::{Orchestration, RoleCaps, load_config, save_config};

const START_MARKER: &[u8] = b"<!-- varde:start -->";
const END_MARKER: &[u8] = b"<!-- varde:end -->";
/// Template for the embedded Toz section (an app-crate test pins its output).
const TOZ_TEMPLATE: &str = "<!-- varde-toz:start -->\n## varde-toz (tool-output-zone)\n\n{{TOZ_SHARED_NOTE}}\n<!-- varde-toz:end -->\n";
const LEGACY_TOZ_MARKER: &[u8] = b"<!-- varde-toz:start -->";

/// Shared warning for commands that need an instruction target before Varde can work as designed.
pub const SETUP_WARNING: &str = "Varde will not work as designed until its instruction block is installed: agents will not delegate as designed or use captured command output. Install it with `varde setup instructions install --target <file>`. Use one canonical `AGENTS.md` symlinked into each harness.";

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
    if let Some(builders) = args.builders {
        config.orchestration.set_builders(builders);
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

    if !args.dry_run && (supplied_targets || args.builders.is_some()) {
        save_config(&config).context("could not save Varde config")?;
    }

    if target_paths.is_empty() {
        println!("{SETUP_WARNING}");
        return Ok(());
    }

    let caps = resolved_caps(&config.orchestration);
    let mut sections = if args.sections.is_empty() {
        Vec::new()
    } else {
        args.sections
            .split(',')
            .map(str::to_owned)
            .collect::<Vec<_>>()
    };
    if let Some(section) = sections
        .iter()
        .find(|section| !["orchestration", "toz", "learn"].contains(&section.as_str()))
    {
        anyhow::bail!("unknown instruction section: {section}");
    }
    if args.learn && !sections.iter().any(|section| section == "learn") {
        sections.push("learn".to_owned());
    }
    let block = render_block(caps, &sections);
    for path in target_paths {
        install_target(&path, &block, args.dry_run);
    }
    Ok(())
}

/// Resolve the per-role caps, warning once per invalid key.
fn resolved_caps(orchestration: &Orchestration) -> RoleCaps {
    let warn = |key: &str, (value, reason): (u32, Option<String>)| {
        if let Some(reason) = reason {
            eprintln!(
                "varde-workflow instructions: orchestration {key} ignored ({reason}); using {value}"
            );
        }
        value
    };
    RoleCaps {
        orchestrators: warn("orchestrators", orchestration.orchestrators()),
        builders: warn("builders", orchestration.builders()),
        planners: warn("planners", orchestration.planners()),
        reviewers: warn("reviewers", orchestration.reviewers()),
        explorers: warn("explorers", orchestration.explorers()),
    }
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

fn render_block(caps: RoleCaps, sections: &[String]) -> String {
    let mut body = Vec::new();
    if sections.iter().any(|section| section == "orchestration") {
        body.push(orchestration_brief(caps));
    }
    if sections.iter().any(|section| section == "toz") {
        body.push(toz_note());
    }
    if sections.iter().any(|section| section == "learn") {
        body.push(format!(
            "<!-- varde-learn:start -->\n## varde-learn\n\n{}\n<!-- varde-learn:end -->",
            varde_core::LEARN_NOTE
        ));
    }
    let body = body.join("\n\n");
    format!(
        "{}\n{}\n{}",
        String::from_utf8_lossy(START_MARKER),
        body,
        String::from_utf8_lossy(END_MARKER)
    )
}

/// The Toz section, rendered in process from the shared Varde template.
fn toz_note() -> String {
    let note = varde_core::toz_instruction_block(TOZ_TEMPLATE);
    note.trim().to_string()
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
            "varde-workflow instructions: {} contains a legacy varde-toz block; run `varde setup sync` to remove it",
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

/// Whether the file at `path` holds a paired Varde start/end marker block.
/// An unreadable or missing file holds none.
pub fn has_managed_block(path: &Path) -> bool {
    fs::read(path).is_ok_and(|content| !block_ranges(&content).is_empty())
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
pub(super) fn orchestration_brief(caps: RoleCaps) -> String {
    format!(
        "Orchestration: you are the main agent, the session manager: talk to the user, launch one orchestrator per plan, relay decisions and approvals, keep session notes; do not explore or implement. Orchestrators run their plan's workers, reviewers, merges, sync, memory commits and `varde plan conclude`.\n\
         Route every change through `varde-change`.\n\
         Role caps per orchestrator: {builders} builders, {planners} planners, {reviewers} reviewers, {explorers} explorers; at most {orchestrators} orchestrators, one per plan.\n\
         Orchestrators and workers report milestones with `varde msg send` to `main`; their final reply is one line. Main agent status format: details: varde-change `references/status.md`. On a wake-up or without the per-prompt hook, the main agent runs `varde msg read`.\n\
         Update the hand-written session notes section when a rule is set or a decision opens or closes; tidy it at the nudge, before compaction, or on request, and never edit the generated block.\n\
         Run `varde plan watch --stale 20m --notes <session notes path>` under your harness's monitor while orchestrators run; the session notes block shows plan state.\n\
         If you were launched with a bounded task, follow that brief instead.",
        builders = caps.builders,
        planners = caps.planners,
        reviewers = caps.reviewers,
        explorers = caps.explorers,
        orchestrators = caps.orchestrators,
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn toz_note_is_always_included() {
        let block = render_block(RoleCaps::default(), &["orchestration".into(), "toz".into()]);
        assert!(block.contains("## varde-toz (tool-output-zone)"), "{block}");
    }

    #[test]
    fn role_caps_line_is_rendered_from_config() {
        let caps = RoleCaps {
            orchestrators: 3,
            builders: 5,
            planners: 1,
            reviewers: 1,
            explorers: 2,
        };
        let block = render_block(caps, &["orchestration".into(), "toz".into()]);
        assert!(block.contains(
            "Role caps per orchestrator: 5 builders, 1 planners, 1 reviewers, 2 explorers; at most 3 orchestrators, one per plan."
        ), "{block}");
    }
}
