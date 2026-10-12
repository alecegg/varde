//! Removal of the session-start hooks the old per-feature code installer wrote, kept for
//! `varde setup sync` migration. Installing moved to `varde setup hooks install`.
//!
//! Two kinds of target: whole-file writes (`HookKind::WriteFile`, matched against the
//! embedded asset and earlier releases) and merges into a shared config file
//! (`HookKind::MergeInto`: JSON via `serde_json`, TOML via `toml_edit`, which keeps the
//! user's comments and formatting). Removal touches only this tool's own entry and skips
//! one the user edited unless forced.

use std::io;
use std::path::{Path, PathBuf};
use varde_core::json_order;

/// Stable marker identifying an entry this tool injected, used both to
/// merge idempotently and to scope `remove`'s diff check to just this
/// tool's own addition — never the whole shared config file.
pub const MARKER_KEY: &str = "__source";
pub const MARKER_VALUE: &str = "varde-code";

/// A path relative to an agent's install target directory.
pub type RelPath = &'static str;

/// How to merge an injected entry into an existing structured file without
/// clobbering unrelated content.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum MergeStrategy {
    /// Merge one key into a top-level JSON object (`serde_json`).
    Json,
    /// Merge one table into a top-level TOML document (`toml_edit`),
    /// preserving the rest of the file's comments/formatting.
    Toml,
}

