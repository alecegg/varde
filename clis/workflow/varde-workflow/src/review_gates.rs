//! Local reviewer evidence, normalized contracts, and immutable source baselines.

use crate::review_contract;
use crate::review_coverage::{self, SnapshotEntry};
use anyhow::{Context, Result, anyhow};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use serde_yaml::Value as YamlValue;
use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::io;
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use varde_workflow_core::memory::{self, MemoryPaths};

const SUBJECT_SCHEMA: u32 = 1;
const RECORD_SCHEMA: u32 = 1;

#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(deny_unknown_fields)]
pub(crate) struct Subject {
    pub(crate) schema_version: u32,
    pub(crate) subject_id: String,
    pub(crate) repository_root: PathBuf,
    pub(crate) plan_path: Option<PathBuf>,
    pub(crate) bounded_contract: Option<Value>,
    pub(crate) scope: Vec<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub(crate) artifact_scope: Vec<String>,
    pub(crate) excludes: Vec<String>,
    pub(crate) baseline_id: String,
    pub(crate) snapshots: BTreeMap<String, SnapshotEntry>,
    pub(crate) scope_additions: BTreeSet<String>,
    #[serde(default)]
    pub(crate) tier_evidence: Option<TierEvidence>,
    /// History of prior `baseline_id` values a fully-covered `expand_scope`
    /// call carried forward. Not a `baseline_fingerprint_with_artifacts`
    /// hash input.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub(crate) carried_baselines: Vec<String>,
    /// The plan's task-declared ownership paths (`modifies`, `creates`, and
    /// renamed-to paths), frozen at the moment a `phase == "pre-edit"`
    /// `EvidenceRecord` is accepted. Meaningful only for plan subjects;
    /// stays empty for bounded subjects.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub(crate) approved_ownership: Vec<String>,
    #[serde(skip)]
    pub(crate) metadata_revision: String,
    #[serde(skip)]
    pub(crate) baseline_revisions: Vec<EvidenceRevision>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct EvidenceRevision {
    pub path: PathBuf,
    pub revision: String,
}

/// Fingerprinted `scripts/risk-tier.py` output, or the safe default when
/// `--tier-evidence` is missing, unreadable, or malformed.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct TierEvidence {
    pub(crate) fingerprint: String,
    pub(crate) tier: String,
    pub(crate) signals: Vec<String>,
    pub(crate) recorded_at: String,
}

impl Subject {
    /// Subjects created before this field existed default to `high`, same as
    /// a missing or unreadable `--tier-evidence` file.
    pub(crate) fn tier(&self) -> &str {
        self.tier_evidence
            .as_ref()
            .map(|evidence| evidence.tier.as_str())
            .unwrap_or("high")
    }
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Reviewer {
    identity: String,
    provenance: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct EvidenceRecord {
    schema_version: u32,
    subject_id: String,
    phase: String,
    reviewer: Reviewer,
    verdict: String,
    unresolved_choices: Vec<String>,
    contract_fingerprint: String,
    baseline_id: String,
    #[serde(default)]
    change_fingerprint: Option<String>,
    #[serde(default)]
    coverage: Option<String>,
    verification_approach: String,
    verification_rationale: String,
    verification_expected_results: String,
    #[serde(default)]
    structural_risk: Option<String>,
    #[serde(default)]
    structural_risk_rationale: Option<String>,
    #[serde(default)]
    implementation_review_required: Option<bool>,
    #[serde(default)]
    tier_confirmed: Option<bool>,
    rationale: String,
}

#[derive(Debug)]
pub struct ReviewError {
    pub code: &'static str,
    pub exit_code: i32,
    pub message: String,
    pub details: Value,
}

impl std::fmt::Display for ReviewError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.message)
    }
}

impl std::error::Error for ReviewError {}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ReviewPrerequisites {
    pub subject_id: String,
    pub repository_root: PathBuf,
    pub plan_path: Option<PathBuf>,
    pub subject_revision: String,
    #[serde(default)]
    pub subject_metadata_revision: String,
    #[serde(default)]
    pub baseline_revisions: Vec<EvidenceRevision>,
    pub pre_edit_revision: Option<String>,
    pub implementation_revision: Option<String>,
    pub contract_fingerprint: String,
    pub baseline_id: String,
    pub change_fingerprint: String,
    pub coverage_manifest: Vec<Value>,
}

pub fn scope_for_plan(repository: &Path, plan_path: &Path) -> Result<Option<Vec<String>>> {
    let repository = canonical_directory(repository)?;
    let plan_path = plan_path.canonicalize()?;
    let root = gate_root_for(&repository, false)?;
    if !root.exists() {
        return Ok(None);
    }
    let mut found = None;
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        if !entry.file_type()?.is_dir() || entry.file_name().to_string_lossy().starts_with('.') {
            continue;
        }
        let path = entry.path().join("subject.json");
        match fs::symlink_metadata(&path) {
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error.into()),
        }
        let subject = read_subject_file(&entry.path())?;
        if subject.plan_path.as_deref() == Some(plan_path.as_path()) {
            if subject.repository_root != repository {
                return Err(invalid(
                    "review subject repository identity does not match its configured working store",
                ));
            }
            if found.replace(subject.scope).is_some() {
                return Err(invalid("multiple review subjects refer to the same plan"));
            }
        }
    }
    Ok(found)
}

pub fn approved_contract_fingerprint_for_plan(
    repository: &Path,
    plan_path: &Path,
) -> Result<Option<String>> {
    let repository = canonical_directory(repository)?;
    let plan_path = plan_path.canonicalize()?;
    let Some(prereq) = subject_for_plan(&repository, &plan_path)? else {
        return Ok(None);
    };
    let subject = load_subject(&repository, &prereq.subject_id)?;
    Ok(read_record(&repository, &subject, "pre-edit")?.map(|record| record.contract_fingerprint))
}

#[derive(Debug, Clone, Serialize)]
pub struct CheckReport {
    pub subject_id: String,
    pub checkpoint: String,
    pub ready: bool,
    pub blockers: Vec<Value>,
    pub consumed: ReviewPrerequisites,
}

fn failure(
    code: &'static str,
    exit_code: i32,
    message: impl Into<String>,
    details: Value,
) -> anyhow::Error {
    anyhow!(ReviewError {
        code,
        exit_code,
        message: message.into(),
        details
    })
}

pub(crate) fn invalid(message: impl Into<String>) -> anyhow::Error {
    failure("review_invalid", 4, message, json!({}))
}

pub fn stale_contract(message: impl Into<String>) -> anyhow::Error {
    failure("review_stale_contract", 4, message, json!({}))
}

pub fn missing_approval(message: impl Into<String>) -> anyhow::Error {
    failure("review_missing", 4, message, json!({}))
}

pub fn conflict(message: impl Into<String>) -> anyhow::Error {
    failure("conflict", 3, message, json!({}))
}

pub fn failure_details(error: &anyhow::Error) -> Option<(&'static str, i32, &str, &Value)> {
    error.downcast_ref::<ReviewError>().map(|error| {
        (
            error.code,
            error.exit_code,
            error.message.as_str(),
            &error.details,
        )
    })
}

