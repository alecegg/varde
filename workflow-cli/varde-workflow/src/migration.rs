//! Explicit legacy artifact migration.

use crate::artifact;
use anyhow::{Context, Result, bail};
use serde_json::{Value as JsonValue, json};
use serde_yaml::Value as YamlValue;
use std::path::{Path, PathBuf};

#[derive(Debug)]
pub struct MigrationPreview {
    pub path: PathBuf,
    pub id: String,
    pub source_revision: String,
    pub target_revision: String,
    pub content: String,
}

impl MigrationPreview {
    pub fn to_json(&self) -> JsonValue {
        json!({
            "path": self.path,
            "id": self.id,
            "source_revision": self.source_revision,
            "target_revision": self.target_revision,
            "content": self.content,
        })
    }
}

pub fn preview(path: &Path) -> Result<MigrationPreview> {
    let source = std::fs::read(path)
        .with_context(|| format!("failed to read artifact {}", path.display()))?;
    let source_revision = okf_core::occ::version(&source);
    let envelope = artifact::inspect(path).map_err(|diagnostics| {
        anyhow::anyhow!(
            "artifact validation failed: {}",
            diagnostics
                .iter()
                .map(|item| format!("{}: {}", item.field, item.message))
                .collect::<Vec<_>>()
                .join(", ")
        )
    })?;
    if !envelope.legacy {
        bail!("artifact is already versioned");
    }

    let (frontmatter, body) = okf_core::frontmatter::parse(&source)?;
    let mut mapping = frontmatter
        .as_mapping()
        .expect("parser guarantees mapping")
        .clone();
    mapping.insert(key("schema_version"), YamlValue::Number(1_u64.into()));
    mapping.insert(
        key("artifact_type"),
        YamlValue::String(envelope.artifact_type),
    );
    mapping.insert(key("id"), YamlValue::String(envelope.id.clone()));
    mapping.insert(key("relationships"), YamlValue::Sequence(Vec::new()));
    mapping.insert(
        key("provenance"),
        serde_yaml::to_value(json!({
            "source": "explicit-migration",
            "source_revision": source_revision,
        }))?,
    );
    let content = okf_core::frontmatter::serialize(&YamlValue::Mapping(mapping), &body)?;
    let target_revision = okf_core::occ::version(content.as_bytes());

    Ok(MigrationPreview {
        path: path.to_path_buf(),
        id: envelope.id,
        source_revision,
        target_revision,
        content,
    })
}

pub fn apply(preview: &MigrationPreview) -> Result<()> {
    let current = std::fs::read(&preview.path)?;
    let current_revision = okf_core::occ::version(&current);
    if current_revision != preview.source_revision {
        bail!("artifact changed after migration preview");
    }
    crate::journal::commit(&preview.path, preview.content.as_bytes())
}

pub fn enforce_concept_migration(bundle: &Path, slug: &str, json_mode: bool) -> Result<()> {
    let shown = match okf_core::crud::show::show(bundle, slug) {
        Ok(shown) => shown,
        Err(_) => return Ok(()),
    };
    if shown
        .frontmatter
        .as_mapping()
        .is_some_and(|mapping| mapping.contains_key(key("schema_version")))
    {
        return Ok(());
    }

    let path = bundle.join(format!("{slug}.md"));
    let preview = preview(&path)?;
    if json_mode {
        crate::output::print_failure(
            "migration_required",
            "explicit migration is required before mutation",
            preview.to_json(),
        );
    } else {
        eprintln!("explicit migration required: {}", path.display());
        println!("{}", preview.content);
    }
    std::process::exit(4);
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}