/// How a hook is installed for a given agent.
#[derive(Debug, Clone, Copy)]
pub enum HookKind {
    /// Merge the injected entry into an existing (or newly created) file at
    /// `rel_path`, using `merge` to combine with any unrelated content.
    MergeInto(RelPath, MergeStrategy),
    /// Write embedded `contents` verbatim to `rel_path`, overwriting only
    /// this tool's own file.
    WriteFile(RelPath, &'static str),
}

/// One agent's hook install target.
#[derive(Debug, Clone, Copy)]
pub struct HookTarget {
    /// Bare agent name, e.g. `"claude"`.
    pub agent: &'static str,
    pub kind: HookKind,
}

/// Bare agent name for the Claude Code hook target.
pub const CLAUDE_AGENT: &str = "claude";

/// The command injected into Claude Code's `SessionStart` hook. `$(pwd)` is
/// resolved by the shell at hook-run time (not baked in statically), so the
/// `repoRoot` always reflects the session's actual working directory.
pub const CLAUDE_SESSION_START_COMMAND: &str = "varde map nav_map --json \"{\\\"repoRoot\\\":\\\"$(pwd)\\\"}\" --format text --with-project-knowledge";

/// Earlier session-start command, retained for removal.
pub const LEGACY_SESSION_START_COMMAND: &str = "varde-code nav_map --json \"{\\\"repoRoot\\\":\\\"$(pwd)\\\"}\" --format text --with-project-knowledge";

/// Bare agent name for the Codex CLI hook target.
pub const CODEX_AGENT: &str = "codex";

/// The command injected into Codex's `SessionStart` hook. Same command as
/// Claude Code's; `$(pwd)` is resolved by the shell at hook-run time.
pub const CODEX_SESSION_START_COMMAND: &str = CLAUDE_SESSION_START_COMMAND;

/// Bare agent name for the opencode hook target.
pub const OPENCODE_AGENT: &str = "opencode";

/// The opencode plugin JS the retired installer wrote to
/// `~/.config/opencode/plugin/varde-code-nav-map.js`, kept to recognize an unedited file.
pub const OPENCODE_PLUGIN_JS: &str = include_str!("../assets/hooks/opencode-plugin.js");

/// Bare agent name for the Pi coding agent hook target.
pub const PI_AGENT: &str = "pi";

/// Exact asset bytes shipped in v1.3.0 and v1.4.0, retained for hook migration.
pub const LEGACY_OPENCODE_PLUGIN_V1_4: &str = r#"// Injected by varde-code (see `varde-code hooks install --agent opencode`).
//
// opencode plugin: on session start, shells out to `varde-code nav_map`
// and injects the result into the session as context so the
// coding agent starts oriented in the repo. Follows opencode's documented
// plugin function shape: an async function receiving the plugin context
// (`project`, `client`, `$`, `directory`, `worktree`) and returning an
// object of hook handlers.
//
// Best-effort: written against opencode's documented plugin API without a
// live opencode install to verify against (see the session-start-hooks
// plan's Assumptions section). If opencode's actual hook name or context
// injection mechanism differs, this may need a follow-up update.
export const VardeCodeNavMap = async ({ $, directory }) => {
  return {
    event: async ({ event }) => {
      if (event.type !== "session.start") return;

      let navMap;
      try {
        navMap = await $`varde-code nav_map --json ${JSON.stringify({
          repoRoot: directory,
        })} --format text`.cwd(directory).text();
      } catch (err) {
        // Best-effort: never block session start on a nav_map failure.
        console.error("varde-code nav_map hook failed:", err);
        return;
      }

      if (!navMap || !navMap.trim()) return;

      await event.client?.session?.messages?.append?.({
        role: "system",
        content: navMap,
      });
    },
  };
};
"#;

/// Exact asset bytes shipped in v1.3.0 and v1.4.0, retained for hook migration.
pub const LEGACY_PI_EXTENSION_V1_4: &str = r#"// Injected by varde-code (see `varde-code hooks install --agent pi`).
//
// Pi extension: on session start, shells out to `varde-code nav_map`
// and returns the result as the session's system prompt so the coding agent
// starts oriented in the repo. Follows Pi's native, first-party
// `ExtensionAPI` factory function shape: `export default function(pi) {...}`
// which registers event handlers via `pi.on(...)`. No third-party
// `pi-hooks` compat shim is used.
//
// Best-effort: written against Pi's documented `ExtensionAPI` without a
// live Pi install to verify against (see the session-start-hooks plan's
// Assumptions section). If Pi's actual event name or return-value shape
// differs, this may need a follow-up update.
import { execFileSync } from "node:child_process";

export default function (pi) {
  pi.on("session_start", async (event, ctx) => {
    let navMap = "";
    try {
      const cwd = (ctx && (ctx.cwd || ctx.directory)) || process.cwd();
      navMap = execFileSync(
        "varde-code",
        ["nav_map", "--json", JSON.stringify({ repoRoot: cwd }), "--format", "text"],
        { cwd, encoding: "utf8" }
      );
    } catch (err) {
      // Best-effort: never block session start on a nav_map failure.
      console.error("varde-code nav_map hook failed:", err);
      navMap = "";
    }

    return { systemPrompt: navMap };
  });
}
"#;

/// The Pi extension JS the retired installer wrote to `~/.pi/agent/extensions/pi-extension.js`,
/// kept to recognize an unedited file.
pub const PI_EXTENSION_JS: &str = include_str!("../assets/hooks/pi-extension.js");

/// The per-agent hook targets the retired installer wrote: Claude Code merges a
/// `SessionStart` entry into `settings.json`, Codex a `[hooks.session_start]` table into
/// `config.toml`; opencode and Pi get a whole-file plugin or extension.
pub const HOOK_TARGETS: &[HookTarget] = &[
    HookTarget {
        agent: CLAUDE_AGENT,
        kind: HookKind::MergeInto("settings.json", MergeStrategy::Json),
    },
    HookTarget {
        agent: CODEX_AGENT,
        kind: HookKind::MergeInto("config.toml", MergeStrategy::Toml),
    },
    HookTarget {
        agent: OPENCODE_AGENT,
        kind: HookKind::WriteFile("plugin/varde-code-nav-map.js", OPENCODE_PLUGIN_JS),
    },
    HookTarget {
        agent: PI_AGENT,
        kind: HookKind::WriteFile("pi-extension.js", PI_EXTENSION_JS),
    },
];

/// Outcome of removing a single previously installed hook target.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RemoveResult {
    pub agent: String,
    pub path: PathBuf,
    pub removed: bool,
    /// `true` when the injected entry (or, for whole-file targets, the
    /// whole file) no longer matches what this tool would have written
    /// (locally edited) and `force` was false, so it was left alone.
    pub skipped_modified: bool,
}