pub fn initialize_plan(
    repository: &Path,
    plan_path: &Path,
    scope: &[String],
    excludes: &[String],
    artifacts: &[PathBuf],
    tier_evidence: Option<&Path>,
) -> Result<Value> {
    let repository = canonical_directory(repository)?;
    let plan_path = plan_path
        .canonicalize()
        .with_context(|| format!("failed to resolve plan path {}", plan_path.display()))?;
    let plan_bytes = fs::read(&plan_path)
        .with_context(|| format!("failed to read plan {}", plan_path.display()))?;
    review_contract::contract_fingerprint(&plan_bytes)?;
    let digest = review_contract::fingerprint_parts(
        "varde-review-plan-id-v1",
        [
            repository.to_string_lossy().as_bytes(),
            plan_path.to_string_lossy().as_bytes(),
        ],
    );
    let subject_id = format!("plan-{}", digest.trim_start_matches("sha1-v1:"));
    initialize(
        repository,
        subject_id,
        Some(plan_path),
        None,
        scope,
        excludes,
        artifacts,
        tier_evidence,
    )
}

pub fn initialize_bounded(
    repository: &Path,
    subject_id: &str,
    contract_path: &Path,
    scope: &[String],
    excludes: &[String],
    artifacts: &[PathBuf],
    tier_evidence: Option<&Path>,
) -> Result<Value> {
    validate_subject_id(subject_id)?;
    let repository = canonical_directory(repository)?;
    let bytes = fs::read(contract_path).with_context(|| {
        format!(
            "failed to read bounded contract {}",
            contract_path.display()
        )
    })?;
    let contract = review_contract::parse_bounded_contract(&bytes)?;
    initialize(
        repository,
        subject_id.to_string(),
        None,
        Some(contract),
        scope,
        excludes,
        artifacts,
        tier_evidence,
    )
}

#[allow(clippy::too_many_arguments)]
fn initialize(
    repository: PathBuf,
    subject_id: String,
    plan_path: Option<PathBuf>,
    bounded_contract: Option<Value>,
    scope: &[String],
    excludes: &[String],
    artifacts: &[PathBuf],
    tier_evidence: Option<&Path>,
) -> Result<Value> {
    validate_subject_id(&subject_id)?;
    if scope.is_empty() && artifacts.is_empty() {
        return Err(invalid(
            "at least one --scope or --artifact path is required",
        ));
    }
    let scope = normalize_roots(&repository, scope)?;
    let excludes = normalize_roots(&repository, excludes)?;
    let working = working_root(&repository)?;
    let artifact_scope = review_coverage::normalize_artifacts(&repository, &working, artifacts)?;
    let gate_root = ensure_gate_root(&working)?;
    let subject_dir = gate_root.join(&subject_id);
    if subject_dir.exists() {
        return Err(conflict(format!(
            "review subject `{subject_id}` already exists; its baseline cannot be reset"
        )));
    }

    let mut snapshots = BTreeMap::new();
    let current = review_coverage::inventory_with_artifacts(
        &repository,
        &working,
        &scope,
        &excludes,
        &artifact_scope,
    )?;
    ensure_scope_matches(&scope, &current)?;
    let tier_evidence = load_tier_evidence(tier_evidence);
    let staging = gate_root.join(stage_name(&format!("{subject_id}.init")));
    fs::create_dir(&staging).with_context(|| {
        format!(
            "failed to create review initialization staging directory {}",
            staging.display()
        )
    })?;
    fs::create_dir_all(staging.join("baseline/blobs"))?;
    if let Err(error) = review_coverage::capture_baseline(&staging, &current, &mut snapshots) {
        let _ = fs::remove_dir_all(&staging);
        return Err(error);
    }
    review_coverage::relocate_content_paths(&mut snapshots, &staging, &subject_dir);
    let mut subject = Subject {
        schema_version: SUBJECT_SCHEMA,
        subject_id,
        repository_root: repository.clone(),
        plan_path,
        bounded_contract,
        scope,
        artifact_scope,
        excludes,
        baseline_id: String::new(),
        snapshots,
        scope_additions: BTreeSet::new(),
        tier_evidence: Some(tier_evidence),
        carried_baselines: Vec::new(),
        approved_ownership: Vec::new(),
        metadata_revision: String::new(),
        baseline_revisions: Vec::new(),
    };
    subject.baseline_id = review_coverage::baseline_fingerprint_with_artifacts(
        &subject.subject_id,
        &subject.scope,
        &subject.excludes,
        &subject.snapshots,
        &subject.scope_additions,
        &subject.artifact_scope,
    )?;
    let serialized = serde_json::to_vec_pretty(&subject)?;
    write_new_file(&staging.join("subject.json"), &serialized)?;
    fs::rename(&staging, &subject_dir)
        .with_context(|| format!("failed to publish review subject {}", subject.subject_id))?;
    inspect(&repository, &subject.subject_id, "pre-edit")
}

pub fn update_bounded_contract(
    repository: &Path,
    subject_id: &str,
    expected_version: &str,
    contract_path: &Path,
) -> Result<Value> {
    let repository = canonical_directory(repository)?;
    let mut subject = load_subject(&repository, subject_id)?;
    if subject.plan_path.is_some() || subject.bounded_contract.is_none() {
        return Err(invalid("review contract can update bounded subjects only"));
    }
    ensure_expected_version(&repository, &subject, "pre-edit", expected_version)?;
    let inspected_subject = subject.clone();
    let bytes = fs::read(contract_path).with_context(|| {
        format!(
            "failed to read bounded contract {}",
            contract_path.display()
        )
    })?;
    subject.bounded_contract = Some(review_contract::parse_bounded_contract(&bytes)?);
    ensure_expected_version(
        &repository,
        &inspected_subject,
        "pre-edit",
        expected_version,
    )?;
    write_subject(&repository, &subject)?;
    inspect(&repository, subject_id, "pre-edit")
}

