use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::str::FromStr;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum HarnessId {
    Claude,
    Codex,
    OpenCode,
    Pi,
}

impl HarnessId {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Claude => "claude",
            Self::Codex => "codex",
            Self::OpenCode => "opencode",
            Self::Pi => "pi",
        }
    }
}

impl FromStr for HarnessId {
    type Err = String;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        match value {
            "claude" => Ok(Self::Claude),
            "codex" => Ok(Self::Codex),
            "opencode" => Ok(Self::OpenCode),
            "pi" => Ok(Self::Pi),
            _ => Err(format!("unknown harness id: {value}")),
        }
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Harness {
    pub id: HarnessId,
    pub skills_dir: Option<PathBuf>,
    pub agents_dir: PathBuf,
}

fn layout(id: HarnessId, home: &Path, pi_agent_dir: Option<&Path>) -> Harness {
    match id {
        HarnessId::Claude => Harness {
            id,
            skills_dir: Some(home.join(".claude/skills")),
            agents_dir: home.join(".claude/agents"),
        },
        HarnessId::Codex => Harness {
            id,
            skills_dir: Some(home.join(".codex/skills")),
            agents_dir: home.join(".codex/agents"),
        },
        HarnessId::OpenCode => Harness {
            id,
            skills_dir: Some(home.join(".config/opencode/skills")),
            agents_dir: home.join(".config/opencode/agents"),
        },
        HarnessId::Pi => Harness {
            id,
            skills_dir: None,
            agents_dir: pi_agent_dir
                .map(Path::to_path_buf)
                .unwrap_or_else(|| home.join(".pi/agent"))
                .join("agents"),
        },
    }
}

fn all(home: &Path, pi_agent_dir: Option<&Path>) -> [Harness; 4] {
    [
        layout(HarnessId::Claude, home, pi_agent_dir),
        layout(HarnessId::Codex, home, pi_agent_dir),
        layout(HarnessId::OpenCode, home, pi_agent_dir),
        layout(HarnessId::Pi, home, pi_agent_dir),
    ]
}

pub fn detect(home: &Path, pi_agent_dir: Option<&Path>) -> Vec<Harness> {
    all(home, pi_agent_dir)
        .into_iter()
        .filter(|harness| match harness.id {
            HarnessId::Claude => home.join(".claude").is_dir(),
            HarnessId::Codex => home.join(".codex").is_dir(),
            HarnessId::OpenCode => home.join(".config/opencode").is_dir(),
            HarnessId::Pi => {
                home.join(".pi").is_dir()
                    || pi_agent_dir.is_some_and(|path| !path.as_os_str().is_empty())
            }
        })
        .collect()
}

pub fn select(ids: &[HarnessId], home: &Path, pi_agent_dir: Option<&Path>) -> Vec<Harness> {
    all(home, pi_agent_dir)
        .into_iter()
        .filter(|harness| ids.contains(&harness.id))
        .collect()
}

/// Commands that still reference an installed legacy Varde binary in a
/// supported harness hook file. These references let the final migration
/// report protect binaries when a hook could not be rewritten or was not
/// selected for migration.
pub fn remaining_legacy_hook_commands(
    env: &crate::migrate::MigrateEnv,
    pi_agent_dir: Option<&Path>,
) -> Vec<(PathBuf, String)> {
    let default_xdg = env.home.join(".config");
    let xdg = env.xdg_config_home.as_deref().unwrap_or(&default_xdg);
    let pi = pi_agent_dir
        .map(Path::to_path_buf)
        .unwrap_or_else(|| env.home.join(".pi/agent"));
    let files = [
        env.home.join(".claude/settings.json"),
        env.home.join(".claude/skills/toz/hooks/hooks.json"),
        env.home
            .join(".claude/skills/varde-toz-hooks/hooks/hooks.json"),
        env.home.join(".codex/config.toml"),
        env.home.join(".codex/hooks.json"),
        env.home
            .join(".config/opencode/plugin/varde-code-nav-map.js"),
        xdg.join("opencode/plugin/toz.ts"),
        xdg.join("opencode/plugin/varde-toz.ts"),
        xdg.join("opencode/plugin/varde-session.ts"),
        pi.join("extensions/pi-extension.js"),
        pi.join("extensions/toz.ts"),
        pi.join("extensions/varde-toz.ts"),
        pi.join("extensions/varde-session.ts"),
    ];
    let bin_dir = env.cargo_install_root.join("bin");
    let Ok(entries) = fs::read_dir(bin_dir) else {
        return Vec::new();
    };
    let names = entries
        .filter_map(Result::ok)
        .map(|entry| entry.file_name())
        .filter_map(|name| name.to_str().map(str::to_owned))
        .filter(|name| name.starts_with("varde-") || name == "toz")
        .collect::<Vec<_>>();
    if names.is_empty() {
        return Vec::new();
    }

    let mut commands = BTreeSet::new();
    for path in files {
        let Ok(contents) = fs::read_to_string(&path) else {
            continue;
        };
        let values = match path.extension().and_then(|extension| extension.to_str()) {
            Some("json") => serde_json::from_str::<serde_json::Value>(&contents)
                .map(|value| json_commands(&value))
                .unwrap_or_else(|_| active_command_lines(&contents)),
            Some("toml") => toml::from_str::<toml::Value>(&contents)
                .map(|value| toml_commands(&value))
                .unwrap_or_else(|_| active_command_lines(&contents)),
            _ => active_command_lines(&contents),
        };
        for command in values {
            if names.iter().any(|name| mentions_binary(&command, name)) {
                commands.insert((path.clone(), command));
            }
        }
    }
    commands.into_iter().collect()
}

fn active_command_lines(contents: &str) -> Vec<String> {
    contents
        .lines()
        .filter(|line| {
            let line = line.trim();
            !line.is_empty() && !line.starts_with("//")
        })
        .map(str::to_owned)
        .collect()
}

fn json_commands(value: &serde_json::Value) -> Vec<String> {
    match value {
        serde_json::Value::Object(object) => object
            .iter()
            .flat_map(|(key, child)| {
                if key == "command" {
                    match child {
                        serde_json::Value::String(command) => vec![command.clone()],
                        _ => json_commands(child),
                    }
                } else {
                    json_commands(child)
                }
            })
            .collect(),
        serde_json::Value::Array(array) => array.iter().flat_map(json_commands).collect(),
        _ => Vec::new(),
    }
}

fn toml_commands(value: &toml::Value) -> Vec<String> {
    match value {
        toml::Value::Table(table) => table
            .iter()
            .flat_map(|(key, child)| {
                if key == "command" {
                    child
                        .as_str()
                        .map(str::to_owned)
                        .into_iter()
                        .collect::<Vec<_>>()
                } else {
                    toml_commands(child)
                }
            })
            .collect(),
        toml::Value::Array(array) => array.iter().flat_map(toml_commands).collect(),
        _ => Vec::new(),
    }
}

fn mentions_binary(command: &str, name: &str) -> bool {
    command
        .split(|character: char| {
            !(character.is_ascii_alphanumeric() || character == '_' || character == '-')
        })
        .any(|part| part == name)
}
