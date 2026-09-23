//! Contract promotion and conclusion preparation.

use crate::journal::PendingWrite;
use anyhow::{Context, Result, bail};
use okf_core::memory::{self, MemoryPaths};
use serde_json::{Value as JsonValue, json};
use serde_yaml::{Mapping, Value as YamlValue};
use sha1::{Digest, Sha1};
use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

#[derive(Debug)]
pub struct PreparedConclusion {
    pub memory: MemoryPaths,
    pub plan_id: String,
    pub writes: Vec<PendingWrite>,
    pub contracts: Vec<JsonValue>,
    pub specifications: Vec<JsonValue>,
    pub promotions: Vec<JsonValue>,
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

pub fn prepare(plan_path: &Path) -> Result<PreparedConclusion> {
    let plan_path = plan_path.canonicalize()?;
    let root = project_root(&plan_path)?;
    let memory = MemoryPaths::resolve(&root)?;
    let plan_bytes = std::fs::read(&plan_path)
        .with_context(|| format!("failed to read plan {}", plan_path.display()))?;
    let plan_revision = okf_core::occ::version(&plan_bytes);
    let (frontmatter, body) = okf_core::frontmatter::parse(&plan_bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    let plan_id = optional_string(mapping, "id").unwrap_or_else(|| derived_id(&plan_path));
    if has_unchecked_acceptance(&body)? {
        bail!("plan `{plan_id}` has unchecked acceptance criteria");
    }

    let mut writes = Vec::new();
    let contracts = prepare_contracts(&memory, &root, mapping, &plan_path, &plan_id, &mut writes)?;
    let specifications = prepare_specifications(&memory, &root, mapping)?;
    let promotions =
        prepare_promotions(&memory, &root, mapping, &plan_path, &plan_id, &mut writes)?;
    append_conclusion_writes(
        &memory,
        &root,
        &plan_path,
        &plan_bytes,
        &plan_revision,
        &plan_id,
        &contracts,
        &specifications,
        &promotions,
        &mut writes,
    )?;
    Ok(PreparedConclusion {
        memory,
        plan_id,
        writes,
        contracts,
        specifications,
        promotions,
    })
}

fn prepare_contracts(
    memory: &MemoryPaths,
    root: &Path,
    mapping: &Mapping,
    plan_path: &Path,
    plan_id: &str,
    writes: &mut Vec<PendingWrite>,
) -> Result<Vec<JsonValue>> {
    let mut contracts = Vec::new();
    for delta_path in declared_paths(mapping, "contract_deltas", plan_path)? {
        let delta_path = contained_file(memory, &delta_path, "contract delta")?;
        let delta = ContractDelta::read(&delta_path, plan_id)?;
        require_safe_id(&delta.capability, "contract capability")?;
        let target = memory
            .knowledge
            .path
            .join("contracts")
            .join(format!("{}.md", delta.capability));
        let merged = delta.merge(&target)?;
        let revision = okf_core::occ::version(merged.as_bytes());
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
) -> Result<Vec<JsonValue>> {
    let mut specifications = Vec::new();
    for domain in optional_strings(mapping, "observed_specs")? {
        require_safe_id(&domain, "observed specification domain")?;
        let path = memory
            .knowledge
            .path
            .join("specs")
            .join(format!("{domain}.md"));
        let source_hash = validate_specification(memory, &path)?;
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
    writes: &mut Vec<PendingWrite>,
) -> Result<Vec<JsonValue>> {
    let mut promotions = Vec::new();
    for candidate_path in declared_paths(mapping, "promotion_candidates", plan_path)? {
        let candidate_path = contained_file(memory, &candidate_path, "promotion candidate")?;
        let candidate = PromotionCandidate::read(&candidate_path, plan_id)?;
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
    root: &Path,
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
        .join(format!("{plan_id}.md"));
    let conclusion = render_conclusion(
        plan_id,
        &relative(root, plan_path),
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
    PostActionDocument::load(plan_path)?.into_data()
}

pub fn retry(plan_path: &Path) -> Result<(PathBuf, Vec<u8>, JsonValue)> {
    let mut document = PostActionDocument::load(plan_path)?;
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
    document.finish()
}

pub fn update_action(
    plan_path: &Path,
    action: &str,
    failed: bool,
    output: Option<&str>,
) -> Result<(PathBuf, Vec<u8>, JsonValue)> {
    if !matches!(action, "reflection" | "friction" | "handoff") {
        bail!("unknown post-conclusion action `{action}`");
    }
    let mut document = PostActionDocument::load(plan_path)?;
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
    if let Some(output) = output {
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
    document.finish()
}

struct PostActionDocument {
    path: PathBuf,
    mapping: Mapping,
    body: String,
}

impl PostActionDocument {
    fn load(plan_path: &Path) -> Result<Self> {
        let plan_path = plan_path.canonicalize()?;
        let root = project_root(&plan_path)?;
        let memory = MemoryPaths::resolve(&root)?;
        let plan_id = plan_id(&plan_path)?;
        let path = post_action_path(&memory, &plan_id);
        let bytes = std::fs::read(&path)?;
        let (frontmatter, body) = okf_core::frontmatter::parse(&bytes)?;
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
        let content = okf_core::frontmatter::serialize(&frontmatter, &self.body)?.into_bytes();
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
    fn read(path: &Path, plan_id: &str) -> Result<Self> {
        let bytes = std::fs::read(path)?;
        let (frontmatter, body) = okf_core::frontmatter::parse(&bytes)?;
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

    fn merge(&self, target: &Path) -> Result<String> {
        let mut requirements = if target.exists() {
            let bytes = std::fs::read(target)?;
            let revision = okf_core::occ::version(&bytes);
            if self.base_revision.as_deref() != Some(revision.as_str()) {
                bail!("contract `{}` base revision changed", self.capability);
            }
            let (_, body) = okf_core::frontmatter::parse(&bytes)?;
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
    fn read(path: &Path, plan_id: &str) -> Result<Self> {
        let bytes = std::fs::read(path)?;
        let (frontmatter, _) = okf_core::frontmatter::parse(&bytes)?;
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
            content: bytes,
        })
    }
}

fn validate_specification(memory: &MemoryPaths, path: &Path) -> Result<String> {
    let bytes = std::fs::read(path)
        .with_context(|| format!("observed specification {} is missing", path.display()))?;
    let (frontmatter, _) = okf_core::frontmatter::parse(&bytes)?;
    let mapping = frontmatter.as_mapping().expect("parser guarantees mapping");
    let expected = required_string(mapping, "source_hash")?;
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
        let actual = git_blob_hash(&std::fs::read(source_path)?);
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
    plan_path: &str,
    plan_revision: &str,
    contracts: &[JsonValue],
    specifications: &[JsonValue],
    promotions: &[JsonValue],
) -> Result<String> {
    let details = serde_yaml::to_string(&json!({
        "plan": plan_path,
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
    let (frontmatter, body) = okf_core::frontmatter::parse(bytes)?;
    let mut mapping = frontmatter
        .as_mapping()
        .expect("parser guarantees mapping")
        .clone();
    mapping.insert(key("status"), YamlValue::String(status.to_string()));
    Ok(okf_core::frontmatter::serialize(&YamlValue::Mapping(mapping), &body)?.into_bytes())
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
    let (frontmatter, _) = okf_core::frontmatter::parse(&bytes)?;
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

fn relative(root: &Path, path: &Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .to_string()
}

fn key(name: &str) -> YamlValue {
    YamlValue::String(name.to_string())
}
