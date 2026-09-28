//! Markdown friction import parsing and validation.

use std::fs;
use std::path::{Path, PathBuf};

use serde_yaml::{Mapping, Value};

use crate::LearnError;
use crate::store::{
    FrictionIncidentProvenance, FrictionOccurrence, FrictionStatus, FrictionStatusChange,
    validate_provenance,
};

/// A validated friction record read from Markdown frontmatter.
#[derive(Debug, Clone)]
pub struct FrictionImportEntry {
    pub id: Option<i64>,
    pub slug: String,
    pub title: String,
    pub source: String,
    pub repo_root: Option<String>,
    pub status: FrictionStatus,
    pub target: Option<String>,
    pub created_at: Option<String>,
    pub occurrences: Vec<FrictionOccurrence>,
    pub status_changes: Vec<FrictionStatusChange>,
}

/// One regular Markdown file and either its validated record or skip reason.
#[derive(Debug, Clone)]
pub enum FrictionImportFile {
    Ready {
        file: String,
        entry: FrictionImportEntry,
    },
    Skipped {
        file: String,
        reason: String,
    },
}

/// Counts for all files, including entries outside a displayed report page.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct FrictionImportSummary {
    pub total: usize,
    pub imported: usize,
    pub would_import: usize,
    pub skipped: usize,
}

/// Read and validate regular Markdown files in one directory, in filename order.
pub fn read_import_files(
    directory: &Path,
    repo_root: &Path,
) -> Result<Vec<FrictionImportFile>, LearnError> {
    let metadata = fs::symlink_metadata(directory).map_err(|source| LearnError::StoreIo {
        operation: "inspect import directory",
        path: directory.to_path_buf(),
        source,
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(invalid(format!(
            "import source `{}` must be a directory, not a symlink",
            directory.display()
        )));
    }
    let directory = directory
        .canonicalize()
        .map_err(|source| LearnError::StoreIo {
            operation: "resolve import directory",
            path: directory.to_path_buf(),
            source,
        })?;
    let repo_root = normalize_repo_root(repo_root)?;
    let entries = fs::read_dir(&directory).map_err(|source| LearnError::StoreIo {
        operation: "read import directory",
        path: directory.clone(),
        source,
    })?;
    let mut paths = Vec::<(PathBuf, Option<String>)>::new();
    for entry in entries {
        let entry = entry.map_err(|source| LearnError::StoreIo {
            operation: "read import directory entry",
            path: directory.clone(),
            source,
        })?;
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path).map_err(|source| LearnError::StoreIo {
            operation: "inspect import file",
            path: path.clone(),
            source,
        })?;
        if path
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("md"))
        {
            let reason = if metadata.file_type().is_symlink() {
                Some("symbolic links are not imported".to_owned())
            } else if !metadata.is_file() {
                Some("not a regular Markdown file".to_owned())
            } else {
                None
            };
            paths.push((path, reason));
        }
    }
    paths.sort_by(|left, right| left.0.cmp(&right.0));

    Ok(paths
        .into_iter()
        .map(|(path, rejected)| {
            let file = path
                .file_name()
                .map(|name| name.to_string_lossy().into_owned())
                .unwrap_or_else(|| path.display().to_string());
            if let Some(reason) = rejected {
                return FrictionImportFile::Skipped { file, reason };
            }
            match fs::read_to_string(&path) {
                Ok(contents) => match parse_markdown(&contents, &path, &repo_root) {
                    Ok(entry) => FrictionImportFile::Ready { file, entry },
                    Err(reason) => FrictionImportFile::Skipped { file, reason },
                },
                Err(error) => FrictionImportFile::Skipped {
                    file,
                    reason: format!("could not read Markdown: {error}"),
                },
            }
        })
        .collect())
}

