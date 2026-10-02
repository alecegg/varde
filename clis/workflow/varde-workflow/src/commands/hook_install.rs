//! `varde-workflow hook install|remove`: manage the unified SessionStart hook.
//!
//! Claude and Codex get one entry merged into their JSON hook config; opencode
//! and pi get a whole-file plugin or extension. An entry is ours when its command runs an
//! executable named `varde-workflow` with `hook session-start` arguments.

use crate::cli::{Harness, HookInstallArgs};
use anyhow::{Context, Result, bail};
use serde_json::{Value, json};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

const OPENCODE_ASSET: &str = include_str!("../../assets/opencode/varde-session.ts");
const PI_ASSET: &str = include_str!("../../assets/pi/varde-session.ts");
const ENTRY_TIMEOUT: u64 = 20;

pub fn run(args: HookInstallArgs, remove: bool) -> Result<()> {
    let home = home_dir()?;
    match args.harness {
        Harness::Claude => update_json(
            &home.join(".claude/settings.json"),
            "claude",
            remove,
            args.dry_run,
        ),
        Harness::Codex => update_json(
            &home.join(".codex/hooks.json"),
            "codex",
            remove,
            args.dry_run,
        ),
        Harness::Opencode => update_plugin(
            &config_home(&home).join("opencode/plugin/varde-session.ts"),
            remove,
            args.dry_run,
        ),
        Harness::Pi => {
            let text = if remove || args.dry_run {
                String::new()
            } else {
                with_bin(PI_ASSET, &running_exe()?)
            };
            update_file(
                &pi_agent_dir(&home).join("extensions/varde-session.ts"),
                &text,
                remove,
                args.dry_run,
            )
        }
    }
}

fn pi_agent_dir(home: &Path) -> PathBuf {
    match std::env::var_os("PI_CODING_AGENT_DIR") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => home.join(".pi/agent"),
    }
}

fn home_dir() -> Result<PathBuf> {
    match std::env::var_os("HOME") {
        Some(home) if !home.is_empty() => Ok(PathBuf::from(home)),
        _ => bail!("HOME is not set"),
    }
}

fn config_home(home: &Path) -> PathBuf {
    match std::env::var_os("XDG_CONFIG_HOME") {
        Some(x) if !x.is_empty() => PathBuf::from(x),
        _ => home.join(".config"),
    }
}

fn update_json(path: &Path, harness: &str, remove: bool, dry_run: bool) -> Result<()> {
    let mut root = match fs::read_to_string(path) {
        Ok(text) => serde_json::from_str::<Value>(&text)
            .with_context(|| format!("{} is not valid JSON", path.display()))?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if remove {
                report(path, remove, dry_run);
                return Ok(());
            }
            json!({})
        }
        Err(error) => return Err(error).with_context(|| format!("reading {}", path.display())),
    };
    let original = root.clone();
    let command = if remove {
        None
    } else {
        Some(hook_command(harness)?)
    };
    // Only Codex's hooks.json lacks another owner for legacy nav_map entries;
    // `varde-code hooks remove` owns the Claude one.
    let drop_legacy = harness == "codex";
    let legacy = merge_session_start(&mut root, command.as_deref(), drop_legacy)?;
    report(path, remove, dry_run);
    for old in legacy {
        let verb = if dry_run { "would drop" } else { "dropping" };
        println!("{verb} legacy varde-code nav_map hook: {old}");
    }
    if dry_run || root == original {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    write_atomic(path, &(serde_json::to_string_pretty(&root)? + "\n"))
}

/// Write via a temp file next to the real target and rename, so a crash cannot
/// truncate it. A symlinked `path` is followed and an existing file keeps its
/// permissions.
fn write_atomic(path: &Path, text: &str) -> Result<()> {
    let target = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let mut temp = target.as_os_str().to_owned();
    temp.push(format!(".varde-tmp-{}", std::process::id()));
    let temp = PathBuf::from(temp);
    fs::write(&temp, text).with_context(|| format!("writing {}", temp.display()))?;
    if let Ok(metadata) = fs::metadata(&target) {
        fs::set_permissions(&temp, metadata.permissions())
            .with_context(|| format!("setting permissions on {}", temp.display()))?;
    }
    fs::rename(&temp, &target).with_context(|| format!("replacing {}", target.display()))
}

/// Drop our entries from `hooks.SessionStart`, then add `command` when given.
/// Installing with `drop_legacy` also drops `varde-code nav_map` entries and
/// returns them.
fn merge_session_start(
    root: &mut Value,
    command: Option<&str>,
    drop_legacy: bool,
) -> Result<Vec<String>> {
    let Some(object) = root.as_object_mut() else {
        bail!("hook config root is not a JSON object");
    };
    let hooks = if command.is_some() {
        object.entry("hooks").or_insert_with(|| json!({}))
    } else {
        let Some(hooks) = object.get_mut("hooks") else {
            return Ok(Vec::new());
        };
        hooks
    };
    let Some(hooks) = hooks.as_object_mut() else {
        bail!("`hooks` is not a JSON object");
    };
    let mut groups = match hooks.remove("SessionStart") {
        None => Vec::new(),
        Some(Value::Array(groups)) => groups,
        Some(_) => bail!("`hooks.SessionStart` is not an array"),
    };
    let mut legacy = Vec::new();
    for group in &mut groups {
        if let Some(inner) = group.get_mut("hooks").and_then(Value::as_array_mut) {
            inner.retain(|hook| {
                let text = hook["command"].as_str().unwrap_or_default();
                if command.is_some() && drop_legacy && is_legacy_nav_map(text) {
                    legacy.push(text.to_string());
                    return false;
                }
                !is_ours(text)
            });
        }
    }
    groups.retain(|group| {
        group["hooks"]
            .as_array()
            .is_none_or(|inner| !inner.is_empty())
    });
    if let Some(command) = command {
        groups.push(json!({
            "hooks": [{"type": "command", "command": command, "timeout": ENTRY_TIMEOUT}]
        }));
    }
    if !groups.is_empty() {
        hooks.insert("SessionStart".into(), Value::Array(groups));
    }
    Ok(legacy)
}

