//! Declarative workflow schema resolution.

use anyhow::{Context, Result, bail};
use okf_core::memory::{self, MemoryPaths};
use serde_json::{Value as JsonValue, json};
use serde_yaml::{Mapping, Value as YamlValue};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

pub const SCHEMA_VERSION: u64 = 1;
const OVERRIDE_PATH: &str = "workflow/schema.yml";

#[derive(Debug, Clone)]
pub struct ArtifactTypeSchema {
    pub initial_state: String,
    pub states: BTreeSet<String>,
    pub completion_states: BTreeSet<String>,
    pub transitions: BTreeMap<String, BTreeSet<String>>,
}

#[derive(Debug, Clone)]
pub struct WorkflowSchema {
    pub artifact_types: BTreeMap<String, ArtifactTypeSchema>,
    pub project_schema: Option<PathBuf>,
}

impl WorkflowSchema {
    pub fn resolve(artifact: &Path) -> Result<Self> {
        let mut schema = built_in();
        let Some(root) = project_root(artifact) else {
            return Ok(schema);
        };
        let path = MemoryPaths::resolve(&root)?
            .knowledge
            .path
            .join(OVERRIDE_PATH);
        if !path.exists() {
            return Ok(schema);
        }
        let bytes = std::fs::read(&path)
            .with_context(|| format!("failed to read workflow schema {}", path.display()))?;
        let value: YamlValue = serde_yaml::from_slice(&bytes)
            .with_context(|| format!("failed to parse workflow schema {}", path.display()))?;
        merge_override(&mut schema, &value)?;
        schema.project_schema = Some(path);
        Ok(schema)
    }

    pub fn artifact_type(&self, name: &str) -> Result<&ArtifactTypeSchema> {
        self.artifact_types
            .get(name)
            .with_context(|| format!("unknown workflow artifact type `{name}`"))
    }

    pub fn to_json(&self) -> JsonValue {
        let artifact_types = self
            .artifact_types
            .iter()
            .map(|(name, state)| {
                let transitions = state
                    .transitions
                    .iter()
                    .map(|(from, targets)| {
                        (from.clone(), json!(targets.iter().collect::<Vec<_>>()))
                    })
                    .collect::<serde_json::Map<_, _>>();
                (
                    name.clone(),
                    json!({
                        "initial_state": state.initial_state,
                        "states": state.states.iter().collect::<Vec<_>>(),
                        "completion_states": state.completion_states.iter().collect::<Vec<_>>(),
                        "transitions": transitions,
                    }),
                )
            })
            .collect::<serde_json::Map<_, _>>();
        json!({
            "schema_version": SCHEMA_VERSION,
            "artifact_types": artifact_types,
            "project_schema": self.project_schema,
        })
    }
}

fn built_in() -> WorkflowSchema {
    let mut artifact_types = BTreeMap::new();
    artifact_types.insert(
        "plan".to_string(),
        state_machine(
            "backlog",
            &["active", "backlog", "blocked", "completed"],
            &["completed"],
            &[
                ("backlog", &["active", "blocked"]),
                ("active", &["blocked", "completed"]),
                ("blocked", &["active"]),
                ("completed", &[]),
            ],
        ),
    );
    artifact_types.insert(
        "task".to_string(),
        state_machine(
            "todo",
            &["blocked", "done", "in_progress", "todo"],
            &["done"],
            &[
                ("todo", &["blocked", "in_progress"]),
                ("in_progress", &["blocked", "done"]),
                ("blocked", &["in_progress"]),
                ("done", &[]),
            ],
        ),
    );
    WorkflowSchema {
        artifact_types,
        project_schema: None,
    }
}

fn state_machine(
    initial_state: &str,
    states: &[&str],
    completion_states: &[&str],
    transitions: &[(&str, &[&str])],
) -> ArtifactTypeSchema {
    ArtifactTypeSchema {
        initial_state: initial_state.to_string(),
        states: strings(states),
        completion_states: strings(completion_states),
        transitions: transitions
            .iter()
            .map(|(from, targets)| (from.to_string(), strings(targets)))
            .collect(),
    }
}

fn strings(values: &[&str]) -> BTreeSet<String> {
    values.iter().map(|value| value.to_string()).collect()
}

fn merge_override(schema: &mut WorkflowSchema, value: &YamlValue) -> Result<()> {
    let mapping = value
        .as_mapping()
        .context("workflow schema must be a mapping")?;
    let version = mapping
        .get(key("schema_version"))
        .and_then(YamlValue::as_u64)
        .context("workflow schema requires `schema_version`")?;
    if version != SCHEMA_VERSION {
        bail!("unsupported workflow schema version {version}");
    }
    let additions = mapping
        .get(key("artifact_types"))
        .and_then(YamlValue::as_mapping)
        .context("workflow schema requires `artifact_types` mapping")?;

    for (name, definition) in additions {
        let name = name
            .as_str()
            .context("workflow artifact type names must be strings")?;
        if schema.artifact_types.contains_key(name) {
            bail!("project schema cannot replace core artifact type `{name}`");
        }
        let parsed = parse_artifact_type(name, definition)?;
        schema.artifact_types.insert(name.to_string(), parsed);
    }
    Ok(())
}

fn parse_artifact_type(name: &str, value: &YamlValue) -> Result<ArtifactTypeSchema> {
    let mapping = value
        .as_mapping()
        .with_context(|| format!("artifact type `{name}` must be a mapping"))?;
    let initial_state = required_string(mapping, "initial_state")?;
    let states = required_strings(mapping, "states")?;
    let completion_states = required_strings(mapping, "completion_states")?;
    if !states.contains(&initial_state) {
        bail!("artifact type `{name}` has an unknown initial state `{initial_state}`");
    }
    for state in &completion_states {
        if !states.contains(state) {
            bail!("artifact type `{name}` has an unknown completion state `{state}`");
        }
    }

    let transition_values = mapping
        .get(key("transitions"))
        .and_then(YamlValue::as_mapping)
        .with_context(|| format!("artifact type `{name}` requires `transitions` mapping"))?;
    let mut transitions = BTreeMap::new();
    for (from, targets) in transition_values {
        let from = from
            .as_str()
            .with_context(|| format!("artifact type `{name}` transition keys must be strings"))?;
        if !states.contains(from) {
            bail!("artifact type `{name}` has an unknown transition state `{from}`");
        }
        let targets = yaml_strings(targets, "transition targets")?;
        for target in &targets {
            if !states.contains(target) {
                bail!("artifact type `{name}` has an unknown transition target `{target}`");
            }
        }
        transitions.insert(from.to_string(), targets);
    }
    for state in &states {
        transitions.entry(state.clone()).or_default();
    }

    Ok(ArtifactTypeSchema {
        initial_state,
        states,
        completion_states,
        transitions,
    })
}

fn required_string(mapping: &Mapping, field: &str) -> Result<String> {
    mapping
        .get(key(field))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
        .with_context(|| format!("workflow schema requires string `{field}`"))
}

fn required_strings(mapping: &Mapping, field: &str) -> Result<BTreeSet<String>> {
    let value = mapping
        .get(key(field))
        .with_context(|| format!("workflow schema requires `{field}`"))?;
    yaml_strings(value, field)
}

fn yaml_strings(value: &YamlValue, field: &str) -> Result<BTreeSet<String>> {
    value
        .as_sequence()
        .with_context(|| format!("workflow schema `{field}` must be a sequence"))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_string)
                .with_context(|| format!("workflow schema `{field}` entries must be strings"))
        })
        .collect()
}

fn project_root(artifact: &Path) -> Option<PathBuf> {
    memory::find_root(artifact)
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}