fn parse_markdown(
    contents: &str,
    path: &Path,
    repo_root: &str,
) -> Result<FrictionImportEntry, String> {
    let (frontmatter, body) = split_frontmatter(contents)?;
    let value: Value = serde_yaml::from_str(frontmatter)
        .map_err(|error| format!("invalid YAML frontmatter: {error}"))?;
    let mapping = value
        .as_mapping()
        .ok_or_else(|| "frontmatter must be a YAML mapping".to_owned())?;

    if optional_string(mapping, "format")?.as_deref() == Some("varde-friction-item") {
        parse_structured(mapping)
    } else {
        parse_legacy(mapping, body, path, repo_root)
    }
}

fn parse_structured(mapping: &Mapping) -> Result<FrictionImportEntry, String> {
    let version = required_i64(mapping, "version")?;
    if version != 1 {
        return Err(format!("unsupported friction export version `{version}`"));
    }
    let id = required_positive_id(mapping, "id")?;
    let slug = slugify(&required_nonblank(mapping, "slug")?);
    let title = required_nonblank(mapping, "title")?;
    let source = required_nonblank(mapping, "source")?;
    let repo_root = optional_string(mapping, "repo_root")?;
    let status = parse_status(&required_string(mapping, "status")?)?;
    let target = optional_string(mapping, "target")?;
    let created_at = Some(required_nonblank(mapping, "created_at")?);
    let occurrences = sequence(mapping, "occurrences")?
        .iter()
        .map(|value| parse_occurrence(value, id))
        .collect::<Result<Vec<_>, _>>()?;
    let status_changes = sequence(mapping, "status_changes")?
        .iter()
        .map(|value| parse_status_change(value, id))
        .collect::<Result<Vec<_>, _>>()?;

    Ok(FrictionImportEntry {
        id: Some(id),
        slug,
        title,
        source,
        repo_root,
        status,
        target,
        created_at,
        occurrences,
        status_changes,
    })
}

fn parse_occurrence(value: &Value, item_id: i64) -> Result<FrictionOccurrence, String> {
    let mapping = value
        .as_mapping()
        .ok_or_else(|| "each occurrence must be a YAML mapping".to_owned())?;
    let id = required_positive_id(mapping, "id")?;
    let stored_item_id = required_positive_id(mapping, "item_id")?;
    if stored_item_id != item_id {
        return Err("occurrence item_id does not match its item".to_owned());
    }
    Ok(FrictionOccurrence {
        id,
        item_id,
        at: required_nonblank(mapping, "at")?,
        cwd: required_nonblank(mapping, "cwd")?,
        repo_root: optional_string(mapping, "repo_root")?,
        head_sha: optional_string(mapping, "head_sha")?,
        evidence: required_nonblank(mapping, "evidence")?,
        cost: optional_string(mapping, "cost")?,
        provenance: optional_provenance(mapping)?,
    })
}

fn optional_provenance(mapping: &Mapping) -> Result<Option<FrictionIncidentProvenance>, String> {
    match get(mapping, "provenance") {
        None | Some(Value::Null) => Ok(None),
        Some(value) => {
            let provenance: FrictionIncidentProvenance = serde_yaml::from_value(value.clone())
                .map_err(|error| format!("invalid incident provenance: {error}"))?;
            validate_provenance(&provenance).map_err(|error| error.to_string())?;
            Ok(Some(provenance))
        }
    }
}

fn parse_status_change(value: &Value, item_id: i64) -> Result<FrictionStatusChange, String> {
    let mapping = value
        .as_mapping()
        .ok_or_else(|| "each status change must be a YAML mapping".to_owned())?;
    let id = required_positive_id(mapping, "id")?;
    let stored_item_id = required_positive_id(mapping, "item_id")?;
    if stored_item_id != item_id {
        return Err("status change item_id does not match its item".to_owned());
    }
    Ok(FrictionStatusChange {
        id,
        item_id,
        at: required_nonblank(mapping, "at")?,
        from_status: parse_status(&required_string(mapping, "from_status")?)?
            .as_str()
            .to_owned(),
        to_status: parse_status(&required_string(mapping, "to_status")?)?
            .as_str()
            .to_owned(),
        reason: required_nonblank(mapping, "reason")?,
    })
}

