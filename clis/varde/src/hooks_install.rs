//! `varde setup hooks install|remove`: the unified hook installer.
//!
//! Claude and Codex get one SessionStart, PostToolUse and UserPromptSubmit
//! entry merged into their JSON hook config; OpenCode and Pi get one whole-file
//! plugin. Both call `varde hook <event> --harness <h>`. OpenCode has no
//! per-user-prompt hook that can add context, so its UserPromptSubmit event is
//! reported unsupported.
//!
//! Ownership: a JSON entry is Varde's when its command runs `varde` (or the
//! legacy `varde-workflow`) with `hook <event>`. It is the unified entry when
//! it is exactly the group and hook this installer writes (any `varde` path);
//! any other Varde entry for the event, including one behind a wrapper such as
//! `env`, is edited. A plugin file is Varde's when its first
//! line records the hash of the rest. An edited entry or file is kept, reported
//! with its fix, and replaced or removed only with `--force`.

use clap::{Arg, ArgAction, Command};
use serde_json::Value;
use std::ffi::OsString;
use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{ExitCode, Stdio};
use std::time::{Duration, Instant};
use varde_core::json_order::{self, RemoveOptions};

const HARNESSES: [&str; 4] = ["claude", "codex", "opencode", "pi"];
const FEATURES: [&str; 5] = ["change", "toz", "learn", "code", "knowledge"];
const PLACEHOLDER: &str = "\"{{VARDE_BIN}}\"";
const MARKER: &str = "// varde-managed: fnv64=";
const OPENCODE_V2: &str = include_str!("../assets/hooks/opencode.ts");
const OPENCODE_V1: &str = include_str!("../assets/hooks/opencode-v1.ts");
const PI: &str = include_str!("../assets/hooks/pi.ts");
const OPENCODE_PROBE_LIMIT: Duration = Duration::from_secs(2);
const CODEX_NOTICE: &str =
    "codex: needs `hooks = true` in ~/.codex/config.toml and will ask you to trust the hooks";

struct Event {
    key: &'static str,
    arg: &'static str,
    matcher: Option<&'static str>,
    timeout: u64,
}

const EVENTS: [Event; 3] = [
    Event {
        key: "SessionStart",
        arg: "session-start",
        matcher: None,
        timeout: 20,
    },
    Event {
        key: "PostToolUse",
        arg: "post-tool-use",
        matcher: Some("*"),
        timeout: 30,
    },
    Event {
        key: "UserPromptSubmit",
        arg: "user-prompt-submit",
        matcher: None,
        timeout: 20,
    },
];

/// Why OpenCode gets no `UserPromptSubmit` entry: its per-user-prompt hooks only
/// rewrite the prompt, and the hooks that add context run on every model call.
const OPENCODE_UNSUPPORTED: &str =
    "no per-user-prompt hook adds context; the context hook runs on every model call";

/// A harness with no working hook for `event_key`, and why.
fn unsupported_event(harness: &str, event_key: &str) -> Option<&'static str> {
    (harness == "opencode" && event_key == "UserPromptSubmit").then_some(OPENCODE_UNSUPPORTED)
}

/// A hook document with one event whose field order the merge preserves.
fn entry_json(event: &Event, command: &str) -> String {
    let matcher = event
        .matcher
        .map_or(String::new(), |m| format!("\"matcher\": \"{m}\", "));
    let command = Value::String(command.to_owned());
    let timeout = event.timeout;
    format!(
        "{{\"hooks\": {{\"{key}\": [{{{matcher}\"hooks\": [{{\"type\": \"command\", \"command\": {command}, \"timeout\": {timeout}}}]}}]}}}}",
        key = event.key
    )
}

