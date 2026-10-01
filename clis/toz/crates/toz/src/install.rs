//! Harness integrations: file bundles embedded at build time, written by `varde-toz install`.

use anyhow::{Context, Result};
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

/// How a bundle file lands on disk.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    /// Owned by toz: written verbatim.
    Own,
    /// Claude-Code-style `hooks.json` shared with other tools: toz's entries are merged in,
    /// keyed by the command containing `varde-toz `.
    MergeHooks,
    /// A markdown file the user owns: the block between `<!-- varde-toz:start -->` and
    /// `<!-- varde-toz:end -->` is inserted or replaced, everything else is left alone.
    MergeBlock,
}

pub struct Bundle {
    pub harness: &'static str,
    pub default_dir: fn() -> Result<PathBuf>,
    pub files: &'static [(&'static str, &'static str, Mode)],
    /// Printed after a successful install.
    pub after: &'static str,
    /// Executable to probe for the harness version, and the minimum the shim needs.
    pub binary: &'static str,
    pub min_version: (u64, u64, u64),
    pub why_min: &'static str,
    /// Variant for harness versions older than `min_version`, when one exists.
    pub older: Option<&'static Bundle>,
}

/// Run `<binary> --version` and pull the first `x.y.z` out of it.
pub fn installed_version(binary: &str) -> Option<(u64, u64, u64)> {
    let out = std::process::Command::new(binary)
        .arg("--version")
        .stdin(std::process::Stdio::null())
        .output()
        .ok()?;
    let text = format!(
        "{}{}",
        String::from_utf8_lossy(&out.stdout),
        String::from_utf8_lossy(&out.stderr)
    );
    parse_version(&text)
}

pub fn parse_version(text: &str) -> Option<(u64, u64, u64)> {
    for token in text.split(|c: char| c.is_whitespace() || c == '(' || c == ')') {
        let t = token.trim_start_matches('v');
        let mut parts = t.split('.');
        let (Some(a), Some(b), Some(c)) = (parts.next(), parts.next(), parts.next()) else {
            continue;
        };
        let c = c.trim_end_matches(|ch: char| !ch.is_ascii_digit());
        if let (Ok(a), Ok(b), Ok(c)) = (a.parse(), b.parse(), c.parse()) {
            return Some((a, b, c));
        }
    }
    None
}

pub fn fmt_version(v: (u64, u64, u64)) -> String {
    format!("{}.{}.{}", v.0, v.1, v.2)
}

const CLAUDE_CODE: Bundle = Bundle {
    harness: "claude-code",
    default_dir: || {
        Ok(home()?
            .join(".claude")
            .join("skills")
            .join("varde-toz-hooks"))
    },
    files: &[
        (
            ".claude-plugin/plugin.json",
            include_str!("../assets/claude-code/plugin.json"),
            Mode::Own,
        ),
        (
            "hooks/hooks.json",
            include_str!("../assets/claude-code/hooks.json"),
            Mode::Own,
        ),
    ],
    after: "Loads as varde-toz@skills-dir on the next Claude Code session (requires ≥ 2.1.236).",
    binary: "claude",
    min_version: (2, 1, 236),
    why_min: "PostToolUse.updatedToolOutput",
    older: None,
};

const PI: Bundle = Bundle {
    harness: "pi",
    default_dir: || Ok(home()?.join(".pi").join("agent")),
    files: &[(
        "extensions/varde-toz.ts",
        include_str!("../assets/pi/toz.ts"),
        Mode::Own,
    )],
    after: "Loaded as a global pi extension on the next pi session.",
    binary: "pi",
    min_version: (0, 84, 0),
    why_min: "tool_result content patches",
    older: None,
};

/// opencode 1.x: hook-map plugins (`tool.execute.after`, `experimental.chat.system.transform`).
const OPENCODE_V1: Bundle = Bundle {
    harness: "opencode",
    default_dir: || Ok(config_home()?.join("opencode")),
    files: &[(
        "plugin/varde-toz.ts",
        include_str!("../assets/opencode/toz-v1.ts"),
        Mode::Own,
    )],
    after: "Loaded from ~/.config/opencode/plugin on the next opencode session. This is the 1.x \
plugin shim; rerun `varde-toz install opencode` after upgrading to opencode 2.x.",
    binary: "opencode",
    min_version: (1, 2, 0),
    why_min: "the shell.env and experimental.chat.system.transform hooks",
    older: None,
};

const OPENCODE: Bundle = Bundle {
    harness: "opencode",
    default_dir: || Ok(config_home()?.join("opencode")),
    files: &[
        (
            "plugin/varde-toz.ts",
            include_str!("../assets/opencode/toz.ts"),
            Mode::Own,
        ),
    ],
    after: "Loaded from ~/.config/opencode/plugin on the next opencode session (`opencode plugin list` to confirm).",
    binary: "opencode",
    min_version: (2, 0, 0),
    why_min: "the 2.x { id, setup(ctx) } plugin API",
    older: Some(&OPENCODE_V1),
};

const CODEX: Bundle = Bundle {
    harness: "codex",
    default_dir: || Ok(home()?.join(".codex")),
    files: &[
        (
            "hooks.json",
            include_str!("../assets/codex/hooks.json"),
            Mode::MergeHooks,
        ),
        (
            "AGENTS.md",
            include_str!("../assets/codex/AGENTS.md"),
            Mode::MergeBlock,
        ),
    ],
    after: "Codex captures completed unified execution through PostToolUse; use `varde-toz run --script -` for batches with complete command output. \
The AGENTS.md block explains both paths. Codex needs `hooks = true` in ~/.codex/config.toml and will ask you to trust \
the SessionStart and PostToolUse hooks. The adapter uses the primary Toz store by default.",
    binary: "codex",
    min_version: (0, 140, 0),
    why_min: "PostToolUse for completed unified execution",
    older: None,
};

