//! Contract promotion and conclusion preparation.

use crate::journal::{ExpectedSource, PendingWrite};
use anyhow::{Context, Result, bail};
use serde_json::{Value as JsonValue, json};
use serde_yaml::{Mapping, Value as YamlValue};
use sha1::{Digest, Sha1};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use varde_workflow_core::memory::{self, MemoryKind, MemoryPaths, Source};

#[derive(Debug)]
pub struct PreparedConclusion {
    pub memory: MemoryPaths,
    pub plan_id: String,
    pub writes: Vec<PendingWrite>,
    pub contracts: Vec<JsonValue>,
    pub specifications: Vec<JsonValue>,
    pub promotions: Vec<JsonValue>,
    pub expected_sources: Vec<ExpectedSource>,
}

struct InputSnapshot {
    expected_sources: Vec<ExpectedSource>,
    plan_bytes: Vec<u8>,
    bytes: BTreeMap<PathBuf, Vec<u8>>,
}

impl PreparedConclusion {
    pub fn to_json(&self) -> JsonValue {
        json!({
            "plan_id": self.plan_id,
            "contracts": self.contracts,
            "specifications": self.specifications,
            "promotions": self.promotions,
            "post_actions": ["reflection", "friction", "handoff"],
        })
    }
}

pub fn prepare_with_memory(plan_path: &Path, memory: MemoryPaths) -> Result<PreparedConclusion> {
    let plan_path = plan_path.canonicalize()?;
    let (memory, _) = memory_for_root(&memory.root)?;
    let root = memory.root.clone();
    let snapshot = collect_input_sources(&plan_path, &memory)?;
    let plan_bytes = snapshot.plan_bytes;
    let expected_sources = snapshot.expected_sources;
    let plan_revision = varde_workflow_core::occ::version(&plan_bytes);
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(&plan_bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    let plan_id = optional_string(mapping, "id").unwrap_or_else(|| derived_id(&plan_path));
    if has_unchecked_acceptance(&body)? {
        bail!("plan `{plan_id}` has unchecked acceptance criteria");
    }

    let mut writes = Vec::new();
    let contracts = prepare_contracts(
        &memory,
        &root,
        mapping,
        &plan_path,
        &plan_id,
        &snapshot.bytes,
        &mut writes,
    )?;
    let specifications =
        prepare_specifications(&memory, &root, mapping, &snapshot.bytes, &expected_sources)?;
    let promotions = prepare_promotions(
        &memory,
        &root,
        mapping,
        &plan_path,
        &plan_id,
        &snapshot.bytes,
        &mut writes,
    )?;
    append_conclusion_writes(
        &memory,
        &plan_path,
        &plan_bytes,
        &plan_revision,
        &plan_id,
        &contracts,
        &specifications,
        &promotions,
        &mut writes,
    )?;
    crate::journal::validate_expected_sources(&expected_sources)?;
    Ok(PreparedConclusion {
        memory,
        plan_id,
        writes,
        contracts,
        specifications,
        promotions,
        expected_sources,
    })
}

fn collect_input_sources(plan_path: &Path, memory: &MemoryPaths) -> Result<InputSnapshot> {
    let plan_bytes = std::fs::read(plan_path)?;
    let mut expected_sources: BTreeMap<PathBuf, ExpectedSource> = BTreeMap::new();
    let mut input_bytes = BTreeMap::new();
    let mut inventories = Vec::new();
    remember_bytes(
        &mut expected_sources,
        &mut input_bytes,
        plan_path,
        &plan_bytes,
    )?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&plan_bytes)?;
    let mapping = frontmatter
        .as_mapping()
        .context("plan frontmatter must be a mapping")?;
    let plan_id = optional_string(mapping, "id").unwrap_or_else(|| derived_id(plan_path));
    let mut paths = vec![plan_path.to_path_buf()];

    for raw in declared_paths(mapping, "contract_deltas", plan_path)? {
        let delta_path = contained_file(memory, &raw, "contract delta")?;
        let bytes = std::fs::read(&delta_path)?;
        remember_bytes(&mut expected_sources, &mut input_bytes, &delta_path, &bytes)?;
        let delta = ContractDelta::parse(&delta_path, &plan_id, &bytes)?;
        require_safe_id(&delta.capability, "contract capability")?;
        paths.push(
            memory
                .knowledge
                .path
                .join("contracts")
                .join(format!("{}.md", delta.capability)),
        );
    }
    for domain in optional_strings(mapping, "observed_specs")? {
        require_safe_id(&domain, "observed specification domain")?;
        let spec_path = memory
            .knowledge
            .path
            .join("specs")
            .join(format!("{domain}.md"));
        let bytes = std::fs::read(&spec_path)?;
        remember_bytes(&mut expected_sources, &mut input_bytes, &spec_path, &bytes)?;
        paths.push(spec_path);
        let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)?;
        let spec = frontmatter.as_mapping().expect("parser guarantees mapping");
        let roots = spec_paths(spec, "source_roots")?;
        inventories.push(crate::journal::expected_git_inventory(
            &memory.root,
            &roots,
        )?);
        let spec_sources = spec
            .get(key("sources"))
            .and_then(YamlValue::as_sequence)
            .context("observed specification requires `sources`")?;
        for source in spec_sources {
            let source = source
                .as_mapping()
                .context("spec source must be a mapping")?;
            let relative_path = required_string(source, "path")?;
            let source_path =
                contained_file(memory, &memory.root.join(relative_path), "spec source")?;
            let bytes = std::fs::read(&source_path)?;
            remember_bytes(
                &mut expected_sources,
                &mut input_bytes,
                &source_path,
                &bytes,
            )?;
            paths.push(source_path);
        }
    }
    for candidate_path in declared_paths(mapping, "promotion_candidates", plan_path)? {
        let candidate_path = contained_file(memory, &candidate_path, "promotion candidate")?;
        let bytes = std::fs::read(&candidate_path)?;
        remember_bytes(
            &mut expected_sources,
            &mut input_bytes,
            &candidate_path,
            &bytes,
        )?;
        let candidate = PromotionCandidate::parse(&candidate_path, &plan_id, &bytes)?;
        require_safe_id(&candidate.destination, "promotion destination")?;
        paths.push(
            memory
                .knowledge
                .path
                .join("findings")
                .join(format!("{}.md", candidate.destination)),
        );
    }
    paths.push(
        memory
            .knowledge
            .path
            .join("conclusions")
            .join(conclusion_filename(&plan_id)),
    );
    paths.push(
        memory
            .knowledge
            .path
            .join("promotions")
            .join(format!("{plan_id}.md")),
    );
    paths.push(post_action_path(memory, &plan_id));
    for path in paths {
        remember_current(&mut expected_sources, &mut input_bytes, &path)?;
    }
    let mut expected_sources: Vec<ExpectedSource> = expected_sources.into_values().collect();
    expected_sources.extend(inventories);
    Ok(InputSnapshot {
        expected_sources,
        plan_bytes,
        bytes: input_bytes,
    })
}