/// The clap command for `install` or `remove`.
pub fn command(action: &'static str) -> Command {
    let about = if action == "install" {
        "Install Varde hooks for Claude, Codex, OpenCode and Pi; use --harness to select targets"
    } else {
        "Remove the Varde hooks installed by `setup hooks install`"
    };
    Command::new(action)
        .about(about)
        .arg(
            Arg::new("harness")
                .long("harness")
                .value_name("HARNESS")
                .action(ArgAction::Append)
                .value_parser(HARNESSES)
                .help("Harness to change; repeat for several (default: all)"),
        )
        .arg(
            Arg::new("skip-event")
                .long("skip-event")
                .value_name("EVENT")
                .action(ArgAction::Append)
                .value_parser(EVENTS.map(|event| event.key))
                .hide(true)
                .help("Leave this event alone (used by `varde setup sync`)"),
        )
        .arg(
            Arg::new("features")
                .long("features")
                .value_name("FEATURES")
                .value_delimiter(',')
                .value_parser(FEATURES)
                .action(ArgAction::Append)
                .help("Features to install (change,toz,learn,code,knowledge; default: all)"),
        )
        .arg(
            Arg::new("force")
                .long("force")
                .action(ArgAction::SetTrue)
                .help("Replace or remove entries and files you edited"),
        )
        .after_help("If sandbox denial blocks a target, other selected targets may already be installed. Retry the denied target. Watcher registration may time out; check setup doctor afterward.")
}

/// `args[0]` is `install` or `remove`.
pub fn run(args: Vec<OsString>) -> ExitCode {
    let action = if args[0] == "remove" {
        "remove"
    } else {
        "install"
    };
    let mut argv = vec![OsString::from(format!("varde setup hooks {action}"))];
    argv.extend(args.into_iter().skip(1));
    let matches = match command(action).try_get_matches_from(argv) {
        Ok(matches) => matches,
        Err(error) => error.exit(),
    };
    let mut harnesses: Vec<&str> = matches
        .get_many::<String>("harness")
        .map(|values| values.map(String::as_str).collect())
        .unwrap_or_else(|| HARNESSES.to_vec());
    let mut seen = Vec::new();
    harnesses.retain(|harness| {
        let new = !seen.contains(harness);
        seen.push(*harness);
        new
    });
    let force = matches.get_flag("force");
    let skip: Vec<&str> = matches
        .get_many::<String>("skip-event")
        .map(|values| values.map(String::as_str).collect())
        .unwrap_or_default();
    let features = matches
        .get_many::<String>("features")
        .map(|values| values.map(String::as_str).collect::<Vec<_>>());
    match apply(
        action == "install",
        &harnesses,
        force,
        &skip,
        features.as_deref(),
    ) {
        Ok(()) => ExitCode::SUCCESS,
        Err(message) => {
            eprintln!("varde setup hooks {action}: {message}");
            ExitCode::FAILURE
        }
    }
}

fn apply(
    install: bool,
    harnesses: &[&str],
    force: bool,
    skip: &[&str],
    features: Option<&[&str]>,
) -> Result<(), String> {
    let home = home_dir()?;
    let exe = std::env::current_exe()
        .map_err(|error| format!("locating the running varde: {error}"))?
        .to_string_lossy()
        .into_owned();
    for harness in harnesses {
        let disabled = disabled_events(features);
        let mut lines = match *harness {
            "claude" => json_hooks(
                &home.join(".claude/settings.json"),
                "claude",
                &exe,
                install,
                force,
                skip,
                if install { &disabled } else { &[] },
            ),
            "codex" => json_hooks(
                &home.join(".codex/hooks.json"),
                "codex",
                &exe,
                install,
                force,
                skip,
                if install { &disabled } else { &[] },
            ),
            "opencode" => {
                let template = if install && opencode_major().is_some_and(|major| major < 2) {
                    OPENCODE_V1
                } else {
                    OPENCODE_V2
                };
                let path = config_home(&home).join("opencode/plugin/varde.ts");
                plugin_file(&path, harness, template, &exe, install, force, features)
            }
            _ => {
                let path = pi_agent_dir(&home).join("extensions/varde.ts");
                plugin_file(&path, harness, PI, &exe, install, force, features)
            }
        }?;
        if install {
            if let Some(reason) = unsupported_event(harness, "UserPromptSubmit") {
                lines.push(format!(
                    "{harness}: user-prompt-submit unsupported ({reason})"
                ));
            }
        }
        for line in lines {
            println!("{line}");
        }
        if install && *harness == "codex" {
            println!("{CODEX_NOTICE}");
        }
    }
    Ok(())
}

fn disabled_events(features: Option<&[&str]>) -> Vec<&'static str> {
    let Some(features) = features else {
        return Vec::new();
    };
    [
        (
            "SessionStart",
            features.contains(&"code") || features.contains(&"toz"),
        ),
        (
            "PostToolUse",
            features.contains(&"toz")
                || features.contains(&"knowledge")
                || features.contains(&"change"),
        ),
        ("UserPromptSubmit", features.contains(&"change")),
    ]
    .into_iter()
    .filter_map(|(event, enabled)| (!enabled).then_some(event))
    .collect()
}

