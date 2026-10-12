//! Retire the per-feature harness integrations in-process, then install the unified hooks
//! through `varde setup hooks install`.

use super::{MigrateEnv, Report, ReportEntry};
use serde_json::Value;
use std::env;
use std::ffi::OsString;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::process::{Command, Output, Stdio};

const SETUP_WARNING: &str = "Varde will not work as designed until its instruction block is installed: agents will not delegate as designed or use captured command output. Install it with `varde setup instructions install --target <file>`. Use one canonical `AGENTS.md` symlinked into each harness.";
const STDERR_LINES: usize = 6;
const WORKFLOW_BIN_PLACEHOLDER: &str = "\"{{VARDE_WORKFLOW_BIN}}\"";
const LEGACY_OPENCODE_SESSION: &str = include_str!("legacy/opencode-varde-session.ts");
const LEGACY_PI_SESSION: &str = include_str!("legacy/pi-varde-session.ts");

struct HarnessPaths {
    id: &'static str,
    install: PathBuf,
    /// Directories the per-feature Toz install wrote under, and the files it owned there.
    toz_dirs: Vec<PathBuf>,
    toz_files: &'static [&'static str],
    /// Files or directories the per-feature Toz install owned, current and old names.
    toz_artifacts: Vec<PathBuf>,
    /// The directory the per-feature code hooks were written under.
    code_dir: PathBuf,
    code_hooks: PathBuf,
    session_hooks: PathBuf,
}

impl HarnessPaths {
    fn resolve(env: &MigrateEnv, id: &str) -> Option<Self> {
        let pi_root = env::var_os("PI_CODING_AGENT_DIR")
            .filter(|path| !path.is_empty())
            .map_or_else(|| env.home.join(".pi/agent"), PathBuf::from);
        let xdg = env
            .xdg_config_home
            .as_deref()
            .unwrap_or_else(|| Path::new(""));
        let config_home = if xdg.as_os_str().is_empty() {
            env.home.join(".config")
        } else {
            xdg.to_path_buf()
        };

        match id {
            "claude" => Some(Self {
                id: "claude",
                install: env.home.join(".claude/skills/varde-toz-hooks"),
                toz_dirs: vec![
                    env.home.join(".claude/skills/varde-toz-hooks"),
                    env.home.join(".claude/skills/toz"),
                ],
                toz_files: &[
                    ".claude-plugin/plugin.json",
                    "hooks/hooks.json",
                    "skills/toz/SKILL.md",
                ],
                toz_artifacts: vec![
                    env.home.join(".claude/skills/toz"),
                    env.home.join(".claude/skills/varde-toz-hooks"),
                ],
                code_dir: env.home.join(".claude"),
                code_hooks: env.home.join(".claude/settings.json"),
                session_hooks: env.home.join(".claude/settings.json"),
            }),
            "codex" => Some(Self {
                id: "codex",
                install: env.home.join(".codex/hooks.json"),
                toz_dirs: vec![env.home.join(".codex")],
                toz_files: &[],
                toz_artifacts: Vec::new(),
                code_dir: env.home.join(".codex"),
                code_hooks: env.home.join(".codex/config.toml"),
                session_hooks: env.home.join(".codex/hooks.json"),
            }),
            "opencode" => Some(Self {
                id: "opencode",
                install: config_home.join("opencode/plugin/varde-toz.ts"),
                toz_dirs: vec![config_home.join("opencode")],
                toz_files: &["plugin/varde-toz.ts", "plugin/toz.ts"],
                toz_artifacts: vec![
                    config_home.join("opencode/plugin/toz.ts"),
                    config_home.join("opencode/plugin/varde-toz.ts"),
                ],
                code_dir: env.home.join(".config/opencode"),
                code_hooks: env
                    .home
                    .join(".config/opencode/plugin/varde-code-nav-map.js"),
                session_hooks: config_home.join("opencode/plugin/varde-session.ts"),
            }),
            "pi" => Some(Self {
                id: "pi",
                install: pi_root.join("extensions/varde-toz.ts"),
                toz_dirs: vec![pi_root.clone()],
                toz_files: &["extensions/varde-toz.ts", "extensions/toz.ts"],
                toz_artifacts: vec![
                    pi_root.join("extensions/toz.ts"),
                    pi_root.join("extensions/varde-toz.ts"),
                ],
                code_dir: pi_root.join("extensions"),
                code_hooks: pi_root.join("extensions/pi-extension.js"),
                session_hooks: pi_root.join("extensions/varde-session.ts"),
            }),
            _ => None,
        }
    }
}