fn remember_bytes(
    sources: &mut BTreeMap<PathBuf, ExpectedSource>,
    contents: &mut BTreeMap<PathBuf, Vec<u8>>,
    path: &Path,
    bytes: &[u8],
) -> Result<()> {
    let source = crate::journal::expected_source_from_bytes(path, bytes)?;
    contents
        .entry(source.path.clone())
        .or_insert_with(|| bytes.to_vec());
    sources.entry(source.path.clone()).or_insert(source);
    Ok(())
}

fn remember_current(
    sources: &mut BTreeMap<PathBuf, ExpectedSource>,
    contents: &mut BTreeMap<PathBuf, Vec<u8>>,
    path: &Path,
) -> Result<()> {
    let path = memory::canonical_or_lexical(path);
    if sources.contains_key(&path) {
        return Ok(());
    }
    match std::fs::read(&path) {
        Ok(bytes) => remember_bytes(sources, contents, &path, &bytes)?,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            if crate::journal::file_identity(&path)?.is_some() {
                bail!(
                    "workflow output {} is not a readable regular file",
                    path.display()
                );
            }
            sources.insert(path.clone(), crate::journal::expected_source_at(&path)?);
        }
        Err(error) => return Err(error.into()),
    }
    Ok(())
}

fn prepare_contracts(
    memory: &MemoryPaths,
    root: &Path,
    mapping: &Mapping,
    plan_path: &Path,
    plan_id: &str,
    inputs: &BTreeMap<PathBuf, Vec<u8>>,
    writes: &mut Vec<PendingWrite>,
) -> Result<Vec<JsonValue>> {
    let mut contracts = Vec::new();
    for delta_path in declared_paths(mapping, "contract_deltas", plan_path)? {
        let delta_path = contained_file(memory, &delta_path, "contract delta")?;
        let delta_path_key = memory::canonical_or_lexical(&delta_path);
        let delta_bytes = inputs.get(&delta_path_key).with_context(|| {
            format!("contract delta was not captured: {}", delta_path.display())
        })?;
        let delta = ContractDelta::parse(&delta_path, plan_id, delta_bytes)?;
        require_safe_id(&delta.capability, "contract capability")?;
        let target = memory
            .knowledge
            .path
            .join("contracts")
            .join(format!("{}.md", delta.capability));
        let target_bytes = inputs
            .get(&memory::canonical_or_lexical(&target))
            .map(Vec::as_slice);
        let merged = delta.merge(target_bytes)?;
        let revision = varde_workflow_core::occ::version(merged.as_bytes());
        writes.push(PendingWrite {
            target: target.clone(),
            content: merged.into_bytes(),
        });
        contracts.push(json!({
            "capability": delta.capability,
            "delta": relative(root, &delta_path),
            "destination": relative(root, &target),
            "revision": revision,
        }));
    }
    Ok(contracts)
}

fn prepare_specifications(
    memory: &MemoryPaths,
    root: &Path,
    mapping: &Mapping,
    inputs: &BTreeMap<PathBuf, Vec<u8>>,
    expected_sources: &[ExpectedSource],
) -> Result<Vec<JsonValue>> {
    let mut specifications = Vec::new();
    for domain in optional_strings(mapping, "observed_specs")? {
        require_safe_id(&domain, "observed specification domain")?;
        let path = memory
            .knowledge
            .path
            .join("specs")
            .join(format!("{domain}.md"));
        let path_key = memory::canonical_or_lexical(&path);
        let bytes = inputs.get(&path_key).with_context(|| {
            format!(
                "observed specification was not captured: {}",
                path.display()
            )
        })?;
        let source_hash = validate_specification(memory, &path, bytes, inputs, expected_sources)?;
        specifications.push(json!({
            "domain": domain,
            "path": relative(root, &path),
            "source_hash": source_hash,
        }));
    }
    Ok(specifications)
}

