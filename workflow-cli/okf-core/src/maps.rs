//! Deterministic discovery maps for Knowledge Bundles.
//!
//! Maps are reserved index.md files. They are navigation surfaces, not
//! Concepts, and can be regenerated without changing Concept content.

use crate::bundle::is_reserved;
use crate::frontmatter;
use serde::Serialize;
use std::collections::BTreeMap;
use std::io;
use std::path::{Path, PathBuf};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GeneratedMaps {
    pub root: String,
    pub type_maps: Vec<String>,
    pub entries: usize,
}

#[derive(Debug, Error)]
pub enum MapError {
    #[error("failed to read bundle entry {path}: {source}")]
    ReadFailed { path: PathBuf, source: io::Error },
    #[error("failed to create map directory {path}: {source}")]
    CreateDirFailed { path: PathBuf, source: io::Error },
    #[error("failed to write map {path}: {source}")]
    WriteFailed { path: PathBuf, source: io::Error },
    #[error("invalid root map frontmatter: {0}")]
    Frontmatter(#[from] frontmatter::FrontmatterError),
    #[error("failed to walk bundle: {0}")]
    Walk(String),
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct MapEntry {
    slug: String,
    type_name: String,
    title: String,
    description: String,
    aliases: Vec<String>,
    status: String,
}

impl MapEntry {
    fn is_deprecated(&self) -> bool {
        self.status == "deprecated"
    }
}

/// Generate the root map and one type map per observed Concept type.
pub fn generate(bundle: &Path) -> Result<GeneratedMaps, MapError> {
    let mut entries = collect_entries(bundle)?;
    sort_entries(&mut entries);
    let root_body = render_map("Knowledge map", &entries, bundle, bundle, true);
    write_root_map(bundle, &root_body)?;

    let type_maps = write_type_maps(bundle, &entries)?;

    Ok(GeneratedMaps {
        root: "index.md".to_string(),
        type_maps,
        entries: entries.len(),
    })
}

fn collect_entries(bundle: &Path) -> Result<Vec<MapEntry>, MapError> {
    let mut entries = Vec::new();
    crate::walk::visit_concepts(bundle, &is_reserved, |file| {
        entries.push(map_entry(bundle, file));
    })
    .map_err(map_walk_error)?;
    Ok(entries)
}

fn map_entry(bundle: &Path, file: crate::walk::WalkedFile) -> MapEntry {
    let frontmatter = &file.frontmatter;
    let slug = crate::crud::relative_slug(bundle, &file.path);
    MapEntry {
        type_name: frontmatter_string(frontmatter, "type", "untyped"),
        title: frontmatter_string(frontmatter, "title", &display_slug(&slug)),
        description: frontmatter_string(frontmatter, "description", "(no description)"),
        aliases: aliases(frontmatter.get("aliases")),
        status: frontmatter_string(frontmatter, "status", "active"),
        slug,
    }
}

fn frontmatter_string(value: &serde_yaml::Value, field: &str, default: &str) -> String {
    value
        .get(field)
        .and_then(|item| item.as_str())
        .filter(|item| !item.trim().is_empty())
        .unwrap_or(default)
        .to_string()
}

fn map_walk_error(error: crate::walk::WalkError) -> MapError {
    match error {
        crate::walk::WalkError::ReadDirFailed { path, source }
        | crate::walk::WalkError::ReadFailed { path, source } => {
            MapError::ReadFailed { path, source }
        }
        crate::walk::WalkError::InvalidConcept { path, source } => {
            MapError::Walk(format!("{}: {source}", path.display()))
        }
    }
}

fn write_type_maps(bundle: &Path, entries: &[MapEntry]) -> Result<Vec<String>, MapError> {
    let mut by_type: BTreeMap<String, Vec<MapEntry>> = BTreeMap::new();
    for entry in entries {
        by_type
            .entry(entry.type_name.clone())
            .or_default()
            .push(entry.clone());
    }
    let mut paths = Vec::new();
    for (type_name, type_entries) in by_type {
        let dir_name = safe_type_dir(&type_name);
        let map_dir = bundle.join(&dir_name);
        let body = render_map(
            &format!("{type_name} concepts"),
            &type_entries,
            &map_dir,
            bundle,
            false,
        );
        write_map(&map_dir.join("index.md"), body.as_bytes())?;
        paths.push(format!("{dir_name}/index.md"));
    }
    Ok(paths)
}

fn aliases(value: Option<&serde_yaml::Value>) -> Vec<String> {
    match value {
        Some(serde_yaml::Value::Sequence(values)) => values
            .iter()
            .filter_map(|value| value.as_str().map(str::to_string))
            .collect(),
        Some(value) => value
            .as_str()
            .map(|value| vec![value.to_string()])
            .unwrap_or_default(),
        None => Vec::new(),
    }
}

fn sort_entries(entries: &mut [MapEntry]) {
    entries.sort_by(|left, right| {
        left.type_name
            .cmp(&right.type_name)
            .then_with(|| left.title.to_lowercase().cmp(&right.title.to_lowercase()))
            .then_with(|| left.slug.cmp(&right.slug))
    });
}

fn render_map(
    heading: &str,
    entries: &[MapEntry],
    map_dir: &Path,
    bundle: &Path,
    group_by_type: bool,
) -> String {
    let mut out = format!("# {heading}\n\n");
    out.push_str("Generated by varde-workflow concept map.\n\n");
    render_status_section(
        &mut out,
        "Active",
        entries,
        map_dir,
        bundle,
        group_by_type,
        false,
    );
    render_status_section(
        &mut out,
        "Deprecated",
        entries,
        map_dir,
        bundle,
        group_by_type,
        true,
    );
    out
}

fn render_status_section(
    out: &mut String,
    heading: &str,
    entries: &[MapEntry],
    map_dir: &Path,
    bundle: &Path,
    group_by_type: bool,
    deprecated: bool,
) {
    out.push_str(&format!("## {heading}\n\n"));
    let mut current_type = None;
    for entry in entries
        .iter()
        .filter(|entry| entry.is_deprecated() == deprecated)
    {
        if group_by_type && current_type.as_deref() != Some(entry.type_name.as_str()) {
            out.push_str(&format!("### {}\n\n", entry.type_name));
            current_type = Some(entry.type_name.clone());
        }
        let target = bundle.join(format!("{}.md", entry.slug));
        let link = relative_link(map_dir, &target, bundle);
        let aliases = if entry.aliases.is_empty() {
            "none".to_string()
        } else {
            entry.aliases.join(", ")
        };
        out.push_str(&format!(
            "- [{}]({link})\n  - Description: {}\n  - Aliases: {}\n  - Status: {}\n\n",
            entry.title, entry.description, aliases, entry.status
        ));
    }
    if !entries
        .iter()
        .any(|entry| entry.is_deprecated() == deprecated)
    {
        out.push_str("No concepts.\n\n");
    }
}

fn relative_link(map_dir: &Path, target: &Path, bundle: &Path) -> String {
    let map_relative = map_dir.strip_prefix(bundle).unwrap_or(Path::new(""));
    let target_relative = target.strip_prefix(bundle).unwrap_or(target);
    let map_parts: Vec<_> = map_relative
        .components()
        .filter_map(|component| component.as_os_str().to_str())
        .collect();
    let target_parts: Vec<_> = target_relative
        .components()
        .filter_map(|component| component.as_os_str().to_str())
        .collect();
    let common = map_parts
        .iter()
        .zip(&target_parts)
        .take_while(|(left, right)| left == right)
        .count();
    let mut parts = vec![".."; map_parts.len() - common];
    parts.extend(target_parts.into_iter().skip(common));
    if parts.is_empty() {
        target_relative.to_string_lossy().replace('\\', "/")
    } else {
        parts.join("/")
    }
}

fn display_slug(slug: &str) -> String {
    slug.rsplit('/')
        .next()
        .unwrap_or(slug)
        .split('-')
        .map(|word| {
            let mut chars = word.chars();
            match chars.next() {
                Some(first) => first.to_uppercase().chain(chars).collect(),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn safe_type_dir(type_name: &str) -> String {
    let mut result = String::new();
    for character in type_name.chars() {
        if character.is_ascii_alphanumeric() || character == '-' || character == '_' {
            result.push(character.to_ascii_lowercase());
        } else if !result.ends_with('-') {
            result.push('-');
        }
    }
    let result = result.trim_matches('-');
    if result.is_empty() {
        "untyped".to_string()
    } else {
        result.to_string()
    }
}

fn write_root_map(bundle: &Path, body: &str) -> Result<(), MapError> {
    let path = bundle.join("index.md");
    let output = match std::fs::read(&path) {
        Ok(bytes) => match frontmatter::parse(&bytes) {
            Ok((frontmatter, _)) => frontmatter::serialize(&frontmatter, body)?,
            Err(_) => body.to_string(),
        },
        Err(error) if error.kind() == io::ErrorKind::NotFound => body.to_string(),
        Err(source) => return Err(MapError::ReadFailed { path, source }),
    };
    write_map(&path, output.as_bytes())
}

fn write_map(path: &Path, bytes: &[u8]) -> Result<(), MapError> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|source| MapError::CreateDirFailed {
            path: parent.to_path_buf(),
            source,
        })?;
    }
    std::fs::write(path, bytes).map_err(|source| MapError::WriteFailed {
        path: path.to_path_buf(),
        source,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::test_support::tempdir;

    fn write_concept(bundle: &Path, slug: &str, frontmatter: &str) {
        let path = bundle.join(format!("{slug}.md"));
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(path, format!("---\n{frontmatter}---\nbody\n")).unwrap();
    }

    #[test]
    fn maps_are_sorted_and_separate_deprecated_entries() {
        let bundle = tempdir("okf-core-maps");
        std::fs::write(bundle.join("index.md"), "---\nokf_version: 0.2\n---\n").unwrap();
        write_concept(
            &bundle,
            "decision/zeta",
            "type: decision\ntitle: Zeta\ndescription: Old.\nstatus: deprecated\n",
        );
        write_concept(
            &bundle,
            "decision/alpha",
            "type: decision\ntitle: Alpha\ndescription: New.\naliases:\n  - first\n",
        );
        write_concept(
            &bundle,
            "pattern/rule",
            "type: pattern\ndescription: Rule.\n",
        );

        let generated = generate(&bundle).unwrap();
        assert_eq!(
            generated.type_maps,
            vec!["decision/index.md", "pattern/index.md"]
        );
        let root = std::fs::read_to_string(bundle.join("index.md")).unwrap();
        assert!(root.contains("## Active\n\n### decision\n\n- [Alpha]"));
        assert!(root.contains("## Deprecated\n\n### decision\n\n- [Zeta]"));
        assert!(root.contains("Aliases: first"));
        assert!(root.contains("Status: deprecated"));

        let first = root;
        generate(&bundle).unwrap();
        assert_eq!(
            first,
            std::fs::read_to_string(bundle.join("index.md")).unwrap()
        );
        let decision = std::fs::read_to_string(bundle.join("decision/index.md")).unwrap();
        assert!(decision.contains("[Alpha](alpha.md)"));
        assert!(decision.contains("[Zeta](zeta.md)"));
    }

    #[test]
    fn legacy_concepts_without_description_remain_mappable() {
        let bundle = tempdir("okf-core-maps-legacy");
        write_concept(&bundle, "legacy", "type: reference\n");
        generate(&bundle).unwrap();
        let root = std::fs::read_to_string(bundle.join("index.md")).unwrap();
        assert!(root.contains("Description: (no description)"));
    }
}