/// Retire the per-feature Toz, code and session hooks Varde wrote, then install
/// the unified hooks. A legacy file or entry the user edited is kept and
/// reported; it also holds back the unified install where both would run.
pub fn rewrite_harness(env: &MigrateEnv, id: &str, report: &mut Report) {
    rewrite_harness_with_features(env, id, report, None);
}

/// Rewrite legacy hooks and install only the selected sync features.
pub fn rewrite_harness_with_features(
    env: &MigrateEnv,
    id: &str,
    report: &mut Report,
    features: Option<&std::collections::BTreeSet<&'static str>>,
) {
    let Some(paths) = HarnessPaths::resolve(env, id) else {
        report.unrewritable.push(ReportEntry::new(
            env.home.join(format!(".{id}")),
            format!("unsupported harness {id:?}; expected claude, codex, opencode, or pi"),
        ));
        return;
    };

    let mut keep_legacy = retire_toz(env, &paths, report);
    let mut skip_events = Vec::new();
    if retire_code_hooks(env, &paths, report) {
        if matches!(paths.id, "claude" | "codex") {
            skip_events.push("SessionStart");
        } else {
            keep_legacy = true;
        }
    }
    if matches!(paths.id, "claude" | "codex") {
        retire_session_entries(env, &paths, report);
    } else {
        keep_legacy |= retire_session_plugin(env, &paths, report);
    }
    if keep_legacy {
        return;
    }

    let mut install = args(&["setup", "hooks", "install", "--harness", paths.id]);
    if let Some(features) = features {
        if !features.is_empty() {
            install.extend(args(&[
                "--features",
                &features.iter().copied().collect::<Vec<_>>().join(","),
            ]));
        } else {
            install.extend(args(&["--features", "learn"]));
        }
    }
    for event in skip_events {
        install.extend(args(&["--skip-event", event]));
    }
    let unified_file = &paths.session_hooks;
    if let Some(output) = run_step(
        env,
        &install,
        unified_file,
        &format!("install the unified hooks for {}", paths.id),
        report,
    ) && output.status.success()
    {
        report_blocked_events(&output.stdout, unified_file, report);
    }
}

/// Remove the per-feature Toz install, keeping any file Toz did not write.
/// True when an edited file was kept or the removal failed.
fn retire_toz(env: &MigrateEnv, paths: &HarnessPaths, report: &mut Report) -> bool {
    if !has_toz_install(paths) {
        return false;
    }
    let action = format!("remove the per-feature Toz integration for {}", paths.id);
    if env.dry_run {
        report.would.push(ReportEntry::new(
            &paths.install,
            format!("prediction: {action}"),
        ));
        return false;
    }
    let mut kept = Vec::new();
    for dir in &paths.toz_dirs {
        let removed = if paths.id == "codex" {
            // An edited Toz entry stays in hooks.json; it is the one thing left to report.
            varde_toz::retire_legacy_codex(dir).map(|()| {
                if has_toz_install(paths) {
                    vec![paths.session_hooks.clone()]
                } else {
                    Vec::new()
                }
            })
        } else {
            varde_toz::retire_legacy_files(dir, paths.toz_files)
        };
        match removed {
            Ok(files) => kept.extend(files),
            Err(error) => {
                report.unrewritable.push(ReportEntry::new(
                    &paths.install,
                    format!("{action} failed: {error:#}"),
                ));
                return true;
            }
        }
        if paths.id == "claude" {
            // Best effort: the plugin dir goes once nothing else (such as captures) is in it.
            let _ = fs::remove_dir(dir);
        }
    }
    let Some(kept) = kept.into_iter().next() else {
        return false;
    };
    let fix = if paths.id == "codex" {
        format!("Remove its Toz entry from {}", kept.display())
    } else {
        format!("Delete {}", kept.display())
    };
    report.unrewritable.push(ReportEntry::new(
        &kept,
        format!(
            "the per-feature Toz install for {} was edited and kept; the unified hooks were not installed for it. {fix}, then rerun `varde setup sync`",
            paths.id
        ),
    ));
    true
}