/// The paths `expand_scope` treats as already authorized, for the covered-
/// expansion carry-forward rule (plan Design > API / interface contracts,
/// Item 1). A plan subject uses its frozen `approved_ownership` snapshot; a
/// bounded subject uses its contract's `scope` array, read live (see the
/// task's Out of scope: safe because it is already a
/// `current_contract_fingerprint` hash input, independently caught by
/// `check()` on edit).
fn approved_ownership_scope(subject: &Subject) -> Vec<String> {
    if subject.plan_path.is_some() {
        return subject.approved_ownership.clone();
    }
    subject
        .bounded_contract
        .as_ref()
        .and_then(|contract| contract.get("scope"))
        .and_then(Value::as_array)
        .map(|values| {
            values
                .iter()
                .filter_map(|value| value.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default()
}

pub fn expand_scope(
    repository: &Path,
    subject_id: &str,
    expected_version: &str,
    additions: &[String],
    artifacts: &[PathBuf],
    tier_evidence: Option<&Path>,
) -> Result<Value> {
    if additions.is_empty() && artifacts.is_empty() {
        return Err(invalid(
            "scope expansion requires at least one --scope or --artifact path",
        ));
    }
    let repository = canonical_directory(repository)?;
    let mut subject = load_subject(&repository, subject_id)?;
    ensure_expected_version(&repository, &subject, "pre-edit", expected_version)?;
    let inspected_subject = subject.clone();
    let prior_baseline_id = subject.baseline_id.clone();
    let additions = normalize_roots(&repository, additions)?;
    let prior = subject.scope.clone();
    let prior_artifacts = subject.artifact_scope.clone();
    let working = working_root(&repository)?;
    subject
        .artifact_scope
        .extend(review_coverage::normalize_artifacts(
            &repository,
            &working,
            artifacts,
        )?);
    subject.artifact_scope.sort();
    subject.artifact_scope.dedup();
    for root in &additions {
        if !subject
            .scope
            .iter()
            .any(|existing| roots_cover(existing, root))
        {
            subject.scope.push(root.clone());
        }
    }
    subject.scope.sort();
    subject.scope.dedup();
    if subject.scope == prior && subject.artifact_scope == prior_artifacts {
        // Scope did not grow, but caller-supplied evidence still applies
        // (e.g. a low tier reconfirmed with fresh evidence on request).
        if let Some(evidence_path) = tier_evidence {
            subject.tier_evidence = Some(load_tier_evidence(Some(evidence_path)));
            ensure_expected_version(
                &repository,
                &inspected_subject,
                "pre-edit",
                expected_version,
            )?;
            write_subject(&repository, &subject)?;
        }
        return inspect(&repository, subject_id, "pre-edit");
    }

    let current = review_coverage::inventory_with_artifacts(
        &repository,
        &working,
        &subject.scope,
        &subject.excludes,
        &subject.artifact_scope,
    )?;
    ensure_scope_matches(&additions, &current)?;
    // Scope grew: a low tier without fresh evidence reverts to high, and
    // fresh evidence that still computes low keeps it low (plan Design >
    // API / interface contracts).
    if subject.tier() == "low" || tier_evidence.is_some() {
        subject.tier_evidence = Some(match tier_evidence {
            Some(path) => load_tier_evidence(Some(path)),
            None => finish_tier_evidence(
                "high".to_string(),
                vec!["scope_expanded_without_evidence".to_string()],
            ),
        });
    }
    let gate_root = ensure_gate_root(&working)?;
    let subject_dir = gate_root.join(subject_id);
    let new_roots: Vec<String> = subject
        .scope
        .iter()
        .filter(|root| !prior.iter().any(|old| roots_cover(old, root)))
        .cloned()
        .collect();
    let artifact_keys: BTreeSet<_> = subject
        .artifact_scope
        .iter()
        .map(|path| review_coverage::artifact_key(path))
        .collect();
    review_coverage::capture_scope_additions(
        &subject_dir,
        &current,
        &new_roots,
        &prior,
        &mut subject.snapshots,
        &mut subject.scope_additions,
        &artifact_keys,
    )?;
    // Repository root coverage never counts as prior authorization of an artifact.
    let new_artifacts: Vec<_> = subject
        .artifact_scope
        .iter()
        .filter(|path| !prior_artifacts.contains(path))
        .map(|path| review_coverage::artifact_key(path))
        .collect();
    let old_artifacts: Vec<_> = prior_artifacts
        .iter()
        .map(|path| review_coverage::artifact_key(path))
        .collect();
    review_coverage::capture_scope_additions(
        &subject_dir,
        &current,
        &new_artifacts,
        &old_artifacts,
        &mut subject.snapshots,
        &mut subject.scope_additions,
        &BTreeSet::new(),
    )?;
    subject.baseline_id = review_coverage::baseline_fingerprint_with_artifacts(
        &subject.subject_id,
        &subject.scope,
        &subject.excludes,
        &subject.snapshots,
        &subject.scope_additions,
        &subject.artifact_scope,
    )?;
    // All-or-nothing: only a fully-covered, artifact-free expansion carries
    // its pre-call baseline forward (plan Design > API / interface
    // contracts, Item 1). Artifacts never carry forward.
    if artifacts.is_empty() {
        let approved = approved_ownership_scope(&subject);
        if !approved.is_empty()
            && additions
                .iter()
                .all(|added| approved.iter().any(|owned| roots_cover(owned, added)))
        {
            subject.carried_baselines.push(prior_baseline_id);
            subject.carried_baselines.sort();
            subject.carried_baselines.dedup();
        }
    }
    ensure_expected_version(
        &repository,
        &inspected_subject,
        "pre-edit",
        expected_version,
    )?;
    write_subject(&repository, &subject)?;
    inspect(&repository, subject_id, "pre-edit")
}

pub fn inspect(repository: &Path, subject_id: &str, phase: &str) -> Result<Value> {
    validate_phase(phase)?;
    let repository = canonical_directory(repository)?;
    let subject = load_subject(&repository, subject_id)?;
    let state = inspect_state(&repository, &subject, phase)?;
    Ok(state)
}

/// The plan's task-declared ownership paths, scanned fresh from every
/// `tasks/**/*.md` file beside `plan_path`: each task's `modifies`,
/// `creates`, and the new-path half of each `"old -> new"` entry in
/// `renames`. Frozen into `Subject::approved_ownership` at each `record()`
/// pre-edit acceptance (plan Design > API / interface contracts, Item 1).
fn approved_ownership_for_plan(repository: &Path, plan_path: &Path) -> Result<Vec<String>> {
    let mut declared = Vec::new();
    let artifacts = artifact_scope_for_plan(repository, plan_path)?;
    if let Some(tasks_dir) = plan_path.parent().map(|dir| dir.join("tasks"))
        && tasks_dir.is_dir()
    {
        collect_task_ownership(repository, &tasks_dir, &artifacts, &mut declared)?;
    }
    declared.sort();
    declared.dedup();
    Ok(declared)
}

pub(crate) fn artifact_scope_for_plan(repository: &Path, plan_path: &Path) -> Result<Vec<String>> {
    let Some(prerequisites) = subject_for_plan(repository, plan_path)? else {
        return Ok(Vec::new());
    };
    Ok(load_subject(repository, &prerequisites.subject_id)?.artifact_scope)
}

pub(crate) fn is_plan_artifact(artifacts: &[String], raw: &str) -> bool {
    let path = Path::new(raw.trim());
    path.is_absolute()
        && artifacts.iter().any(|artifact| {
            memory::canonical_or_lexical(Path::new(artifact)) == memory::canonical_or_lexical(path)
        })
}

fn collect_task_ownership(
    repository: &Path,
    dir: &Path,
    artifacts: &[String],
    declared: &mut Vec<String>,
) -> Result<()> {
    let entries = fs::read_dir(dir)
        .with_context(|| format!("failed to read task directory {}", dir.display()))?;
    for entry in entries {
        let entry = entry?;
        let path = entry.path();
        if entry.file_type()?.is_dir() {
            collect_task_ownership(repository, &path, artifacts, declared)?;
            continue;
        }
        if path.extension().and_then(|ext| ext.to_str()) != Some("md") {
            continue;
        }
        let bytes =
            fs::read(&path).with_context(|| format!("failed to read task {}", path.display()))?;
        let (frontmatter, _) =
            varde_workflow_core::frontmatter::parse(&bytes).map_err(|error| {
                invalid(format!(
                    "task {} has invalid frontmatter: {error}",
                    path.display()
                ))
            })?;
        let Some(mapping) = frontmatter.as_mapping() else {
            continue;
        };
        for field in ["modifies", "creates"] {
            let Some(values) = mapping
                .get(YamlValue::String(field.to_string()))
                .and_then(YamlValue::as_sequence)
            else {
                continue;
            };
            for value in values.iter().filter_map(YamlValue::as_str) {
                if is_plan_artifact(artifacts, value) {
                    continue;
                }
                declared.push(normalize_relative_path(repository, value)?);
            }
        }
        let Some(renames) = mapping
            .get(YamlValue::String("renames".to_string()))
            .and_then(YamlValue::as_sequence)
        else {
            continue;
        };
        for value in renames.iter().filter_map(YamlValue::as_str) {
            if let Some((_, new)) = value.split_once(" -> ") {
                if is_plan_artifact(artifacts, new) {
                    continue;
                }
                declared.push(normalize_relative_path(repository, new)?);
            }
        }
    }
    Ok(())
}

/// A reviewer file written over a stored record moves the inspected version
/// and makes `record` report a conflict, so reject those paths up front.
fn reject_cli_owned_file(repository: &Path, subject_id: &str, record_path: &Path) -> Result<()> {
    let Ok(file) = record_path.canonicalize() else {
        return Ok(());
    };
    let directory = subject_directory(repository, subject_id)?.canonicalize()?;
    let reserved = ["subject.json", "pre-edit.json", "implementation.json"];
    if file.parent() == Some(directory.as_path())
        && file
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| reserved.contains(&name))
    {
        return Err(invalid(format!(
            "review record file {} is a CLI-owned file in the subject directory; \
             write reviewer evidence elsewhere and pass it with --file",
            file.display()
        )));
    }
    Ok(())
}

pub fn record(
    repository: &Path,
    subject_id: &str,
    expected_version: &str,
    record_path: &Path,
) -> Result<Value> {
    let repository = canonical_directory(repository)?;
    let mut subject = load_subject(&repository, subject_id)?;
    reject_cli_owned_file(&repository, subject_id, record_path)?;
    let record_bytes = fs::read(record_path)
        .with_context(|| format!("failed to read reviewer record {}", record_path.display()))?;
    let record: EvidenceRecord = serde_json::from_slice(&record_bytes)
        .map_err(|error| invalid(format!("review record is invalid JSON: {error}")))?;
    validate_record(&record, subject_id)?;
    let phase = record.phase.as_str();
    let current = inspect_state(&repository, &subject, phase)?;
    if current["version"].as_str() != Some(expected_version) {
        return Err(conflict(
            "review subject or evidence changed after inspection",
        ));
    }
    bind_record(&record, &current)?;
    if phase == "implementation" {
        let pre_edit = check(&repository, subject_id, "start")?;
        if !pre_edit.ready {
            return Err(blocked_from_report(pre_edit));
        }
    }

    let directory = subject_directory(&repository, subject_id)?;
    let destination = directory.join(record_file(phase));
    let latest = inspect_state(&repository, &subject, phase)?;
    if latest["version"].as_str() != Some(expected_version) {
        return Err(conflict(
            "review subject or evidence changed before the record could be written",
        ));
    }
    if phase == "pre-edit"
        && let Some(plan_path) = subject.plan_path.clone()
    {
        subject.approved_ownership = approved_ownership_for_plan(&repository, &plan_path)?;
        write_subject(&repository, &subject)?;
    }
    write_atomic(&destination, &serde_json::to_vec_pretty(&record)?)?;
    inspect(&repository, subject_id, phase)
}

pub fn check(repository: &Path, subject_id: &str, checkpoint: &str) -> Result<CheckReport> {
    if !["start", "resume", "complete"].contains(&checkpoint) {
        return Err(invalid(format!(
            "unsupported review checkpoint `{checkpoint}`"
        )));
    }
    let repository = canonical_directory(repository)?;
    let subject = load_subject(&repository, subject_id)?;
    let prereq = prerequisites_for(&repository, &subject)?;
    let low_tier = subject.tier() == "low"
        && !review_contract::requires_high_tier(
            subject.plan_path.as_deref(),
            subject.bounded_contract.as_ref(),
        )?;
    let mut blockers = Vec::new();
    let pre_edit = read_record(&repository, &subject, "pre-edit")?;
    match pre_edit.as_ref() {
        None if low_tier => {}
        None => blockers.push(blocker(
            "review_missing",
            "independent pre-edit approval is missing",
            json!({}),
        )),
        Some(record) if record.verdict == "blocked" => blockers.push(blocker(
            "review_blocked",
            "pre-edit review is blocked",
            json!({ "choices": record.unresolved_choices }),
        )),
        Some(record) => {
            if record.contract_fingerprint != prereq.contract_fingerprint
                || (record.baseline_id != prereq.baseline_id
                    && !subject.carried_baselines.contains(&record.baseline_id))
            {
                blockers.push(blocker(
                    "review_stale_contract",
                    "pre-edit approval no longer matches the reviewed contract or scope baseline",
                    json!({
                        "approved_contract_fingerprint": record.contract_fingerprint,
                        "current_contract_fingerprint": prereq.contract_fingerprint,
                        "approved_baseline_id": record.baseline_id,
                        "current_baseline_id": prereq.baseline_id,
                    }),
                ));
            }
        }
    }

    if checkpoint == "complete" && crate::review_worktrees::has_active(&repository, subject_id)? {
        blockers.push(blocker(
            "review_blocked",
            "active worktree bindings must be integrated and released before completion",
            json!({}),
        ));
    }
    if checkpoint == "complete" && blockers.is_empty() {
        // An implementation record is always required at completion now,
        // independent of tier or the pre-edit reviewer's
        // `implementation_review_required` judgment (no grandfathering: plan
        // Design > API / interface contracts).
        let _ = crate::review_worktrees::requires_final_review(&repository, subject_id)?;
        match read_record(&repository, &subject, "implementation")? {
            None => blockers.push(blocker(
                "review_missing",
                "required final implementation review is missing",
                json!({ "phase": "implementation" }),
            )),
            Some(record) => {
                if !record.tier_confirmed.unwrap_or(true) {
                    blockers.push(blocker(
                        "review_blocked",
                        "the implementation reviewer explicitly contradicted the computed tier",
                        json!({ "phase": "implementation", "reason": "tier_confirmed_false" }),
                    ));
                }
                if record.verdict == "blocked" {
                    blockers.push(blocker(
                        "review_blocked",
                        "final implementation review is blocked",
                        json!({ "phase": "implementation", "choices": record.unresolved_choices }),
                    ));
                } else if record.contract_fingerprint != prereq.contract_fingerprint
                    || record.baseline_id != prereq.baseline_id
                {
                    blockers.push(blocker(
                        "review_stale_contract",
                        "final review does not match the current contract or baseline",
                        json!({ "phase": "implementation" }),
                    ));
                } else if record.change_fingerprint.as_deref()
                    != Some(prereq.change_fingerprint.as_str())
                {
                    blockers.push(blocker(
                        "review_stale_changes",
                        "final review does not cover the current subject changes",
                        json!({
                            "approved_change_fingerprint": record.change_fingerprint,
                            "current_change_fingerprint": prereq.change_fingerprint,
                        }),
                    ));
                }
            }
        }
    }

    Ok(CheckReport {
        subject_id: subject.subject_id.clone(),
        checkpoint: checkpoint.to_string(),
        ready: blockers.is_empty(),
        blockers,
        consumed: prereq,
    })
}

#[allow(dead_code)] // Consumed by the workflow checkpoint integration slice.
pub fn subject_for_plan(
    repository: &Path,
    plan_path: &Path,
) -> Result<Option<ReviewPrerequisites>> {
    let repository = canonical_directory(repository)?;
    let plan_path = plan_path.canonicalize()?;
    let root = gate_root_for(&repository, false)?;
    if !root.exists() {
        return Ok(None);
    }
    let mut found = None;
    for entry in fs::read_dir(&root)? {
        let entry = entry?;
        let name = entry.file_name();
        if name.to_string_lossy().starts_with('.') {
            continue;
        }
        if !entry.file_type()?.is_dir() {
            continue;
        }
        let path = entry.path().join("subject.json");
        match fs::symlink_metadata(&path) {
            Ok(_) => {}
            Err(error) if error.kind() == io::ErrorKind::NotFound => continue,
            Err(error) => return Err(error.into()),
        }
        let subject = read_subject_file(&entry.path())?;
        if subject.plan_path.as_deref() == Some(plan_path.as_path()) {
            if subject.repository_root != repository {
                return Err(invalid(
                    "review subject repository identity does not match its configured working store",
                ));
            }
            if found.is_some() {
                return Err(invalid(format!(
                    "multiple review subjects refer to plan {}",
                    plan_path.display()
                )));
            }
            let subject = load_subject(&repository, &subject.subject_id)?;
            found = Some(prerequisites_for(&repository, &subject)?);
        }
    }
    Ok(found)
}

#[allow(dead_code)] // Consumed by the workflow checkpoint integration slice.
pub fn check_plan(repository: &Path, plan_path: &Path, checkpoint: &str) -> Result<CheckReport> {
    let repository = canonical_directory(repository)?;
    let plan_path = plan_path.canonicalize()?;
    match subject_for_plan(&repository, &plan_path)? {
        Some(prereq) => check(&repository, &prereq.subject_id, checkpoint),
        None => {
            let prereq = empty_prerequisites(&repository, &plan_path);
            Ok(CheckReport {
                subject_id: String::new(),
                checkpoint: checkpoint.to_string(),
                ready: false,
                blockers: vec![blocker(
                    "review_missing",
                    "review subject and independent pre-edit approval are missing",
                    json!({ "plan_path": plan_path }),
                )],
                consumed: prereq,
            })
        }
    }
}

#[allow(dead_code)] // Consumed by the journal prerequisite integration slice.
pub fn prerequisites(repository: &Path, subject_id: &str) -> Result<ReviewPrerequisites> {
    let repository = canonical_directory(repository)?;
    let subject = load_subject(&repository, subject_id)?;
    prerequisites_for(&repository, &subject)
}

fn empty_prerequisites(repository: &Path, plan_path: &Path) -> ReviewPrerequisites {
    ReviewPrerequisites {
        subject_id: String::new(),
        repository_root: repository.to_path_buf(),
        plan_path: Some(plan_path.to_path_buf()),
        subject_revision: String::new(),
        subject_metadata_revision: String::new(),
        baseline_revisions: Vec::new(),
        pre_edit_revision: None,
        implementation_revision: None,
        contract_fingerprint: String::new(),
        baseline_id: String::new(),
        change_fingerprint: String::new(),
        coverage_manifest: Vec::new(),
    }
}

/// A filled-in-shape `EvidenceRecord` for `phase`, so a reviewer copies
/// `data.record_template` from `review inspect` instead of retyping the
/// schema from prose (friction 14). Keys are exactly what `validate_record`
/// requires for `phase`, plus the fields `review-gate-record.md` documents
/// as optional for it. CLI-known values (`subject_id`, `phase`,
/// `contract_fingerprint`, `baseline_id`, and for `implementation`
/// `change_fingerprint`) are pre-filled; reviewer-authored fields are
/// empty-string or `null` placeholders. No `EvidenceRecord` field change.
fn record_template(
    phase: &str,
    subject_id: &str,
    contract_fingerprint: &str,
    baseline_id: &str,
    change_fingerprint: &str,
) -> Value {
    let mut template = json!({
        "schema_version": RECORD_SCHEMA,
        "subject_id": subject_id,
        "phase": phase,
        "reviewer": { "identity": "", "provenance": "" },
        "verdict": "",
        "unresolved_choices": [],
        "contract_fingerprint": contract_fingerprint,
        "baseline_id": baseline_id,
        "verification_approach": "",
        "verification_rationale": "",
        "verification_expected_results": "",
        "rationale": "",
    });
    let object = template
        .as_object_mut()
        .expect("record_template literal is always a JSON object");
    if phase == "pre-edit" {
        object.insert("structural_risk".to_string(), json!(""));
        object.insert("structural_risk_rationale".to_string(), json!(""));
        object.insert("implementation_review_required".to_string(), Value::Null);
    } else {
        object.insert("change_fingerprint".to_string(), json!(change_fingerprint));
        object.insert("coverage".to_string(), Value::Null);
        object.insert("tier_confirmed".to_string(), Value::Null);
    }
    template
}

fn inspect_state(repository: &Path, subject: &Subject, phase: &str) -> Result<Value> {
    validate_phase(phase)?;
    let contract = review_contract::current_contract_fingerprint(
        subject.plan_path.as_deref(),
        subject.bounded_contract.as_ref(),
    )?;
    let working = working_root(repository)?;
    let current = review_coverage::inventory_with_artifacts(
        repository,
        &working,
        &subject.scope,
        &subject.excludes,
        &subject.artifact_scope,
    )?;
    let manifest =
        review_coverage::manifest(&subject.snapshots, &subject.scope_additions, &current);
    let change_fingerprint = review_contract::fingerprint_json(
        "varde-review-change-v1",
        &json!({ "baseline_id": subject.baseline_id, "entries": manifest, "worktrees": crate::review_worktrees::fingerprint_evidence(repository, &subject.subject_id)? }),
    )?;
    let directory = subject_directory(repository, &subject.subject_id)?;
    let record_path = directory.join(record_file(phase));
    let record_bytes = read_optional_regular(&record_path)?;
    let record_value = match record_bytes.as_deref() {
        Some(bytes) => {
            let record: EvidenceRecord = serde_json::from_slice(bytes).map_err(|error| {
                invalid(format!("stored review evidence is invalid JSON: {error}"))
            })?;
            validate_record(&record, &subject.subject_id)?;
            Some(serde_json::to_value(record)?)
        }
        None => None,
    };
    let subject_bytes = fs::read(directory.join("subject.json"))?;
    let version = review_contract::fingerprint_parts(
        "varde-review-inspection-v1",
        [
            subject_bytes.as_slice(),
            record_bytes.as_deref().unwrap_or_default(),
            contract.as_bytes(),
            subject.baseline_id.as_bytes(),
            change_fingerprint.as_bytes(),
            phase.as_bytes(),
        ],
    );
    Ok(json!({
        "subject": {
            "schema_version": subject.schema_version,
            "subject_id": subject.subject_id,
            "repository_root": subject.repository_root,
            "plan_path": subject.plan_path,
            "kind": if subject.plan_path.is_some() { "plan" } else { "bounded" },
            "scope": subject.scope,
            "excludes": subject.excludes,
            "artifact_scope": subject.artifact_scope,
            "baseline_id": subject.baseline_id,
            "tier": subject.tier(),
            "tier_evidence": subject.tier_evidence,
        },
        "phase": phase,
        "version": version,
        "contract_fingerprint": contract,
        "baseline_id": subject.baseline_id,
        "change_fingerprint": change_fingerprint,
        "record": record_value,
        "manifest": { "entries": manifest },
        "record_template": record_template(
            phase,
            &subject.subject_id,
            &contract,
            &subject.baseline_id,
            &change_fingerprint,
        ),
    }))
}

fn prerequisites_for(repository: &Path, subject: &Subject) -> Result<ReviewPrerequisites> {
    let pre_edit = read_optional_regular(
        &subject_directory(repository, &subject.subject_id)?.join("pre-edit.json"),
    )?;
    let implementation = read_optional_regular(
        &subject_directory(repository, &subject.subject_id)?.join("implementation.json"),
    )?;
    let state = inspect_state(repository, subject, "pre-edit")?;
    Ok(ReviewPrerequisites {
        subject_id: subject.subject_id.clone(),
        repository_root: subject.repository_root.clone(),
        plan_path: subject.plan_path.clone(),
        subject_revision: state["version"].as_str().unwrap_or_default().to_string(),
        subject_metadata_revision: subject.metadata_revision.clone(),
        baseline_revisions: subject.baseline_revisions.clone(),
        pre_edit_revision: pre_edit
            .as_deref()
            .map(|bytes| review_contract::hash_bytes(b"review-record-v1", bytes)),
        implementation_revision: implementation
            .as_deref()
            .map(|bytes| review_contract::hash_bytes(b"review-record-v1", bytes)),
        contract_fingerprint: state["contract_fingerprint"]
            .as_str()
            .unwrap_or_default()
            .to_string(),
        baseline_id: subject.baseline_id.clone(),
        change_fingerprint: state["change_fingerprint"]
            .as_str()
            .unwrap_or_default()
            .to_string(),
        coverage_manifest: state["manifest"]["entries"]
            .as_array()
            .cloned()
            .unwrap_or_default(),
    })
}

pub(crate) fn load_subject(repository: &Path, subject_id: &str) -> Result<Subject> {
    validate_subject_id(subject_id)?;
    let directory = subject_directory(repository, subject_id)?;
    let mut subject = read_subject_file(&directory)?;
    if subject.repository_root != repository {
        return Err(invalid(format!(
            "review subject `{subject_id}` is bound to {}, not {}",
            subject.repository_root.display(),
            repository.display()
        )));
    }
    if subject.subject_id != subject_id {
        return Err(invalid(
            "review subject identifier does not match its storage path",
        ));
    }
    let expected_baseline = review_coverage::baseline_fingerprint_with_artifacts(
        &subject.subject_id,
        &subject.scope,
        &subject.excludes,
        &subject.snapshots,
        &subject.scope_additions,
        &subject.artifact_scope,
    )?;
    if subject.baseline_id != expected_baseline {
        return Err(invalid(
            "review baseline metadata was modified or is unsupported",
        ));
    }
    review_coverage::verify_baseline_blobs(&directory, &subject.snapshots)?;
    subject.baseline_revisions = subject
        .snapshots
        .values()
        .filter_map(|entry| entry.content_path.as_ref())
        .map(|path| {
            let canonical = path.canonicalize()?;
            let bytes = fs::read(&canonical)?;
            Ok(EvidenceRevision {
                path: canonical,
                revision: varde_workflow_core::occ::version(&bytes),
            })
        })
        .collect::<Result<Vec<_>>>()?;
    Ok(subject)
}

fn read_subject_file(directory: &Path) -> Result<Subject> {
    let path = directory.join("subject.json");
    let bytes = read_regular(&path)?;
    let mut subject: Subject = serde_json::from_slice(&bytes)
        .map_err(|error| invalid(format!("review subject is invalid JSON: {error}")))?;
    subject.metadata_revision = varde_workflow_core::occ::version(&bytes);
    if subject.schema_version != SUBJECT_SCHEMA {
        return Err(invalid(format!(
            "unsupported review subject schema version {}",
            subject.schema_version
        )));
    }
    validate_subject_id(&subject.subject_id)?;
    Ok(subject)
}

pub(crate) fn subject_directory(repository: &Path, subject_id: &str) -> Result<PathBuf> {
    validate_subject_id(subject_id)?;
    let gate_root = gate_root_for(repository, false)?;
    let path = gate_root.join(subject_id);
    let metadata = match fs::symlink_metadata(&path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            return Err(failure(
                "review_missing",
                4,
                format!("review subject `{subject_id}` does not exist for this repository"),
                json!({ "subject_id": subject_id }),
            ));
        }
        Err(error) => return Err(error.into()),
    };
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(invalid("review subject storage must be a real directory"));
    }
    let canonical = path.canonicalize()?;
    if !canonical.starts_with(&gate_root) {
        return Err(invalid(
            "review subject storage escapes the configured working store",
        ));
    }
    Ok(canonical)
}