fn prepare_promotions(
    memory: &MemoryPaths,
    root: &Path,
    mapping: &Mapping,
    plan_path: &Path,
    plan_id: &str,
    inputs: &BTreeMap<PathBuf, Vec<u8>>,
    writes: &mut Vec<PendingWrite>,
) -> Result<Vec<JsonValue>> {
    let mut promotions = Vec::new();
    for candidate_path in declared_paths(mapping, "promotion_candidates", plan_path)? {
        let candidate_path = contained_file(memory, &candidate_path, "promotion candidate")?;
        let candidate_key = memory::canonical_or_lexical(&candidate_path);
        let candidate_bytes = inputs.get(&candidate_key).with_context(|| {
            format!(
                "promotion candidate was not captured: {}",
                candidate_path.display()
            )
        })?;
        let candidate = PromotionCandidate::parse(&candidate_path, plan_id, candidate_bytes)?;
        require_safe_id(&candidate.destination, "promotion destination")?;
        let target = memory
            .knowledge
            .path
            .join("findings")
            .join(format!("{}.md", candidate.destination));
        writes.push(PendingWrite {
            target: target.clone(),
            content: candidate.content,
        });
        promotions.push(json!({
            "source": relative(root, &candidate_path),
            "destination": relative(root, &target),
            "disposition": candidate.disposition,
            "staleness": candidate.staleness,
            "resolution": candidate.resolution,
        }));
    }
    Ok(promotions)
}

#[allow(clippy::too_many_arguments)]
fn append_conclusion_writes(
    memory: &MemoryPaths,
    plan_path: &Path,
    plan_bytes: &[u8],
    plan_revision: &str,
    plan_id: &str,
    contracts: &[JsonValue],
    specifications: &[JsonValue],
    promotions: &[JsonValue],
    writes: &mut Vec<PendingWrite>,
) -> Result<()> {
    let completed_plan = content_with_status(plan_bytes, "completed")?;
    writes.push(PendingWrite {
        target: plan_path.to_path_buf(),
        content: completed_plan,
    });

    let conclusion_path = memory
        .knowledge
        .path
        .join("conclusions")
        .join(conclusion_filename(plan_id));
    let conclusion = render_conclusion(
        plan_id,
        plan_revision,
        contracts,
        specifications,
        promotions,
    )?;
    writes.push(PendingWrite {
        target: conclusion_path,
        content: conclusion.into_bytes(),
    });

    let promotion_path = memory
        .knowledge
        .path
        .join("promotions")
        .join(format!("{plan_id}.md"));
    let promotion = render_promotion_record(plan_id, plan_revision, contracts, promotions)?;
    writes.push(PendingWrite {
        target: promotion_path,
        content: promotion.into_bytes(),
    });

    let post_path = post_action_path(memory, plan_id);
    let post_state = render_post_actions(plan_id, 0, &[])?;
    writes.push(PendingWrite {
        target: post_path,
        content: post_state.into_bytes(),
    });
    Ok(())
}

pub fn status(plan_path: &Path) -> Result<JsonValue> {
    let memory = output_memory(plan_path)?;
    let mut data = PostActionDocument::load(plan_path)?.into_data()?;
    let references: Vec<_> = data["outputs"].as_array().into_iter().flatten()
        .filter_map(JsonValue::as_str)
        .filter(|reference| reference.starts_with('<'))
        .map(|reference| match resolve_output_reference(&memory, reference) {
            Ok(path) => json!({"reference": reference, "available": path.exists(), "path": path}),
            Err(error) => json!({"reference": reference, "available": false, "path": null, "error": error.to_string()}),
        }).collect();
    data["output_references"] = json!(references);
    Ok(data)
}

pub fn retry(plan_path: &Path) -> Result<JsonValue> {
    PostActionDocument::update(plan_path, |document| {
        let attempts = document
            .mapping
            .get(key("attempts"))
            .and_then(YamlValue::as_u64)
            .unwrap_or(0)
            + 1;
        document
            .mapping
            .insert(key("attempts"), YamlValue::Number(attempts.into()));
        document.mapping.remove(key("failed_action"));
        let actions = document.actions_mut()?;
        for value in actions.values_mut() {
            if value.as_str() == Some("failed") {
                *value = YamlValue::String("pending".to_string());
            }
        }
        Ok(())
    })
}

pub fn update_action(
    plan_path: &Path,
    action: &str,
    failed: bool,
    output: Option<&str>,
) -> Result<JsonValue> {
    if !matches!(action, "reflection" | "friction" | "handoff") {
        bail!("unknown post-conclusion action `{action}`");
    }
    let output = output
        .map(|value| normalize_output(&output_memory(plan_path)?, value))
        .transpose()?;
    PostActionDocument::update(plan_path, |document| {
        let actions = document.actions_mut()?;
        actions.insert(
            key(action),
            YamlValue::String(if failed { "failed" } else { "completed" }.to_string()),
        );
        if failed {
            document
                .mapping
                .insert(key("failed_action"), YamlValue::String(action.to_string()));
        } else if document
            .mapping
            .get(key("failed_action"))
            .and_then(YamlValue::as_str)
            == Some(action)
        {
            document.mapping.remove(key("failed_action"));
        }
        if let Some(output) = output.as_deref() {
            let outputs = document
                .mapping
                .entry(key("outputs"))
                .or_insert_with(|| YamlValue::Sequence(Vec::new()))
                .as_sequence_mut()
                .context("post-conclusion outputs must be a sequence")?;
            if !outputs.iter().any(|value| value.as_str() == Some(output)) {
                outputs.push(YamlValue::String(output.to_string()));
                outputs.sort_by_key(|value| value.as_str().unwrap_or_default().to_string());
            }
        }
        Ok(())
    })
}

fn output_memory(plan_path: &Path) -> Result<MemoryPaths> {
    let root = project_root(&plan_path.canonicalize()?)?;
    let (mut paths, checkout) = memory_for_root(&root)?;
    paths.root = checkout;
    Ok(paths)
}