// ---- JSON hook files (Claude, Codex) ----

/// One Varde command found under an event.
struct Found {
    command: String,
    unified: bool,
}

fn json_hooks(
    path: &Path,
    harness: &str,
    exe: &str,
    install: bool,
    force: bool,
    skip: &[&str],
    disabled: &[&str],
) -> Result<Vec<String>, String> {
    let original = match fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound && !install => {
            return Ok(vec![format!(
                "{harness}: {} not found, nothing to remove",
                path.display()
            )]);
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => "{}".to_owned(),
        Err(error) => return Err(format!("reading {}: {error}", path.display())),
    };
    let doc: Value = serde_json::from_str(&original)
        .map_err(|error| format!("{} is not valid JSON: {error}", path.display()))?;
    if !doc.is_object() || doc.get("hooks").is_some_and(|hooks| !hooks.is_object()) {
        return Err(format!("{} is not a hook config object", path.display()));
    }
    let mut text = original.clone();
    let mut lines = Vec::new();
    for event in &EVENTS {
        if skip.contains(&event.key) {
            lines.push(format!(
                "{harness}: skipped {} in {}",
                event.key,
                path.display()
            ));
            continue;
        }
        let found = find_entries(&doc, event, harness, exe);
        if disabled.contains(&event.key) {
            let managed = found
                .iter()
                .filter(|entry| entry.unified)
                .map(|entry| entry.command.as_str())
                .collect::<Vec<_>>();
            if !managed.is_empty() {
                let owned = |command: &str| managed.contains(&command);
                text = json_order::remove_matching_commands_with_options(
                    &text,
                    event.key,
                    owned,
                    RemoveOptions {
                        prune_empty_hooks: true,
                    },
                )
                .map_err(|error| format!("editing {}: {error}", path.display()))?
                .0;
                lines.push(format!(
                    "{harness}: removed {} in {}",
                    event.key,
                    path.display()
                ));
            }
            continue;
        }
        let edited = found.iter().find(|entry| !entry.unified);
        if let Some(edited) = edited
            && !force
        {
            lines.push(format!(
                "{harness}: blocked, {} has an edited Varde {} entry ({}); kept. Fix: varde setup hooks {} --harness {harness} --force",
                path.display(),
                event.key,
                edited.command,
                if install { "install" } else { "remove" },
            ));
            continue;
        }
        let command = hook_command(exe, event, harness);
        let current = found.len() == 1 && found[0].unified && found[0].command == command;
        let owned = |text: &str| varde_words(text, event).is_some();
        let result = if install && current {
            continue;
        } else if install {
            let document = entry_json(event, &command);
            json_order::replace_owned_entries_from_json(
                &text, event.key, owned, &document, event.key,
            )
        } else if found.is_empty() {
            continue;
        } else {
            let options = RemoveOptions {
                prune_empty_hooks: true,
            };
            json_order::remove_matching_commands_with_options(&text, event.key, owned, options)
        };
        text = result
            .map_err(|error| format!("editing {}: {error}", path.display()))?
            .0;
        let verb = if install { "installed" } else { "removed" };
        lines.push(format!(
            "{harness}: {verb} {} in {}",
            event.key,
            path.display()
        ));
    }
    if text != original {
        write_atomic(path, &text)?;
    } else if lines.is_empty() {
        lines.push(format!("{harness}: {} is up to date", path.display()));
    }
    Ok(lines)
}

// ---- `varde setup doctor` ----

/// The installation state of every harness integration, for `setup doctor`.
pub fn doctor_section() -> varde_toz::DoctorSection {
    let home = home_dir().unwrap_or_default();
    let exe = std::env::current_exe()
        .map(|path| path.to_string_lossy().into_owned())
        .unwrap_or_default();
    let mut entries = Vec::new();
    for harness in HARNESSES {
        let (path, targets) = match harness {
            "claude" => (
                home.join(".claude/settings.json"),
                json_states(harness, &exe, &home),
            ),
            "codex" => (
                home.join(".codex/hooks.json"),
                json_states(harness, &exe, &home),
            ),
            "opencode" => (
                config_home(&home).join("opencode/plugin/varde.ts"),
                vec![(
                    "plugin",
                    plugin_state(&config_home(&home).join("opencode/plugin/varde.ts")),
                )],
            ),
            _ => (
                pi_agent_dir(&home).join("extensions/varde.ts"),
                vec![(
                    "plugin",
                    plugin_state(&pi_agent_dir(&home).join("extensions/varde.ts")),
                )],
            ),
        };
        for (target, state) in targets {
            entries.push(doctor_entry(harness, target, state, &path));
        }
        if let Some(reason) = unsupported_event(harness, "UserPromptSubmit") {
            entries.push(unsupported_entry(
                harness,
                "user-prompt-submit",
                reason,
                &path,
            ));
        }
    }
    varde_toz::DoctorSection {
        key: "hooks",
        entries,
    }
}