fn hook_command(harness: &str) -> Result<String> {
    Ok(format!(
        "{} hook session-start --harness {harness}",
        shell_quote(&running_exe()?)
    ))
}

fn running_exe() -> Result<String> {
    let exe = std::env::current_exe().context("locating the running varde-workflow")?;
    Ok(exe.to_string_lossy().into_owned())
}

fn shell_quote(word: &str) -> String {
    let plain = |c: char| c.is_ascii_alphanumeric() || "/._-+:@".contains(c);
    if word.chars().all(plain) {
        word.to_string()
    } else {
        format!("'{}'", word.replace('\'', r"'\''"))
    }
}

/// Split a command line on whitespace, honoring quotes and backslash escapes
/// (outside quotes, and before `"` or `\` inside double quotes).
fn shell_words(command: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut current = String::new();
    let mut quote: Option<char> = None;
    let mut started = false;
    let mut chars = command.chars().peekable();
    while let Some(c) = chars.next() {
        match (quote, c) {
            (None, '\\') => {
                if let Some(next) = chars.next() {
                    current.push(next);
                    started = true;
                }
            }
            (Some('"'), '\\') if matches!(chars.peek(), Some('"' | '\\')) => {
                current.extend(chars.next());
            }
            (Some(q), c) if c == q => quote = None,
            (Some(_), c) => current.push(c),
            (None, '\'' | '"') => {
                quote = Some(c);
                started = true;
            }
            (None, c) if c.is_whitespace() => {
                if started {
                    words.push(std::mem::take(&mut current));
                    started = false;
                }
            }
            (None, c) => {
                current.push(c);
                started = true;
            }
        }
    }
    if started {
        words.push(current);
    }
    words
}

fn is_ours(command: &str) -> bool {
    let words = shell_words(command);
    let Some(exe) = words.first() else {
        return false;
    };
    Path::new(exe).file_name().and_then(|f| f.to_str()) == Some("varde-workflow")
        && words[1..]
            .windows(2)
            .any(|w| w == ["hook", "session-start"])
}

/// A pre-unification `varde-code nav_map` SessionStart command.
fn is_legacy_nav_map(command: &str) -> bool {
    let words = shell_words(command);
    let Some(exe) = words.first() else {
        return false;
    };
    Path::new(exe).file_name().and_then(|f| f.to_str()) == Some("varde-code")
        && words[1..].iter().any(|w| w == "nav_map")
}

fn update_plugin(path: &Path, remove: bool, dry_run: bool) -> Result<()> {
    let text = if remove || dry_run {
        String::new()
    } else {
        opencode_plugin(opencode_major(), &running_exe()?)
    };
    update_file(path, &text, remove, dry_run)
}

/// Write `text` to `path` atomically, or delete `path` when removing.
fn update_file(path: &Path, text: &str, remove: bool, dry_run: bool) -> Result<()> {
    report(path, remove, dry_run);
    if dry_run {
        return Ok(());
    }
    if remove {
        return match fs::remove_file(path) {
            Err(error) if error.kind() != std::io::ErrorKind::NotFound => {
                Err(error).with_context(|| format!("removing {}", path.display()))
            }
            _ => Ok(()),
        };
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    write_atomic(path, text)
}

/// Header plus the half of the asset for the installed opencode: 2.x or later
/// gets the 2.x plugin, anything else (including not installed) the 1.x plugin.
fn opencode_plugin(major: Option<u64>, bin: &str) -> String {
    let (header, rest) = OPENCODE_ASSET.split_once("//@@v1\n").unwrap();
    let (v1, v2) = rest.split_once("//@@v2\n").unwrap();
    let body = if major.is_some_and(|m| m >= 2) {
        v2
    } else {
        v1
    };
    with_bin(&format!("{header}{body}"), bin)
}

fn with_bin(asset: &str, bin: &str) -> String {
    let bin_json = Value::String(bin.to_string()).to_string();
    asset.replace("\"{{VARDE_WORKFLOW_BIN}}\"", &bin_json)
}

fn opencode_major() -> Option<u64> {
    let out = Command::new("opencode")
        .arg("--version")
        .stdin(Stdio::null())
        .output()
        .ok()?;
    let text = String::from_utf8_lossy(&out.stdout);
    let token = text
        .split_whitespace()
        .find(|t| t.trim_start_matches('v').contains('.'))?;
    token
        .trim_start_matches('v')
        .split('.')
        .next()?
        .parse()
        .ok()
}

fn report(path: &Path, remove: bool, dry_run: bool) {
    let verb = match (remove, dry_run) {
        (false, false) => "installing into",
        (true, false) => "removing from",
        (false, true) => "would install into",
        (true, true) => "would remove from",
    };
    println!("{verb} {}", path.display());
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quoted_command_round_trips_for_paths_with_apostrophe_and_space() {
        let command = format!(
            "{} hook session-start --harness claude",
            shell_quote("/x/it's here/varde-workflow")
        );
        assert_eq!(shell_words(&command)[0], "/x/it's here/varde-workflow");
        assert!(is_ours(&command));
    }
}