fn memory_for_root(root: &Path) -> Result<(MemoryPaths, PathBuf)> {
    let checkout = if let Ok(output) = std::process::Command::new("git")
        .args(["rev-parse", "--show-toplevel"])
        .output()
        && output.status.success()
    {
        let checkout = PathBuf::from(String::from_utf8(output.stdout)?.trim()).canonicalize()?;
        if memory::repository_memory_root(&checkout) == root {
            checkout
        } else {
            root.to_path_buf()
        }
    } else {
        root.to_path_buf()
    };
    let mut paths = MemoryPaths::resolve(&checkout)?;
    if checkout != root {
        // MemoryPaths resolves linked worktrees through their shared repository root.
        // Built-in stores belong to the invoking checkout; configured stores keep precedence.
        if paths.working.source == Source::Builtin {
            paths.working.path = checkout.join(MemoryKind::Working.default_relative());
        }
        if paths.knowledge.source == Source::Builtin {
            paths.knowledge.path = checkout.join(MemoryKind::Knowledge.default_relative());
        }
    }
    Ok((paths, checkout))
}

fn output_roots(memory: &MemoryPaths) -> [(&'static str, &Path); 3] {
    [
        ("<working>", &memory.working.path),
        ("<knowledge>", &memory.knowledge.path),
        ("<repo>", &memory.root),
    ]
}

// Resolve only ordinary missing suffixes. A broken link is not a missing artifact.
fn resolve_output_path(path: &Path) -> Result<PathBuf> {
    if path
        .components()
        .any(|component| matches!(component, std::path::Component::ParentDir))
    {
        bail!("output references cannot contain parent components");
    }
    let mut ancestor = path.to_path_buf();
    let mut missing = Vec::new();
    loop {
        match ancestor.canonicalize() {
            Ok(mut resolved) => {
                for component in missing.iter().rev() {
                    resolved.push(component);
                }
                return Ok(resolved);
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                match std::fs::symlink_metadata(&ancestor) {
                    Ok(metadata) if metadata.file_type().is_symlink() => {
                        bail!("output reference contains an unresolved symlink")
                    }
                    Ok(_) => return Err(error.into()),
                    Err(metadata_error)
                        if metadata_error.kind() == std::io::ErrorKind::NotFound => {}
                    Err(metadata_error) => return Err(metadata_error.into()),
                }
                let component = ancestor
                    .file_name()
                    .context("cannot resolve output reference")?
                    .to_os_string();
                missing.push(component);
                if !ancestor.pop() {
                    bail!("cannot resolve output reference");
                }
            }
            Err(error) => return Err(error.into()),
        }
    }
}

fn reference_parts(reference: &str) -> Result<(&str, &str)> {
    let (token, suffix) = reference
        .split_once('/')
        .context("use <working>/path, <knowledge>/path or <repo>/path")?;
    if !matches!(token, "<working>" | "<knowledge>" | "<repo>")
        || suffix.is_empty()
        || !Path::new(suffix)
            .components()
            .all(|component| matches!(component, std::path::Component::Normal(_)))
        || suffix
            .split('/')
            .any(|part| part.is_empty() || matches!(part, "." | "..") || part.contains('\\'))
    {
        bail!("output reference requires a known root and nonempty normal path components");
    }
    Ok((token, suffix))
}

fn resolve_output_reference(memory: &MemoryPaths, reference: &str) -> Result<PathBuf> {
    let (token, suffix) = reference_parts(reference)?;
    let root = output_roots(memory)
        .into_iter()
        .find(|(name, _)| *name == token)
        .unwrap()
        .1;
    let root = resolve_output_path(root)?;
    let path = resolve_output_path(&root.join(suffix))?;
    if !path.starts_with(&root) {
        bail!("output reference escapes its configured root");
    }
    Ok(path)
}

fn replace_embedded_root(output: &mut String, root: &str, token: &str) {
    let mut cursor = 0;
    while let Some(offset) = output[cursor..].find(root) {
        let start = cursor + offset;
        let end = start + root.len();
        let starts_at_boundary = output[..start].chars().next_back().is_none_or(|character| {
            !character.is_alphanumeric() && !matches!(character, '_' | '/' | '\\')
        });
        let has_child_path = output[end..]
            .chars()
            .next()
            .is_some_and(|character| character == std::path::MAIN_SEPARATOR || character == '/');
        if starts_at_boundary && has_child_path {
            output.replace_range(start..end, token);
            cursor = start + token.len();
        } else {
            cursor = end;
        }
    }
}

fn normalize_embedded_roots(memory: &MemoryPaths, output: &str) -> String {
    let mut roots: Vec<_> = output_roots(memory)
        .into_iter()
        .filter_map(|(token, root)| {
            let root = resolve_output_path(root).ok()?;
            let text = root.to_str()?.to_owned();
            Some((root.components().count(), token, text))
        })
        .collect();
    roots.sort_by_key(|(depth, _, _)| std::cmp::Reverse(*depth));

    let mut normalized = output.to_owned();
    for (_, token, root) in roots {
        replace_embedded_root(&mut normalized, &root, token);
    }
    normalized
}

fn normalize_output(memory: &MemoryPaths, output: &str) -> Result<String> {
    if output
        .get(..5)
        .is_some_and(|scheme| scheme.eq_ignore_ascii_case("file:"))
    {
        bail!("file URI outputs are not portable; use a configured root reference");
    }
    if output.starts_with('<') {
        resolve_output_reference(memory, output)?;
        return Ok(output.to_string());
    }
    if !Path::new(output).is_absolute() {
        return Ok(normalize_embedded_roots(memory, output));
    }
    let path = resolve_output_path(Path::new(output))?;
    let mut matches = Vec::new();
    for (token, root) in output_roots(memory) {
        let root = resolve_output_path(root)?;
        if let Ok(suffix) = path.strip_prefix(&root)
            && !suffix.as_os_str().is_empty()
        {
            matches.push((root.components().count(), token, suffix.to_path_buf()));
        }
    }
    // Stable ordering retains working, knowledge, repo precedence for equal roots.
    matches.sort_by_key(|(depth, _, _)| std::cmp::Reverse(*depth));
    let (_, token, suffix) = matches.first().context("absolute output is outside configured stores and checkout; use a portable descriptive label")?;
    let components: Vec<_> = suffix
        .components()
        .map(|component| match component {
            std::path::Component::Normal(name) => {
                name.to_str().context("output reference must be UTF-8")
            }
            _ => bail!("output reference requires normal path components"),
        })
        .collect::<Result<_>>()?;
    let reference = format!("{token}/{}", components.join("/"));
    reference_parts(&reference)?;
    Ok(reference)
}

struct PostActionDocument {
    path: PathBuf,
    mapping: Mapping,
    body: String,
}

impl PostActionDocument {
    fn load(plan_path: &Path) -> Result<Self> {
        let path = Self::resolve_path(plan_path)?;
        let bytes = std::fs::read(&path)?;
        Self::from_bytes(path, &bytes)
    }

    fn update(plan_path: &Path, mutate: impl FnOnce(&mut Self) -> Result<()>) -> Result<JsonValue> {
        let path = Self::resolve_path(plan_path)?;
        crate::journal::update(&path, |bytes| {
            let mut document = Self::from_bytes(path.clone(), bytes)?;
            mutate(&mut document)?;
            let (_, content, data) = document.finish()?;
            Ok((content, data))
        })
    }

    fn resolve_path(plan_path: &Path) -> Result<PathBuf> {
        let plan_path = plan_path.canonicalize()?;
        let root = project_root(&plan_path)?;
        let (memory, _) = memory_for_root(&root)?;
        let plan_id = plan_id(&plan_path)?;
        require_safe_id(&plan_id, "plan id")?;
        let post_root = memory
            .knowledge
            .path
            .canonicalize()?
            .join("workflow/post-conclusion");
        let path = post_action_path(&memory, &plan_id).canonicalize()?;
        if !path.starts_with(&post_root) {
            bail!("post-conclusion document points outside the post-conclusion directory");
        }
        Ok(path)
    }

    fn from_bytes(path: PathBuf, bytes: &[u8]) -> Result<Self> {
        let (frontmatter, body) = varde_workflow_core::frontmatter::parse(bytes)?;
        let YamlValue::Mapping(mapping) = frontmatter else {
            unreachable!("parser guarantees mapping");
        };
        Ok(Self {
            path,
            mapping,
            body,
        })
    }

    fn actions_mut(&mut self) -> Result<&mut Mapping> {
        self.mapping
            .get_mut(key("actions"))
            .and_then(YamlValue::as_mapping_mut)
            .context("post-conclusion actions are missing")
    }

    fn finish(mut self) -> Result<(PathBuf, Vec<u8>, JsonValue)> {
        let status = self
            .mapping
            .get(key("actions"))
            .and_then(YamlValue::as_mapping)
            .map(overall_action_status)
            .context("post-conclusion actions are missing")?;
        self.mapping
            .insert(key("status"), YamlValue::String(status.to_string()));
        let frontmatter = YamlValue::Mapping(self.mapping);
        let content =
            varde_workflow_core::frontmatter::serialize(&frontmatter, &self.body)?.into_bytes();
        let data = serde_json::to_value(&frontmatter)?;
        Ok((self.path, content, data))
    }

    fn into_data(self) -> Result<JsonValue> {
        Ok(serde_json::to_value(YamlValue::Mapping(self.mapping))?)
    }
}

fn overall_action_status(actions: &Mapping) -> &'static str {
    if actions
        .values()
        .any(|value| value.as_str() == Some("failed"))
    {
        "failed"
    } else if actions
        .values()
        .all(|value| value.as_str() == Some("completed"))
    {
        "completed"
    } else {
        "pending"
    }
}