#[derive(Clone, Copy, PartialEq)]
enum State {
    Current,
    Missing,
    Edited,
}

impl State {
    fn name(self) -> &'static str {
        match self {
            State::Current => "current",
            State::Missing => "missing",
            State::Edited => "edited",
        }
    }
}

fn doctor_entry(harness: &str, target: &str, state: State, path: &Path) -> varde_toz::DoctorEntry {
    let name = state.name();
    let mut json = serde_json::json!({
        "harness": harness,
        "target": target,
        "state": name,
        "path": path.display().to_string(),
    });
    let mut line = format!("hook {harness} {target}: {name} ({})", path.display());
    if state != State::Current {
        let fix = format!(
            "varde setup hooks install --harness {harness}{}",
            if state == State::Edited {
                " --force"
            } else {
                ""
            }
        );
        line.push_str(&format!("; fix: {fix}"));
        json["fix"] = Value::String(fix);
    }
    varde_toz::DoctorEntry { line, json }
}

/// A doctor entry for an event a harness cannot support, with the reason.
fn unsupported_entry(
    harness: &str,
    target: &str,
    reason: &str,
    path: &Path,
) -> varde_toz::DoctorEntry {
    varde_toz::DoctorEntry {
        line: format!("hook {harness} {target}: unsupported ({reason})"),
        json: serde_json::json!({
            "harness": harness,
            "target": target,
            "state": "unsupported",
            "reason": reason,
            "path": path.display().to_string(),
        }),
    }
}