fn parse_legacy(
    mapping: &Mapping,
    body: &str,
    path: &Path,
    repo_root: &str,
) -> Result<FrictionImportEntry, String> {
    let item_type = optional_string(mapping, "type")?;
    if !matches!(item_type.as_deref(), Some("friction" | "friction-item")) {
        return Err("missing or unsupported friction type".to_owned());
    }
    let status = optional_string(mapping, "status")?
        .map(|value| parse_status(&value))
        .transpose()?
        .unwrap_or(FrictionStatus::Open);
    let source = if let Some(source) = optional_string(mapping, "source")? {
        source
    } else if let Some(skill) = optional_string(mapping, "skill")? {
        skill
    } else if let Some(tool) = optional_string(mapping, "tool")? {
        tool
    } else {
        "legacy-import".to_owned()
    };
    if source.trim().is_empty() {
        return Err("source must not be blank".to_owned());
    }
    let title = match optional_string(mapping, "title")? {
        Some(title) if !title.trim().is_empty() => title,
        Some(_) => return Err("title must not be blank".to_owned()),
        None => first_heading(body).unwrap_or_else(|| humanize_filename(path)),
    };
    let created_at = first_legacy_string(mapping, &["created_at", "created", "date"])?;
    let cwd = optional_string(mapping, "cwd")?.unwrap_or_else(|| repo_root.to_owned());
    if cwd.trim().is_empty() {
        return Err("`cwd` must not be blank".to_owned());
    }
    let head_sha = optional_scalar_text(mapping, "head_sha")?;
    let evidence = body.trim().to_owned();
    if evidence.is_empty() {
        return Err("Markdown body must contain occurrence evidence".to_owned());
    }
    let slug = path
        .file_stem()
        .map(|name| slugify(&name.to_string_lossy()))
        .filter(|slug| !slug.is_empty())
        .ok_or_else(|| "filename must have a usable Markdown stem".to_owned())?;

    Ok(FrictionImportEntry {
        id: None,
        slug,
        title,
        source,
        repo_root: Some(repo_root.to_owned()),
        status,
        target: optional_string(mapping, "target")?,
        created_at: created_at.clone().filter(|value| !value.trim().is_empty()),
        occurrences: vec![FrictionOccurrence {
            id: 0,
            item_id: 0,
            at: created_at.unwrap_or_default(),
            cwd,
            repo_root: Some(repo_root.to_owned()),
            head_sha,
            evidence,
            cost: optional_scalar_text(mapping, "cost")?,
            provenance: None,
        }],
        status_changes: Vec::new(),
    })
}

fn split_frontmatter(contents: &str) -> Result<(&str, &str), String> {
    let mut lines = contents.split_inclusive('\n');
    let first = lines
        .next()
        .ok_or_else(|| "missing YAML frontmatter".to_owned())?;
    if first.trim_end_matches(['\r', '\n']) != "---" {
        return Err("missing YAML frontmatter opening delimiter".to_owned());
    }
    let yaml_start = first.len();
    let mut offset = yaml_start;
    for line in lines {
        if line.trim_end_matches(['\r', '\n']) == "---" {
            let yaml = &contents[yaml_start..offset];
            let body_start = offset + line.len();
            let body = contents[body_start..].trim_start_matches(['\r', '\n']);
            return Ok((yaml, body));
        }
        offset += line.len();
    }
    Err("missing YAML frontmatter closing delimiter".to_owned())
}

fn sequence<'a>(mapping: &'a Mapping, key: &str) -> Result<&'a Vec<Value>, String> {
    get(mapping, key)
        .ok_or_else(|| format!("missing `{key}` collection"))?
        .as_sequence()
        .ok_or_else(|| format!("`{key}` must be a YAML sequence"))
}