/// True when Toz capture hooks or files from the per-feature install exist.
fn has_toz_install(paths: &HarnessPaths) -> bool {
    if paths.id == "codex" {
        return fs::read_to_string(&paths.session_hooks)
            .is_ok_and(|text| text.contains("capture --hook") || text.contains("note --harness"));
    }
    paths.toz_artifacts.iter().any(|path| path.exists())
}

/// Remove the legacy code hooks. True when one was kept or the removal failed;
/// it would run beside the unified session hook.
fn retire_code_hooks(env: &MigrateEnv, paths: &HarnessPaths, report: &mut Report) -> bool {
    let action = format!("remove legacy code hooks for {}", paths.id);
    if env.dry_run {
        report.would.push(ReportEntry::new(
            &paths.code_hooks,
            format!("prediction: {action}"),
        ));
        return false;
    }
    let targets: Vec<_> = varde_code::hooks::HOOK_TARGETS
        .iter()
        .filter(|target| target.agent == paths.id)
        .copied()
        .collect();
    let held_back = if matches!(paths.id, "claude" | "codex") {
        "the unified SessionStart hook was not installed beside it"
    } else {
        "the unified hooks were not installed beside it"
    };
    match varde_code::hooks::remove_hooks(&paths.code_dir, &targets, false) {
        Ok(removed) if removed.iter().any(|result| result.skipped_modified) => {
            report.unrewritable.push(ReportEntry::new(
                &paths.code_hooks,
                format!(
                    "locally modified {} code hook was left in place; {held_back}. Delete it from {}, then rerun `varde setup sync`",
                    paths.id,
                    paths.code_hooks.display()
                ),
            ));
            true
        }
        Ok(_) => false,
        Err(error) => {
            report.unrewritable.push(ReportEntry::new(
                &paths.code_hooks,
                format!("{action} failed: {error}; {held_back}"),
            ));
            true
        }
    }
}

/// What the legacy `varde-workflow` session installer left in a JSON hook file.
#[derive(Default)]
struct LegacySession {
    /// Unmodified entries running the legacy `varde-workflow` binary.
    workflow: bool,
    /// Pre-unification nav_map entries (Codex hooks.json only).
    nav_map: bool,
    /// A `varde-workflow` entry that differs from what the legacy installer wrote.
    edited: bool,
}

/// Drop unmodified legacy `varde-workflow` SessionStart entries (and, for Codex,
/// nav_map entries) so the unified installer can own the event. An edited legacy
/// entry stays; the unified installer then blocks the event and reports it.
fn retire_session_entries(env: &MigrateEnv, paths: &HarnessPaths, report: &mut Report) {
    let path = &paths.session_hooks;
    let Ok(text) = fs::read_to_string(path) else {
        return;
    };
    let Ok(doc) = serde_json::from_str::<Value>(&text) else {
        return;
    };
    let codex = paths.id == "codex";
    let found = scan_legacy_session(&doc, paths.id, codex);
    if found.edited || !(found.workflow || found.nav_map) {
        return;
    }
    if env.dry_run {
        report.would.push(ReportEntry::new(
            path,
            format!(
                "prediction: remove legacy session hook entries for {}",
                paths.id
            ),
        ));
        return;
    }
    let owned = |command: &str| {
        is_legacy_workflow_command(command, paths.id) || (codex && is_nav_map_command(command))
    };
    let result = varde_core::json_order::remove_matching_commands(&text, "SessionStart", owned)
        .map_err(|error| error.to_string())
        .and_then(|(updated, _)| fs::write(path, updated).map_err(|error| error.to_string()));
    match result {
        Ok(()) => report.moved.push(ReportEntry::new(
            path,
            format!("removed legacy session hook entries for {}", paths.id),
        )),
        Err(error) => report.unrewritable.push(ReportEntry::new(
            path,
            format!("could not remove legacy session hook entries: {error}"),
        )),
    }
}

