//! Legacy per-feature Toz installs. Installing moved to `varde setup hooks install`;
//! `varde setup sync` calls these functions to remove what older per-feature Toz installs
//! wrote, without touching anything the user edited.

use anyhow::{Context, Result};
use serde_json::Value;
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use varde_core::json_order;
use varde_core::{TOZ_BLOCK_END as BLOCK_END, TOZ_BLOCK_START as BLOCK_START};

const MANIFESTS: [&str; 2] = [".varde-toz-install.json", ".toz-install.json"];

/// Remove the files `rels` under `dir` that the old Toz installer wrote. A file counts as
/// written by Toz only when its hash matches the install manifest in `dir`; if any existing
/// file differs, none is removed. Returns the existing files that were kept.
pub fn retire_owned_files(dir: &Path, rels: &[&str]) -> Result<Vec<PathBuf>> {
    let manifest = read_manifest(dir);
    let mut owned = Vec::new();
    let mut kept = Vec::new();
    for rel in rels {
        let path = dir.join(rel);
        let Some(current) = read_optional(&path)? else {
            continue;
        };
        if manifest
            .get(*rel)
            .is_some_and(|hash| *hash == toz_core::content_hash(current.as_bytes()))
        {
            owned.push(path);
        } else {
            kept.push(path);
        }
    }
    if !kept.is_empty() {
        return Ok(kept);
    }
    for path in owned {
        std::fs::remove_file(&path).with_context(|| format!("removing {}", path.display()))?;
        prune_empty_dirs(path.parent(), dir);
    }
    remove_manifests(dir);
    Ok(kept)
}

/// Strip Toz's hook entries from `dir/hooks.json` and its instruction block from
/// `dir/AGENTS.md` (a Codex home), keeping everything else.
pub fn retire_codex_files(dir: &Path) -> Result<()> {
    strip_file(&dir.join("hooks.json"), strip_hooks, false)?;
    strip_file(&dir.join("AGENTS.md"), |text| Ok(strip_block(text)), true)?;
    remove_manifests(dir);
    Ok(())
}

fn read_optional(path: &Path) -> Result<Option<String>> {
    match std::fs::read_to_string(path) {
        Ok(text) => Ok(Some(text)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error).with_context(|| format!("reading {}", path.display())),
    }
}

fn read_manifest(dir: &Path) -> BTreeMap<String, String> {
    MANIFESTS
        .iter()
        .find_map(|name| std::fs::read_to_string(dir.join(name)).ok())
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|doc| doc.get("files").cloned())
        .and_then(|files| serde_json::from_value(files).ok())
        .unwrap_or_default()
}

fn remove_manifests(dir: &Path) {
    for name in MANIFESTS {
        let _ = std::fs::remove_file(dir.join(name));
    }
}

/// Rewrite the file at `path` without Toz's part; delete it when nothing else is left.
/// `clear_symlink` empties a symlink's target instead of deleting the link.
fn strip_file(
    path: &Path,
    strip: impl Fn(&str) -> Result<String>,
    clear_symlink: bool,
) -> Result<()> {
    let Ok(current) = std::fs::read_to_string(path) else {
        return Ok(());
    };
    let stripped = strip(&current)?;
    if stripped == current {
        return Ok(());
    }
    let write = |text: &str| {
        std::fs::write(path, text).with_context(|| format!("writing {}", path.display()))
    };
    if !stripped.trim().is_empty() {
        return write(&stripped);
    }
    let is_symlink = std::fs::symlink_metadata(path)
        .map(|metadata| metadata.file_type().is_symlink())
        .unwrap_or(false);
    if clear_symlink && is_symlink {
        return write("");
    }
    std::fs::remove_file(path).with_context(|| format!("removing {}", path.display()))
}

fn prune_empty_dirs(mut cur: Option<&Path>, stop: &Path) {
    while let Some(d) = cur {
        if d == stop || !d.starts_with(stop) {
            break;
        }
        if std::fs::remove_dir(d).is_err() {
            break;
        }
        cur = d.parent();
    }
}