/// Remove every target in `targets` under `target_dir`. A target edited
/// since install (content-scoped for merge targets) is left in place unless
/// `force` is true.
pub fn remove_hooks(
    target_dir: &Path,
    targets: &[HookTarget],
    force: bool,
) -> io::Result<Vec<RemoveResult>> {
    let mut results = Vec::new();
    for target in targets {
        let result = match target.kind {
            HookKind::WriteFile(rel_path, contents) => {
                remove_write_file(target_dir, target.agent, rel_path, contents, force)?
            }
            HookKind::MergeInto(rel_path, strategy) => {
                remove_merge(target_dir, target.agent, rel_path, strategy, force)?
            }
        };
        if let Some(result) = result {
            results.push(result);
        }
    }
    Ok(results)
}

/// Join a `RelPath` under `target_dir`, asserting the relative path cannot
/// escape it. `RelPath` is always a `&'static str` constant today, so a `..`
/// or absolute component would be a programming error, not untrusted input —
/// the `debug_assert!` catches such a constant in tests/debug before it can
/// write outside the install root.
fn safe_join(target_dir: &Path, rel_path: RelPath) -> PathBuf {
    debug_assert!(
        !rel_path.contains("..") && !Path::new(rel_path).is_absolute(),
        "hook rel_path must stay within target_dir: {rel_path:?}",
    );
    target_dir.join(rel_path)
}

fn remove_write_file(
    target_dir: &Path,
    agent: &str,
    rel_path: RelPath,
    contents: &str,
    force: bool,
) -> io::Result<Option<RemoveResult>> {
    let path = safe_join(target_dir, rel_path);
    if !path.exists() {
        return Ok(None);
    }
    let on_disk = std::fs::read_to_string(&path)?;
    let modified = on_disk != contents && !is_legacy_asset_contents(agent, contents, &on_disk);
    if modified && !force {
        return Ok(Some(RemoveResult {
            agent: agent.to_string(),
            path,
            removed: false,
            skipped_modified: true,
        }));
    }
    std::fs::remove_file(&path)?;
    Ok(Some(RemoveResult {
        agent: agent.to_string(),
        path,
        removed: true,
        skipped_modified: false,
    }))
}

fn legacy_asset_contents(agent: &str, contents: &str) -> Option<String> {
    let mut legacy_command = LEGACY_SESSION_START_COMMAND.split_whitespace();
    let executable = legacy_command.next()?;
    let nav_map = legacy_command.next()?;
    let legacy = match agent {
        OPENCODE_AGENT => contents.replace("varde map nav_map", &format!("{executable} {nav_map}")),
        PI_AGENT => contents
            .replace("varde map nav_map", &format!("{executable} {nav_map}"))
            .replace(
                "\"varde\",\n        [\n          \"map\",\n          \"nav_map\",",
                &format!("\"{executable}\",\n        [\n          \"{nav_map}\","),
            ),
        _ => return None,
    };
    (legacy != contents).then_some(legacy)
}

fn is_legacy_asset_contents(agent: &str, contents: &str, on_disk: &str) -> bool {
    let Some(legacy) = legacy_asset_contents(agent, contents) else {
        return false;
    };
    if legacy == on_disk {
        return true;
    }

    match agent {
        OPENCODE_AGENT => on_disk == LEGACY_OPENCODE_PLUGIN_V1_4,
        PI_AGENT => on_disk == LEGACY_PI_EXTENSION_V1_4,
        _ => false,
    }
}

fn remove_merge(
    target_dir: &Path,
    agent: &str,
    rel_path: RelPath,
    strategy: MergeStrategy,
    force: bool,
) -> io::Result<Option<RemoveResult>> {
    let path = safe_join(target_dir, rel_path);
    if !path.exists() {
        return Ok(None);
    }
    match strategy {
        MergeStrategy::Json => remove_json_merge(path, agent, force),
        MergeStrategy::Toml => remove_toml_merge(path, agent, force),
    }
}