fn get<'a>(mapping: &'a Mapping, key: &str) -> Option<&'a Value> {
    mapping.get(Value::String(key.to_owned()))
}

fn required_string(mapping: &Mapping, key: &str) -> Result<String, String> {
    get(mapping, key)
        .and_then(Value::as_str)
        .map(str::to_owned)
        .ok_or_else(|| format!("missing or invalid `{key}` string"))
}

fn required_nonblank(mapping: &Mapping, key: &str) -> Result<String, String> {
    let value = required_string(mapping, key)?;
    if value.trim().is_empty() {
        Err(format!("`{key}` must not be blank"))
    } else {
        Ok(value)
    }
}

fn required_i64(mapping: &Mapping, key: &str) -> Result<i64, String> {
    get(mapping, key)
        .and_then(Value::as_i64)
        .ok_or_else(|| format!("missing or invalid `{key}` integer"))
}

fn required_positive_id(mapping: &Mapping, key: &str) -> Result<i64, String> {
    let value = required_i64(mapping, key)?;
    if value <= 0 {
        Err(format!("`{key}` must be a positive integer"))
    } else {
        Ok(value)
    }
}

fn optional_string(mapping: &Mapping, key: &str) -> Result<Option<String>, String> {
    match get(mapping, key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(_) => Err(format!("`{key}` must be a string or null")),
    }
}

fn optional_scalar_text(mapping: &Mapping, key: &str) -> Result<Option<String>, String> {
    match get(mapping, key) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => Ok(Some(value.clone())),
        Some(Value::Number(value)) => Ok(Some(value.to_string())),
        Some(_) => Err(format!("`{key}` must be a scalar string or number")),
    }
}

fn first_legacy_string(mapping: &Mapping, keys: &[&str]) -> Result<Option<String>, String> {
    for key in keys {
        if let Some(value) = optional_string(mapping, key)? {
            return Ok(Some(value));
        }
    }
    Ok(None)
}

fn parse_status(value: &str) -> Result<FrictionStatus, String> {
    FrictionStatus::parse(value).ok_or_else(|| format!("invalid friction status `{value}`"))
}

fn first_heading(body: &str) -> Option<String> {
    body.lines()
        .find_map(|line| line.trim().strip_prefix("# "))
        .map(str::trim)
        .filter(|title| !title.is_empty())
        .map(str::to_owned)
}

fn humanize_filename(path: &Path) -> String {
    path.file_stem()
        .unwrap_or_default()
        .to_string_lossy()
        .split(['-', '_'])
        .filter(|part| !part.is_empty())
        .map(|part| {
            let mut chars = part.chars();
            match chars.next() {
                Some(first) => format!("{}{}", first.to_ascii_uppercase(), chars.as_str()),
                None => String::new(),
            }
        })
        .collect::<Vec<_>>()
        .join(" ")
}

fn slugify(value: &str) -> String {
    let mut slug = String::new();
    let mut separator = false;
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() {
            if separator && !slug.is_empty() {
                slug.push('-');
            }
            slug.push((byte as char).to_ascii_lowercase());
            separator = false;
        } else {
            separator = true;
        }
    }
    if slug.is_empty() {
        "friction".to_owned()
    } else if slug.bytes().all(|byte| byte.is_ascii_digit()) {
        format!("friction-{slug}")
    } else {
        slug
    }
}

fn normalize_repo_root(path: &Path) -> Result<String, LearnError> {
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|source| LearnError::StoreIo {
                operation: "resolve import repository root",
                path: path.to_path_buf(),
                source,
            })?
            .join(path)
    };
    Ok(absolute
        .canonicalize()
        .unwrap_or(absolute)
        .to_string_lossy()
        .into_owned())
}

fn invalid(message: String) -> LearnError {
    LearnError::StoreInvalid { message }
}