pub const BUNDLES: &[&Bundle] = &[&CLAUDE_CODE, &PI, &OPENCODE, &CODEX];

fn config_home() -> Result<PathBuf> {
    match std::env::var_os("XDG_CONFIG_HOME") {
        Some(x) if !x.is_empty() => Ok(PathBuf::from(x)),
        _ => Ok(home()?.join(".config")),
    }
}

fn home() -> Result<PathBuf> {
    dirs::home_dir().context("could not determine home directory")
}

pub fn bundle(harness: &str) -> Result<&'static Bundle> {
    BUNDLES
        .iter()
        .copied()
        .find(|b| b.harness == harness)
        .ok_or_else(|| {
            let known: Vec<_> = BUNDLES.iter().map(|b| b.harness).collect();
            anyhow::anyhow!("unknown harness {harness:?}; known: {}", known.join(", "))
        })
}

/// Pick the bundle variant matching the harness version actually installed: when the harness
/// predates `min_version` and an older-API variant covers that version, use the variant.
/// `version` overrides probing `<binary> --version`.
pub fn resolve(b: &'static Bundle, version: Option<(u64, u64, u64)>) -> &'static Bundle {
    let mut cur = b;
    let Some(v) = version.or_else(|| installed_version(b.binary)) else {
        return cur;
    };
    while v < cur.min_version {
        match cur.older {
            Some(older) => cur = older,
            None => break,
        }
    }
    cur
}

/// Every template that could legitimately sit at `rel` for this harness — the current bundle's
/// and those of its older-API variants — so a variant switch is not mistaken for a user's file.
fn template_variants(harness: &str, rel: &str) -> Vec<&'static str> {
    let mut out = Vec::new();
    let mut cur = BUNDLES.iter().copied().find(|b| b.harness == harness);
    while let Some(b) = cur {
        if let Some((_, template, _)) = b.files.iter().find(|(r, _, _)| *r == rel) {
            out.push(*template);
        }
        cur = b.older;
    }
    out
}

/// Substitute template variables: `{{TOZ_BIN}}` → absolute path of this binary,
/// `{{TOZ_BIN_SHELL}}` → its shell-quoted path, `{{TOZ_NOTE}}` → the usage note,
/// `{{TOZ_NOTE_JSON}}` → the note as a JSON string literal;
/// `{{TOZ_SHARED_NOTE}}` → the note without a harness-specific fallback path.
#[cfg(test)]
pub fn render(template: &str) -> Result<String> {
    render_with_exe(
        template,
        Path::new("/tmp/toz-render-test"),
        Path::new("/tmp/toz"),
    )
}

fn shell_quote(value: &str) -> String {
    format!("'{}'", value.replace('\'', "'\\''"))
}

fn shell_quote_executable(value: &str) -> String {
    if value
        .chars()
        .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '/' | '.' | '_' | '-'))
    {
        value.to_string()
    } else {
        shell_quote(value)
    }
}

pub fn usage_note() -> String {
    NOTE.to_string()
}

pub fn render_at(template: &str, dir: &Path) -> Result<String> {
    let exe = std::env::current_exe().context("locating toz binary")?;
    let exe = exe.canonicalize().unwrap_or(exe);
    render_with_exe(template, dir, &exe)
}

fn render_with_exe(template: &str, dir: &Path, exe: &Path) -> Result<String> {
    let dir = if dir.is_absolute() {
        dir.to_path_buf()
    } else {
        std::env::current_dir()?.join(dir)
    };
    let legacy = dir.join("tool-output-zone");
    let fallback = if legacy.exists() {
        legacy
    } else {
        dir.join("varde-toz")
    };
    let note = usage_note();
    let shell_json = serde_json::to_string(&shell_quote(&fallback.to_string_lossy()))?;
    Ok(template
        .replace(
            "{{TOZ_BIN_SHELL}}",
            &shell_quote_executable(&exe.to_string_lossy()),
        )
        .replace("{{TOZ_BIN}}", &exe.to_string_lossy())
        .replace(
            "\"{{TOZ_FALLBACK_JSON}}\"",
            &serde_json::to_string(&fallback)?,
        )
        .replace("{{TOZ_FALLBACK_JSON}}", &serde_json::to_string(&fallback)?)
        .replace(
            "{{TOZ_FALLBACK_SHELL_JSON}}",
            &shell_json[1..shell_json.len() - 1],
        )
        .replace("\"{{TOZ_NOTE_JSON}}\"", &serde_json::to_string(&note)?)
        .replace("{{TOZ_NOTE_JSON}}", &serde_json::to_string(&note)?)
        .replace("{{TOZ_SHARED_NOTE}}", NOTE)
        .replace("{{TOZ_NOTE}}", &note))
}

/// What the file at `path` should contain after install, given its current content.
pub fn desired(mode: Mode, template: &str, current: Option<&str>, dir: &Path) -> Result<String> {
    let rendered = render_at(template, dir)?;
    Ok(match mode {
        Mode::Own => rendered,
        Mode::MergeHooks => merge_hooks(current.unwrap_or(""), &rendered)?,
        Mode::MergeBlock => merge_block(current.unwrap_or(""), &rendered),
    })
}