/// Remove toz's entries from a hooks file; returns "" when no hooks remain at all.
/// An event holding an owned command in a group or hook the installer did not
/// write is left whole: the user edited it.
fn strip_hooks(current: &str) -> Result<String> {
    let doc: Value =
        serde_json::from_str(current).context("existing hooks.json is not valid JSON")?;
    let Some(events) = doc["hooks"].as_object() else {
        return Ok(current.to_string());
    };
    let event_names: Vec<String> = events
        .iter()
        .filter(|(_, entries)| entries.is_array())
        .map(|(event, _)| event.clone())
        .collect();
    let mut updated = current.to_owned();
    let mut changed = false;
    for event in event_names {
        if !owned_groups_are_pristine(&event, &doc["hooks"][&event]) {
            continue;
        }
        let (text, removed) =
            json_order::remove_matching_commands(&updated, &event, is_owned_hook_command)?;
        if !removed.is_empty() {
            updated = text;
            changed = true;
        }
    }
    if !changed {
        return Ok(current.to_string());
    }
    let doc: Value = serde_json::from_str(&updated)?;
    let only_hooks = doc.as_object().map(|o| o.len() == 1).unwrap_or(false);
    if only_hooks
        && doc["hooks"]
            .as_object()
            .map(|o| o.is_empty())
            .unwrap_or(false)
    {
        return Ok(String::new());
    }
    Ok(updated)
}

/// True when every owned command in `groups` is the hook the installer wrote
/// for `event`, in a group with only its keys (foreign sibling hooks may share
/// the group). Every shipped Codex `hooks.json` wrote `PostToolUse` as matcher
/// `*` with timeout 30 and `SessionStart` with no matcher and timeout 5.
fn owned_groups_are_pristine(event: &str, groups: &Value) -> bool {
    let owned = |hook: &Value| hook["command"].as_str().is_some_and(is_owned_hook_command);
    let (matcher, timeout) = match event {
        "PostToolUse" => (Some("*"), 30),
        "SessionStart" => (None, 5),
        _ => return !groups_hold_owned_hook(groups, owned),
    };
    let keys_within = |value: &Value, allowed: &[&str]| {
        value
            .as_object()
            .is_some_and(|fields| fields.keys().all(|key| allowed.contains(&key.as_str())))
    };
    groups.as_array().into_iter().flatten().all(|group| {
        let hooks = group["hooks"].as_array().map_or(&[][..], Vec::as_slice);
        if owned(group) {
            return false;
        }
        if !hooks.iter().any(owned) {
            return true;
        }
        keys_within(group, &["matcher", "hooks"])
            && group.get("matcher").and_then(Value::as_str) == matcher
            && hooks.iter().filter(|hook| owned(hook)).all(|hook| {
                keys_within(hook, &["type", "command", "timeout"])
                    && hook["command"]
                        .as_str()
                        .is_some_and(|command| is_shipped_codex_command(event, command))
                    && hook["type"] == "command"
                    && hook["timeout"] == timeout
            })
    })
}

fn groups_hold_owned_hook(groups: &Value, owned: impl Fn(&Value) -> bool) -> bool {
    groups.as_array().into_iter().flatten().any(|group| {
        owned(group)
            || group["hooks"]
                .as_array()
                .is_some_and(|hooks| hooks.iter().any(&owned))
    })
}

/// Remove the toz block from a markdown file while preserving the surrounding text.
fn strip_block(current: &str) -> String {
    const LEGACY_START: &str = "<!-- toz:start -->";
    const LEGACY_END: &str = "<!-- toz:end -->";

    let start = [BLOCK_START, LEGACY_START]
        .into_iter()
        .filter_map(|marker| current.find(marker).map(|start| (start, marker.len())))
        .min_by_key(|(start, _)| *start);
    let Some((start, start_len)) = start else {
        return current.to_string();
    };

    let after_start = start + start_len;
    let end = [BLOCK_END, LEGACY_END]
        .into_iter()
        .filter_map(|marker| {
            current[after_start..]
                .find(marker)
                .map(|relative| (after_start + relative, marker.len()))
        })
        .min_by_key(|(end, _)| *end);
    let Some((end, end_len)) = end else {
        return current.to_string();
    };

    let prefix = &current[..start];
    let suffix = &current[end + end_len..];
    // Remove separator newlines while preserving all other surrounding bytes.
    let head = prefix.trim_end_matches('\n');
    let tail = suffix.trim_start_matches('\n');
    if head.is_empty() {
        tail.to_string()
    } else if tail.is_empty() {
        format!("{head}\n")
    } else {
        format!("{head}\n\n{tail}")
    }
}