/// Per-event state of a Claude or Codex hook file; a file that cannot be read
/// as a hook config counts as edited.
fn json_states(harness: &'static str, exe: &str, home: &Path) -> Vec<(&'static str, State)> {
    let path = home.join(if harness == "claude" {
        ".claude/settings.json"
    } else {
        ".codex/hooks.json"
    });
    let doc = match fs::read_to_string(&path) {
        Ok(text) => serde_json::from_str::<Value>(&text)
            .ok()
            .filter(|doc| doc.is_object() && doc.get("hooks").is_none_or(Value::is_object)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Some(Value::Null),
        Err(_) => None,
    };
    EVENTS
        .iter()
        .map(|event| {
            let state = match &doc {
                None => State::Edited,
                Some(doc) => {
                    let found = find_entries(doc, event, harness, exe);
                    match found.as_slice() {
                        [] => State::Missing,
                        [only] if only.unified => State::Current,
                        _ => State::Edited,
                    }
                }
            };
            (event.key, state)
        })
        .collect()
}

fn plugin_state(path: &Path) -> State {
    match fs::read_to_string(path) {
        Ok(text) if is_unedited(&text) => State::Current,
        Ok(_) => State::Edited,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => State::Missing,
        Err(_) => State::Edited,
    }
}

fn hook_command(exe: &str, event: &Event, harness: &str) -> String {
    format!(
        "{} hook {} --harness {harness}",
        shell_quote(exe),
        event.arg
    )
}

/// Every Varde command for `event` in the parsed config, flat or in a group.
fn find_entries(doc: &Value, event: &Event, harness: &str, exe: &str) -> Vec<Found> {
    let groups = doc["hooks"][event.key]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    let mut found = Vec::new();
    for group in groups {
        let nested = group["hooks"].as_array().map_or(&[][..], Vec::as_slice);
        let direct = std::iter::once(group).filter(|group| group.get("command").is_some());
        let group_shape = is_unified_group(group, event);
        for hook in nested.iter().chain(direct) {
            let Some(command) = hook["command"].as_str() else {
                continue;
            };
            let Some(words) = varde_words(command, event) else {
                continue;
            };
            let unified = group_shape
                && hook["type"] == "command"
                && hook["timeout"] == event.timeout
                && hook.as_object().is_some_and(|fields| fields.len() == 3)
                && is_unified_command(&words, event, harness, exe);
            found.push(Found {
                command: command.to_owned(),
                unified,
            });
        }
    }
    found
}

/// A group holding exactly one nested hook, with only the keys (and matcher)
/// the installer writes.
fn is_unified_group(group: &Value, event: &Event) -> bool {
    let keys = 1 + usize::from(event.matcher.is_some());
    group.as_object().is_some_and(|fields| fields.len() == keys)
        && group.get("matcher").and_then(Value::as_str) == event.matcher
        && group["hooks"]
            .as_array()
            .is_some_and(|hooks| hooks.len() == 1)
}

/// The words of `command` when a `varde` (or legacy `varde-workflow`)
/// executable runs `hook <event>`, directly or behind a wrapper such as `env`.
fn varde_words(command: &str, event: &Event) -> Option<Vec<String>> {
    let words = shell_words(command);
    let is_varde = |word: &String| {
        Path::new(word)
            .file_name()
            .is_some_and(|name| name == "varde" || name == "varde-workflow")
    };
    words
        .windows(3)
        .any(|run| is_varde(&run[0]) && run[1] == "hook" && run[2] == event.arg)
        .then_some(words)
}

/// Exactly `<varde> hook <event> --harness <harness>`, with `varde` at any path.
fn is_unified_command(words: &[String], event: &Event, harness: &str, exe: &str) -> bool {
    let is_varde = words[0] == exe
        || Path::new(&words[0])
            .file_name()
            .is_some_and(|name| name == "varde");
    is_varde && words[1..] == ["hook", event.arg, "--harness", harness]
}

// ---- plugin files (OpenCode, Pi) ----

fn plugin_file(
    path: &Path,
    harness: &str,
    template: &str,
    exe: &str,
    install: bool,
    force: bool,
    features: Option<&[&str]>,
) -> Result<Vec<String>, String> {
    let existing = match fs::read_to_string(path) {
        Ok(text) => Some(text),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => None,
        Err(error) => return Err(format!("reading {}: {error}", path.display())),
    };
    let Some(existing) = existing else {
        if !install {
            return Ok(vec![format!(
                "{harness}: {} not found, nothing to remove",
                path.display()
            )]);
        }
        write_atomic(path, &render_plugin(template, exe, features))?;
        return Ok(vec![format!("{harness}: installed {}", path.display())]);
    };
    if !is_unedited(&existing) && !force {
        return Ok(vec![format!(
            "{harness}: blocked, {} was edited or is not a Varde plugin; kept. Fix: varde setup hooks {} --harness {harness} --force",
            path.display(),
            if install { "install" } else { "remove" },
        )]);
    }
    if !install {
        fs::remove_file(path).map_err(|error| format!("removing {}: {error}", path.display()))?;
        return Ok(vec![format!("{harness}: removed {}", path.display())]);
    }
    let desired = render_plugin(template, exe, features);
    if existing == desired {
        return Ok(vec![format!("{harness}: {} is up to date", path.display())]);
    }
    write_atomic(path, &desired)?;
    Ok(vec![format!("{harness}: installed {}", path.display())])
}

/// The template with the binary path filled in, under a hash marker line.
fn render_plugin(template: &str, exe: &str, features: Option<&[&str]>) -> String {
    let bin = Value::String(exe.to_owned()).to_string();
    let body = filter_plugin_features(template, features).replace(PLACEHOLDER, &bin);
    format!("{MARKER}{:016x}\n{body}", fnv64(&body))
}

fn filter_plugin_features(template: &str, features: Option<&[&str]>) -> String {
    let mut include = Vec::new();
    let mut output = Vec::new();
    for line in template.lines() {
        let marker = line.trim().strip_prefix("// VARDE_FEATURE:");
        if let Some(marker) = marker {
            if let Some(name) = marker.strip_suffix(":start") {
                let parent = include.last().copied().unwrap_or(true);
                include.push(parent && plugin_feature_enabled(name, features));
                continue;
            }
            if marker.ends_with(":end") {
                include.pop();
                continue;
            }
        }
        if include.last().copied().unwrap_or(true) {
            output.push(line);
        }
    }
    let mut body = output.join("\n");
    if template.ends_with('\n') {
        body.push('\n');
    }
    body
}

fn plugin_feature_enabled(name: &str, features: Option<&[&str]>) -> bool {
    let Some(features) = features else {
        return true;
    };
    let session_start = features.contains(&"code") || features.contains(&"toz");
    match name {
        "session-start" => session_start,
        "toz" => features.contains(&"toz"),
        "post-tool-use" => {
            features.contains(&"toz")
                || features.contains(&"knowledge")
                || features.contains(&"change")
        }
        "inbox" => features.contains(&"change"),
        "agent-start" => session_start || features.contains(&"change"),
        _ => false,
    }
}

/// True when the first line records the hash of everything after it.
fn is_unedited(text: &str) -> bool {
    let Some((first, body)) = text.split_once('\n') else {
        return false;
    };
    first
        .strip_prefix(MARKER)
        .and_then(|hash| u64::from_str_radix(hash, 16).ok())
        .is_some_and(|hash| hash == fnv64(body))
}

/// FNV-1a: a stable, dependency-free change detector (not a security hash).
fn fnv64(text: &str) -> u64 {
    text.bytes().fold(0xcbf2_9ce4_8422_2325, |hash, byte| {
        (hash ^ u64::from(byte)).wrapping_mul(0x0100_0000_01b3)
    })
}

// ---- paths and files ----

fn home_dir() -> Result<PathBuf, String> {
    match std::env::var_os("HOME") {
        Some(home) if !home.is_empty() => Ok(PathBuf::from(home)),
        _ => Err("HOME is not set".to_owned()),
    }
}

fn config_home(home: &Path) -> PathBuf {
    match std::env::var_os("XDG_CONFIG_HOME") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => home.join(".config"),
    }
}