/// Write the bundle. Returns (path, changed) per file.
pub fn install(b: &Bundle, dir: &Path, force: bool) -> Result<Vec<(PathBuf, bool)>> {
    migrate_legacy_claude_plugin(b, dir)?;
    let manifest = read_manifest(dir);
    let retired = legacy_adapter_to_retire(b, dir, &manifest)?;
    let prepared = prepare_files(b, dir, force, &manifest)?;

    // All collision checks have completed. Retire the old entry point before activating the new one.
    if let Some(path) = retired {
        std::fs::remove_file(&path).with_context(|| format!("retiring {}", path.display()))?;
    }
    let (out, written) = write_prepared_files(prepared)?;
    write_manifest(dir, &written)?;
    let _ = std::fs::remove_file(dir.join(".toz-install.json"));
    Ok(out)
}

fn migrate_legacy_claude_plugin(b: &Bundle, dir: &Path) -> Result<()> {
    if b.harness != "claude-code"
        || !dir
            .file_name()
            .is_some_and(|name| name == "varde-toz-hooks")
    {
        return Ok(());
    }
    let legacy = dir.with_file_name("toz");
    if !legacy.join("hooks/hooks.json").exists() {
        return Ok(());
    }
    if dir.exists() {
        anyhow::bail!(
            "both {} and {} exist; retire the legacy plugin before activating varde-toz",
            legacy.display(),
            dir.display()
        );
    }
    let old_manifest = read_manifest(&legacy);
    for rel in [".claude-plugin/plugin.json", "hooks/hooks.json"] {
        let current = std::fs::read(legacy.join(rel))?;
        if !old_manifest
            .get(rel)
            .is_some_and(|hash| *hash == toz_core::content_hash(&current))
        {
            anyhow::bail!(
                "refusing to migrate customized legacy Claude plugin {}; move it aside first",
                legacy.display()
            );
        }
    }
    let old_skill = legacy.join("skills/toz/SKILL.md");
    if let Some(current) = read_optional(&old_skill)? {
        if !old_manifest
            .get("skills/toz/SKILL.md")
            .is_some_and(|hash| *hash == toz_core::content_hash(current.as_bytes()))
        {
            anyhow::bail!(
                "refusing to migrate customized legacy skill {}; move it aside first",
                old_skill.display()
            );
        }
        std::fs::remove_file(&old_skill)?;
        prune_empty_dirs(old_skill.parent(), &legacy);
    }
    // Moving the plugin also preserves its fallback capture directory.
    std::fs::rename(&legacy, dir).with_context(|| format!("migrating {}", legacy.display()))?;
    Ok(())
}

fn legacy_adapter_to_retire(
    b: &Bundle,
    dir: &Path,
    manifest: &BTreeMap<String, String>,
) -> Result<Option<PathBuf>> {
    // Refuse customized old adapters before activating a second capture hook.
    let old_rel = match b.harness {
        "pi" => Some("extensions/toz.ts"),
        "opencode" => Some("plugin/toz.ts"),
        _ => None,
    };
    if let Some(rel) = old_rel {
        let path = dir.join(rel);
        if let Some(current) = read_optional(&path)? {
            if !manifest
                .get(rel)
                .is_some_and(|hash| *hash == toz_core::content_hash(current.as_bytes()))
            {
                anyhow::bail!("refusing to activate varde-toz beside customized legacy adapter {}; move it aside first", path.display());
            }
            return Ok(Some(path));
        }
    }
    Ok(None)
}

type PreparedFile = (&'static str, Mode, PathBuf, Option<String>, String);

fn prepare_files(
    b: &Bundle,
    dir: &Path,
    force: bool,
    manifest: &BTreeMap<String, String>,
) -> Result<Vec<PreparedFile>> {
    let mut prepared = Vec::new();
    for (rel, template, mode) in b.files {
        let path = dir.join(rel);
        let current = read_optional(&path)?;
        let content = desired(*mode, template, current.as_deref(), dir)?;
        if *mode == Mode::Own
            && !force
            && current
                .as_deref()
                .is_some_and(|text| !is_owned(text, b.harness, rel, dir, &content, &manifest))
        {
            anyhow::bail!(
                "refusing to overwrite {}: its contents do not match anything toz wrote here, so it \
                 looks hand-edited. Move it aside, or re-run with --force to replace it.",
                path.display()
            );
        }
        prepared.push((*rel, *mode, path, current, content));
    }
    Ok(prepared)
}

fn write_prepared_files(
    prepared: Vec<PreparedFile>,
) -> Result<(Vec<(PathBuf, bool)>, BTreeMap<String, String>)> {
    let mut out = Vec::new();
    let mut written: BTreeMap<String, String> = BTreeMap::new();
    for (rel, mode, path, current, content) in prepared {
        let changed = current.as_deref() != Some(content.as_str());
        if changed {
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent)
                    .with_context(|| format!("creating {}", parent.display()))?;
            }
            std::fs::write(&path, &content)
                .with_context(|| format!("writing {}", path.display()))?;
        }
        if mode == Mode::Own {
            written.insert(rel.to_string(), toz_core::content_hash(content.as_bytes()));
        }
        out.push((path, changed));
    }
    Ok((out, written))
}

fn read_optional(path: &Path) -> Result<Option<String>> {
    match std::fs::read_to_string(path) {
        Ok(text) => Ok(Some(text)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error).with_context(|| format!("reading {}", path.display())),
    }
}

/// Records the hash of every owned file `install` wrote.
///
/// Ownership used to be inferred by comparing a file against the compiled-in template. That makes
/// any edit to a bundled template look like a user edit: every existing install becomes "unowned",
/// so `doctor` reports drift and tells you to run `toz install`, which then refuses. Recording what
/// toz actually wrote separates "stale because the template moved on" from "the user changed it".
const MANIFEST: &str = ".varde-toz-install.json";