fn write_subject(repository: &Path, subject: &Subject) -> Result<()> {
    let directory = subject_directory(repository, &subject.subject_id)?;
    write_atomic(
        &directory.join("subject.json"),
        &serde_json::to_vec_pretty(subject)?,
    )
}

pub(crate) fn ensure_expected_version(
    repository: &Path,
    subject: &Subject,
    phase: &str,
    expected_version: &str,
) -> Result<()> {
    let current = inspect_state(repository, subject, phase)?;
    if current["version"].as_str() != Some(expected_version) {
        return Err(conflict(
            "review subject or evidence changed after inspection",
        ));
    }
    Ok(())
}

fn read_record(
    repository: &Path,
    subject: &Subject,
    phase: &str,
) -> Result<Option<EvidenceRecord>> {
    let path = subject_directory(repository, &subject.subject_id)?.join(record_file(phase));
    let Some(bytes) = read_optional_regular(&path)? else {
        return Ok(None);
    };
    let record: EvidenceRecord = serde_json::from_slice(&bytes)
        .map_err(|error| invalid(format!("stored review evidence is invalid JSON: {error}")))?;
    validate_record(&record, &subject.subject_id)?;
    if record.phase != phase {
        return Err(invalid(
            "stored review evidence phase does not match its file",
        ));
    }
    Ok(Some(record))
}

