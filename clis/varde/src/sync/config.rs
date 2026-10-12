use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::path::{Path, PathBuf};

use varde_workflow_core::memory::Config;

#[derive(Debug, Default)]
pub struct SavedSettings {
    pub skills_dir: Option<PathBuf>,
    pub agents_dir: Option<PathBuf>,
    pub link_mode: Option<String>,
    pub skills: Option<Vec<String>>,
}

pub fn validate_skills(names: &[String]) -> Result<(), String> {
    let valid = super::embedded::skills()
        .iter()
        .map(|skill| skill.name)
        .collect::<Vec<_>>();
    if let Some(name) = names.iter().find(|name| !valid.contains(&name.as_str())) {
        return Err(format!(
            "unknown skill {name}; valid skills: {}",
            valid.join(", ")
        ));
    }
    Ok(())
}

/// The embedded `skills/presets.json`, copied into `OUT_DIR` by `build.rs`.
const PRESETS_JSON: &str = include_str!(concat!(env!("OUT_DIR"), "/presets.json"));

/// The embedded `skills/presets.json` as preset name -> skill names.
fn presets() -> Result<BTreeMap<String, Vec<String>>, String> {
    let value: serde_json::Value = serde_json::from_str(PRESETS_JSON)
        .map_err(|error| format!("embedded skills/presets.json is invalid: {error}"))?;
    let table = value
        .as_object()
        .ok_or_else(|| "embedded skills/presets.json must be an object".to_string())?;
    let mut presets = BTreeMap::new();
    for (name, entry) in table {
        let skills = entry
            .get("skills")
            .and_then(serde_json::Value::as_array)
            .ok_or_else(|| format!("preset {name} must list skills"))?
            .iter()
            .map(|value| {
                value
                    .as_str()
                    .map(str::to_owned)
                    .ok_or_else(|| format!("preset {name} skills must be strings"))
            })
            .collect::<Result<Vec<_>, _>>()?;
        presets.insert(name.clone(), skills);
    }
    Ok(presets)
}

/// Every preset name, sorted.
pub fn preset_names() -> Result<Vec<String>, String> {
    Ok(presets()?.into_keys().collect())
}

/// The `--preset` help text, listing every preset name.
pub fn preset_help() -> String {
    format!(
        "Preset of skills to install (combines with --skills): {}",
        preset_names().unwrap_or_default().join(", ")
    )
}

/// The skills one preset names, or an error listing every valid preset. An
/// empty list selects every shipped skill: the caller installs all and saves
/// no selection, so `full` tracks skills added by later releases.
pub fn preset_skills(name: &str) -> Result<Vec<String>, String> {
    let presets = presets()?;
    let skills = presets.get(name).ok_or_else(|| {
        format!(
            "unknown preset {name}; valid presets: {}",
            presets.keys().cloned().collect::<Vec<_>>().join(", ")
        )
    })?;
    validate_skills(skills)?;
    Ok(skills.clone())
}

pub fn read(config: &Config) -> Result<SavedSettings, String> {
    let Some(value) = config.unknown.get("sync") else {
        return Ok(SavedSettings::default());
    };
    let table = value
        .as_table()
        .ok_or_else(|| "the [sync] config must be a table".to_string())?;

    let path = |key: &str| -> Result<Option<PathBuf>, String> {
        table
            .get(key)
            .map(|value| {
                value
                    .as_str()
                    .map(PathBuf::from)
                    .ok_or_else(|| format!("[sync].{key} must be a string"))
            })
            .transpose()
    };
    let link_mode = table
        .get("link_mode")
        .map(|value| {
            value
                .as_str()
                .map(str::to_owned)
                .ok_or_else(|| "[sync].link_mode must be a string".to_string())
        })
        .transpose()?;
    let skills = table
        .get("skills")
        .map(|value| {
            let values = value
                .as_array()
                .ok_or_else(|| "[sync].skills must be an array of strings".to_string())?;
            let names = values
                .iter()
                .map(|value| {
                    value
                        .as_str()
                        .map(str::to_owned)
                        .ok_or_else(|| "[sync].skills must be an array of strings".to_string())
                })
                .collect::<Result<Vec<_>, _>>()?;
            validate_skills(&names)?;
            Ok::<Vec<String>, String>(names)
        })
        .transpose()?;

    Ok(SavedSettings {
        skills_dir: path("skills_dir")?,
        agents_dir: path("agents_dir")?,
        link_mode,
        skills,
    })
}

/// Config aliases kept during the session-notes transition.
pub fn deprecated_session_notes_aliases(config: &Config) -> Vec<&'static str> {
    let mut aliases = Vec::new();
    if config
        .hooks
        .post_tool_use
        .providers
        .as_ref()
        .is_some_and(|providers| {
            providers
                .iter()
                .any(|provider| provider == "context_handoff")
        })
    {
        aliases.push("context_handoff -> session_notes");
    }
    if config
        .unknown
        .get("session")
        .and_then(toml::Value::as_table)
        .is_some_and(|session| session.contains_key("handoff_at_tokens"))
    {
        aliases.push("[session].handoff_at_tokens -> [session].notes_at_tokens (new key wins)");
    }
    aliases
}