fn scan_legacy_session(doc: &Value, harness: &str, codex: bool) -> LegacySession {
    let mut found = LegacySession::default();
    let groups = doc["hooks"]["SessionStart"]
        .as_array()
        .map_or(&[][..], Vec::as_slice);
    for group in groups {
        let nested = group["hooks"].as_array().map_or(&[][..], Vec::as_slice);
        let direct = std::iter::once(group).filter(|group| group.get("command").is_some());
        for hook in nested.iter().chain(direct) {
            let Some(command) = hook["command"].as_str() else {
                continue;
            };
            if codex && is_nav_map_command(command) {
                found.nav_map = true;
            } else if executable_name(command).as_deref() == Some("varde-workflow")
                && command.contains("hook session-start")
            {
                // The legacy installer wrote only type, command and timeout 20 under
                // no (or an empty) matcher; older versions omitted the timeout.
                let pristine = group
                    .get("matcher")
                    .is_none_or(|matcher| matcher.as_str() == Some(""))
                    && group.as_object().is_some_and(|fields| {
                        fields
                            .keys()
                            .all(|key| matches!(key.as_str(), "matcher" | "hooks"))
                    })
                    && group["hooks"]
                        .as_array()
                        .is_some_and(|hooks| hooks.len() == 1)
                    && hook["type"] == "command"
                    && hook.get("timeout").is_none_or(|timeout| timeout == 20)
                    && hook.as_object().is_some_and(|fields| {
                        fields
                            .keys()
                            .all(|key| matches!(key.as_str(), "type" | "command" | "timeout"))
                    })
                    && is_legacy_workflow_command(command, harness);
                found.workflow |= pristine;
                found.edited |= !pristine;
            }
        }
    }
    found
}

/// `<varde-workflow> hook session-start --harness <harness>` and nothing else.
fn is_legacy_workflow_command(command: &str, harness: &str) -> bool {
    executable_name(command).as_deref() == Some("varde-workflow")
        && command_args(command) == ["hook", "session-start", "--harness", harness]
}

/// A pre-unification `varde-code ... nav_map` or `varde map nav_map` command.
fn is_nav_map_command(command: &str) -> bool {
    let rest = command_args(command);
    match executable_name(command).as_deref() {
        Some("varde-code") => rest.iter().any(|word| word == "nav_map"),
        Some("varde") => {
            rest.first().is_some_and(|word| word == "map")
                && rest.get(1).is_some_and(|word| word == "nav_map")
        }
        _ => false,
    }
}

/// The first word of `command`, honoring a leading quoted path.
fn first_word(command: &str) -> (String, &str) {
    let command = command.trim_start();
    for quote in ['\'', '"'] {
        if let Some(rest) = command.strip_prefix(quote)
            && let Some(end) = rest.find(quote)
        {
            return (rest[..end].replace("'\\''", "'"), &rest[end + 1..]);
        }
    }
    let end = command.find(char::is_whitespace).unwrap_or(command.len());
    (command[..end].to_owned(), &command[end..])
}

fn executable_name(command: &str) -> Option<String> {
    let (first, _) = first_word(command);
    Path::new(&first)
        .file_name()
        .and_then(|name| name.to_str())
        .map(str::to_owned)
}

fn command_args(command: &str) -> Vec<String> {
    first_word(command)
        .1
        .split_whitespace()
        .map(str::to_owned)
        .collect()
}

/// Remove the legacy `varde-session.ts` plugin when it is what the legacy
/// installer wrote. True when an edited plugin was kept.
fn retire_session_plugin(env: &MigrateEnv, paths: &HarnessPaths, report: &mut Report) -> bool {
    let path = &paths.session_hooks;
    let Ok(text) = fs::read_to_string(path) else {
        return false;
    };
    if !is_unedited_legacy_plugin(paths.id, &text) {
        report.unrewritable.push(ReportEntry::new(
            path,
            format!(
                "the legacy session hook for {} was edited and kept; the unified hooks were not installed for it. Delete {}, then rerun `varde setup sync`",
                paths.id,
                path.display()
            ),
        ));
        return true;
    }
    if env.dry_run {
        report.would.push(ReportEntry::new(
            path,
            format!(
                "prediction: remove the legacy session hook for {}",
                paths.id
            ),
        ));
    } else if let Err(error) = fs::remove_file(path) {
        report.unrewritable.push(ReportEntry::new(
            path,
            format!("could not remove the legacy session hook: {error}"),
        ));
        return true;
    } else {
        report.moved.push(ReportEntry::new(
            path,
            format!("removed the legacy session hook for {}", paths.id),
        ));
    }
    false
}

