//! Workflow artifact inspection: versioned envelopes and plain template frontmatter.

use serde_json::{Value as JsonValue, json};
use serde_yaml::{Mapping, Value as YamlValue};
use std::path::{Path, PathBuf};

#[derive(Debug)]
pub struct ArtifactEnvelope {
    pub schema_version: u64,
    pub artifact_type: String,
    pub id: String,
    pub status: Option<String>,
    pub relationships: JsonValue,
    pub provenance: JsonValue,
    pub revision: String,
    pub source_path: PathBuf,
}

#[derive(Debug)]
pub struct Diagnostic {
    pub field: String,
    pub message: String,
}

impl Diagnostic {
    pub fn to_json(&self) -> JsonValue {
        json!({ "field": self.field, "message": self.message })
    }
}

impl ArtifactEnvelope {
    pub fn to_json(&self) -> JsonValue {
        json!({
            "schema_version": self.schema_version,
            "artifact_type": self.artifact_type,
            "id": self.id,
            "status": self.status,
            "relationships": self.relationships,
            "provenance": self.provenance,
            "revision": self.revision,
            "source_path": self.source_path,
        })
    }
}

pub fn inspect(path: &Path) -> Result<ArtifactEnvelope, Vec<Diagnostic>> {
    let bytes = std::fs::read(path).map_err(|error| {
        vec![Diagnostic {
            field: "document".to_string(),
            message: error.to_string(),
        }]
    })?;
    let revision = varde_workflow_core::occ::version(&bytes);
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes).map_err(|error| {
        vec![Diagnostic {
            field: "frontmatter".to_string(),
            message: error.to_string(),
        }]
    })?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");

    if mapping.contains_key(YamlValue::String("schema_version".to_string())) {
        inspect_versioned(path, mapping, revision)
    } else {
        Ok(inspect_frontmatter(path, mapping, revision))
    }
}

fn inspect_versioned(
    path: &Path,
    mapping: &Mapping,
    revision: String,
) -> Result<ArtifactEnvelope, Vec<Diagnostic>> {
    let mut diagnostics = Vec::new();
    let schema_version = integer(mapping, "schema_version", &mut diagnostics);
    if let Some(version) = schema_version
        && version != 1
    {
        diagnostics.push(Diagnostic {
            field: "schema_version".to_string(),
            message: format!("unsupported schema version {version}"),
        });
    }
    let artifact_type = string(mapping, "artifact_type", &mut diagnostics);
    let id = string(mapping, "id", &mut diagnostics);
    let relationships = sequence_value(mapping, "relationships", &mut diagnostics);
    let provenance = mapping_value(mapping, "provenance", &mut diagnostics);
    let status = optional_string_checked(mapping, "status", &mut diagnostics);

    diagnostics.sort_by(|a, b| a.field.cmp(&b.field));
    if !diagnostics.is_empty() {
        return Err(diagnostics);
    }

    Ok(ArtifactEnvelope {
        schema_version: schema_version.expect("validated"),
        artifact_type: artifact_type.expect("validated"),
        id: id.expect("validated"),
        status,
        relationships: relationships.expect("validated"),
        provenance: provenance.expect("validated"),
        revision,
        source_path: path.to_path_buf(),
    })
}

/// Plain template frontmatter (`type`, `status`, ...) with no versioned
/// envelope fields: the format the varde skills write. The id is the task's
/// file stem, or the plan's directory name for a `plan.md`.
fn inspect_frontmatter(path: &Path, mapping: &Mapping, revision: String) -> ArtifactEnvelope {
    let stem = path
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or_default();
    let id = if stem == "plan" {
        path.parent()
            .and_then(|dir| dir.file_name())
            .and_then(|name| name.to_str())
            .unwrap_or(stem)
    } else {
        stem
    };
    ArtifactEnvelope {
        schema_version: 1,
        artifact_type: optional_string(mapping, "type").unwrap_or_else(|| "document".to_string()),
        id: id.to_string(),
        status: optional_string(mapping, "status"),
        relationships: json!([]),
        provenance: json!({ "source": "derived", "path": path }),
        revision,
        source_path: path.to_path_buf(),
    }
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}

fn integer(mapping: &Mapping, name: &str, diagnostics: &mut Vec<Diagnostic>) -> Option<u64> {
    match mapping.get(key(name)).and_then(YamlValue::as_u64) {
        Some(value) => Some(value),
        None => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "required unsigned integer is missing".to_string(),
            });
            None
        }
    }
}

fn string(mapping: &Mapping, name: &str, diagnostics: &mut Vec<Diagnostic>) -> Option<String> {
    match optional_string(mapping, name).filter(|value| !value.is_empty()) {
        Some(value) => Some(value),
        None => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "required non-empty string is missing".to_string(),
            });
            None
        }
    }
}

fn optional_string(mapping: &Mapping, name: &str) -> Option<String> {
    mapping
        .get(key(name))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
}

fn value(mapping: &Mapping, name: &str, diagnostics: &mut Vec<Diagnostic>) -> Option<JsonValue> {
    match mapping.get(key(name)) {
        Some(value) => match serde_json::to_value(value) {
            Ok(value) => Some(value),
            Err(error) => {
                diagnostics.push(Diagnostic {
                    field: name.to_string(),
                    message: error.to_string(),
                });
                None
            }
        },
        None => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "required field is missing".to_string(),
            });
            None
        }
    }
}

fn sequence_value(
    mapping: &Mapping,
    name: &str,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<JsonValue> {
    match mapping.get(key(name)) {
        Some(YamlValue::Sequence(value)) => serde_json::to_value(value).ok(),
        Some(_) => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "field must be a sequence".to_string(),
            });
            None
        }
        None => value(mapping, name, diagnostics),
    }
}

fn mapping_value(
    mapping: &Mapping,
    name: &str,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<JsonValue> {
    match mapping.get(key(name)) {
        Some(YamlValue::Mapping(value)) => serde_json::to_value(value).ok(),
        Some(_) => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "field must be a mapping".to_string(),
            });
            None
        }
        None => value(mapping, name, diagnostics),
    }
}

fn optional_string_checked(
    mapping: &Mapping,
    name: &str,
    diagnostics: &mut Vec<Diagnostic>,
) -> Option<String> {
    match mapping.get(key(name)) {
        Some(YamlValue::String(value)) => Some(value.clone()),
        Some(_) => {
            diagnostics.push(Diagnostic {
                field: name.to_string(),
                message: "field must be a string".to_string(),
            });
            None
        }
        None => None,
    }
}
