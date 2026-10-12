//! Set or clear the optional owner in a plan's frontmatter.

use crate::cli::OwnerArgs;
use crate::commands::status;
use anyhow::{Context, Result, anyhow, bail};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use varde_workflow_core::memory::MemoryPaths;

pub fn run(args: OwnerArgs) -> Result<()> {
    let cwd = std::env::current_dir().context("could not resolve current directory")?;
    let working = MemoryPaths::resolve(&cwd)?.working.path;
    let plan = resolve_plan(&args.plan, &cwd, &working.join("plans"))?;
    let bytes = fs::read(&plan).with_context(|| format!("could not read {}", plan.display()))?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)
        .with_context(|| format!("could not parse plan {}", plan.display()))?;
    let mapping = frontmatter
        .as_mapping()
        .ok_or_else(|| anyhow!("{} has invalid frontmatter", plan.display()))?;
    if status::artifact_type(mapping) != "plan" {
        bail!("{} is not a plan", plan.display());
    }

    if let Some(owner) = args.owner.as_deref() {
        validate_owner(owner)?;
        let replacement = serde_yaml::to_string(owner)?;
        let replacement = replacement.trim_end_matches('\n');
        let updated = set_owner_line(&bytes, replacement)?;
        write_plan(&plan, &updated)?;
        println!("Set owner for {}.", plan.display());
    } else {
        let updated = remove_owner_line(&bytes)?;
        if updated != bytes {
            write_plan(&plan, &updated)?;
        }
        println!("Cleared owner for {}.", plan.display());
    }
    Ok(())
}

fn validate_owner(owner: &str) -> Result<()> {
    let Some((harness, id)) = owner.split_once(':') else {
        bail!("owner must use `<harness>:<id>` form");
    };
    if harness.is_empty()
        || id.is_empty()
        || owner
            .chars()
            .any(|character| character.is_whitespace() || character.is_control())
    {
        bail!(
            "owner harness and id must be non-empty and contain no whitespace or control characters"
        );
    }
    Ok(())
}

fn write_plan(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path.parent().context("plan path has no parent")?;
    let filename = path
        .file_name()
        .context("plan path has no filename")?
        .to_string_lossy();
    let temporary = parent.join(format!(".{filename}.{}.tmp", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)?;
        file.write_all(bytes)?;
        file.sync_all()?;
        fs::rename(&temporary, path)
    })();
    if let Err(error) = result {
        let _ = fs::remove_file(&temporary);
        return Err(error).with_context(|| format!("could not write {}", path.display()));
    }
    Ok(())
}

fn resolve_plan(argument: &Path, cwd: &Path, plans_dir: &Path) -> Result<PathBuf> {
    let direct = if argument.is_absolute() {
        argument.to_path_buf()
    } else {
        cwd.join(argument)
    };
    let candidate = if direct.is_file() {
        direct
    } else {
        plans_dir.join(argument)
    };
    let plans_root = fs::canonicalize(plans_dir)
        .with_context(|| format!("could not read plans tree {}", plans_dir.display()))?;
    let canonical = fs::canonicalize(&candidate)
        .with_context(|| format!("could not read plan {}", candidate.display()))?;
    if canonical.file_name().and_then(|name| name.to_str()) != Some("plan.md") {
        bail!("{} is not a plan.md file", candidate.display());
    }
    if !canonical.starts_with(&plans_root) {
        bail!("plan path must be inside {}", plans_dir.display());
    }
    Ok(canonical)
}

fn frontmatter_bounds(bytes: &[u8]) -> Result<(usize, usize)> {
    if !bytes.starts_with(b"---\n") {
        bail!("plan must begin with `---` frontmatter");
    }
    let mut line_start = 4;
    while line_start <= bytes.len() {
        let line_end = bytes[line_start..]
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|offset| line_start + offset)
            .unwrap_or(bytes.len());
        if &bytes[line_start..line_end] == b"---" {
            return Ok((4, line_start));
        }
        if line_end == bytes.len() {
            break;
        }
        line_start = line_end + 1;
    }
    bail!("plan is missing a closing frontmatter delimiter")
}

fn owner_line(bytes: &[u8], start: usize, end: usize) -> Option<(usize, usize)> {
    let mut line_start = start;
    while line_start < end {
        let line_end = bytes[line_start..end]
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|offset| line_start + offset)
            .unwrap_or(end);
        if bytes[line_start..line_end].starts_with(b"owner:") {
            return Some((line_start, line_end));
        }
        line_start = line_end.saturating_add(1);
    }
    None
}

fn set_owner_line(bytes: &[u8], value: &str) -> Result<Vec<u8>> {
    let (start, end) = frontmatter_bounds(bytes)?;
    let line = format!("owner: {value}");
    let mut updated = Vec::with_capacity(bytes.len() + line.len());
    if let Some((line_start, line_end)) = owner_line(bytes, start, end) {
        let remove_end = continuation_end(bytes, line_end, end);
        updated.extend_from_slice(&bytes[..line_start]);
        updated.extend_from_slice(line.as_bytes());
        updated.push(b'\n');
        updated.extend_from_slice(&bytes[remove_end..]);
    } else {
        updated.extend_from_slice(&bytes[..end]);
        updated.extend_from_slice(line.as_bytes());
        updated.push(b'\n');
        updated.extend_from_slice(&bytes[end..]);
    }
    Ok(updated)
}

fn remove_owner_line(bytes: &[u8]) -> Result<Vec<u8>> {
    let (start, end) = frontmatter_bounds(bytes)?;
    let Some((line_start, line_end)) = owner_line(bytes, start, end) else {
        return Ok(bytes.to_vec());
    };
    let remove_end = continuation_end(bytes, line_end, end);
    let mut updated = Vec::with_capacity(bytes.len() - (remove_end - line_start));
    updated.extend_from_slice(&bytes[..line_start]);
    updated.extend_from_slice(&bytes[remove_end..]);
    Ok(updated)
}

fn continuation_end(bytes: &[u8], line_end: usize, frontmatter_end: usize) -> usize {
    let mut next = if bytes.get(line_end) == Some(&b'\n') {
        line_end + 1
    } else {
        line_end
    };
    while next < frontmatter_end {
        let end = bytes[next..frontmatter_end]
            .iter()
            .position(|byte| *byte == b'\n')
            .map(|offset| next + offset)
            .unwrap_or(frontmatter_end);
        if !matches!(bytes.get(next), Some(b' ' | b'\t')) {
            break;
        }
        next = if bytes.get(end) == Some(&b'\n') {
            end + 1
        } else {
            end
        };
    }
    next
}