/// The words after `toz`, `varde-toz` or `varde run` and an optional
/// `--fallback-dir <dir>`, or `None` when `command` does not start that way.
fn toz_command_args(command: &str) -> Option<Vec<String>> {
    let words = shell_words(command)?;
    let exe = words.first()?;
    let executable = Path::new(exe).file_name().and_then(|f| f.to_str());
    if !matches!(executable, Some("toz" | "varde-toz" | "varde")) {
        return None;
    }
    let mut args = &words[1..];
    if executable == Some("varde") {
        if args.first().is_some_and(|word| word == "run") {
            args = &args[1..];
        } else if args.first().is_some_and(|word| word == "--fallback-dir") {
            return None;
        }
    }
    if args.first().is_some_and(|word| word == "--fallback-dir") && args.len() >= 2 {
        args = &args[2..];
    }
    Some(args.to_vec())
}

/// True when `command` is exactly what the Codex asset shipped for `event`.
fn is_shipped_codex_command(event: &str, command: &str) -> bool {
    let Some(args) = toz_command_args(command) else {
        return false;
    };
    let args: Vec<&str> = args.iter().map(String::as_str).collect();
    match event {
        "PostToolUse" => args == ["capture", "--hook", "--harness", "codex"],
        "SessionStart" => args == ["note", "--harness", "codex"],
        _ => false,
    }
}

fn is_owned_hook_command(command: &str) -> bool {
    let Some(args) = toz_command_args(command) else {
        return false;
    };
    matches!(
        args.as_slice(),
        [note, harness_flag, harness]
            if note == "note"
                && harness_flag == "--harness"
                && matches!(harness.as_str(), "claude-code" | "codex")
    ) || matches!(args.as_slice(), [capture, hook] if capture == "capture" && hook == "--hook")
        || matches!(
            args.as_slice(),
            [capture, hook, harness_flag, harness]
                if capture == "capture"
                    && hook == "--hook"
                    && harness_flag == "--harness"
                    && harness == "codex"
        )
}