pub fn mark_post_failure(memory: &MemoryPaths, plan_id: &str, action: &str) -> Result<()> {
    let path = post_action_path(memory, plan_id);
    let frontmatter = json!({
        "type": "reference",
        "status": "failed",
        "plan": plan_id,
        "attempts": 1,
        "failed_action": action,
        "outputs": [],
        "actions": {
            "reflection": if action == "reflection" { "failed" } else { "pending" },
            "friction": if action == "friction" { "failed" } else { "pending" },
            "handoff": if action == "handoff" { "failed" } else { "pending" },
        },
    });
    let content = render_post_document(&frontmatter)?;
    crate::journal::commit(&path, content.as_bytes())
}

struct ContractDelta {
    capability: String,
    source_plan: String,
    base_revision: Option<String>,
    added: BTreeMap<String, String>,
    modified: BTreeMap<String, String>,
    removed: Vec<String>,
}

impl ContractDelta {
    fn parse(path: &Path, plan_id: &str, bytes: &[u8]) -> Result<Self> {
        let (frontmatter, body) = varde_workflow_core::frontmatter::parse(bytes)?;
        let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
        if required_string(mapping, "type")? != "contract-delta" {
            bail!("contract delta {} has an invalid type", path.display());
        }
        if mapping
            .get(key("schema_version"))
            .and_then(YamlValue::as_u64)
            != Some(1)
        {
            bail!(
                "contract delta {} has an invalid schema version",
                path.display()
            );
        }
        let source_plan = required_string(mapping, "source_plan")?;
        if source_plan != plan_id {
            bail!("contract delta {} references another plan", path.display());
        }
        let capability = required_string(mapping, "capability")?;
        let base_revision = optional_string(mapping, "base_revision");
        let sections = operation_sections(&body)?;
        Ok(Self {
            capability,
            source_plan,
            base_revision,
            added: requirement_blocks(sections.get("ADDED").map(String::as_str).unwrap_or(""))?,
            modified: requirement_blocks(
                sections.get("MODIFIED").map(String::as_str).unwrap_or(""),
            )?,
            removed: removed_requirements(
                sections.get("REMOVED").map(String::as_str).unwrap_or(""),
            ),
        })
    }

