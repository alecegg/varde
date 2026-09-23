//! Deterministic workflow graph and readiness resolution.

use crate::workflow_schema::WorkflowSchema;
use anyhow::{Context, Result, bail};
use serde_json::{Value as JsonValue, json};
use serde_yaml::{Mapping, Value as YamlValue};
use std::collections::{BTreeMap, BTreeSet};
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct WorkflowArtifact {
    pub id: String,
    pub artifact_type: String,
    pub status: String,
    pub depends_on: Vec<String>,
    pub path: PathBuf,
    pub revision: String,
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Blocker {
    pub code: String,
    pub artifact_id: String,
    pub dependency: String,
    pub status: Option<String>,
}

impl Blocker {
    pub fn to_json(&self) -> JsonValue {
        json!({
            "code": self.code,
            "artifact_id": self.artifact_id,
            "dependency": self.dependency,
            "status": self.status,
        })
    }
}

#[derive(Debug)]
pub struct ArtifactGraph {
    pub root_id: String,
    pub nodes: BTreeMap<String, WorkflowArtifact>,
    pub blockers: Vec<Blocker>,
}

impl ArtifactGraph {
    pub fn resolve(path: &Path, schema: &WorkflowSchema) -> Result<Self> {
        let root = read_artifact(path, schema)?;
        let root_id = root.id.clone();
        let mut graph = Self {
            root_id,
            nodes: BTreeMap::new(),
            blockers: Vec::new(),
        };
        let mut visiting = BTreeSet::new();
        graph.visit(root, schema, &mut visiting)?;
        graph.add_completion_blockers(schema)?;
        graph.blockers.sort();
        graph.blockers.dedup();
        Ok(graph)
    }

    pub fn root(&self) -> &WorkflowArtifact {
        self.nodes.get(&self.root_id).expect("root node is present")
    }

    pub fn root_blockers(&self) -> Vec<&Blocker> {
        self.blockers
            .iter()
            .filter(|blocker| blocker.artifact_id == self.root_id)
            .collect()
    }

    pub fn actions(&self, schema: &WorkflowSchema) -> Result<Vec<String>> {
        let root = self.root();
        let artifact_type = schema.artifact_type(&root.artifact_type)?;
        let mut actions = artifact_type
            .transitions
            .get(&root.status)
            .into_iter()
            .flatten()
            .cloned()
            .collect::<Vec<_>>();
        if !self.root_blockers().is_empty() {
            actions.retain(|action| action == "blocked");
        }
        Ok(actions)
    }

    pub fn to_json(&self, schema: &WorkflowSchema) -> Result<JsonValue> {
        let nodes = self
            .nodes
            .values()
            .map(|node| {
                json!({
                    "id": node.id,
                    "artifact_type": node.artifact_type,
                    "status": node.status,
                    "path": node.path,
                })
            })
            .collect::<Vec<_>>();
        let mut edges = self
            .nodes
            .values()
            .flat_map(|node| {
                node.depends_on.iter().map(|dependency| {
                    json!({
                        "from": node.id,
                        "to": self.resolved_dependency_id(dependency).unwrap_or(dependency),
                        "relationship": "depends_on",
                    })
                })
            })
            .collect::<Vec<_>>();
        edges.sort_by_key(JsonValue::to_string);
        Ok(json!({
            "schema": schema.to_json(),
            "root_id": self.root_id,
            "nodes": nodes,
            "edges": edges,
            "blockers": self.blockers.iter().map(Blocker::to_json).collect::<Vec<_>>(),
        }))
    }

    pub fn readiness_json(&self, schema: &WorkflowSchema) -> Result<JsonValue> {
        let blockers = self.root_blockers();
        Ok(json!({
            "schema_version": crate::workflow_schema::SCHEMA_VERSION,
            "artifact_id": self.root_id,
            "ready": blockers.is_empty(),
            "blockers": blockers.iter().map(|item| item.to_json()).collect::<Vec<_>>(),
            "actions": self.actions(schema)?,
        }))
    }

    fn visit(
        &mut self,
        artifact: WorkflowArtifact,
        schema: &WorkflowSchema,
        visiting: &mut BTreeSet<String>,
    ) -> Result<()> {
        if self.nodes.contains_key(&artifact.id) {
            let existing = self.nodes.get(&artifact.id).expect("node exists");
            if existing.path != artifact.path {
                bail!(
                    "duplicate workflow artifact id `{}` appears at {} and {}",
                    artifact.id,
                    existing.path.display(),
                    artifact.path.display()
                );
            }
            return Ok(());
        }
        if !visiting.insert(artifact.id.clone()) {
            bail!("workflow dependency cycle includes `{}`", artifact.id);
        }
        let id = artifact.id.clone();
        let dependencies = artifact.depends_on.clone();
        let path = artifact.path.clone();
        self.nodes.insert(id.clone(), artifact);
        for dependency in dependencies {
            let dependency_path = dependency_path(&path, &dependency);
            if !dependency_path.exists() {
                self.blockers.push(Blocker {
                    code: "dependency_missing".to_string(),
                    artifact_id: id.clone(),
                    dependency,
                    status: None,
                });
                continue;
            }
            let child = read_artifact(&dependency_path, schema)?;
            if visiting.contains(&child.id) {
                self.blockers.push(Blocker {
                    code: "dependency_cycle".to_string(),
                    artifact_id: id.clone(),
                    dependency: child.id,
                    status: None,
                });
                continue;
            }
            self.visit(child, schema, visiting)?;
        }
        visiting.remove(&id);
        Ok(())
    }

    fn add_completion_blockers(&mut self, schema: &WorkflowSchema) -> Result<()> {
        for node in self.nodes.values() {
            for dependency in &node.depends_on {
                let Some(target) = self.resolved_dependency(dependency) else {
                    continue;
                };
                let target_schema = schema.artifact_type(&target.artifact_type)?;
                if !target_schema.completion_states.contains(&target.status) {
                    self.blockers.push(Blocker {
                        code: "dependency_incomplete".to_string(),
                        artifact_id: node.id.clone(),
                        dependency: dependency.clone(),
                        status: Some(target.status.clone()),
                    });
                }
            }
        }
        Ok(())
    }

    fn resolved_dependency(&self, reference: &str) -> Option<&WorkflowArtifact> {
        self.nodes.get(reference).or_else(|| {
            self.nodes
                .values()
                .find(|node| derived_id(&node.path) == reference)
        })
    }

    fn resolved_dependency_id<'a>(&'a self, reference: &'a str) -> Option<&'a str> {
        self.resolved_dependency(reference)
            .map(|artifact| artifact.id.as_str())
    }
}

pub fn read_artifact(path: &Path, schema: &WorkflowSchema) -> Result<WorkflowArtifact> {
    let bytes = std::fs::read(path)
        .with_context(|| format!("failed to read workflow artifact {}", path.display()))?;
    let revision = okf_core::occ::version(&bytes);
    let (frontmatter, _) = okf_core::frontmatter::parse(&bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    let artifact_type = optional_string(mapping, "artifact_type")
        .or_else(|| optional_string(mapping, "type"))
        .unwrap_or_else(|| "plan".to_string());
    let artifact_schema = schema.artifact_type(&artifact_type)?;
    let status =
        optional_string(mapping, "status").unwrap_or_else(|| artifact_schema.initial_state.clone());
    if !artifact_schema.states.contains(&status) {
        bail!(
            "artifact `{}` has unknown status `{status}`",
            path.display()
        );
    }
    let id = optional_string(mapping, "id").unwrap_or_else(|| derived_id(path));
    let mut depends_on = optional_strings(mapping, "depends_on")?;
    depends_on.sort();
    depends_on.dedup();
    Ok(WorkflowArtifact {
        id,
        artifact_type,
        status,
        depends_on,
        path: path.to_path_buf(),
        revision,
    })
}

pub fn content_with_status(path: &Path, status: &str) -> Result<Vec<u8>> {
    let bytes = std::fs::read(path)?;
    let (frontmatter, body) = okf_core::frontmatter::parse(&bytes)?;
    let mut mapping = frontmatter
        .as_mapping()
        .expect("parser guarantees mapping")
        .clone();
    mapping.insert(key("status"), YamlValue::String(status.to_string()));
    Ok(okf_core::frontmatter::serialize(&YamlValue::Mapping(mapping), &body)?.into_bytes())
}

fn dependency_path(source: &Path, dependency: &str) -> PathBuf {
    if source.file_name().and_then(|name| name.to_str()) == Some("plan.md") {
        source
            .parent()
            .and_then(Path::parent)
            .unwrap_or_else(|| Path::new("."))
            .join(dependency)
            .join("plan.md")
    } else {
        source
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .join(format!("{dependency}.md"))
    }
}

fn derived_id(path: &Path) -> String {
    if path.file_name().and_then(|name| name.to_str()) == Some("plan.md") {
        path.parent()
            .and_then(Path::file_name)
            .and_then(|name| name.to_str())
            .unwrap_or("plan")
            .to_string()
    } else {
        path.file_stem()
            .and_then(|name| name.to_str())
            .unwrap_or("artifact")
            .to_string()
    }
}

fn optional_string(mapping: &Mapping, name: &str) -> Option<String> {
    mapping
        .get(key(name))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
}

fn optional_strings(mapping: &Mapping, name: &str) -> Result<Vec<String>> {
    let Some(value) = mapping.get(key(name)) else {
        return Ok(Vec::new());
    };
    value
        .as_sequence()
        .with_context(|| format!("artifact field `{name}` must be a sequence"))?
        .iter()
        .map(|item| {
            item.as_str()
                .map(str::to_string)
                .with_context(|| format!("artifact field `{name}` entries must be strings"))
        })
        .collect()
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}