/// True when `text` is a legacy session plugin with any binary path filled in.
fn is_unedited_legacy_plugin(harness: &str, text: &str) -> bool {
    let templates = if harness == "opencode" {
        let (header, rest) = LEGACY_OPENCODE_SESSION
            .split_once("//@@v1\n")
            .unwrap_or_default();
        let (v1, v2) = rest.split_once("//@@v2\n").unwrap_or_default();
        vec![format!("{header}{v1}"), format!("{header}{v2}")]
    } else {
        vec![LEGACY_PI_SESSION.to_owned()]
    };
    templates
        .iter()
        .any(|template| matches_with_json_string_bin(template, text))
}

/// True when `text` equals `template` with each binary placeholder replaced by
/// a JSON string.
fn matches_with_json_string_bin(template: &str, text: &str) -> bool {
    let mut parts = template.split(WORKFLOW_BIN_PLACEHOLDER);
    let Some(first) = parts.next() else {
        return false;
    };
    let Some(mut rest) = text.strip_prefix(first) else {
        return false;
    };
    for part in parts {
        let mut values = serde_json::Deserializer::from_str(rest).into_iter::<String>();
        if !matches!(values.next(), Some(Ok(_))) {
            return false;
        }
        let Some(after) = rest[values.byte_offset()..].strip_prefix(part) else {
            return false;
        };
        rest = after;
    }
    rest.is_empty()
}

/// Report each `blocked` line the unified installer printed, with its fix.
fn report_blocked_events(stdout: &[u8], default_path: &Path, report: &mut Report) {
    for line in String::from_utf8_lossy(stdout).lines() {
        let Some((_, detail)) = line.split_once(": blocked, ") else {
            continue;
        };
        let (reason, command) = match detail.split_once(" Fix: ") {
            Some((reason, command)) => (reason, Some(command.trim())),
            None => (detail, None),
        };
        let path = reason
            .split_once(" has an edited ")
            .or_else(|| reason.split_once(" was edited"))
            .map_or_else(
                || default_path.to_path_buf(),
                |(path, _)| PathBuf::from(path),
            );
        let mut entry = ReportEntry::new(path, format!("blocked: {reason}"));
        if let Some(command) = command {
            entry = entry.with_command(command);
        }
        report.unrewritable.push(entry);
    }
}

/// Install the shared instruction block into explicit or configured targets.
pub fn install_instructions(
    env: &MigrateEnv,
    targets: &[PathBuf],
    sections: &[String],
    report: &mut Report,
) {
    let explicit_targets = !targets.is_empty();
    let configured_targets;
    let targets = if explicit_targets {
        targets
    } else {
        match configured_instruction_targets(env, report) {
            Some(found) => {
                configured_targets = found;
                configured_targets.as_slice()
            }
            None => return,
        }
    };

    if targets.is_empty() {
        if env.dry_run {
            report.skipped.push(ReportEntry::new(
                env.config_dir.join("config.toml"),
                SETUP_WARNING,
            ));
        } else {
            let mut install = args(&["setup", "instructions", "install"]);
            append_instruction_sections(&mut install, sections);
            match run_command(env, &install) {
                Ok(output) if output.status.success() => {
                    let warning = String::from_utf8_lossy(&output.stdout).trim().to_owned();
                    report.skipped.push(ReportEntry::new(
                        env.config_dir.join("config.toml"),
                        if warning.is_empty() {
                            SETUP_WARNING.to_owned()
                        } else {
                            warning
                        },
                    ));
                }
                Ok(output) => report_command_failure(
                    report,
                    env.config_dir.join("config.toml"),
                    "install the Varde instruction block",
                    &install,
                    &output,
                ),
                Err(error) => report_spawn_failure(
                    report,
                    env.config_dir.join("config.toml"),
                    "install the Varde instruction block",
                    &install,
                    error,
                ),
            }
        }
        return;
    }

    let mut install = args(&["setup", "instructions", "install"]);
    append_instruction_sections(&mut install, sections);
    if explicit_targets {
        for target in targets {
            install.extend(args(&["--target"]));
            install.push(target.clone().into_os_string());
        }
    }

    if env.dry_run {
        for target in targets {
            add_prediction(
                report,
                target,
                "install the shared Varde instruction block".to_owned(),
                &install,
            );
        }
        return;
    }

    match run_command(env, &install) {
        Ok(output) if output.status.success() => {}
        Ok(output) => {
            let affected = if targets.is_empty() {
                vec![env.config_dir.join("config.toml")]
            } else {
                targets.to_vec()
            };
            for target in affected {
                report_command_failure(
                    report,
                    target,
                    "install the Varde instruction block",
                    &install,
                    &output,
                );
            }
        }
        Err(error) => report_spawn_failure(
            report,
            env.config_dir.join("config.toml"),
            "install the Varde instruction block",
            &install,
            error,
        ),
    }
}