pub fn write(
    config: &mut Config,
    skills_dir: &Path,
    agents_dir: &Path,
    link_mode: &str,
    skills: Option<&[String]>,
) {
    let mut table = config
        .unknown
        .get("sync")
        .and_then(toml::Value::as_table)
        .cloned()
        .unwrap_or_default();
    table.insert(
        "skills_dir".to_string(),
        toml::Value::String(skills_dir.to_string_lossy().into_owned()),
    );
    table.insert(
        "agents_dir".to_string(),
        toml::Value::String(agents_dir.to_string_lossy().into_owned()),
    );
    table.insert(
        "link_mode".to_string(),
        toml::Value::String(link_mode.to_string()),
    );
    match skills {
        Some(skills) if !skills.is_empty() => {
            table.insert(
                "skills".to_string(),
                toml::Value::Array(skills.iter().cloned().map(toml::Value::String).collect()),
            );
        }
        Some(_) => {
            table.remove("skills");
        }
        None => {}
    }
    config
        .unknown
        .insert("sync".to_string(), toml::Value::Table(table));
}

const SESSION_START_COMMENT: &str = "\
# Providers that run when an agent session starts, in order.
#   nav_map        - injects the knowledge navigation map (default)
#   toz_note       - injects the tool-output-zone usage note (default)
#   orchestration  - injects the orchestration guidance
# Defaults: providers = [\"nav_map\", \"toz_note\"]
# Setup sync writes providers for the selected skills. Edit to override:
# providers = [\"nav_map\", \"toz_note\"]
";

const POST_TOOL_USE_COMMENT: &str = "\
# Providers that run after each tool call, in order.
#   capture          - captures large tool output by handle (default)
#   session_notes    - nudges once per context-threshold crossing (default)
#   context_handoff  - deprecated alias for session_notes
# Defaults: providers = [\"capture\", \"session_notes\"]
# Setup sync writes providers for the selected skills. Edit to override:
# providers = [\"capture\", \"session_notes\"]

# Absolute token threshold for session-notes nudges. Set to 0 to disable.
# [session]
# notes_at_tokens = 250000
# handoff_at_tokens = 250000 # deprecated alias; notes_at_tokens takes precedence
";

/// Add the `[hooks.session_start]` and `[hooks.post_tool_use]` tables, each
/// preceded by comments describing its providers, when absent. Existing
/// `[hooks]` entries are never rewritten. Returns whether the file changed.
pub fn seed_hooks(path: &Path, features: &BTreeSet<&'static str>) -> Result<bool, String> {
    let text = match std::fs::read_to_string(path) {
        Ok(text) => text,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => String::new(),
        Err(error) => return Err(format!("could not read {}: {error}", path.display())),
    };
    let mut document = text
        .parse::<toml_edit::DocumentMut>()
        .map_err(|error| format!("could not parse {}: {error}", path.display()))?;
    let hooks = document
        .entry("hooks")
        .or_insert_with(|| {
            let mut table = toml_edit::Table::new();
            table.set_implicit(true);
            toml_edit::Item::Table(table)
        })
        .as_table_mut()
        .ok_or_else(|| "the [hooks] config must be a table".to_string())?;
    let mut changed = false;
    let session = [
        ("nav_map", features.contains("code")),
        ("toz_note", features.contains("toz")),
    ];
    let post = [
        ("capture", features.contains("toz")),
        (
            "session_notes",
            features.contains("knowledge") || features.contains("change"),
        ),
    ];
    let inbox = [("inbox", features.contains("change"))];
    for (name, comment, providers) in [
        ("session_start", SESSION_START_COMMENT, session.as_slice()),
        ("post_tool_use", POST_TOOL_USE_COMMENT, post.as_slice()),
        (
            "user_prompt_submit",
            "# Inbox hook providers.\n",
            inbox.as_slice(),
        ),
    ] {
        if !hooks.contains_key(name) {
            let mut table = toml_edit::Table::new();
            table.decor_mut().set_prefix(format!("\n{comment}"));
            let mut selected = toml_edit::Array::new();
            for (provider, _) in providers.iter().filter(|(_, enabled)| *enabled) {
                selected.push(*provider);
            }
            table.insert("providers", toml_edit::value(selected));
            hooks.insert(name, toml_edit::Item::Table(table));
            changed = true;
            continue;
        }
        let table = hooks
            .get_mut(name)
            .and_then(toml_edit::Item::as_table_mut)
            .ok_or_else(|| format!("[hooks.{name}] config must be a table"))?;
        if table.contains_key("providers") {
            continue;
        }
        let mut selected = toml_edit::Array::new();
        for (provider, _) in providers.iter().filter(|(_, enabled)| *enabled) {
            selected.push(*provider);
        }
        table.insert("providers", toml_edit::value(selected));
        changed = true;
    }
    if !changed {
        return Ok(false);
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|error| format!("could not create {}: {error}", parent.display()))?;
    }
    std::fs::write(path, document.to_string())
        .map_err(|error| format!("could not write {}: {error}", path.display()))?;
    Ok(true)
}