fn record_file(phase: &str) -> &'static str {
    match phase {
        "pre-edit" => "pre-edit.json",
        "implementation" => "implementation.json",
        _ => unreachable!("phase validated before use"),
    }
}

fn validate_record(record: &EvidenceRecord, subject_id: &str) -> Result<()> {
    if record.schema_version != RECORD_SCHEMA {
        return Err(invalid(format!(
            "unsupported review record schema version {}",
            record.schema_version
        )));
    }
    if record.subject_id != subject_id {
        return Err(invalid("review record is bound to a different subject"));
    }
    validate_phase(&record.phase)?;
    if record.reviewer.identity.trim().is_empty() || record.reviewer.provenance.trim().is_empty() {
        return Err(invalid(
            "review record requires non-empty reviewer identity and provenance",
        ));
    }
    if record.rationale.trim().is_empty()
        || record.verification_approach.trim().is_empty()
        || record.verification_rationale.trim().is_empty()
        || record.verification_expected_results.trim().is_empty()
    {
        return Err(invalid(
            "review record requires rationale, verification approach, rationale, and expected results",
        ));
    }
    if !["approved", "blocked"].contains(&record.verdict.as_str()) {
        return Err(invalid("review verdict must be `approved` or `blocked`"));
    }
    if record.verdict == "approved" && !record.unresolved_choices.is_empty() {
        return Err(invalid(
            "approved review records cannot contain unresolved choices",
        ));
    }
    if record.phase == "pre-edit" {
        let risk = record.structural_risk.as_deref().unwrap_or_default().trim();
        let risk_rationale = record
            .structural_risk_rationale
            .as_deref()
            .unwrap_or_default()
            .trim();
        let required = record.implementation_review_required.unwrap_or(false);
        if risk.is_empty()
            || risk_rationale.is_empty()
            || record.implementation_review_required.is_none()
        {
            return Err(invalid(
                "pre-edit evidence requires a structural-risk assessment, rationale, and implementation-review decision",
            ));
        }
        if !["low", "none"].contains(&risk.to_ascii_lowercase().as_str()) && !required {
            return Err(invalid(
                "non-low structural risk requires final implementation review",
            ));
        }
        if record.change_fingerprint.is_some() || record.coverage.is_some() {
            return Err(invalid(
                "pre-edit evidence cannot supply implementation coverage",
            ));
        }
    } else if record
        .change_fingerprint
        .as_deref()
        .unwrap_or_default()
        .trim()
        .is_empty()
        || record.coverage.as_deref() != Some("entire-subject-change")
        || record.tier_confirmed.is_none()
    {
        return Err(invalid(
            "implementation evidence requires coverage: \"entire-subject-change\", a non-empty change_fingerprint, and tier_confirmed",
        ));
    }
    Ok(())
}