fn append_instruction_sections(install: &mut Vec<OsString>, sections: &[String]) {
    install.extend(args(&["--sections"]));
    install.push(sections.join(",").into());
}

/// Pin the currently resolved Toz root as the default when no default exists.
pub fn pin_toz_store(env: &MigrateEnv, report: &mut Report) {
    let show = args(&["setup", "paths", "--json"]);
    let output = match run_command(env, &show) {
        Ok(output) if output.status.success() => output,
        Ok(output) => {
            report_command_failure(
                report,
                env.config_dir.join("config.toml"),
                "read configured Varde paths",
                &show,
                &output,
            );
            return;
        }
        Err(error) => {
            report_spawn_failure(
                report,
                env.config_dir.join("config.toml"),
                "read configured Varde paths",
                &show,
                error,
            );
            return;
        }
    };
    let paths: Value = match serde_json::from_slice::<Value>(&output.stdout) {
        Ok(value) if value.get("ok").and_then(Value::as_bool) == Some(true) => value,
        Ok(value) => {
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("config.toml"),
                format!("could not read configured Varde paths: {}", value),
            ));
            return;
        }
        Err(error) => {
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("config.toml"),
                format!("could not parse `varde setup paths --json` output: {error}"),
            ));
            return;
        }
    };
    match paths.pointer("/data/toz") {
        Some(Value::String(_)) => return,
        Some(Value::Null) => {}
        _ => {
            report.unrewritable.push(ReportEntry::new(
                env.config_dir.join("config.toml"),
                "`varde setup paths --json` returned no valid Toz path field",
            ));
            return;
        }
    }

    let store = match &env.toz_config_override {
        Some(path) => path.clone(),
        None => match toz_core::config::config_dir() {
            Ok(path) => path,
            Err(error) => {
                report.unrewritable.push(ReportEntry::new(
                    env.config_dir.join("config.toml"),
                    format!("could not resolve the Toz config directory: {error:#}"),
                ));
                return;
            }
        },
    };
    let set = args(&["setup", "paths", "set", "--default", "--toz"]);
    let mut set = set;
    set.push(store.clone().into_os_string());
    if env.dry_run {
        add_prediction(
            report,
            &store,
            "pin the resolved Toz store as the default".to_owned(),
            &set,
        );
        return;
    }

    match run_command(env, &set) {
        Ok(output) if output.status.success() => report.moved.push(
            ReportEntry::new(&store, "pinned the resolved Toz store as the default")
                .with_command(public_command(&set)),
        ),
        Ok(output) => report_command_failure(
            report,
            store,
            "pin the resolved Toz store as the default",
            &set,
            &output,
        ),
        Err(error) => report_spawn_failure(
            report,
            store,
            "pin the resolved Toz store as the default",
            &set,
            error,
        ),
    }
}

fn configured_instruction_targets(env: &MigrateEnv, report: &mut Report) -> Option<Vec<PathBuf>> {
    match targets_from_config(env) {
        Ok(targets) => Some(targets),
        Err((args, error)) => {
            report.unrewritable.push(
                ReportEntry::new(
                    env.config_dir.join("config.toml"),
                    format!("could not read configured instruction targets: {error}"),
                )
                .with_command(public_command(&args)),
            );
            None
        }
    }
}