fn read_manifest(dir: &Path) -> BTreeMap<String, String> {
    std::fs::read_to_string(dir.join(MANIFEST))
        .or_else(|_| std::fs::read_to_string(dir.join(".toz-install.json")))
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok())
        .and_then(|doc| doc.get("files").cloned())
        .and_then(|files| serde_json::from_value(files).ok())
        .unwrap_or_default()
}

fn write_manifest(dir: &Path, files: &BTreeMap<String, String>) -> Result<()> {
    let doc = json!({ "version": 1, "files": files });
    let path = dir.join(MANIFEST);
    std::fs::write(&path, format!("{}\n", serde_json::to_string_pretty(&doc)?))
        .with_context(|| format!("writing {}", path.display()))
}

/// Whether toz may replace this file: either it is byte-for-byte what toz last wrote, or it still
/// matches one of the compiled-in templates (installs predating the manifest).
pub fn is_owned(
    current: &str,
    harness: &str,
    rel: &str,
    dir: &Path,
    rendered: &str,
    manifest: &BTreeMap<String, String>,
) -> bool {
    if manifest
        .get(rel)
        .is_some_and(|hash| *hash == toz_core::content_hash(current.as_bytes()))
    {
        return true;
    }
    matches_owned_template(current, harness, rel, dir, rendered)
}

/// Owned files a fresh `install` would refuse to replace. Lets `doctor` say so instead of
/// recommending a command that will fail.
pub fn unowned_files(b: &Bundle, dir: &Path) -> Vec<&'static str> {
    let manifest = read_manifest(dir);
    let mut out = Vec::new();
    for (rel, template, mode) in b.files {
        if *mode != Mode::Own {
            continue;
        }
        let Ok(Some(current)) = read_optional(&dir.join(rel)) else {
            continue;
        };
        let Ok(rendered) = desired(*mode, template, Some(&current), dir) else {
            continue;
        };
        if !is_owned(&current, b.harness, rel, dir, &rendered, &manifest) {
            out.push(*rel);
        }
    }
    out
}

fn matches_owned_template(
    current: &str,
    harness: &str,
    rel: &str,
    dir: &Path,
    rendered: &str,
) -> bool {
    if current == rendered {
        return true;
    }
    template_variants(harness, rel).into_iter().any(|template| {
        render_at(template, dir).map(|c| c == current).unwrap_or(false)
                // Accept hooks installed before TOZ_BIN_SHELL existed. This permits a safe
                // upgrade without treating arbitrary content as owned.
                || {
                    let legacy = template.replace("{{TOZ_BIN_SHELL}}", "{{TOZ_BIN}}");
                    legacy != template
                        && render_at(&legacy, dir).map(|c| c == current).unwrap_or(false)
                }
    })
}

/// Reverse `install`. Owned files are deleted (and empty parent dirs up to `dir` pruned);
/// merged files have toz's entries/block removed and are deleted only if that leaves them
/// empty. Returns (path, what happened).
pub fn uninstall(b: &Bundle, dir: &Path) -> Result<Vec<(PathBuf, &'static str)>> {
    let manifest = read_manifest(dir);
    let mut out = Vec::new();
    for (rel, template, mode) in b.files {
        out.push(uninstall_file(b, dir, &manifest, rel, template, *mode)?);
    }
    // Drop the manifest last, so the dir can then prune as empty.
    let _ = std::fs::remove_file(dir.join(MANIFEST));
    let _ = std::fs::remove_file(dir.join(".toz-install.json"));
    prune_empty_dirs(Some(dir), dir);
    // The Claude Code bundle owns its whole plugin dir.
    if b.harness == "claude-code"
        && dir.exists()
        && std::fs::read_dir(dir)
            .map(|mut d| d.next().is_none())
            .unwrap_or(false)
    {
        let _ = std::fs::remove_dir(dir);
    }
    Ok(out)
}