fn bind_record(record: &EvidenceRecord, inspection: &Value) -> Result<()> {
    for (field, value) in [
        ("contract_fingerprint", &record.contract_fingerprint),
        ("baseline_id", &record.baseline_id),
    ] {
        if inspection[field].as_str() != Some(value.as_str()) {
            return Err(failure(
                "review_stale_contract",
                4,
                format!("review record {field} does not match the inspected subject"),
                json!({ "field": field }),
            ));
        }
    }
    if record.phase == "implementation"
        && inspection["change_fingerprint"].as_str() != record.change_fingerprint.as_deref()
    {
        return Err(failure(
            "review_stale_changes",
            4,
            "implementation review does not match the current complete change manifest",
            json!({ "field": "change_fingerprint" }),
        ));
    }
    Ok(())
}

pub fn blocked_from_report(report: CheckReport) -> anyhow::Error {
    let first =
        report.blockers.first().cloned().unwrap_or_else(|| {
            blocker("review_blocked", "review checkpoint is blocked", json!({}))
        });
    let code = first["code"].as_str().unwrap_or("review_blocked");
    let code = match code {
        "review_missing" => "review_missing",
        "review_stale_contract" => "review_stale_contract",
        "review_stale_changes" => "review_stale_changes",
        "review_invalid" => "review_invalid",
        _ => "review_blocked",
    };
    failure(
        code,
        4,
        first["message"]
            .as_str()
            .unwrap_or("review checkpoint is blocked"),
        json!({ "blockers": report.blockers, "consumed": report.consumed }),
    )
}

