//! Versioned and legacy workflow artifact inspection.

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
    pub legacy: bool,
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
            "legacy": self.legacy,
            "migration_required": self.legacy,
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
    let revision = okf_core::occ::version(&bytes);
    let (frontmatter, _) = okf_core::frontmatter::parse(&bytes).map_err(|error| {
        vec![Diagnostic {
            field: "frontmatter".to_string(),
            message: error.to_string(),
        }]
    })?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");

    if mapping.contains_key(YamlValue::String("schema_version".to_string())) {
        inspect_versioned(path, mapping, revision)
    } else {
        Ok(inspect_legacy(path, mapping, revision))
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
        legacy: false,
    })
}

fn inspect_legacy(path: &Path, mapping: &Mapping, revision: String) -> ArtifactEnvelope {
    ArtifactEnvelope {
        schema_version: 1,
        artifact_type: optional_string(mapping, "type").unwrap_or_else(|| "legacy".to_string()),
        id: format!("legacy-{revision}"),
        status: optional_string(mapping, "status"),
        relationships: json!([]),
        provenance: json!({ "source": "derived", "path": path }),
        revision,
        source_path: path.to_path_buf(),
        legacy: true,
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