fn remove_json_merge(path: PathBuf, agent: &str, force: bool) -> io::Result<Option<RemoveResult>> {
    let text = std::fs::read_to_string(&path)?;
    let mut doc: serde_json::Value = match serde_json::from_str(&text) {
        Ok(value) => value,
        Err(_) => return Ok(None),
    };
    let (present, modified) = if agent == CLAUDE_AGENT {
        (
            claude_session_start_entry_index(&doc).is_some(),
            claude_session_start_modified(&doc),
        )
    } else {
        (json_marker_present(&doc), json_marker_modified(&doc))
    };
    if !present {
        return Ok(None);
    }
    if modified && !force {
        return Ok(Some(skipped_remove(agent, path)));
    }
    let updated = if agent == CLAUDE_AGENT {
        let commands = claude_session_start_commands(&doc);
        json_order::remove_matching_commands_with_options(
            &text,
            "SessionStart",
            |command| commands.iter().any(|owned| owned == command),
            json_order::RemoveOptions {
                prune_empty_hooks: true,
            },
        )
        .map_err(io::Error::from)?
        .0
    } else {
        json_remove_marker(&mut doc);
        serde_json::to_string_pretty(&doc).map_err(io::Error::from)?
    };
    std::fs::write(&path, updated)?;
    Ok(Some(completed_remove(agent, path)))
}

fn remove_toml_merge(path: PathBuf, agent: &str, force: bool) -> io::Result<Option<RemoveResult>> {
    let text = std::fs::read_to_string(&path)?;
    let mut doc = match text.parse::<toml_edit::DocumentMut>() {
        Ok(doc) => doc,
        Err(_) => return Ok(None),
    };
    let (present, modified) = if agent == CODEX_AGENT {
        (
            codex_session_start_present(&doc),
            codex_session_start_modified(&doc),
        )
    } else {
        (toml_marker_present(&doc), toml_marker_modified(&doc))
    };
    if !present {
        return Ok(None);
    }
    if modified && !force {
        return Ok(Some(skipped_remove(agent, path)));
    }
    if agent == CODEX_AGENT {
        codex_remove_session_start(&mut doc);
    } else {
        toml_remove_marker(&mut doc);
    }
    std::fs::write(&path, doc.to_string())?;
    Ok(Some(completed_remove(agent, path)))
}

fn skipped_remove(agent: &str, path: PathBuf) -> RemoveResult {
    RemoveResult {
        agent: agent.to_string(),
        path,
        removed: false,
        skipped_modified: true,
    }
}

fn completed_remove(agent: &str, path: PathBuf) -> RemoveResult {
    RemoveResult {
        agent: agent.to_string(),
        path,
        removed: true,
        skipped_modified: false,
    }
}

// --- Claude Code `hooks.SessionStart` merge/diff helpers --------------
//
// Claude Code's `settings.json` shape for a `SessionStart` hook is:
// `{"hooks": {"SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "..."}]}]}}`.
// The marker is embedded on the innermost `command` hook object (not the
// document root) so identity/diff-scoping stays scoped to just this
// tool's own entry, never the whole `settings.json` file or the whole
// `SessionStart` array.

/// The `SessionStart` array entry the retired installer injected for `command`.
fn claude_session_start_entry_value(command: &str) -> serde_json::Value {
    serde_json::json!({
        "matcher": "",
        "hooks": [{ "type": "command", "command": command, MARKER_KEY: MARKER_VALUE }],
    })
}

/// Index of this tool's entry within `doc.hooks.SessionStart`, if present.
fn claude_session_start_entry_index(doc: &serde_json::Value) -> Option<usize> {
    doc.get("hooks")?
        .get("SessionStart")?
        .as_array()?
        .iter()
        .position(|entry| {
            entry
                .get("hooks")
                .and_then(|h| h.as_array())
                .map(|hooks| hooks.iter().any(|h| h.get(MARKER_KEY).is_some()))
                .unwrap_or(false)
        })
}