fn targets_from_config(env: &MigrateEnv) -> Result<Vec<PathBuf>, (Vec<OsString>, String)> {
    let args = args(&["setup", "instructions", "targets"]);
    let output = run_command(env, &args).map_err(|error| (args.clone(), error.to_string()))?;
    if !output.status.success() {
        return Err((args, stderr_tail(&output)));
    }
    Ok(String::from_utf8_lossy(&output.stdout)
        .lines()
        .map(str::trim)
        .filter(|target| !target.is_empty())
        .map(PathBuf::from)
        .collect())
}

fn run_step(
    env: &MigrateEnv,
    args: &[OsString],
    path: &Path,
    action: &str,
    report: &mut Report,
) -> Option<Output> {
    if env.dry_run {
        add_prediction(report, path, action.to_owned(), args);
        return None;
    }
    match run_command(env, args) {
        Ok(output) if output.status.success() => Some(output),
        Ok(output) => {
            report_command_failure(report, path, action, args, &output);
            Some(output)
        }
        Err(error) => {
            report_spawn_failure(report, path, action, args, error);
            None
        }
    }
}

fn run_command(env: &MigrateEnv, args: &[OsString]) -> io::Result<Output> {
    let mut command = Command::new(&env.exe);
    command
        .args(args)
        .env("HOME", &env.home)
        .env("VARDE_CONFIG_DIR", &env.config_dir)
        .env("PATH", &env.path)
        .env_remove("VARDE_TOZ_CONFIG_DIR")
        .env_remove("TOZ_CONFIG_DIR")
        .stdin(Stdio::null());
    if let Some(xdg) = &env.xdg_config_home {
        command.env("XDG_CONFIG_HOME", xdg);
    } else {
        command.env_remove("XDG_CONFIG_HOME");
    }
    if let Some(override_path) = &env.toz_config_override {
        command.env("VARDE_TOZ_CONFIG_DIR", override_path);
    }
    command.output()
}

fn args(parts: &[&str]) -> Vec<OsString> {
    parts.iter().map(OsString::from).collect()
}

fn add_prediction(report: &mut Report, path: &Path, action: String, args: &[OsString]) {
    report.would.push(
        ReportEntry::new(path, format!("prediction: {action}")).with_command(public_command(args)),
    );
}

fn public_command(args: &[OsString]) -> String {
    std::iter::once("varde".to_owned())
        .chain(args.iter().map(|arg| shell_quote(&arg.to_string_lossy())))
        .collect::<Vec<_>>()
        .join(" ")
}

fn shell_quote(word: &str) -> String {
    if word
        .chars()
        .all(|character| character.is_ascii_alphanumeric() || "/._-+:@".contains(character))
    {
        word.to_owned()
    } else {
        format!("'{}'", word.replace('\'', r"'\''"))
    }
}

fn report_command_failure(
    report: &mut Report,
    path: impl Into<PathBuf>,
    action: &str,
    args: &[OsString],
    output: &Output,
) {
    report.unrewritable.push(
        ReportEntry::new(
            path,
            format!(
                "{action} failed with exit {}: {}",
                output
                    .status
                    .code()
                    .map_or_else(|| "signal".to_owned(), |code| code.to_string()),
                stderr_tail(output)
            ),
        )
        .with_command(public_command(args)),
    );
}

fn report_spawn_failure(
    report: &mut Report,
    path: impl Into<PathBuf>,
    action: &str,
    args: &[OsString],
    error: io::Error,
) {
    report.unrewritable.push(
        ReportEntry::new(path, format!("{action} could not run: {error}"))
            .with_command(public_command(args)),
    );
}

fn stderr_tail(output: &Output) -> String {
    let stderr = String::from_utf8_lossy(&output.stderr);
    let mut lines = stderr.lines().rev().take(STDERR_LINES).collect::<Vec<_>>();
    lines.reverse();
    if lines.is_empty() {
        "stderr was empty".to_owned()
    } else {
        lines.join("\n")
    }
}