    fn merge(&self, target_bytes: Option<&[u8]>) -> Result<String> {
        let mut requirements = if let Some(bytes) = target_bytes {
            let revision = varde_workflow_core::occ::version(bytes);
            if self.base_revision.as_deref() != Some(revision.as_str()) {
                bail!("contract `{}` base revision changed", self.capability);
            }
            let (_, body) = varde_workflow_core::frontmatter::parse(bytes)?;
            contract_requirements(&body)?
        } else {
            if self.base_revision.is_some() {
                bail!(
                    "new contract `{}` cannot declare base revision",
                    self.capability
                );
            }
            BTreeMap::new()
        };

        for id in &self.removed {
            if requirements.remove(id).is_none() {
                bail!("removed requirement `{id}` does not exist");
            }
        }
        for (id, content) in &self.modified {
            if !requirements.contains_key(id) {
                bail!("modified requirement `{id}` does not exist");
            }
            requirements.insert(id.clone(), content.clone());
        }
        for (id, content) in &self.added {
            if requirements.insert(id.clone(), content.clone()).is_some() {
                bail!("added requirement `{id}` already exists");
            }
        }

        let mut output = format!(
            "---\ntype: reference\ntitle: Contract for {}\nsource: {}\nstatus: stable\n---\n\n# Contract: {}\n",
            self.capability, self.source_plan, self.capability
        );
        for content in requirements.values() {
            output.push('\n');
            output.push_str(content.trim_end());
            output.push('\n');
        }
        Ok(output)
    }
}

struct PromotionCandidate {
    destination: String,
    disposition: String,
    staleness: String,
    resolution: String,
    content: Vec<u8>,
}

impl PromotionCandidate {
    fn parse(path: &Path, plan_id: &str, bytes: &[u8]) -> Result<Self> {
        let (frontmatter, _) = varde_workflow_core::frontmatter::parse(bytes)?;
        let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
        if required_string(mapping, "source_plan")? != plan_id {
            bail!(
                "promotion candidate {} references another plan",
                path.display()
            );
        }
        if required_string(mapping, "status")? != "accepted" {
            bail!("promotion candidate {} is not accepted", path.display());
        }
        Ok(Self {
            destination: optional_string(mapping, "destination")
                .unwrap_or_else(|| derived_id(path)),
            disposition: required_string(mapping, "disposition")?,
            staleness: required_string(mapping, "staleness")?,
            resolution: required_string(mapping, "resolution")?,
            content: bytes.to_vec(),
        })
    }
}

fn validate_specification(
    memory: &MemoryPaths,
    path: &Path,
    bytes: &[u8],
    inputs: &BTreeMap<PathBuf, Vec<u8>>,
    expected_sources: &[ExpectedSource],
) -> Result<String> {
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    let expected = required_string(mapping, "source_hash")?;
    validate_spec_coverage(memory, path, mapping, expected_sources)?;
    let sources = mapping
        .get(key("sources"))
        .and_then(YamlValue::as_sequence)
        .context("observed specification requires `sources`")?;
    let mut pairs = Vec::new();
    for source in sources {
        let source = source
            .as_mapping()
            .context("spec source must be a mapping")?;
        let relative_path = required_string(source, "path")?;
        let recorded = required_string(source, "hash")?;
        let source_path = contained_file(memory, &memory.root.join(&relative_path), "spec source")?;
        let source_key = memory::canonical_or_lexical(&source_path);
        let source_bytes = inputs.get(&source_key).with_context(|| {
            format!(
                "observed specification source was not captured: {}",
                source_path.display()
            )
        })?;
        let actual = git_blob_hash(source_bytes);
        if actual != recorded {
            bail!("observed specification {} is stale", path.display());
        }
        pairs.push((relative_path, actual));
    }
    pairs.sort();
    let aggregate = pairs
        .iter()
        .map(|(path, hash)| format!("{path}{hash}"))
        .collect::<String>();
    let actual = git_blob_hash(aggregate.as_bytes());
    if actual != expected {
        bail!(
            "observed specification {} has a stale aggregate",
            path.display()
        );
    }
    Ok(actual)
}

fn validate_spec_coverage(
    memory: &MemoryPaths,
    spec: &Path,
    mapping: &Mapping,
    expected_sources: &[ExpectedSource],
) -> Result<()> {
    let roots = spec_paths(mapping, "source_roots")?;
    let covered = spec_paths(mapping, "covered_paths")?;
    if roots.is_empty() {
        bail!(
            "observed specification {} requires source_roots",
            spec.display()
        );
    }
    let mut recorded = covered.clone();
    recorded.sort();
    recorded.dedup();
    if covered != recorded {
        bail!(
            "observed specification {} has unsorted or duplicate covered_paths",
            spec.display()
        );
    }

    let repository = memory.root.canonicalize()?;
    let actual = expected_sources
        .iter()
        .find(|source| {
            source.path == repository
                && source
                    .inventory
                    .as_ref()
                    .is_some_and(|inventory| inventory.roots == roots)
        })
        .and_then(|source| source.inventory.as_ref())
        .context("observed specification source inventory was not captured")?
        .paths
        .clone();
    if actual != covered {
        bail!(
            "observed specification {} has stale covered_paths",
            spec.display()
        );
    }
    Ok(())
}