fn blocker(code: &str, message: &str, details: Value) -> Value {
    let mut value = json!({ "code": code, "message": message });
    if let (Some(target), Some(source)) = (value.as_object_mut(), details.as_object()) {
        target.extend(source.clone());
    } else if !details.is_null() {
        value["details"] = details;
    }
    value
}

fn validate_phase(phase: &str) -> Result<()> {
    if !["pre-edit", "implementation"].contains(&phase) {
        return Err(invalid(format!("unsupported review phase `{phase}`")));
    }
    Ok(())
}

pub(crate) fn validate_subject_id(subject_id: &str) -> Result<()> {
    let valid = !subject_id.is_empty()
        && subject_id.len() <= 100
        && subject_id
            .bytes()
            .all(|byte| byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-')
        && subject_id.as_bytes()[0].is_ascii_lowercase();
    if valid {
        Ok(())
    } else {
        Err(invalid(
            "subject id must begin with a lowercase letter and contain only lowercase letters, digits, and hyphens",
        ))
    }
}

fn canonical_directory(path: &Path) -> Result<PathBuf> {
    let canonical = path
        .canonicalize()
        .with_context(|| format!("repository directory does not exist: {}", path.display()))?;
    if !canonical.is_dir() {
        return Err(invalid(format!(
            "repository root is not a directory: {}",
            path.display()
        )));
    }
    Ok(canonical)
}

pub(crate) fn working_root(repository: &Path) -> Result<PathBuf> {
    let paths = MemoryPaths::resolve(repository)?;
    fs::create_dir_all(&paths.working.path).with_context(|| {
        format!(
            "failed to create working store {}",
            paths.working.path.display()
        )
    })?;
    paths.working.path.canonicalize().with_context(|| {
        format!(
            "failed to resolve working store {}",
            paths.working.path.display()
        )
    })
}

fn gate_root_for(repository: &Path, create: bool) -> Result<PathBuf> {
    let working = if create {
        working_root(repository)?
    } else {
        MemoryPaths::resolve(repository)?.working.path
    };
    let path = working.join("review-gates");
    match fs::symlink_metadata(&path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            return Err(invalid("review-gates storage must be a real directory"));
        }
        Ok(_) => {}
        Err(error) if error.kind() == io::ErrorKind::NotFound && create => {
            fs::create_dir_all(&path)?
        }
        Err(error) if error.kind() == io::ErrorKind::NotFound => return Ok(path),
        Err(error) => return Err(error.into()),
    }
    let canonical_working = working.canonicalize().unwrap_or(working);
    let canonical_gate = path.canonicalize()?;
    if !canonical_gate.starts_with(&canonical_working) {
        return Err(invalid(
            "review-gates storage escapes the configured working store",
        ));
    }
    Ok(canonical_gate)
}