/// Parse enough POSIX shell syntax to identify commands rendered by our hook templates.
fn shell_words(command: &str) -> Option<Vec<String>> {
    let mut words = Vec::new();
    let mut word = String::new();
    let mut chars = command.chars().peekable();
    let mut quote = None;
    let mut started = false;
    while let Some(ch) = chars.next() {
        match quote {
            Some('\'') if ch == '\'' => quote = None,
            Some('"') if ch == '"' => quote = None,
            Some('"') if ch == '\\' => {
                word.push(chars.next()?);
                started = true;
            }
            Some(_) => {
                word.push(ch);
                started = true;
            }
            None if ch == '\'' || ch == '"' => {
                quote = Some(ch);
                started = true;
            }
            None if ch == '\\' => {
                word.push(chars.next()?);
                started = true;
            }
            None if ch.is_whitespace() => {
                if started {
                    words.push(std::mem::take(&mut word));
                    started = false;
                }
            }
            None => {
                word.push(ch);
                started = true;
            }
        }
    }
    if quote.is_some() {
        return None;
    }
    if started {
        words.push(word);
    }
    Some(words)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const CODEX_HOOKS: &str = r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"varde capture --hook --harness codex","timeout":30}]}]}}"#;

    fn write(path: &Path, text: &str) {
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, text).unwrap();
    }

    fn write_manifest(dir: &Path, files: &[(&str, &str)]) {
        let hashes: BTreeMap<_, _> = files
            .iter()
            .map(|(rel, text)| (rel.to_string(), toz_core::content_hash(text.as_bytes())))
            .collect();
        write(
            &dir.join(MANIFESTS[0]),
            &json!({"version": 1, "files": hashes}).to_string(),
        );
    }

    #[test]
    fn owned_files_are_removed_with_their_manifest() {
        let dir = tempfile::tempdir().unwrap();
        write(&dir.path().join("a/one.ts"), "shim");
        write(&dir.path().join("b/two.ts"), "shim");
        write(&dir.path().join("a/foreign.ts"), "foreign");
        write_manifest(dir.path(), &[("a/one.ts", "shim"), ("b/two.ts", "shim")]);
        let kept =
            retire_owned_files(dir.path(), &["a/one.ts", "b/two.ts", "c/absent.ts"]).unwrap();
        assert!(kept.is_empty());
        assert!(!dir.path().join("a/one.ts").exists());
        assert!(!dir.path().join("b").exists());
        assert!(!dir.path().join(MANIFESTS[0]).exists());
        assert!(dir.path().join("a/foreign.ts").exists());
    }

    #[test]
    fn an_edited_file_keeps_every_file() {
        let dir = tempfile::tempdir().unwrap();
        write(&dir.path().join("a/one.ts"), "shim");
        write(&dir.path().join("a/two.ts"), "edited");
        write_manifest(dir.path(), &[("a/one.ts", "shim"), ("a/two.ts", "shim")]);
        let kept = retire_owned_files(dir.path(), &["a/one.ts", "a/two.ts"]).unwrap();
        assert_eq!(kept, vec![dir.path().join("a/two.ts")]);
        assert!(dir.path().join("a/one.ts").exists());
        assert!(dir.path().join(MANIFESTS[0]).exists());
    }

    #[test]
    fn a_file_without_a_manifest_entry_is_kept() {
        let dir = tempfile::tempdir().unwrap();
        write(&dir.path().join("a/one.ts"), "shim");
        assert_eq!(
            retire_owned_files(dir.path(), &["a/one.ts"]).unwrap().len(),
            1
        );
    }

    #[test]
    fn the_old_manifest_name_is_read() {
        let dir = tempfile::tempdir().unwrap();
        write(&dir.path().join("a/one.ts"), "shim");
        write(
            &dir.path().join(MANIFESTS[1]),
            &json!({"version": 1, "files": {"a/one.ts": toz_core::content_hash(b"shim")}})
                .to_string(),
        );
        assert!(retire_owned_files(dir.path(), &["a/one.ts"])
            .unwrap()
            .is_empty());
        assert!(!dir.path().join("a/one.ts").exists());
    }

    #[test]
    fn codex_hooks_and_block_are_stripped_in_place() {
        let dir = tempfile::tempdir().unwrap();
        write(&dir.path().join("hooks.json"), CODEX_HOOKS);
        write(
            &dir.path().join("AGENTS.md"),
            "# Mine\n\n<!-- varde-toz:start -->\nnote\n<!-- varde-toz:end -->\n",
        );
        retire_codex_files(dir.path()).unwrap();
        assert!(!dir.path().join("hooks.json").exists());
        assert_eq!(
            std::fs::read_to_string(dir.path().join("AGENTS.md")).unwrap(),
            "# Mine\n"
        );
    }

    #[cfg(unix)]
    #[test]
    fn codex_block_is_stripped_through_an_agents_symlink() {
        let dir = tempfile::tempdir().unwrap();
        let target = dir.path().join("shared/AGENTS.md");
        let link = dir.path().join("codex/AGENTS.md");
        write(
            &target,
            "# Rules  \n\n<!-- varde-toz:start -->\nold\n<!-- varde-toz:end -->\n\nKeep.  \n",
        );
        std::fs::create_dir_all(link.parent().unwrap()).unwrap();
        std::os::unix::fs::symlink(&target, &link).unwrap();
        retire_codex_files(link.parent().unwrap()).unwrap();
        assert!(std::fs::symlink_metadata(&link)
            .unwrap()
            .file_type()
            .is_symlink());
        assert_eq!(
            std::fs::read_to_string(target).unwrap(),
            "# Rules  \n\nKeep.  \n"
        );
    }

    #[test]
    fn strip_hooks_keeps_foreign_entries() {
        let foreign =
            r#"{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo foreign"}]}]}}"#;
        let mut doc: Value = serde_json::from_str(foreign).unwrap();
        doc["hooks"]["PostToolUse"] =
            serde_json::from_str::<Value>(CODEX_HOOKS).unwrap()["hooks"]["PostToolUse"].clone();
        let stripped = strip_hooks(&doc.to_string()).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&stripped).unwrap(),
            serde_json::from_str::<Value>(foreign).unwrap()
        );
        assert_eq!(strip_hooks(CODEX_HOOKS).unwrap(), "");
    }

    #[test]
    fn edited_toz_entries_are_kept_whole() {
        for existing in [
            // a missing or empty matcher widens or changes the scope
            r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30}]}]}}"#,
            r#"{"hooks":{"PostToolUse":[{"matcher":"","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30}]}]}}"#,
            // a missing timeout, or the capture timeout on a note
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex"}]}]}}"#,
            r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"toz note --harness codex","timeout":20}]}]}}"#,
            // a matcher on SessionStart, which the installer never wrote
            r#"{"hooks":{"SessionStart":[{"matcher":"*","hooks":[{"type":"command","command":"toz note --harness codex","timeout":5}]}]}}"#,
            // another matcher
            r#"{"hooks":{"PostToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"toz capture --hook --harness codex"},{"type":"command","command":"echo foreign"}]}]}}"#,
            // a capture without the Codex harness, a note on the capture event,
            // and a Claude note on SessionStart: owned shapes the asset never wrote
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook","timeout":30}]}]}}"#,
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz note --harness codex","timeout":30}]}]}}"#,
            r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"toz note --harness claude-code","timeout":5}]}]}}"#,
            // a changed timeout
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":99}]}]}}"#,
            // an extra key on the hook or the group
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30,"async":true}]}]}}"#,
            r#"{"hooks":{"PostToolUse":[{"matcher":"*","disabled":true,"hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30}]}]}}"#,
        ] {
            assert_eq!(strip_hooks(existing).unwrap(), existing);
        }
    }

    #[test]
    fn a_foreign_sibling_in_the_group_is_kept_when_the_toz_hook_is_stripped() {
        let existing = r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"toz capture --hook --harness codex","timeout":30},{"type":"command","command":"echo foreign"}]}]}}"#;
        let stripped: Value = serde_json::from_str(&strip_hooks(existing).unwrap()).unwrap();
        assert_eq!(
            stripped["hooks"]["PostToolUse"][0]["hooks"],
            json!([{"type": "command", "command": "echo foreign"}])
        );
    }

    #[test]
    fn the_session_start_note_the_toz_installer_wrote_is_stripped() {
        let written = r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"toz note --harness codex","timeout":5}]}]}}"#;
        assert_eq!(strip_hooks(written).unwrap(), "");
    }

    #[test]
    fn every_shipped_binary_form_is_stripped() {
        for bin in ["toz", "varde-toz", "varde run"] {
            for prefix in ["", "--fallback-dir /tmp/f "] {
                let post = format!(
                    r#"{{"hooks":{{"PostToolUse":[{{"matcher":"*","hooks":[{{"type":"command","command":"{bin} {prefix}capture --hook --harness codex","timeout":30}}]}}]}}}}"#
                );
                let start = format!(
                    r#"{{"hooks":{{"SessionStart":[{{"hooks":[{{"type":"command","command":"{bin} {prefix}note --harness codex","timeout":5}}]}}]}}}}"#
                );
                assert_eq!(strip_hooks(&post).unwrap(), "", "{post}");
                assert_eq!(strip_hooks(&start).unwrap(), "", "{start}");
            }
        }
        // The last installer rendered {{TOZ_BIN_SHELL}} as the `varde` executable path with no `run` (see 61a833d0).
        let post = r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"/path/varde capture --hook --harness codex","timeout":30}]}]}}"#;
        let start = r#"{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"/path/varde note --harness codex","timeout":5}]}]}}"#;
        assert_eq!(strip_hooks(post).unwrap(), "", "{post}");
        assert_eq!(strip_hooks(start).unwrap(), "", "{start}");
    }

    #[test]
    fn the_entry_the_toz_installer_wrote_is_stripped() {
        let written = r#"{"hooks":{"PostToolUse":[{"matcher":"*","hooks":[{"type":"command","command":"'/opt/bin/toz' capture --hook --harness codex","timeout":30}]}]}}"#;
        assert_eq!(strip_hooks(written).unwrap(), "");
    }

    #[test]
    fn strip_block_removes_current_and_legacy_markers() {
        let old = "before\n\n<!-- toz:start -->\nold\n<!-- toz:end -->\nafter\n";
        assert_eq!(strip_block(old), "before\n\nafter\n");
        let block = "<!-- varde-toz:start -->\nnew\n<!-- varde-toz:end -->";
        assert_eq!(
            strip_block(&format!("top\n\n{block}\n\nbottom\n")),
            "top\n\nbottom\n"
        );
        assert_eq!(strip_block(&format!("{block}\n")), "");
    }

    #[test]
    fn hook_matching_requires_exact_owned_command() {
        for command in [
            "toz-helper capture --hook",
            "/tmp/toz-other note --harness codex",
            "toz query --handle abc",
            "toz capture something",
            "toz capture --hook ; echo foreign",
            "toz note --harness foreign",
            "varde --fallback-dir /x note --harness codex",
            "varde run capture something",
        ] {
            assert!(!is_owned_hook_command(command), "{command}");
        }
        for command in [
            "varde run capture --hook",
            "varde run --fallback-dir /x note --harness codex",
            "toz capture --hook --harness codex",
            "varde-toz capture --hook --harness codex",
            "'/tmp/a path/toz' --fallback-dir '/tmp/x' note --harness codex",
        ] {
            assert!(is_owned_hook_command(command), "{command}");
        }
    }
}