fn uninstall_file(
    b: &Bundle,
    dir: &Path,
    manifest: &BTreeMap<String, String>,
    rel: &str,
    template: &str,
    mode: Mode,
) -> Result<(PathBuf, &'static str)> {
    let path = dir.join(rel);
    let Ok(current) = std::fs::read_to_string(&path) else {
        return Ok((path, "absent"));
    };
    let remaining: Option<String> = match mode {
        Mode::Own => {
            let installed = desired(mode, template, Some(&current), dir)?;
            if is_owned(&current, b.harness, rel, dir, &installed, manifest) {
                None
            } else {
                Some(current.clone())
            }
        }
        Mode::MergeHooks => {
            let stripped = strip_hooks(&current)?;
            (!stripped.trim().is_empty()).then_some(stripped)
        }
        Mode::MergeBlock => {
            let stripped = strip_block(&current);
            (!stripped.trim().is_empty()).then_some(stripped)
        }
    };
    match remaining {
        Some(text) if text == current => Ok((path, "untouched")),
        Some(text) => {
            std::fs::write(&path, text).with_context(|| format!("writing {}", path.display()))?;
            Ok((path, "toz entries removed"))
        }
        None => {
            std::fs::remove_file(&path).with_context(|| format!("removing {}", path.display()))?;
            prune_empty_dirs(path.parent(), dir);
            Ok((path, "removed"))
        }
    }
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
fn strip_hooks(current: &str) -> Result<String> {
    let mut doc: Value =
        serde_json::from_str(current).context("existing hooks.json is not valid JSON")?;
    let Some(events) = doc["hooks"].as_object_mut() else {
        return Ok(current.to_string());
    };
    let mut changed = false;
    let mut empty_events = Vec::new();
    for (event, list) in events.iter_mut() {
        if let Some(arr) = list.as_array_mut() {
            let before = arr.len();
            let mut removed = false;
            arr.retain_mut(|entry| {
                let (keep, entry_changed) = strip_owned_hooks(entry);
                removed |= entry_changed;
                keep
            });
            changed |= removed || arr.len() != before;
            if arr.is_empty() {
                empty_events.push(event.clone());
            }
        }
    }
    for ev in empty_events {
        events.remove(&ev);
    }
    if !changed {
        return Ok(current.to_string());
    }
    let only_hooks = doc.as_object().map(|o| o.len() == 1).unwrap_or(false);
    if only_hooks
        && doc["hooks"]
            .as_object()
            .map(|o| o.is_empty())
            .unwrap_or(false)
    {
        return Ok(String::new());
    }
    Ok(serde_json::to_string_pretty(&doc)? + "\n")
}

/// Remove the toz block (and the blank line before it) from a markdown file.
fn strip_block(current: &str) -> String {
    let current = current
        .replace("<!-- toz:start -->", BLOCK_START)
        .replace("<!-- toz:end -->", BLOCK_END);
    match (current.find(BLOCK_START), current.find(BLOCK_END)) {
        (Some(a), Some(b)) if b > a => {
            let end = b + BLOCK_END.len();
            let head = current[..a].trim_end();
            let tail = current[end..].trim_start_matches('\n');
            let mut s = head.to_string();
            if !s.is_empty() {
                s.push('\n');
                if !tail.is_empty() {
                    s.push('\n');
                }
            }
            s.push_str(tail);
            s
        }
        _ => current.to_string(),
    }
}

/// Merge toz's hook entries into an existing Claude-Code-style hooks file. For each event,
/// owned nested commands are replaced; foreign commands and entries are kept.
fn merge_hooks(current: &str, ours: &str) -> Result<String> {
    let mut doc: Value = if current.trim().is_empty() {
        json!({"hooks": {}})
    } else {
        serde_json::from_str(current).context("existing hooks.json is not valid JSON")?
    };
    let ours: Value = serde_json::from_str(ours)?;
    if !doc["hooks"].is_object() {
        doc["hooks"] = json!({});
    }
    let events = doc["hooks"].as_object_mut().unwrap();
    for (event, entries) in ours["hooks"].as_object().unwrap() {
        let list = events.entry(event.clone()).or_insert_with(|| json!([]));
        if !list.is_array() {
            *list = json!([]);
        }
        let arr = list.as_array_mut().unwrap();
        arr.retain_mut(|entry| strip_owned_hooks(entry).0);
        arr.extend(entries.as_array().unwrap().iter().cloned());
    }
    Ok(serde_json::to_string_pretty(&doc)? + "\n")
}

fn strip_owned_hooks(entry: &mut Value) -> (bool, bool) {
    let Some(hooks) = entry["hooks"].as_array_mut() else {
        return (true, false);
    };
    let before = hooks.len();
    hooks.retain(|hook| {
        !hook["command"]
            .as_str()
            .map(is_owned_hook_command)
            .unwrap_or(false)
    });
    (
        before == hooks.len() || !hooks.is_empty(),
        before != hooks.len(),
    )
}

fn is_owned_hook_command(command: &str) -> bool {
    let Some(words) = shell_words(command) else {
        return false;
    };
    let Some(exe) = words.first() else {
        return false;
    };
    if !matches!(
        Path::new(exe).file_name().and_then(|f| f.to_str()),
        Some("toz" | "varde-toz")
    ) {
        return false;
    }
    let args = match words.get(1).map(String::as_str) {
        Some("--fallback-dir") if words.len() >= 4 => &words[3..],
        _ => &words[1..],
    };
    matches!(
        args,
        [note, harness_flag, harness]
            if note == "note"
                && harness_flag == "--harness"
                && matches!(harness.as_str(), "claude-code" | "codex")
    ) || matches!(args, [capture, hook] if capture == "capture" && hook == "--hook")
        || matches!(
            args,
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

const BLOCK_START: &str = "<!-- varde-toz:start -->";
const BLOCK_END: &str = "<!-- varde-toz:end -->";

/// Insert or replace the toz block in a user-owned markdown file.
fn merge_block(current: &str, block: &str) -> String {
    let current = current
        .replace("<!-- toz:start -->", BLOCK_START)
        .replace("<!-- toz:end -->", BLOCK_END);
    let block = block.trim_end();
    match (current.find(BLOCK_START), current.find(BLOCK_END)) {
        (Some(a), Some(b)) if b > a => {
            let end = b + BLOCK_END.len();
            format!("{}{}{}", &current[..a], block, &current[end..])
        }
        _ => {
            let mut s = current.trim_end().to_string();
            if !s.is_empty() {
                s.push_str("\n\n");
            }
            s.push_str(block);
            s.push('\n');
            s
        }
    }
}

/// The usage note injected at session start. Deliberately short.
pub const NOTE: &str = "\
varde-toz (tool-output-zone) is active. Large text results from supported harness tools are captured by handle. \
Use `varde-toz query --handle <H>` to read a capture or add `\"term\"` to search. \
Batch commands with `varde-toz run --script -` and `vardeToz.exec({argv: [...]})`. \
Call other agent tools through the harness, then query any returned handle. \
Read the varde-toz skill for troubleshooting.";

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn claude_root_migration_preserves_skill_and_captures() {
        let home = tempfile::tempdir().unwrap();
        let skill = home.path().join("varde-toz/SKILL.md");
        std::fs::create_dir_all(skill.parent().unwrap()).unwrap();
        std::fs::write(&skill, "Varde skill").unwrap();
        let old = home.path().join("toz");
        install(&CLAUDE_CODE, &old, false).unwrap();
        let old_skill = old.join("skills/toz/SKILL.md");
        std::fs::create_dir_all(old_skill.parent().unwrap()).unwrap();
        std::fs::write(&old_skill, "old skill").unwrap();
        let mut manifest = read_manifest(&old);
        manifest.insert(
            "skills/toz/SKILL.md".into(),
            toz_core::content_hash(b"old skill"),
        );
        write_manifest(&old, &manifest).unwrap();
        let captures = old.join("tool-output-zone");
        std::fs::create_dir_all(&captures).unwrap();
        std::fs::write(captures.join("toz.db"), "capture fixture").unwrap();
        let new = home.path().join("varde-toz-hooks");
        install(&CLAUDE_CODE, &new, false).unwrap();
        assert!(!old.exists());
        assert!(!new.join("skills/toz").exists());
        assert_eq!(std::fs::read_to_string(&skill).unwrap(), "Varde skill");
        assert_eq!(
            std::fs::read_to_string(new.join("tool-output-zone/toz.db")).unwrap(),
            "capture fixture"
        );
        install(&CLAUDE_CODE, &new, false).unwrap();
        let old = home.path().join("toz");
        std::fs::create_dir_all(old.join("hooks")).unwrap();
        std::fs::write(old.join("hooks/hooks.json"), "custom").unwrap();
        assert!(install(&CLAUDE_CODE, &new, false).is_err());
    }

    #[test]
    fn legacy_shared_blocks_are_replaced_and_removed() {
        let old = "before\n\n<!-- toz:start -->\nold\n<!-- toz:end -->\nafter\n";
        let block = "<!-- varde-toz:start -->\nnew\n<!-- varde-toz:end -->";
        let merged = merge_block(old, block);
        assert!(!merged.contains("<!-- toz:"));
        assert_eq!(merged.matches(BLOCK_START).count(), 1);
        assert_eq!(strip_block(old), "before\n\nafter\n");
        assert_eq!(strip_block(&merged), "before\n\nafter\n");
    }

    #[test]
    fn legacy_adapters_migrate_only_when_owned() {
        for b in [&PI, &OPENCODE_V1, &OPENCODE] {
            let dir = tempfile::tempdir().unwrap();
            let old = if b.harness == "pi" {
                "extensions/toz.ts"
            } else {
                "plugin/toz.ts"
            };
            let new = old.replace("/toz.ts", "/varde-toz.ts");
            std::fs::create_dir_all(dir.path().join(old).parent().unwrap()).unwrap();
            std::fs::write(dir.path().join(old), "owned old adapter").unwrap();
            let manifest = BTreeMap::from([(
                old.to_string(),
                toz_core::content_hash(b"owned old adapter"),
            )]);
            std::fs::write(
                dir.path().join(".toz-install.json"),
                serde_json::to_string(&json!({"files":manifest})).unwrap(),
            )
            .unwrap();
            install(b, dir.path(), false).unwrap();
            assert!(!dir.path().join(old).exists());
            assert!(dir.path().join(&new).exists());
            install(b, dir.path(), false).unwrap();
            std::fs::write(dir.path().join(old), "custom adapter").unwrap();
            assert!(install(b, dir.path(), false).is_err());
            assert_eq!(
                std::fs::read_to_string(dir.path().join(old)).unwrap(),
                "custom adapter"
            );
        }
    }

    #[test]
    fn adapters_leave_skill_installation_to_varde() {
        for bundle in [&CLAUDE_CODE, &PI, &OPENCODE_V1, &OPENCODE, &CODEX] {
            let dir = tempfile::tempdir().unwrap();
            let skill = dir.path().join("skills/varde-toz/SKILL.md");
            std::fs::create_dir_all(skill.parent().unwrap()).unwrap();
            std::fs::write(&skill, "Varde-owned skill\n").unwrap();
            install(bundle, dir.path(), false).unwrap();
            assert!(
                !dir.path().join("skills/toz").exists(),
                "{} installed a standalone skill",
                bundle.harness
            );
            assert_eq!(
                std::fs::read_to_string(&skill).unwrap(),
                "Varde-owned skill\n"
            );
            uninstall(bundle, dir.path()).unwrap();
            assert_eq!(
                std::fs::read_to_string(&skill).unwrap(),
                "Varde-owned skill\n"
            );
        }
    }

    const HOOK_REL: &str = "hooks/hooks.json";

    /// The regression this manifest exists for: editing a bundled template used to make every
    /// existing install look hand-edited, so `doctor` said "run toz install" and install refused.
    #[test]
    fn a_template_change_does_not_make_an_existing_install_unowned() {
        let dir = tempfile::tempdir().unwrap();
        install(&CLAUDE_CODE, dir.path(), false).unwrap();

        // Stand in for the next release editing the template: the file is still exactly what toz
        // wrote, it just no longer matches the compiled-in text.
        let path = dir.path().join(HOOK_REL);
        let older = "{\"hooks\":{}}\n";
        std::fs::write(&path, older).unwrap();
        let mut manifest = read_manifest(dir.path());
        manifest.insert(
            HOOK_REL.to_string(),
            toz_core::content_hash(older.as_bytes()),
        );
        write_manifest(dir.path(), &manifest).unwrap();

        install(&CLAUDE_CODE, dir.path(), false)
            .expect("upgrade must not refuse a file toz itself wrote");
        assert!(std::fs::read_to_string(&path).unwrap().contains("toz"));
        assert!(unowned_files(&CLAUDE_CODE, dir.path()).is_empty());
    }

    #[test]
    fn a_hand_edited_file_is_still_refused_and_force_overrides() {
        let dir = tempfile::tempdir().unwrap();
        install(&CLAUDE_CODE, dir.path(), false).unwrap();

        let path = dir.path().join(HOOK_REL);
        std::fs::write(&path, "my own notes, not toz's\n").unwrap();

        let err = install(&CLAUDE_CODE, dir.path(), false).unwrap_err();
        assert!(format!("{err:#}").contains("hand-edited"), "{err:#}");
        assert_eq!(unowned_files(&CLAUDE_CODE, dir.path()), vec![HOOK_REL]);

        install(&CLAUDE_CODE, dir.path(), true).expect("--force replaces it");
        assert!(unowned_files(&CLAUDE_CODE, dir.path()).is_empty());
    }

    #[test]
    fn install_is_idempotent_and_records_every_owned_file() {
        let dir = tempfile::tempdir().unwrap();
        install(&CLAUDE_CODE, dir.path(), false).unwrap();
        let manifest = read_manifest(dir.path());
        let owned: Vec<_> = CLAUDE_CODE
            .files
            .iter()
            .filter(|(_, _, m)| *m == Mode::Own)
            .map(|(rel, _, _)| rel.to_string())
            .collect();
        for rel in &owned {
            assert!(manifest.contains_key(rel), "{rel} missing from manifest");
        }
        let second = install(&CLAUDE_CODE, dir.path(), false).unwrap();
        assert!(
            second.iter().all(|(_, changed)| !changed),
            "second install rewrote files"
        );
    }

    #[test]
    fn uninstall_removes_the_manifest() {
        let dir = tempfile::tempdir().unwrap();
        install(&CLAUDE_CODE, dir.path(), false).unwrap();
        assert!(dir.path().join(MANIFEST).exists());
        uninstall(&CLAUDE_CODE, dir.path()).unwrap();
        assert!(!dir.path().join(MANIFEST).exists());
    }

    #[test]
    fn hooks_merge_keeps_foreign_entries_and_is_idempotent() {
        let existing = r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"/x/orca-hook.sh"}]}],"Stop":[{"hooks":[{"type":"command","command":"echo bye"}]}]}}"#;
        let ours = render(include_str!("../assets/codex/hooks.json")).unwrap();
        let once = merge_hooks(existing, &ours).unwrap();
        let twice = merge_hooks(&once, &ours).unwrap();
        assert_eq!(once, twice);
        let v: Value = serde_json::from_str(&once).unwrap();
        assert_eq!(v["hooks"]["PostToolUse"].as_array().unwrap().len(), 2);
        assert_eq!(v["hooks"]["SessionStart"].as_array().unwrap().len(), 1);
        assert_eq!(v["hooks"]["Stop"][0]["hooks"][0]["command"], "echo bye");
        assert!(once.contains("note --harness codex"));
        assert!(once.contains("capture --hook --harness codex"));
    }

    #[test]
    fn mixed_hook_entry_keeps_foreign_command_on_merge_and_strip() {
        let existing = r#"{"hooks":{"PostToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"toz capture --hook --harness codex"},{"type":"command","command":"echo foreign"}]}]}}"#;
        let ours = render(include_str!("../assets/codex/hooks.json")).unwrap();
        let merged = merge_hooks(existing, &ours).unwrap();
        let merged_doc: Value = serde_json::from_str(&merged).unwrap();
        assert!(merged_doc["hooks"]["PostToolUse"]
            .as_array()
            .unwrap()
            .iter()
            .any(|entry| entry["matcher"] == "Bash"
                && entry["hooks"][0]["command"] == "echo foreign"));
        let stripped: Value = serde_json::from_str(&strip_hooks(existing).unwrap()).unwrap();
        assert_eq!(stripped["hooks"]["PostToolUse"][0]["matcher"], "Bash");
        assert_eq!(
            stripped["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
            "echo foreign"
        );
    }

    #[test]
    fn block_merge_replaces_in_place() {
        let block = "<!-- varde-toz:start -->\nnew\n<!-- varde-toz:end -->";
        let fresh = merge_block("# Mine\n\nkeep\n", block);
        assert_eq!(
            fresh,
            "# Mine\n\nkeep\n\n<!-- varde-toz:start -->\nnew\n<!-- varde-toz:end -->\n"
        );
        let updated = merge_block(&fresh.replace("new", "old"), block);
        assert_eq!(updated, fresh);
        assert_eq!(merge_block("", block), format!("{block}\n"));
    }

    #[test]
    fn strip_hooks_and_block_reverse_merge() {
        let existing =
            r#"{"hooks":{"Stop":[{"hooks":[{"type":"command","command":"echo bye"}]}]}}"#;
        let ours = render(include_str!("../assets/codex/hooks.json")).unwrap();
        let merged = merge_hooks(existing, &ours).unwrap();
        let back: Value = serde_json::from_str(&strip_hooks(&merged).unwrap()).unwrap();
        assert_eq!(back, serde_json::from_str::<Value>(existing).unwrap());
        // Only toz hooks → file becomes empty → caller deletes it.
        let only = merge_hooks("", &ours).unwrap();
        assert_eq!(strip_hooks(&only).unwrap(), "");

        let block = "<!-- varde-toz:start -->\nnew\n<!-- varde-toz:end -->";
        let doc = merge_block("# Mine\n\nkeep\n", block);
        assert_eq!(strip_block(&doc), "# Mine\n\nkeep\n");
        assert_eq!(strip_block(&merge_block("", block)), "");
        let mid = format!("top\n\n{block}\n\nbottom\n");
        assert_eq!(strip_block(&mid), "top\n\nbottom\n");
    }

    #[test]
    fn parses_harness_version_strings() {
        assert_eq!(parse_version("2.1.267 (Claude Code)"), Some((2, 1, 267)));
        assert_eq!(parse_version("opencode v2.0.12\n"), Some((2, 0, 12)));
        assert_eq!(parse_version("codex-cli 0.147.0"), Some((0, 147, 0)));
        assert_eq!(parse_version("Warning: blah\n0.84.2"), Some((0, 84, 2)));
        assert_eq!(parse_version("1.2.3-beta.1"), Some((1, 2, 3)));
        assert_eq!(parse_version("nope"), None);
    }

    #[test]
    fn note_json_renders_as_string_literal() {
        let r = render("const N = {{TOZ_NOTE_JSON}};").unwrap();
        assert!(r.starts_with("const N = \"varde-toz (tool-output-zone)"));
        assert!(r.ends_with("\";"));
        assert_eq!(render("const N = \"{{TOZ_NOTE_JSON}}\";").unwrap(), r);
        assert_eq!(
            render("const F = \"{{TOZ_FALLBACK_JSON}}\";").unwrap(),
            render("const F = {{TOZ_FALLBACK_JSON}};").unwrap()
        );
    }

    #[test]
    fn resolve_picks_the_variant_for_the_installed_harness_version() {
        let oc = bundle("opencode").unwrap();
        assert!(std::ptr::eq(resolve(oc, Some((2, 0, 12))), oc));
        let v1 = resolve(oc, Some((1, 17, 7)));
        assert!(!std::ptr::eq(v1, oc));
        assert_eq!(v1.min_version, (1, 2, 0));
        // Older than every variant: the oldest shim is still the best guess.
        assert!(std::ptr::eq(resolve(oc, Some((1, 0, 0))), v1));
        // Harnesses with a single variant always resolve to themselves.
        let pi = bundle("pi").unwrap();
        assert!(std::ptr::eq(resolve(pi, Some((0, 1, 0))), pi));
    }

    #[test]
    fn own_files_refuse_collisions_and_preserve_modifications() {
        let dir = tempfile::tempdir().unwrap();
        let bundle = Bundle {
            harness: "test",
            default_dir: || Ok(PathBuf::new()),
            files: &[("owned.txt", "installed\n", Mode::Own)],
            after: "",
            binary: "test",
            min_version: (0, 0, 0),
            why_min: "test",
            older: None,
        };
        let path = dir.path().join("owned.txt");
        std::fs::write(&path, "foreign\n").unwrap();
        let error = install(&bundle, dir.path(), false).unwrap_err().to_string();
        assert!(error.contains("refusing to overwrite"));
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "foreign\n");

        std::fs::remove_file(&path).unwrap();
        install(&bundle, dir.path(), false).unwrap();
        std::fs::write(&path, "modified\n").unwrap();
        let result = uninstall(&bundle, dir.path()).unwrap();
        assert_eq!(result[0].1, "untouched");
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "modified\n");
    }

    #[test]
    fn install_checks_every_collision_before_writing_any_bundle_file() {
        let dir = tempfile::tempdir().unwrap();
        let bundle = Bundle {
            harness: "test",
            default_dir: || Ok(PathBuf::new()),
            files: &[
                ("first.txt", "installed first\n", Mode::Own),
                ("second.txt", "installed second\n", Mode::Own),
            ],
            after: "",
            binary: "test",
            min_version: (0, 0, 0),
            why_min: "test",
            older: None,
        };
        std::fs::write(dir.path().join("second.txt"), "foreign\n").unwrap();

        let error = install(&bundle, dir.path(), false).unwrap_err().to_string();
        assert!(error.contains("refusing to overwrite"));
        assert!(!dir.path().join("first.txt").exists());
        assert!(!dir.path().join(MANIFEST).exists());
        assert_eq!(
            std::fs::read_to_string(dir.path().join("second.txt")).unwrap(),
            "foreign\n"
        );
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
        ] {
            assert!(!is_owned_hook_command(command), "{command}");
        }
        assert!(is_owned_hook_command("toz capture --hook --harness codex"));
        assert!(is_owned_hook_command(
            "varde-toz capture --hook --harness codex"
        ));
        assert!(is_owned_hook_command(
            "'/tmp/a path/toz' --fallback-dir '/tmp/x' note --harness codex"
        ));

        let foreign = r#"{"hooks":{"PostToolUse":[{"hooks":[{"type":"command","command":"toz-helper capture --hook"}]}]}}"#;
        let ours = render(include_str!("../assets/codex/hooks.json")).unwrap();
        let merged = merge_hooks(foreign, &ours).unwrap();
        assert!(merged.contains("toz-helper capture --hook"));
        let stripped = strip_hooks(&merged).unwrap();
        assert_eq!(
            serde_json::from_str::<Value>(&stripped).unwrap(),
            serde_json::from_str::<Value>(foreign).unwrap()
        );
    }

    #[test]
    fn shell_hook_binary_path_is_quoted() {
        let rendered = render_with_exe(
            "{{TOZ_BIN_SHELL}} capture --hook; const TOZ = \"{{TOZ_BIN}}\";",
            Path::new("/tmp/install"),
            Path::new("/tmp/a path/it's-toz"),
        )
        .unwrap();
        assert_eq!(
            rendered,
            "'/tmp/a path/it'\\''s-toz' capture --hook; const TOZ = \"/tmp/a path/it's-toz\";"
        );
    }
}