fn claude_session_start_commands(doc: &serde_json::Value) -> Vec<String> {
    let Some(index) = claude_session_start_entry_index(doc) else {
        return Vec::new();
    };
    doc.get("hooks")
        .and_then(|hooks| hooks.get("SessionStart"))
        .and_then(|entries| entries.get(index))
        .and_then(|entry| entry.get("hooks"))
        .and_then(serde_json::Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|hook| hook.get("command")?.as_str().map(str::to_owned))
        .collect()
}

/// `true` when this tool's entry exists but no longer matches what this
/// tool would have written (i.e. the user edited it locally).
fn claude_session_start_modified(doc: &serde_json::Value) -> bool {
    match claude_session_start_entry_index(doc) {
        Some(idx) => {
            let entry = &doc["hooks"]["SessionStart"][idx];
            entry != &claude_session_start_entry_value(CLAUDE_SESSION_START_COMMAND)
                && !is_legacy_session_start_entry(entry)
        }
        None => false,
    }
}

fn is_legacy_session_start_entry(entry: &serde_json::Value) -> bool {
    if entry == &claude_session_start_entry_value(LEGACY_SESSION_START_COMMAND) {
        return true;
    }
    pre_1_5_legacy_session_start_command()
        .is_some_and(|command| entry == &claude_session_start_entry_value(&command))
}

fn pre_1_5_legacy_session_start_command() -> Option<String> {
    LEGACY_SESSION_START_COMMAND
        .strip_suffix(" --with-project-knowledge")
        .map(str::to_owned)
}

// --- Codex `[hooks.session_start]` merge/diff helpers (toml_edit) -----
//
// Codex's `config.toml` shape for a `SessionStart` hook is assumed to be:
// `[hooks.session_start]` with a `command` key (a reasonable table shape
// consistent with Codex's documented `SessionStart` shell-command hook
// type — see the plan's Assumptions section for the medium-confidence
// citation on why user-level scope is used instead of project-local
// `.codex/config.toml`). The marker lives alongside `command` in the same
// table so identity/diff-scoping stays scoped to just this tool's own
// table, never the rest of `config.toml`.

fn codex_session_start_present(doc: &toml_edit::DocumentMut) -> bool {
    doc.get("hooks")
        .and_then(|h| h.get("session_start"))
        .and_then(|s| s.get(MARKER_KEY))
        .is_some()
}

/// `true` when this tool's `[hooks.session_start]` table exists but no
/// longer matches what this tool would have written (i.e. the user edited
/// it locally).
fn codex_session_start_modified(doc: &toml_edit::DocumentMut) -> bool {
    let Some(table) = doc.get("hooks").and_then(|h| h.get("session_start")) else {
        return false;
    };
    let command = table.get("command").and_then(|v| v.as_str());
    let marker = table.get(MARKER_KEY).and_then(|v| v.as_str());
    !command.is_some_and(is_supported_session_start_command) || marker != Some(MARKER_VALUE)
}

fn is_supported_session_start_command(command: &str) -> bool {
    command == CODEX_SESSION_START_COMMAND
        || command == LEGACY_SESSION_START_COMMAND
        || pre_1_5_legacy_session_start_command().as_deref() == Some(command)
}

/// Remove this tool's `[hooks.session_start]` table from `doc`, pruning the
/// now-empty `hooks` table if this was the only entry, but never touching
/// unrelated sibling keys/tables.
fn codex_remove_session_start(doc: &mut toml_edit::DocumentMut) {
    let Some(hooks) = doc.get_mut("hooks").and_then(|h| h.as_table_like_mut()) else {
        return;
    };
    hooks.remove("session_start");
    let hooks_empty = hooks.is_empty();
    if hooks_empty {
        doc.as_table_mut().remove("hooks");
    }
}

// --- JSON merge/diff helpers -----------------------------------------

fn json_marker_present(doc: &serde_json::Value) -> bool {
    doc.get(MARKER_KEY).is_some()
}