fn spec_paths(mapping: &Mapping, field: &str) -> Result<Vec<String>> {
    let paths = mapping
        .get(key(field))
        .and_then(YamlValue::as_sequence)
        .with_context(|| format!("observed specification requires `{field}`"))?;
    paths
        .iter()
        .map(|value| {
            let path = value
                .as_str()
                .with_context(|| format!("{field} entries must be strings"))?;
            require_safe_id(path, field)?;
            Ok(path.to_string())
        })
        .collect()
}

fn git_blob_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha1::new();
    hasher.update(format!("blob {}\0", bytes.len()).as_bytes());
    hasher.update(bytes);
    format!("{:x}", hasher.finalize())
}

fn operation_sections(body: &str) -> Result<BTreeMap<String, String>> {
    let mut sections = BTreeMap::new();
    let mut current: Option<String> = None;
    for line in body.lines() {
        if let Some(name) = line.strip_prefix("## ") {
            if !matches!(name, "ADDED" | "MODIFIED" | "REMOVED") {
                bail!("unknown contract delta section `{name}`");
            }
            current = Some(name.to_string());
            sections.entry(name.to_string()).or_insert_with(String::new);
        } else if let Some(name) = &current {
            let value = sections.get_mut(name).expect("section exists");
            value.push_str(line);
            value.push('\n');
        } else if !line.trim().is_empty() {
            bail!("contract delta content must appear under an operation section");
        }
    }
    Ok(sections)
}

fn requirement_blocks(section: &str) -> Result<BTreeMap<String, String>> {
    let mut blocks = BTreeMap::new();
    let mut current: Option<(String, String)> = None;
    for line in section.lines() {
        if let Some(id) = line.strip_prefix("### Requirement: ") {
            if let Some((previous, content)) = current.take()
                && blocks.insert(previous.clone(), content).is_some()
            {
                bail!("duplicate requirement `{previous}`");
            }
            current = Some((
                id.trim().to_string(),
                format!("## Requirement: {}\n", id.trim()),
            ));
        } else if let Some((_, content)) = &mut current {
            content.push_str(line);
            content.push('\n');
        } else if !line.trim().is_empty() {
            bail!("contract operation content requires a requirement heading");
        }
    }
    if let Some((id, content)) = current
        && blocks.insert(id.clone(), content).is_some()
    {
        bail!("duplicate requirement `{id}`");
    }
    Ok(blocks)
}

fn contract_requirements(body: &str) -> Result<BTreeMap<String, String>> {
    let mut started = false;
    let normalized = body
        .lines()
        .filter_map(|line| {
            if let Some(id) = line.strip_prefix("## Requirement: ") {
                started = true;
                Some(format!("### Requirement: {id}"))
            } else if started {
                Some(line.to_string())
            } else {
                None
            }
        })
        .collect::<Vec<_>>()
        .join("\n");
    requirement_blocks(&normalized)
}

fn removed_requirements(section: &str) -> Vec<String> {
    let mut values = section
        .lines()
        .filter_map(|line| line.trim().strip_prefix("- "))
        .map(str::to_string)
        .collect::<Vec<_>>();
    values.sort();
    values.dedup();
    values
}

fn render_conclusion(
    plan_id: &str,
    plan_revision: &str,
    contracts: &[JsonValue],
    specifications: &[JsonValue],
    promotions: &[JsonValue],
) -> Result<String> {
    let details = serde_yaml::to_string(&json!({
        "plan": plan_id,
        "plan_revision": plan_revision,
        "contracts": contracts,
        "specifications": specifications,
        "promotions": promotions,
    }))?;
    Ok(format!(
        "---\ntype: reference\ntitle: Conclusion for {plan_id}\nstatus: stable\n---\n\n# Conclusion: {plan_id}\n\n```yaml\n{details}```\n"
    ))
}

fn render_promotion_record(
    plan_id: &str,
    plan_revision: &str,
    contracts: &[JsonValue],
    promotions: &[JsonValue],
) -> Result<String> {
    let details = serde_yaml::to_string(&json!({
        "source_plan": plan_id,
        "plan_revision": plan_revision,
        "contracts": contracts,
        "promoted_artifacts": promotions,
    }))?;
    Ok(format!(
        "---\ntype: reference\ntitle: Promotion record for {plan_id}\nstatus: stable\n---\n\n# Promotion: {plan_id}\n\n```yaml\n{details}```\n"
    ))
}

fn render_post_actions(plan_id: &str, attempts: u64, outputs: &[String]) -> Result<String> {
    render_post_document(&json!({
        "type": "reference",
        "status": "pending",
        "plan": plan_id,
        "attempts": attempts,
        "outputs": outputs,
        "actions": {
            "reflection": "pending",
            "friction": "pending",
            "handoff": "pending",
        },
    }))
}

fn render_post_document(frontmatter: &JsonValue) -> Result<String> {
    Ok(format!(
        "---\n{}---\n\nPost-conclusion enrichment remains retryable.\n",
        serde_yaml::to_string(frontmatter)?
    ))
}