fn pi_agent_dir(home: &Path) -> PathBuf {
    match std::env::var_os("PI_CODING_AGENT_DIR") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => home.join(".pi/agent"),
    }
}

/// The major version of the installed `opencode`, when it answers within
/// `OPENCODE_PROBE_LIMIT`.
fn opencode_major() -> Option<u64> {
    let mut child = std::process::Command::new("opencode")
        .arg("--version")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    let deadline = Instant::now() + OPENCODE_PROBE_LIMIT;
    while child.try_wait().ok()?.is_none() {
        if Instant::now() >= deadline {
            let _ = child.kill();
            let _ = child.wait();
            return None;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    let mut text = String::new();
    child.stdout.take()?.read_to_string(&mut text).ok()?;
    let token = text
        .split_whitespace()
        .find(|word| word.trim_start_matches('v').contains('.'))?;
    token
        .trim_start_matches('v')
        .split('.')
        .next()?
        .parse()
        .ok()
}

/// Write via a temp file next to the real target and rename. A symlinked path
/// is followed and an existing file keeps its permissions.
fn write_atomic(path: &Path, text: &str) -> Result<(), String> {
    let fail = |error: std::io::Error| format!("writing {}: {error}", path.display());
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(fail)?;
    }
    let target = fs::canonicalize(path).unwrap_or_else(|_| path.to_path_buf());
    let mut temp = target.as_os_str().to_owned();
    temp.push(format!(".varde-tmp-{}", std::process::id()));
    let temp = PathBuf::from(temp);
    fs::write(&temp, text).map_err(fail)?;
    if let Ok(metadata) = fs::metadata(&target) {
        fs::set_permissions(&temp, metadata.permissions()).map_err(fail)?;
    }
    fs::rename(&temp, &target).map_err(fail)
}

fn shell_quote(word: &str) -> String {
    let plain = |c: char| c.is_ascii_alphanumeric() || "/._-+:@".contains(c);
    if word.chars().all(plain) {
        word.to_owned()
    } else {
        format!("'{}'", word.replace('\'', r"'\''"))
    }
}

/// Split a command line on whitespace, honoring quotes and backslash escapes.
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn quoted_command_round_trips() {
        let command = format!(
            "{} hook session-start --harness claude",
            shell_quote("/x/it's here/varde")
        );
        assert_eq!(shell_words(&command)[0], "/x/it's here/varde");
        assert!(varde_words(&command, &EVENTS[0]).is_some());
    }

    #[test]
    fn marker_detects_edits() {
        let text = render_plugin(PI, "/bin/varde", None);
        assert!(is_unedited(&text));
        assert!(!is_unedited(&text.replace("fails open", "fails shut")));
        assert!(!is_unedited(PI));
    }
}