/// `true` when the marker key exists but its value diverges from what this
/// tool would have written (i.e. the user edited it locally).
fn json_marker_modified(doc: &serde_json::Value) -> bool {
    match doc.get(MARKER_KEY) {
        Some(v) => v != &serde_json::Value::String(MARKER_VALUE.to_string()),
        None => false,
    }
}

fn json_remove_marker(doc: &mut serde_json::Value) {
    if let Some(obj) = doc.as_object_mut() {
        obj.remove(MARKER_KEY);
    }
}

// --- TOML merge/diff helpers (toml_edit, format-preserving) -----------

fn toml_marker_present(doc: &toml_edit::DocumentMut) -> bool {
    doc.get(MARKER_KEY).is_some()
}

fn toml_marker_modified(doc: &toml_edit::DocumentMut) -> bool {
    match doc.get(MARKER_KEY).and_then(|v| v.as_str()) {
        Some(v) => v != MARKER_VALUE,
        None => doc.get(MARKER_KEY).is_some(),
    }
}

fn toml_remove_marker(doc: &mut toml_edit::DocumentMut) {
    doc.remove(MARKER_KEY);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    fn tempdir(label: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("varde-hooks-{label}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).expect("temp dir creates");
        dir
    }

    fn write(path: &Path, text: &str) {
        fs::create_dir_all(path.parent().unwrap()).expect("parent creates");
        fs::write(path, text).expect("fixture writes");
    }

    fn target(agent: &'static str, kind: HookKind) -> [HookTarget; 1] {
        [HookTarget { agent, kind }]
    }

    fn json_target() -> [HookTarget; 1] {
        target(
            "test-json",
            HookKind::MergeInto("settings.json", MergeStrategy::Json),
        )
    }

    fn claude_entry(command: &str) -> serde_json::Value {
        claude_session_start_entry_value(command)
    }

    fn claude_settings(command: &str) -> String {
        serde_json::json!({ "hooks": { "SessionStart": [claude_entry(command)] } }).to_string()
    }

    fn codex_config(command: &str) -> String {
        format!(
            "[hooks.session_start]\ncommand = {}\n{MARKER_KEY} = {}\n",
            toml_edit::value(command),
            toml_edit::value(MARKER_VALUE),
        )
    }

    #[test]
    fn json_remove_scoped_diff_skips_locally_modified_entry_unless_forced() {
        let dir = tempdir("json-remove-modified");
        let path = dir.join("settings.json");
        let targets = json_target();
        write(
            &path,
            &format!(r#"{{"{MARKER_KEY}": "user-changed", "unrelatedKey": "user-added"}}"#),
        );

        let removed = remove_hooks(&dir, &targets, false).expect("remove succeeds");
        assert_eq!(removed.len(), 1);
        assert!(!removed[0].removed && removed[0].skipped_modified);
        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(doc[MARKER_KEY], "user-changed");

        let forced = remove_hooks(&dir, &targets, true).expect("forced remove succeeds");
        assert!(forced[0].removed && !forced[0].skipped_modified);
        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert!(doc.get(MARKER_KEY).is_none());
        assert_eq!(doc["unrelatedKey"], "user-added");
    }

    #[test]
    fn json_remove_drops_only_the_marker_when_unmodified() {
        let dir = tempdir("json-remove-clean");
        let path = dir.join("settings.json");
        write(
            &path,
            &format!(r#"{{"{MARKER_KEY}": "{MARKER_VALUE}", "keep": 1}}"#),
        );

        let removed = remove_hooks(&dir, &json_target(), false).expect("remove succeeds");
        assert!(removed[0].removed && !removed[0].skipped_modified);
        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert!(doc.get(MARKER_KEY).is_none());
        assert_eq!(doc["keep"], 1);
    }

    #[test]
    fn toml_remove_scoped_diff_skips_locally_modified_entry_unless_forced() {
        let dir = tempdir("toml-remove-modified");
        let path = dir.join("config.toml");
        let targets = target(
            "test-toml",
            HookKind::MergeInto("config.toml", MergeStrategy::Toml),
        );
        write(
            &path,
            &format!("{MARKER_KEY} = \"user-changed\"\nunrelated_key = \"kept\"\n"),
        );

        let removed = remove_hooks(&dir, &targets, false).expect("remove succeeds");
        assert!(!removed[0].removed && removed[0].skipped_modified);
        assert!(fs::read_to_string(&path).unwrap().contains("user-changed"));

        let forced = remove_hooks(&dir, &targets, true).expect("forced remove succeeds");
        assert!(forced[0].removed && !forced[0].skipped_modified);
        let text = fs::read_to_string(&path).unwrap();
        assert!(!text.contains(MARKER_KEY));
        assert!(text.contains("unrelated_key = \"kept\""));
    }

    #[test]
    fn claude_remove_preserves_user_key_order() {
        let dir = tempdir("claude-order");
        let path = dir.join("settings.json");
        let seed = "{\n  \"z-last\": true,\n  \"hooks\": {\n    \"ZEvent\": [\n      {\n        \"z-last\": 2,\n        \"hooks\": [\n          {\n            \"command\": \"echo foreign\",\n            \"type\": \"command\"\n          }\n        ],\n        \"a-first\": 1\n      }\n    ]\n  },\n  \"a-first\": false\n}\n";
        let installed = json_order::replace_owned_entries(
            seed,
            "SessionStart",
            |_| false,
            &[claude_entry(CLAUDE_SESSION_START_COMMAND)],
        )
        .expect("fixture builds")
        .0;
        write(&path, &installed);

        remove_hooks(&dir, &HOOK_TARGETS[..1], false).expect("remove succeeds");

        assert_eq!(fs::read_to_string(path).unwrap(), seed);
    }

    #[test]
    fn claude_remove_leaves_unrelated_content_untouched() {
        let dir = tempdir("claude-remove");
        let path = dir.join("settings.json");
        let mut doc: serde_json::Value =
            serde_json::from_str(&claude_settings(CLAUDE_SESSION_START_COMMAND)).unwrap();
        doc["permissions"] = serde_json::json!({ "allow": ["Bash"] });
        write(&path, &doc.to_string());

        let removed = remove_hooks(&dir, &HOOK_TARGETS[..1], false).expect("remove succeeds");
        assert!(removed[0].removed && !removed[0].skipped_modified);

        let doc: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(&path).unwrap()).unwrap();
        assert_eq!(doc["permissions"]["allow"][0], "Bash");
        assert!(doc.get("hooks").is_none(), "emptied hooks pruned: {doc}");
    }

    #[test]
    fn claude_remove_skips_a_locally_edited_entry() {
        let dir = tempdir("claude-remove-edited");
        write(
            &dir.join("settings.json"),
            &claude_settings("echo user-customized"),
        );

        let removed = remove_hooks(&dir, &HOOK_TARGETS[..1], false).expect("remove succeeds");
        assert!(!removed[0].removed && removed[0].skipped_modified);
    }

    #[test]
    fn codex_remove_leaves_unrelated_content_untouched() {
        let dir = tempdir("codex-remove");
        let path = dir.join("config.toml");
        let seed = "# keep this comment\nmodel = \"gpt-5\"\n";
        write(
            &path,
            &format!("{seed}\n{}", codex_config(CODEX_SESSION_START_COMMAND)),
        );

        let removed = remove_hooks(&dir, &HOOK_TARGETS[1..2], false).expect("remove succeeds");
        assert!(removed[0].removed && !removed[0].skipped_modified);

        let text = fs::read_to_string(&path).unwrap();
        assert!(text.contains("# keep this comment"), "{text}");
        assert!(text.contains("model = \"gpt-5\""), "{text}");
        let doc = text.parse::<toml_edit::DocumentMut>().expect("valid toml");
        assert!(doc.get("hooks").is_none(), "emptied hooks pruned: {doc}");
    }

    #[test]
    fn codex_remove_skips_a_locally_edited_entry() {
        let dir = tempdir("codex-remove-edited");
        write(
            &dir.join("config.toml"),
            &codex_config("echo user-customized"),
        );

        let removed = remove_hooks(&dir, &HOOK_TARGETS[1..2], false).expect("remove succeeds");
        assert!(!removed[0].removed && removed[0].skipped_modified);
    }

    #[test]
    fn claude_remove_accepts_legacy_session_start_commands() {
        let pre_1_5 = pre_1_5_legacy_session_start_command()
            .expect("current legacy command has the project-knowledge flag");
        for command in [LEGACY_SESSION_START_COMMAND, pre_1_5.as_str()] {
            let dir = tempdir("claude-remove-legacy-command");
            write(&dir.join("settings.json"), &claude_settings(command));

            let removed = remove_hooks(&dir, &HOOK_TARGETS[..1], false).expect("remove succeeds");
            assert_eq!(removed.len(), 1);
            assert!(
                removed[0].removed && !removed[0].skipped_modified,
                "{command}"
            );
        }
    }

    #[test]
    fn codex_remove_accepts_legacy_session_start_commands() {
        let pre_1_5 = pre_1_5_legacy_session_start_command()
            .expect("current legacy command has the project-knowledge flag");
        for command in [LEGACY_SESSION_START_COMMAND, pre_1_5.as_str()] {
            let dir = tempdir("codex-remove-legacy-command");
            write(&dir.join("config.toml"), &codex_config(command));

            let removed = remove_hooks(&dir, &HOOK_TARGETS[1..2], false).expect("remove succeeds");
            assert_eq!(removed.len(), 1);
            assert!(
                removed[0].removed && !removed[0].skipped_modified,
                "{command}"
            );
        }
    }

    /// Whole-file targets: the opencode plugin (`HOOK_TARGETS[2]`) and the Pi extension
    /// (`HOOK_TARGETS[3]`), each with the contents of every release that wrote it.
    fn whole_file_cases() -> [(usize, &'static str, [String; 3]); 2] {
        [
            (
                2,
                "plugin/varde-code-nav-map.js",
                [
                    OPENCODE_PLUGIN_JS.to_owned(),
                    legacy_asset_contents(OPENCODE_AGENT, OPENCODE_PLUGIN_JS).unwrap(),
                    LEGACY_OPENCODE_PLUGIN_V1_4.to_owned(),
                ],
            ),
            (
                3,
                "pi-extension.js",
                [
                    PI_EXTENSION_JS.to_owned(),
                    legacy_asset_contents(PI_AGENT, PI_EXTENSION_JS).unwrap(),
                    LEGACY_PI_EXTENSION_V1_4.to_owned(),
                ],
            ),
        ]
    }

    #[test]
    fn whole_file_remove_accepts_every_release_that_wrote_it() {
        for (index, rel, releases) in whole_file_cases() {
            for contents in releases {
                let dir = tempdir("whole-file-release");
                let path = dir.join(rel);
                write(&path, &contents);

                let removed = remove_hooks(&dir, &HOOK_TARGETS[index..=index], false)
                    .expect("remove succeeds");
                assert_eq!(removed.len(), 1);
                assert!(removed[0].removed && !removed[0].skipped_modified, "{rel}");
                assert!(!path.exists(), "{rel}");
            }
        }
    }

    #[test]
    fn whole_file_remove_skips_locally_modified_file_unless_forced() {
        for (index, rel, _) in whole_file_cases() {
            let dir = tempdir("whole-file-modified");
            let path = dir.join(rel);
            write(&path, "// user customized\n");
            let targets = &HOOK_TARGETS[index..=index];

            let removed = remove_hooks(&dir, targets, false).expect("remove succeeds");
            assert!(!removed[0].removed && removed[0].skipped_modified, "{rel}");
            assert!(path.exists(), "{rel}");

            let forced = remove_hooks(&dir, targets, true).expect("forced remove succeeds");
            assert!(forced[0].removed && !forced[0].skipped_modified, "{rel}");
            assert!(!path.exists(), "{rel}");
        }
    }
}