fn content_with_status(bytes: &[u8], status: &str) -> Result<Vec<u8>> {
    let (frontmatter, body) = varde_workflow_core::frontmatter::parse(bytes)?;
    let mut mapping = frontmatter
        .as_mapping()
        .expect("parser guarantees mapping")
        .clone();
    mapping.insert(key("status"), YamlValue::String(status.to_string()));
    Ok(
        varde_workflow_core::frontmatter::serialize(&YamlValue::Mapping(mapping), &body)?
            .into_bytes(),
    )
}

fn has_unchecked_acceptance(body: &str) -> Result<bool> {
    let mut in_acceptance = false;
    let mut found = false;
    for line in body.lines() {
        if line.trim() == "## Acceptance criteria" {
            in_acceptance = true;
            found = true;
            continue;
        }
        if in_acceptance && line.starts_with("## ") {
            break;
        }
        if in_acceptance && line.trim_start().starts_with("- [ ]") {
            return Ok(true);
        }
    }
    if !found {
        bail!("plan is missing an acceptance criteria section");
    }
    Ok(false)
}

fn declared_paths(mapping: &Mapping, field: &str, plan_path: &Path) -> Result<Vec<PathBuf>> {
    let base = plan_path.parent().context("plan has no parent directory")?;
    optional_strings(mapping, field).map(|paths| {
        paths
            .into_iter()
            .map(|path| {
                let path = PathBuf::from(path);
                if path.is_absolute() {
                    path
                } else {
                    base.join(path)
                }
            })
            .collect()
    })
}

fn optional_strings(mapping: &Mapping, field: &str) -> Result<Vec<String>> {
    let Some(value) = mapping.get(key(field)) else {
        return Ok(Vec::new());
    };
    value
        .as_sequence()
        .with_context(|| format!("plan field `{field}` must be a sequence"))?
        .iter()
        .map(|value| {
            value
                .as_str()
                .map(str::to_string)
                .with_context(|| format!("plan field `{field}` entries must be strings"))
        })
        .collect()
}

fn required_string(mapping: &Mapping, field: &str) -> Result<String> {
    optional_string(mapping, field).with_context(|| format!("required field `{field}` is missing"))
}

fn optional_string(mapping: &Mapping, field: &str) -> Option<String> {
    mapping
        .get(key(field))
        .and_then(YamlValue::as_str)
        .map(str::to_string)
}

fn project_root(path: &Path) -> Result<PathBuf> {
    memory::find_root(path)
        .context("artifact is outside a project memory bank")?
        .canonicalize()
        .map_err(Into::into)
}

fn plan_id(path: &Path) -> Result<String> {
    let bytes = std::fs::read(path)?;
    let (frontmatter, _) = varde_workflow_core::frontmatter::parse(&bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    Ok(optional_string(mapping, "id").unwrap_or_else(|| derived_id(path)))
}

fn contained_file(memory: &MemoryPaths, path: &Path, kind: &str) -> Result<PathBuf> {
    let path = path
        .canonicalize()
        .with_context(|| format!("failed to resolve {kind} {}", path.display()))?;
    if !memory.contains(&path) {
        bail!("{kind} points outside project root and memory directories");
    }
    Ok(path)
}

fn require_safe_id(value: &str, kind: &str) -> Result<()> {
    let path = Path::new(value);
    if value.is_empty()
        || path.is_absolute()
        || path
            .components()
            .any(|component| !matches!(component, std::path::Component::Normal(_)))
    {
        bail!("{kind} contains unsafe path components");
    }
    Ok(())
}

fn post_action_path(memory: &MemoryPaths, plan_id: &str) -> PathBuf {
    memory
        .knowledge
        .path
        .join("workflow/post-conclusion")
        .join(format!("{plan_id}.md"))
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

fn conclusion_filename(plan_id: &str) -> String {
    let (group, slug) = match plan_id.rsplit_once('/') {
        Some((group, slug)) => (Some(group), slug),
        None => (None, plan_id),
    };
    if let Some(date) = group.and_then(date_prefix) {
        return format!("{date}-{slug}.md");
    }
    if date_prefix(slug).is_some() {
        return format!("{slug}.md");
    }
    format!("{}-{slug}.md", utc_date())
}

fn date_prefix(value: &str) -> Option<&str> {
    value.get(..10).filter(|prefix| {
        let bytes = prefix.as_bytes();
        bytes[4] == b'-'
            && bytes[7] == b'-'
            && bytes
                .iter()
                .enumerate()
                .all(|(index, byte)| index == 4 || index == 7 || byte.is_ascii_digit())
    })
}

fn utc_date() -> String {
    let days = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .expect("current time precedes Unix epoch")
        .as_secs() as i64
        / 86_400;
    date_from_unix_days(days)
}

fn date_from_unix_days(days: i64) -> String {
    // Civil date from Unix days, using the Gregorian 400-year cycle.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}")
}

fn relative(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}

#[cfg(test)]
mod conclusion_filename_tests {
    use super::{conclusion_filename, date_from_unix_days};

    #[test]
    fn nested_plan_inherits_group_date() {
        assert_eq!(
            conclusion_filename("2026-09-25-audit/cli-resolution"),
            "2026-09-25-cli-resolution.md"
        );
        assert_eq!(
            conclusion_filename("2026-09-25-audit"),
            "2026-09-25-audit.md"
        );
        assert_eq!(
            conclusion_filename("2026-09-25-audit/2026-09-24-child"),
            "2026-09-25-2026-09-24-child.md"
        );
    }

    #[test]
    fn utc_date_conversion_matches_known_dates() {
        assert_eq!(date_from_unix_days(0), "1970-01-01");
        assert_eq!(date_from_unix_days(20_721), "2026-09-25");
    }
}