fn ensure_gate_root(working: &Path) -> Result<PathBuf> {
    let path = working.join("review-gates");
    match fs::symlink_metadata(&path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_dir() => {
            Err(invalid("review-gates storage must be a real directory"))
        }
        Ok(_) => Ok(path.canonicalize()?),
        Err(error) if error.kind() == io::ErrorKind::NotFound => {
            fs::create_dir(&path)?;
            Ok(path.canonicalize()?)
        }
        Err(error) => Err(error.into()),
    }
}

fn read_regular(path: &Path) -> Result<Vec<u8>> {
    let metadata = fs::symlink_metadata(path)
        .with_context(|| format!("failed to inspect {}", path.display()))?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(invalid(format!(
            "expected a regular file at {}",
            path.display()
        )));
    }
    fs::read(path).with_context(|| format!("failed to read {}", path.display()))
}

fn read_optional_regular(path: &Path) -> Result<Option<Vec<u8>>> {
    match fs::symlink_metadata(path) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => Err(invalid(
            format!("expected a regular file at {}", path.display()),
        )),
        Ok(_) => fs::read(path)
            .map(Some)
            .with_context(|| format!("failed to read {}", path.display())),
        Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(error.into()),
    }
}

fn write_new_file(path: &Path, bytes: &[u8]) -> Result<()> {
    use std::io::Write;
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .with_context(|| format!("failed to create {}", path.display()))?;
    file.write_all(bytes)?;
    file.sync_all()?;
    Ok(())
}

pub(crate) fn write_atomic(path: &Path, bytes: &[u8]) -> Result<()> {
    let parent = path
        .parent()
        .ok_or_else(|| anyhow!("write path has no parent"))?;
    let target = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("record");
    let stage = parent.join(stage_name(&format!("{target}.review-stage")));
    write_new_file(&stage, bytes)?;
    fs::rename(&stage, path).with_context(|| format!("failed to publish {}", path.display()))
}

fn stage_name(stem: &str) -> String {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!(".{stem}-{}-{nonce}", std::process::id())
}

fn normalize_roots(repository: &Path, roots: &[String]) -> Result<Vec<String>> {
    let mut normalized = Vec::with_capacity(roots.len());
    for root in roots {
        let value = normalize_relative_path(repository, root)?;
        if !normalized.contains(&value) {
            normalized.push(value);
        }
    }
    normalized.sort();
    Ok(normalized)
}

pub(crate) fn normalize_relative_path(repository: &Path, raw: &str) -> Result<String> {
    let path = Path::new(raw);
    if path.as_os_str().is_empty() || path.is_absolute() {
        return Err(invalid(format!(
            "coverage path must be a non-empty repository-relative path: `{raw}`"
        )));
    }
    let mut normalized = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(value) => normalized.push(value),
            Component::CurDir => {}
            Component::ParentDir | Component::RootDir | Component::Prefix(_) => {
                return Err(invalid(format!(
                    "coverage path may not escape the repository: `{raw}`"
                )));
            }
        }
    }
    if normalized.as_os_str().is_empty() {
        normalized.push(".");
    }
    let candidate = repository.join(&normalized);
    let check_path =
        if fs::symlink_metadata(&candidate).is_ok_and(|meta| meta.file_type().is_symlink()) {
            candidate
                .parent()
                .unwrap_or(repository)
                .canonicalize()
                .unwrap_or_else(|_| repository.to_path_buf())
        } else if candidate.exists() {
            candidate.canonicalize()?
        } else {
            let mut ancestor = candidate.as_path();
            while !ancestor.exists() {
                ancestor = ancestor
                    .parent()
                    .ok_or_else(|| invalid(format!("invalid coverage path `{raw}`")))?;
            }
            ancestor.canonicalize()?
        };
    if !check_path.starts_with(repository) {
        return Err(invalid(format!(
            "coverage path escapes the repository: `{raw}`"
        )));
    }
    let result = normalized
        .to_str()
        .ok_or_else(|| invalid("coverage paths must be UTF-8"))?;
    Ok(result.replace(std::path::MAIN_SEPARATOR, "/"))
}

fn roots_cover(root: &str, path: &str) -> bool {
    root == "." || root == path || path.starts_with(&format!("{}/", root.trim_end_matches('/')))
}

/// Rejects any requested scope root that binds no repository entry (for
/// example an unglobbed pattern like `skills/**`), before anything is
/// written.
fn ensure_scope_matches(
    roots: &[String],
    current: &BTreeMap<String, review_coverage::CurrentEntry>,
) -> Result<()> {
    // A plain path may legitimately not exist yet (future coverage). Only a
    // glob-shaped root that silently bound nothing is rejected: `--scope`
    // takes literal paths, so `skills/**` never expands and always means the
    // caller meant to match files it didn't.
    for root in roots {
        let looks_like_glob = root.contains(['*', '?', '[']);
        if looks_like_glob && !current.keys().any(|path| roots_cover(root, path)) {
            return Err(invalid(format!(
                "scope `{root}` does not match any file in the repository"
            )));
        }
    }
    Ok(())
}

/// Loads and fingerprints `scripts/risk-tier.py` output. A missing,
/// unreadable, or malformed file defaults to `tier: "high"` with
/// `signals: ["evidence_missing"]`: the tier never drops to low without
/// evidence (plan Design > Schema / data model).
fn load_tier_evidence(path: Option<&Path>) -> TierEvidence {
    let parsed = path.and_then(|path| fs::read(path).ok()).and_then(|bytes| {
        let value: Value = serde_json::from_slice(&bytes).ok()?;
        let tier = value.get("tier")?.as_str()?;
        if tier != "low" && tier != "high" {
            return None;
        }
        let signals = value
            .get("signals")?
            .as_array()?
            .iter()
            .map(|signal| signal.as_str().map(str::to_string))
            .collect::<Option<Vec<_>>>()?;
        Some((tier.to_string(), signals))
    });
    let (tier, signals) =
        parsed.unwrap_or_else(|| ("high".to_string(), vec!["evidence_missing".to_string()]));
    finish_tier_evidence(tier, signals)
}

fn finish_tier_evidence(tier: String, signals: Vec<String>) -> TierEvidence {
    let fingerprint = review_contract::fingerprint_json(
        "varde-review-tier-evidence-v1",
        &json!({ "tier": tier, "signals": signals }),
    )
    .unwrap_or_default();
    let recorded_at = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs().to_string())
        .unwrap_or_default();
    TierEvidence {
        fingerprint,
        tier,
        signals,
        recorded_at,
    }
}
