//! Bounded, read-only inspection of native agent-session evidence.

mod claude;
mod codex;
mod opencode;

use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};

use crate::{
    HistoricalCaptureRequest, HistoricalItemMode, HistoricalOccurrenceRequest, HistoricalWitness,
    LearnError, Store,
};

pub const MAX_SOURCE_BYTES: usize = 16 * 1024 * 1024;
pub const MAX_FAMILY_SOURCE_BYTES: usize = 32 * 1024 * 1024;
pub const MAX_RECORD_BYTES: usize = 256 * 1024;
pub const MAX_RECORDS: usize = 10_000;
pub const MAX_PAGE_LIMIT: usize = 1_000;
pub const MAX_FAMILY: usize = 32;
pub const MAX_DISCOVERY_FILES: usize = 5_000;
pub const MAX_SNAPSHOT_BYTES: usize = 2 * 1024 * 1024;
const MAX_PAGE_BYTES: usize = 2 * 1024 * 1024;
const MAX_TEXT_EXCERPT: usize = 512;
const MAX_WARNINGS: usize = 128;
const NORMALIZED_RECORD_BUDGET_BYTES: usize = MAX_SNAPSHOT_BYTES - 128 * 1024;

/// Tracks exact serialized record bytes while adapters build a family.
#[derive(Debug, Clone)]
pub(crate) struct NormalizedRecordBudget {
    used_bytes: usize,
}

impl NormalizedRecordBudget {
    pub(crate) fn new() -> Self {
        Self { used_bytes: 0 }
    }

    #[cfg(test)]
    pub(crate) fn used_bytes(&self) -> usize {
        self.used_bytes
    }

    pub(crate) fn try_add<T: Serialize>(&mut self, record: &T) -> bool {
        let Some(bytes) = Self::serialized_bytes(record) else {
            return false;
        };
        if bytes > MAX_RECORD_BYTES
            || self.used_bytes.saturating_add(bytes) > NORMALIZED_RECORD_BUDGET_BYTES
        {
            return false;
        }
        self.used_bytes += bytes;
        true
    }

    pub(crate) fn try_replace<T: Serialize>(&mut self, old: &T, new: &T) -> bool {
        let (Some(old_bytes), Some(new_bytes)) =
            (Self::serialized_bytes(old), Self::serialized_bytes(new))
        else {
            return false;
        };
        if new_bytes > MAX_RECORD_BYTES {
            return false;
        }
        let next_used = self
            .used_bytes
            .saturating_sub(old_bytes)
            .saturating_add(new_bytes);
        if next_used > NORMALIZED_RECORD_BUDGET_BYTES {
            return false;
        }
        self.used_bytes = next_used;
        true
    }

    fn serialized_bytes<T: Serialize>(record: &T) -> Option<usize> {
        serde_json::to_vec(record).ok().map(|bytes| bytes.len())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DiagnosticHarness {
    Codex,
    Claude,
    Opencode,
}

#[derive(Debug, Clone)]
pub enum Intake {
    Current {
        source_root: PathBuf,
        session_id: Option<String>,
        claude_hook: Option<ClaudeHookContext>,
    },
    Session {
        source_root: PathBuf,
        session_id: String,
    },
    Path {
        source_root: PathBuf,
        path: PathBuf,
    },
    Snapshot(PathBuf),
}

/// Verified fields from Claude's command-hook JSON stdin. These are never
/// inferred from the ambient process environment or filesystem recency.
#[derive(Debug, Clone)]
pub struct ClaudeHookContext {
    pub transcript_path: PathBuf,
    pub cwd: Option<PathBuf>,
    pub agent_id: Option<String>,
    pub agent_transcript_path: Option<PathBuf>,
}

#[derive(Debug, Clone)]
pub struct InspectRequest {
    pub harness: Option<DiagnosticHarness>,
    pub intake: Intake,
    pub offset: usize,
    pub limit: usize,
    pub snapshot_out: Option<PathBuf>,
    pub cutoff_anchor: Option<PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GitMetadata {
    pub commit_hash: Option<String>,
    pub branch: Option<String>,
    pub repository_url: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SessionMetadata {
    pub harness: String,
    pub thread_id: String,
    pub session_id: Option<String>,
    pub parent_thread_id: Option<String>,
    pub parent_provenance: Option<String>,
    pub started_at: Option<String>,
    pub cwd: Option<String>,
    pub cli_version: Option<String>,
    pub history_mode: Option<String>,
    pub git: Option<GitMetadata>,
    pub source_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_namespace: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub current_directory: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fork_session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fork_boundary: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceSnapshot {
    pub source_id: String,
    pub canonical_path: String,
    pub device: u64,
    pub inode: u64,
    pub initial_length: u64,
    pub captured_length: u64,
    pub modified_ns: u128,
    pub prefix_digest: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub harness: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_thread_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub format: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub companions: Vec<SourceCompanion>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SourceCompanion {
    pub path: String,
    pub present: bool,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub device: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub inode: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub length: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub modified_ns: Option<u128>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RecordAnchor {
    pub source_id: String,
    pub record_index: u64,
    pub byte_start: u64,
    pub byte_end: u64,
    pub record_digest: String,
    pub native_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub storage_sequence: Option<i64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub context_digest: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct EvidenceRecord {
    pub session_thread_id: String,
    pub anchor: RecordAnchor,
    pub timestamp: Option<String>,
    pub kind: String,
    pub role: Option<String>,
    pub text_excerpt: Option<String>,
    pub tool_name: Option<String>,
    pub tool_input_excerpt: Option<String>,
    pub tool_output_excerpt: Option<String>,
    pub tool_status: Option<String>,
    pub tool_error: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tool_observations: Vec<ToolObservation>,
    pub detail_truncated: bool,
    pub unknown_payload_excerpt: Option<String>,
    pub turn_id: Option<String>,
    pub response_id: Option<String>,
    pub cwd: Option<String>,
    /// Session-start metadata is not evidence of the HEAD at this event.
    pub git_head: Option<String>,
    pub failure_reason: Option<String>,
    pub compacted_before_tokens: Option<u64>,
    pub usage_total: Option<serde_json::Value>,
    pub usage_last: Option<serde_json::Value>,
    /// Per-response usage record; never aggregated with cumulative counters.
    pub usage_record: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub provider_message_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_native_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_sidechain: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_meta: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub is_compact_summary: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timestamp_raw: Option<serde_json::Value>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub session_location: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub location_provenance: Option<String>,
}

/// One bounded tool block within a native message. The containing evidence
/// record supplies the shared anchor; block IDs remain provider data.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ToolObservation {
    pub block_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub input_excerpt: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub output_excerpt: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub status: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    pub detail_truncated: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CurrentOverlap {
    Current,
    NotCurrent,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ChildSession {
    pub thread_id: String,
    pub source_id: String,
    pub parent_thread_id: Option<String>,
    pub started_at: Option<String>,
    pub relationship_evidence: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub transcript_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_agent_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub parent_tool_use_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fork_session_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub fork_boundary: Option<serde_json::Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Coverage {
    pub complete: bool,
    pub source_complete: bool,
    pub analysis_ready: bool,
    pub cutoff_verified: bool,
    pub cutoff_anchor: Option<RecordAnchor>,
    pub incomplete_tail: bool,
    pub truncated: bool,
    pub record_count: usize,
    pub malformed_records: usize,
    pub omitted_records: usize,
    pub warnings: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct SnapshotIdentity {
    pub digest: String,
}

/// Immutable, bounded, normalized evidence suitable for exact paging.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InspectionSnapshot {
    pub schema_version: u32,
    pub digest: String,
    pub session: SessionMetadata,
    pub children: Vec<ChildSession>,
    pub sources: Vec<SourceSnapshot>,
    pub records: Vec<EvidenceRecord>,
    pub overlap: CurrentOverlap,
    pub coverage: Coverage,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Inspection {
    pub session: SessionMetadata,
    pub children: Vec<ChildSession>,
    pub sources: Vec<SourceSnapshot>,
    pub records: Vec<EvidenceRecord>,
    pub overlap: CurrentOverlap,
    pub coverage: Coverage,
    pub snapshot: SnapshotIdentity,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RevalidatedRecord {
    pub anchor: RecordAnchor,
    #[serde(default)]
    pub native_facts: Value,
    pub native_thread_id: String,
    pub native_parent_thread_id: Option<String>,
    pub native_root_thread_id: Option<String>,
    pub inherited_history: bool,
    pub timestamp: Option<String>,
    pub kind: String,
    pub role: Option<String>,
    pub text_excerpt: Option<String>,
    #[serde(default)]
    pub failure_reason: Option<String>,
    pub cwd: Option<String>,
    pub turn_id: Option<String>,
    pub response_id: Option<String>,
    pub usage_record: Option<serde_json::Value>,
    #[serde(default)]
    pub transcript_id: Option<String>,
    #[serde(default)]
    pub provider_message_id: Option<String>,
    #[serde(default)]
    pub agent_id: Option<String>,
    #[serde(default)]
    pub parent_agent_id: Option<String>,
    #[serde(default)]
    pub parent_native_id: Option<String>,
    #[serde(default)]
    pub tool_use_id: Option<String>,
    #[serde(default)]
    pub parent_tool_use_id: Option<String>,
    #[serde(default)]
    pub tool_name: Option<String>,
    #[serde(default)]
    pub tool_input_excerpt: Option<String>,
    #[serde(default)]
    pub tool_output_excerpt: Option<String>,
    #[serde(default)]
    pub tool_status: Option<String>,
    #[serde(default)]
    pub tool_error: Option<String>,
    #[serde(default)]
    pub tool_observations: Vec<ToolObservation>,
    #[serde(default)]
    pub is_sidechain: Option<bool>,
    #[serde(default)]
    pub is_meta: Option<bool>,
    #[serde(default)]
    pub is_compact_summary: Option<bool>,
    #[serde(default)]
    pub timestamp_raw: Option<serde_json::Value>,
    #[serde(default)]
    pub session_location: Option<String>,
    #[serde(default)]
    pub location_provenance: Option<String>,
}

#[derive(Debug)]
struct NativeHeaderIdentity {
    thread_id: String,
    parent_thread_id: Option<String>,
    root_thread_id: Option<String>,
    inherited_history: bool,
}

#[derive(Debug, Clone, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CaptureOutput {
    pub disposition: &'static str,
    pub item_id: i64,
    pub occurrence_id: i64,
    pub at: String,
    pub cwd: String,
    pub repo_root: Option<String>,
    pub head_sha: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CaptureFile {
    snapshot_path: PathBuf,
    snapshot_digest: String,
    session_id: String,
    anchor: RecordAnchor,
    incident_kind: IncidentKind,
    item: CaptureItem,
    evidence: String,
}

#[derive(Debug, Clone, Copy, Deserialize)]
#[serde(rename_all = "kebab-case")]
enum IncidentKind {
    FailedTool,
    RepeatedWork,
    WorkflowDeviation,
}

impl IncidentKind {
    fn as_str(&self) -> &'static str {
        match self {
            Self::FailedTool => "failed-tool",
            Self::RepeatedWork => "repeated-work",
            Self::WorkflowDeviation => "workflow-deviation",
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "mode", rename_all = "snake_case", deny_unknown_fields)]
enum CaptureItem {
    Existing {
        id: i64,
    },
    New {
        source: String,
        title: String,
        target: Option<String>,
    },
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct CutoffAnchorFile {
    source_path: PathBuf,
    record_anchor: RecordAnchor,
}

/// Inspect a bounded source and return a page of normalized evidence.
pub fn inspect(request: &InspectRequest) -> Result<Inspection, LearnError> {
    if request.limit == 0 || request.limit > MAX_PAGE_LIMIT {
        return Err(error(
            "diagnose_limit_invalid",
            format!("limit must be between 1 and {MAX_PAGE_LIMIT}"),
        ));
    }

    let snapshot_input = matches!(request.intake, Intake::Snapshot(_));
    let mut frozen = match &request.intake {
        Intake::Snapshot(path) => load_snapshot(path)?,
        Intake::Current {
            source_root,
            session_id,
            claude_hook,
        } => match request.harness {
            Some(DiagnosticHarness::Codex) => {
                let Some(thread_id) = session_id.as_deref().filter(|id| !id.trim().is_empty())
                else {
                    return Err(error(
                        "diagnose_current_unavailable",
                        "Codex did not provide a verified current thread ID; use --session or --path",
                    ));
                };
                codex::inspect_id(source_root, thread_id)?
            }
            Some(DiagnosticHarness::Claude) => {
                let Some(session_id) = session_id.as_deref().filter(|id| !id.trim().is_empty())
                else {
                    return Err(error(
                        "diagnose_current_unavailable",
                        "Claude hook did not provide a verified session ID",
                    ));
                };
                let Some(context) = claude_hook.as_ref() else {
                    return Err(error(
                        "diagnose_current_unavailable",
                        "Claude current inspection requires verified command-hook JSON on stdin",
                    ));
                };
                claude::inspect_current(source_root, session_id, context)?
            }
            Some(DiagnosticHarness::Opencode) => {
                return Err(error(
                    "diagnose_current_unavailable",
                    "OpenCode does not expose a verified caller context for current-session inspection",
                ));
            }
            _ => {
                return Err(error(
                    "diagnose_unsupported_harness",
                    "current inspection is not supported for this harness",
                ));
            }
        },
        Intake::Session {
            source_root,
            session_id,
        } => match request.harness {
            Some(DiagnosticHarness::Codex) => codex::inspect_id(source_root, session_id)?,
            Some(DiagnosticHarness::Claude) => claude::inspect_id(source_root, session_id)?,
            Some(DiagnosticHarness::Opencode) => opencode::inspect_id(source_root, session_id)?,
            _ => {
                return Err(error(
                    "diagnose_unsupported_harness",
                    "native inspection for this harness is not implemented yet",
                ));
            }
        },
        Intake::Path { source_root, path } => match request.harness {
            Some(DiagnosticHarness::Codex) => codex::inspect_path(source_root, path)?,
            Some(DiagnosticHarness::Claude) => claude::inspect_path(source_root, path)?,
            Some(DiagnosticHarness::Opencode) => opencode::inspect_path(source_root, path)?,
            _ => {
                return Err(error(
                    "diagnose_unsupported_harness",
                    "native inspection for this harness is not implemented yet",
                ));
            }
        },
    };

    if let Some(anchor_path) = &request.cutoff_anchor {
        if matches!(request.intake, Intake::Snapshot(_)) {
            return Err(error(
                "usage_error",
                "--cutoff-anchor cannot be combined with --snapshot-in",
            ));
        }
        apply_cutoff(&mut frozen, anchor_path)?;
        refresh_snapshot_digest(&mut frozen)?;
    } else if !snapshot_input
        && matches!(
            frozen.overlap,
            CurrentOverlap::Current | CurrentOverlap::Unknown
        )
        && !frozen
            .coverage
            .warnings
            .iter()
            .any(|warning| warning.contains("no verified pre-orchestration cutoff"))
    {
        frozen.coverage.complete = false;
        frozen.coverage.analysis_ready = false;
        frozen.coverage.warnings.push(
            "current-session overlap is current or unknown and no verified pre-orchestration cutoff was supplied".into(),
        );
        refresh_snapshot_digest(&mut frozen)?;
    }

    if let Some(path) = &request.snapshot_out {
        write_snapshot(path, &frozen)?;
    }

    let total = frozen.records.len();
    let start = request.offset.min(total);
    let end = start.saturating_add(request.limit).min(total);
    let mut records = frozen.records[start..end].to_vec();
    while !records.is_empty()
        && serde_json::to_vec(&records).is_ok_and(|page| page.len() > MAX_PAGE_BYTES)
    {
        records.pop();
    }
    let mut coverage = frozen.coverage.clone();
    if start + records.len() < end {
        coverage.truncated = true;
        coverage
            .warnings
            .push("page byte limit omitted evidence records".into());
    }
    Ok(Inspection {
        session: frozen.session.clone(),
        children: frozen.children.clone(),
        sources: frozen.sources.clone(),
        records,
        overlap: frozen.overlap.clone(),
        coverage,
        snapshot: SnapshotIdentity {
            digest: frozen.digest.clone(),
        },
    })
}

/// Capture one incident only after its frozen evidence and native witness are revalidated.
pub fn capture(path: &Path) -> Result<CaptureOutput, LearnError> {
    const MAX_CAPTURE_BYTES: usize = 64 * 1024;
    let metadata = fs::symlink_metadata(path).map_err(|cause| {
        error(
            "diagnose_capture_invalid",
            format!("cannot stat capture request: {cause}"),
        )
    })?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err(error(
            "diagnose_capture_invalid",
            "capture request must be a regular file",
        ));
    }
    if metadata.len() > MAX_CAPTURE_BYTES as u64 {
        return Err(error(
            "diagnose_capture_limit",
            "capture request exceeds the 64 KiB limit",
        ));
    }
    let mut bytes = Vec::new();
    File::open(path)
        .and_then(|file| {
            file.take((MAX_CAPTURE_BYTES + 1) as u64)
                .read_to_end(&mut bytes)
        })
        .map_err(|cause| {
            error(
                "diagnose_capture_invalid",
                format!("cannot read capture request: {cause}"),
            )
        })?;
    if bytes.len() > MAX_CAPTURE_BYTES {
        return Err(error(
            "diagnose_capture_limit",
            "capture request exceeds the 64 KiB limit",
        ));
    }
    let request: CaptureFile = serde_json::from_slice(&bytes).map_err(|cause| {
        error(
            "diagnose_capture_invalid",
            format!("invalid strict capture request JSON: {cause}"),
        )
    })?;
    if request.session_id.trim().is_empty() || request.evidence.trim().is_empty() {
        return Err(error(
            "diagnose_capture_invalid",
            "session ID and observed evidence must not be blank",
        ));
    }
    if request.evidence.len() > 8 * 1024 {
        return Err(error(
            "diagnose_capture_limit",
            "observed evidence exceeds the 8 KiB limit",
        ));
    }
    let snapshot = load_snapshot(&request.snapshot_path)?;
    if snapshot.digest != request.snapshot_digest {
        return Err(error(
            "diagnose_snapshot_invalid",
            "capture request snapshot digest does not match the frozen evidence",
        ));
    }
    if snapshot.session.thread_id != request.session_id {
        return Err(error(
            "diagnose_capture_invalid",
            "capture session ID does not match the frozen evidence session",
        ));
    }
    match &snapshot.overlap {
        CurrentOverlap::Current | CurrentOverlap::Unknown if !snapshot.coverage.cutoff_verified => {
            return Err(error(
                "diagnose_capture_incomplete",
                "current or unknown session overlap requires a verified pre-orchestration cutoff",
            ));
        }
        CurrentOverlap::NotCurrent | CurrentOverlap::Current | CurrentOverlap::Unknown => {}
    }
    if snapshot.coverage.cutoff_verified {
        let cutoff = snapshot.coverage.cutoff_anchor.as_ref().ok_or_else(|| {
            error(
                "diagnose_capture_incomplete",
                "verified cutoff is missing its source anchor",
            )
        })?;
        let cutoff_source = snapshot
            .sources
            .iter()
            .find(|source| source.source_id == cutoff.source_id)
            .ok_or_else(|| {
                error(
                    "diagnose_capture_incomplete",
                    "verified cutoff source is missing from the frozen evidence",
                )
            })?;
        let cutoff_record = snapshot
            .records
            .iter()
            .find(|record| record.anchor == *cutoff)
            .ok_or_else(|| {
                error(
                    "diagnose_capture_incomplete",
                    "verified cutoff record is missing from the frozen evidence",
                )
            })?;
        revalidate_record_anchor(cutoff_source, cutoff)?;
        let before_cutoff = if request.anchor.source_id == cutoff.source_id {
            if cutoff.storage_sequence.is_some() || request.anchor.storage_sequence.is_some() {
                request.anchor.session_id == cutoff.session_id
                    && request.anchor.storage_sequence <= cutoff.storage_sequence
            } else {
                request.anchor.record_index <= cutoff.record_index
            }
        } else {
            cutoff_record
                .timestamp
                .as_deref()
                .and_then(parse_rfc3339_nanos)
                .zip(
                    snapshot
                        .records
                        .iter()
                        .find(|record| record.anchor == request.anchor)
                        .and_then(|record| record.timestamp.as_deref())
                        .and_then(parse_rfc3339_nanos),
                )
                .is_some_and(|(cutoff, selected)| selected <= cutoff)
        };
        if !before_cutoff {
            return Err(error(
                "diagnose_capture_uncertain",
                "selected incident cannot be placed before the verified cutoff",
            ));
        }
    }
    let witness_id = request
        .anchor
        .native_id
        .as_deref()
        .filter(|identity| !identity.trim().is_empty());
    let mut selected_records = snapshot
        .records
        .iter()
        .filter(|record| record.anchor == request.anchor);
    let Some(record) = selected_records.next() else {
        return Err(error(
            "diagnose_capture_invalid",
            "selected record anchor is not present in the frozen evidence",
        ));
    };
    if selected_records.next().is_some() {
        return Err(error(
            "diagnose_capture_invalid",
            "selected record anchor is ambiguous in the frozen evidence",
        ));
    }
    if record.session_thread_id.trim().is_empty() {
        return Err(error(
            "diagnose_capture_uncertain",
            "selected event has no verified native session identity",
        ));
    }
    let mut selected_sources = snapshot
        .sources
        .iter()
        .filter(|source| source.source_id == request.anchor.source_id);
    let Some(source) = selected_sources.next() else {
        return Err(error(
            "diagnose_capture_invalid",
            "selected event references an unknown or ambiguous source",
        ));
    };
    if selected_sources.next().is_some() {
        return Err(error(
            "diagnose_capture_invalid",
            "selected event references an unknown or ambiguous source",
        ));
    }
    if source.harness.as_deref() != Some(snapshot.session.harness.as_str()) {
        return Err(error(
            "diagnose_capture_invalid",
            "selected source harness does not match the frozen session identity",
        ));
    }
    if witness_id.is_none()
        && !matches!(
            source.format.as_deref(),
            Some("codex-jsonl" | "claude-jsonl")
        )
    {
        return Err(error(
            "diagnose_capture_uncertain",
            "fallback event identity is available only for a verified JSONL record anchor",
        ));
    }
    let frozen_at = record
        .timestamp
        .as_deref()
        .filter(|value| parse_rfc3339_nanos(value).is_some())
        .ok_or_else(|| {
            error(
                "diagnose_capture_uncertain",
                "selected event has no verified native timestamp",
            )
        })?;
    let frozen_cwd = record
        .cwd
        .as_deref()
        .filter(|cwd| !cwd.trim().is_empty())
        .ok_or_else(|| {
            error(
                "diagnose_capture_uncertain",
                "selected event has no verified historical working directory",
            )
        })?;
    let verified = revalidate_record_anchor(source, &request.anchor)?;
    if verified.native_thread_id != record.session_thread_id {
        return Err(error(
            "diagnose_capture_invalid",
            "selected event session identity does not match the native source",
        ));
    }
    if !verified_family_member(&snapshot, source, &verified)? {
        return Err(error(
            "diagnose_capture_invalid",
            "selected source is not part of the verified session family",
        ));
    }
    if verified.inherited_history {
        return Err(error(
            "diagnose_capture_uncertain",
            "selected native source contains inherited history with uncertain event provenance",
        ));
    }
    let verified_cwd = verified.cwd.as_deref().ok_or_else(|| {
        error(
            "diagnose_capture_uncertain",
            "source revalidation could not verify the event working directory",
        )
    })?;
    if verified.timestamp.as_deref() != Some(frozen_at)
        || verified_cwd != frozen_cwd
        || verified.kind != record.kind
        || verified.session_location != record.session_location
        || verified.location_provenance != record.location_provenance
    {
        return Err(error(
            "diagnose_source_changed",
            "selected native event or its historical context changed after inspection",
        ));
    }
    validate_tool_projection(record, &verified)?;
    if !verified.native_facts.is_object() {
        return Err(error(
            "diagnose_capture_uncertain",
            "selected native event facts could not be preserved",
        ));
    }
    let harness = snapshot.session.harness.as_str();
    if !matches!(harness, "codex" | "claude" | "opencode") {
        return Err(error(
            "diagnose_capture_uncertain",
            "selected evidence has an unsupported harness identity",
        ));
    }
    if matches!(request.incident_kind, IncidentKind::FailedTool)
        && !has_analyst_reviewable_tool_failure(&verified)
    {
        return Err(error(
            "diagnose_capture_kind_invalid",
            "failed-tool capture requires verified native tool output for analyst review",
        ));
    }
    let item_mode = match request.item {
        CaptureItem::Existing { id } if id > 0 => HistoricalItemMode::Append { item_id: id },
        CaptureItem::Existing { .. } => {
            return Err(error(
                "diagnose_capture_invalid",
                "existing friction item ID must be positive",
            ));
        }
        CaptureItem::New {
            source,
            title,
            target,
        } => {
            if source.trim().is_empty()
                || title.trim().is_empty()
                || target
                    .as_deref()
                    .is_some_and(|target| target.trim().is_empty())
            {
                return Err(error(
                    "diagnose_capture_invalid",
                    "new friction item source, title, and optional target must not be blank",
                ));
            }
            HistoricalItemMode::Create {
                source,
                title,
                target,
                repo_root: None,
            }
        }
    };
    if let HistoricalItemMode::Append { item_id } = &item_mode {
        let database = crate::resolve_store_dir()?.join("learn.db");
        if !database.is_file() {
            return Err(LearnError::StoreItemNotFound {
                identifier: item_id.to_string(),
            });
        }
    }
    let mut store = Store::open_global()?;
    let incident_kind = request.incident_kind.as_str();
    let existing = if let Some(witness_id) = witness_id {
        store.find_historical_witness(harness, &record.session_thread_id, witness_id)?
    } else {
        store.find_historical_fallback_witness(
            harness,
            &record.session_thread_id,
            request.anchor.record_index,
            &request.anchor.record_digest,
        )?
    };
    if witness_id.is_none()
        && existing.iter().any(|prior| {
            prior.record_index != request.anchor.record_index
                || prior.record_digest != request.anchor.record_digest
        })
    {
        return Err(error(
            "diagnose_capture_uncertain",
            "a stored fallback witness indicates this source event was rewritten or repositioned",
        ));
    }
    if existing
        .iter()
        .any(|prior| prior.incident_kind != incident_kind)
    {
        return Err(error(
            "diagnose_incident_kind_conflict",
            "the native event is already recorded under a different incident kind",
        ));
    }
    let witness_id = witness_id.map(str::to_owned);
    let context = serde_json::json!({
        "cwd": frozen_cwd,
        "session_location": verified.session_location,
        "location_provenance": verified.location_provenance,
    });
    let result = store.record_historical_occurrence(HistoricalCaptureRequest {
        mode: item_mode,
        occurrence: HistoricalOccurrenceRequest {
            at: frozen_at.to_owned(),
            cwd: frozen_cwd.to_owned(),
            repo_root: None,
            head_sha: None,
            evidence: request.evidence,
            canonical_facts: serde_json::json!({
                "event": verified.native_facts,
                "context": context,
            }),
            witness: HistoricalWitness {
                harness: harness.to_owned(),
                thread_id: record.session_thread_id.clone(),
                incident_kind: incident_kind.to_owned(),
                witness_id,
                source_id: request.anchor.source_id,
                record_index: request.anchor.record_index,
                byte_start: request.anchor.byte_start,
                byte_end: request.anchor.byte_end,
                record_digest: request.anchor.record_digest,
            },
        },
    })?;
    Ok(CaptureOutput {
        disposition: if result.created {
            "created"
        } else {
            "already-recorded"
        },
        item_id: result.item.id,
        occurrence_id: result.occurrence.id,
        at: result.occurrence.at,
        cwd: result.occurrence.cwd,
        repo_root: result.occurrence.repo_root,
        head_sha: result.occurrence.head_sha,
    })
}

fn validate_tool_projection(
    frozen: &EvidenceRecord,
    verified: &RevalidatedRecord,
) -> Result<(), LearnError> {
    if frozen.kind != verified.kind
        || frozen.tool_use_id != verified.tool_use_id
        || frozen.tool_name != verified.tool_name
        || frozen.tool_input_excerpt != verified.tool_input_excerpt
        || frozen.tool_output_excerpt != verified.tool_output_excerpt
        || frozen.tool_status != verified.tool_status
        || frozen.tool_error != verified.tool_error
        || frozen.tool_observations != verified.tool_observations
        || frozen.failure_reason != verified.failure_reason
    {
        return Err(error(
            "diagnose_snapshot_invalid",
            "frozen tool evidence does not match the revalidated native record",
        ));
    }
    Ok(())
}

fn has_analyst_reviewable_tool_failure(verified: &RevalidatedRecord) -> bool {
    let observations = &verified.tool_observations;
    let explicit_failure = verified.tool_error.is_some()
        || matches!(verified.tool_status.as_deref(), Some("error" | "failed"))
        || observations.iter().any(|observation| {
            observation.error.is_some()
                || matches!(observation.status.as_deref(), Some("error" | "failed"))
        });
    let tool_record =
        matches!(verified.kind.as_str(), "tool_result" | "tool_call") || !observations.is_empty();
    let has_output = verified
        .tool_output_excerpt
        .as_deref()
        .is_some_and(|output| !output.trim().is_empty())
        || observations.iter().any(|observation| {
            observation
                .output_excerpt
                .as_deref()
                .is_some_and(|output| !output.trim().is_empty())
        });
    tool_record && (explicit_failure || has_output)
}

fn verified_family_member(
    snapshot: &InspectionSnapshot,
    selected_source: &SourceSnapshot,
    selected: &RevalidatedRecord,
) -> Result<bool, LearnError> {
    if selected.native_thread_id == snapshot.session.thread_id
        && selected_source.source_id == snapshot.session.source_id
    {
        return selected_root_source_matches(snapshot, selected_source);
    }
    if selected_source.harness.as_deref() == Some("claude") {
        return verified_claude_family_member(snapshot, selected_source, selected);
    }
    verified_thread_family_member(snapshot, selected_source, selected)
}

fn selected_root_source_matches(
    snapshot: &InspectionSnapshot,
    source: &SourceSnapshot,
) -> Result<bool, LearnError> {
    if source.source_id != snapshot.session.source_id {
        return Ok(false);
    }
    let Some(identity) = verified_source_thread(snapshot, source, &snapshot.session.thread_id)?
    else {
        return Ok(false);
    };
    if identity.thread_id != snapshot.session.thread_id
        || identity.parent_thread_id != snapshot.session.parent_thread_id
        || identity.inherited_history
    {
        return Ok(false);
    }
    Ok(match snapshot.session.parent_thread_id.as_deref() {
        Some(_) => identity.root_thread_id.is_none(),
        None => identity.root_thread_id.as_deref() == Some(snapshot.session.thread_id.as_str()),
    })
}

fn verified_thread_family_member(
    snapshot: &InspectionSnapshot,
    selected_source: &SourceSnapshot,
    selected: &RevalidatedRecord,
) -> Result<bool, LearnError> {
    let mut thread_id = selected.native_thread_id.clone();
    let mut source_id = selected_source.source_id.as_str();
    let mut parent_thread_id = selected.native_parent_thread_id.clone();
    let mut visited = std::collections::HashSet::new();
    let Some(root_source) = unique_source(snapshot, &snapshot.session.source_id) else {
        return Ok(false);
    };
    for _ in 0..=MAX_FAMILY {
        if thread_id == snapshot.session.thread_id {
            return Ok(source_id == root_source.source_id
                && parent_thread_id == snapshot.session.parent_thread_id
                && selected_root_source_matches(snapshot, root_source)?);
        }
        if !visited.insert(thread_id.clone()) {
            return Ok(false);
        }
        let matching_children = snapshot
            .children
            .iter()
            .filter(|child| child.thread_id == thread_id && child.source_id == source_id)
            .collect::<Vec<_>>();
        let [child] = matching_children.as_slice() else {
            return Ok(false);
        };
        if child.parent_thread_id != parent_thread_id {
            return Ok(false);
        }
        let Some(parent) = child.parent_thread_id.as_deref() else {
            return Ok(false);
        };
        if parent == snapshot.session.thread_id {
            return selected_root_source_matches(snapshot, root_source);
        }
        let parent_children = snapshot
            .children
            .iter()
            .filter(|candidate| candidate.thread_id == parent)
            .collect::<Vec<_>>();
        let [parent_child] = parent_children.as_slice() else {
            return Ok(false);
        };
        let Some(parent_source) = unique_source(snapshot, &parent_child.source_id) else {
            return Ok(false);
        };
        let Some(parent_identity) = verified_source_thread(snapshot, parent_source, parent)? else {
            return Ok(false);
        };
        if parent_child.parent_thread_id != parent_identity.parent_thread_id {
            return Ok(false);
        }
        thread_id = parent_identity.thread_id;
        source_id = parent_source.source_id.as_str();
        parent_thread_id = parent_identity.parent_thread_id;
    }
    Ok(false)
}

fn verified_claude_family_member(
    snapshot: &InspectionSnapshot,
    selected_source: &SourceSnapshot,
    selected: &RevalidatedRecord,
) -> Result<bool, LearnError> {
    let Some(root_source) = unique_source(snapshot, &snapshot.session.source_id) else {
        return Ok(false);
    };
    let mut current_source = selected_source;
    let mut current_identity = selected.clone();
    let mut visited = std::collections::HashSet::new();
    for _ in 0..=MAX_FAMILY {
        if !visited.insert(current_source.source_id.as_str()) {
            return Ok(false);
        }
        let children = snapshot
            .children
            .iter()
            .filter(|child| {
                child.thread_id == current_identity.native_thread_id
                    && child.source_id == current_source.source_id
            })
            .collect::<Vec<_>>();
        let [child] = children.as_slice() else {
            return Ok(false);
        };
        if child.agent_id != current_identity.agent_id
            || child.parent_agent_id != current_identity.parent_agent_id
            || child.parent_tool_use_id != current_identity.parent_tool_use_id
        {
            return Ok(false);
        }
        let parent_source =
            if let Some(parent_agent_id) = current_identity.parent_agent_id.as_deref() {
                let matches = snapshot
                    .children
                    .iter()
                    .filter(|candidate| candidate.agent_id.as_deref() == Some(parent_agent_id))
                    .collect::<Vec<_>>();
                let [parent] = matches.as_slice() else {
                    return Ok(false);
                };
                let Some(source) = unique_source(snapshot, &parent.source_id) else {
                    return Ok(false);
                };
                source
            } else {
                root_source
            };
        let Some(parent_thread_id) = parent_source.session_thread_id.as_deref() else {
            return Ok(false);
        };
        if child.parent_thread_id.as_deref() != Some(parent_thread_id) {
            return Ok(false);
        }
        let Some(parent_tool_use_id) = current_identity.parent_tool_use_id.as_deref() else {
            return Ok(false);
        };
        let parent_records = snapshot
            .records
            .iter()
            .filter(|record| {
                record.session_thread_id == parent_thread_id
                    && record.anchor.source_id == parent_source.source_id
                    && record.tool_use_id.as_deref() == Some(parent_tool_use_id)
            })
            .collect::<Vec<_>>();
        let [parent_record] = parent_records.as_slice() else {
            return Ok(false);
        };
        let parent_identity = revalidate_record_anchor(parent_source, &parent_record.anchor)?;
        if parent_identity.native_thread_id != parent_thread_id
            || parent_identity.kind != "tool_call"
            || parent_identity.tool_use_id.as_deref() != Some(parent_tool_use_id)
        {
            return Ok(false);
        }
        if parent_source.source_id == root_source.source_id {
            let root_identity = verified_source_identity(root_source)?;
            return Ok(root_identity.thread_id == snapshot.session.thread_id
                && root_identity.parent_thread_id.is_none()
                && parent_identity.native_thread_id == snapshot.session.thread_id);
        }
        current_source = parent_source;
        current_identity = parent_identity;
    }
    Ok(false)
}

fn unique_source<'a>(
    snapshot: &'a InspectionSnapshot,
    source_id: &str,
) -> Option<&'a SourceSnapshot> {
    let mut matches = snapshot
        .sources
        .iter()
        .filter(|source| source.source_id == source_id);
    let source = matches.next()?;
    matches.next().is_none().then_some(source)
}

fn verified_source_thread(
    snapshot: &InspectionSnapshot,
    source: &SourceSnapshot,
    thread_id: &str,
) -> Result<Option<NativeHeaderIdentity>, LearnError> {
    if source.harness.as_deref() != Some("opencode") {
        let identity = verified_source_identity(source)?;
        return Ok((identity.thread_id == thread_id).then_some(identity));
    }
    let Some(record) = snapshot.records.iter().find(|record| {
        record.session_thread_id == thread_id && record.anchor.source_id == source.source_id
    }) else {
        return Ok(None);
    };
    let verified = revalidate_record_anchor(source, &record.anchor)?;
    Ok(Some(NativeHeaderIdentity {
        thread_id: verified.native_thread_id,
        parent_thread_id: verified.native_parent_thread_id,
        root_thread_id: verified.native_root_thread_id,
        inherited_history: verified.inherited_history,
    }))
}

fn revalidate_source_prefix(source: &SourceSnapshot) -> Result<Vec<u8>, LearnError> {
    let path = PathBuf::from(&source.canonical_path);
    let canonical = path.canonicalize().map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("cannot resolve source: {e}"),
        )
    })?;
    if canonical.to_string_lossy() != source.canonical_path {
        return Err(error(
            "diagnose_source_changed",
            "source path identity changed",
        ));
    }
    let mut file = File::open(&canonical).map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("cannot open source: {e}"),
        )
    })?;
    let metadata = file.metadata().map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("cannot stat source: {e}"),
        )
    })?;
    let (device, inode, modified_ns) = file_identity(&metadata);
    if device != source.device || inode != source.inode || metadata.len() < source.initial_length {
        return Err(error(
            "diagnose_source_changed",
            "source inode or captured length changed",
        ));
    }
    if metadata.len() == source.initial_length && modified_ns != source.modified_ns {
        return Err(error(
            "diagnose_source_changed",
            "source was rewritten after inspection",
        ));
    }
    let captured_len = usize::try_from(source.captured_length).map_err(|_| {
        error(
            "diagnose_source_changed",
            "captured source length is invalid",
        )
    })?;
    if captured_len > MAX_SOURCE_BYTES || captured_len > source.initial_length as usize {
        return Err(error(
            "diagnose_source_changed",
            "captured source length exceeds the supported bound",
        ));
    }
    let mut prefix = vec![0; captured_len];
    file.read_exact(&mut prefix).map_err(|e| {
        error(
            "diagnose_source_changed",
            format!("captured prefix changed: {e}"),
        )
    })?;
    if digest(&prefix) != source.prefix_digest {
        return Err(error(
            "diagnose_source_changed",
            "captured source prefix changed",
        ));
    }
    Ok(prefix)
}

fn source_header_identity(
    source: &SourceSnapshot,
    header: &Value,
) -> Result<NativeHeaderIdentity, LearnError> {
    match source.harness.as_deref() {
        Some("codex") if source.format.as_deref() == Some("codex-jsonl") => {
            let (thread_id, parent_thread_id, inherited_history) =
                codex::verified_header_identity(header)?;
            if source
                .session_thread_id
                .as_deref()
                .is_some_and(|source_thread| source_thread != thread_id)
            {
                return Err(error(
                    "diagnose_source_changed",
                    "Codex source thread identity changed after inspection",
                ));
            }
            let root_thread_id = parent_thread_id.is_none().then(|| thread_id.clone());
            Ok(NativeHeaderIdentity {
                thread_id,
                parent_thread_id,
                root_thread_id,
                inherited_history,
            })
        }
        Some("claude") if source.format.as_deref() == Some("claude-jsonl") => {
            let (thread_id, root_thread_id) = claude::verified_thread_identity(source, header)?;
            Ok(NativeHeaderIdentity {
                thread_id,
                parent_thread_id: None,
                root_thread_id: Some(root_thread_id),
                inherited_history: false,
            })
        }
        _ => Err(error(
            "diagnose_source_changed",
            "source harness and native format do not match",
        )),
    }
}

fn verified_source_identity(source: &SourceSnapshot) -> Result<NativeHeaderIdentity, LearnError> {
    let prefix = revalidate_source_prefix(source)?;
    let header_line = prefix
        .split_inclusive(|byte| *byte == b'\n')
        .next()
        .and_then(|line| line.strip_suffix(b"\n").or(Some(line)))
        .ok_or_else(|| error("diagnose_source_changed", "source header is missing"))?;
    let header: Value = serde_json::from_slice(header_line).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("source header is no longer valid JSON: {cause}"),
        )
    })?;
    source_header_identity(source, &header)
}

/// Recheck a captured source witness and derive its normalized identity from bytes.
pub fn revalidate_record_anchor(
    source: &SourceSnapshot,
    anchor: &RecordAnchor,
) -> Result<RevalidatedRecord, LearnError> {
    if anchor.source_id != source.source_id {
        return Err(error(
            "diagnose_anchor_invalid",
            "record anchor belongs to a different source",
        ));
    }
    if source.harness.as_deref() == Some("opencode") {
        return opencode::revalidate_record(source, anchor);
    }
    let prefix = revalidate_source_prefix(source)?;
    let header_line = prefix
        .split_inclusive(|byte| *byte == b'\n')
        .next()
        .and_then(|line| line.strip_suffix(b"\n").or(Some(line)))
        .ok_or_else(|| error("diagnose_source_changed", "source header is missing"))?;
    let header: Value = serde_json::from_slice(header_line).map_err(|cause| {
        error(
            "diagnose_source_changed",
            format!("source header is no longer valid JSON: {cause}"),
        )
    })?;
    let header_identity = source_header_identity(source, &header)?;
    let native_thread_id = header_identity.thread_id;
    let native_parent_thread_id = header_identity.parent_thread_id;
    let native_root_thread_id = header_identity.root_thread_id;
    let inherited_history = header_identity.inherited_history;
    let start = usize::try_from(anchor.byte_start)
        .map_err(|_| error("diagnose_anchor_invalid", "record offset is invalid"))?;
    let end = usize::try_from(anchor.byte_end)
        .map_err(|_| error("diagnose_anchor_invalid", "record offset is invalid"))?;
    if start >= end || end > prefix.len() || end - start > MAX_RECORD_BYTES {
        return Err(error(
            "diagnose_anchor_invalid",
            "record anchor is outside the captured prefix",
        ));
    }
    let mut actual_line = None;
    let mut line_start = 0usize;
    for (index, line) in prefix.split_inclusive(|byte| *byte == b'\n').enumerate() {
        let raw = line.strip_suffix(b"\n").unwrap_or(line);
        let line_end = line_start.saturating_add(raw.len());
        if line_start == start {
            if index as u64 != anchor.record_index || line_end != end {
                return Err(error(
                    "diagnose_anchor_invalid",
                    "record anchor does not match its native JSONL line position",
                ));
            }
            actual_line = Some(raw);
            break;
        }
        line_start = line_start.saturating_add(line.len());
    }
    let line = actual_line.ok_or_else(|| {
        error(
            "diagnose_anchor_invalid",
            "record anchor is not at a JSONL line boundary",
        )
    })?;
    if digest(line) != anchor.record_digest {
        return Err(error(
            "diagnose_anchor_invalid",
            "record digest no longer matches",
        ));
    }
    let value: serde_json::Value = serde_json::from_slice(line).map_err(|e| {
        error(
            "diagnose_anchor_invalid",
            format!("anchored record is invalid JSON: {e}"),
        )
    })?;
    let native_id = match source.harness.as_deref() {
        Some("claude") => value
            .get("uuid")
            .and_then(serde_json::Value::as_str)
            .map(str::to_owned),
        _ => codex::native_id(&value),
    };
    if native_id.as_deref() != anchor.native_id.as_deref() {
        return Err(error(
            "diagnose_anchor_invalid",
            "native event identity does not match the anchored source record",
        ));
    }
    if source.harness.as_deref() == Some("claude")
        && value.get("sessionId").and_then(Value::as_str) != anchor.session_id.as_deref()
    {
        return Err(error(
            "diagnose_anchor_invalid",
            "Claude record session identity does not match its native anchor",
        ));
    }
    if source.agent_id.as_deref().is_some_and(|agent_id| {
        value
            .get("agentId")
            .and_then(Value::as_str)
            .is_some_and(|record_agent_id| record_agent_id != agent_id)
    }) {
        return Err(error(
            "diagnose_anchor_invalid",
            "Claude record agent identity does not match its source transcript",
        ));
    }
    let mut normalized = match source.harness.as_deref() {
        Some("claude") => claude::normalize_record(
            &value,
            anchor.clone(),
            source.session_thread_id.as_deref().unwrap_or("unknown"),
            source.transcript_id.as_deref(),
            source.agent_id.as_deref(),
            source.parent_agent_id.as_deref(),
            source.parent_tool_use_id.as_deref(),
        )?,
        _ => codex::normalize_record(&value, anchor.clone(), "unknown")?,
    };
    if normalized.anchor.native_id != anchor.native_id {
        return Err(error(
            "diagnose_anchor_invalid",
            "native record identity changed",
        ));
    }
    let mut turn_cwd = None;
    for (line_start, line) in
        prefix
            .split_inclusive(|byte| *byte == b'\n')
            .scan(0usize, |offset, line| {
                let start = *offset;
                *offset = offset.saturating_add(line.len());
                Some((start, line))
            })
    {
        if line_start >= start {
            break;
        }
        if let Ok(previous) =
            serde_json::from_slice::<serde_json::Value>(line.strip_suffix(b"\n").unwrap_or(line))
            && previous.get("type").and_then(serde_json::Value::as_str) == Some("turn_context")
        {
            turn_cwd = previous
                .get("payload")
                .and_then(|payload| payload.get("cwd"))
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned)
                .or(turn_cwd);
        }
    }
    if normalized.cwd.is_none() {
        normalized.cwd = turn_cwd;
    }
    Ok(RevalidatedRecord {
        anchor: normalized.anchor,
        native_facts: value,
        native_thread_id,
        native_parent_thread_id,
        native_root_thread_id,
        inherited_history,
        timestamp: normalized.timestamp,
        kind: normalized.kind,
        role: normalized.role,
        text_excerpt: normalized.text_excerpt,
        failure_reason: normalized.failure_reason,
        cwd: normalized.cwd,
        turn_id: normalized.turn_id,
        response_id: normalized.response_id,
        usage_record: normalized.usage_record,
        transcript_id: normalized.transcript_id,
        provider_message_id: normalized.provider_message_id,
        agent_id: normalized.agent_id,
        parent_agent_id: normalized.parent_agent_id,
        parent_native_id: normalized.parent_native_id,
        tool_use_id: normalized.tool_use_id,
        parent_tool_use_id: normalized.parent_tool_use_id,
        tool_name: normalized.tool_name,
        tool_input_excerpt: normalized.tool_input_excerpt,
        tool_output_excerpt: normalized.tool_output_excerpt,
        tool_status: normalized.tool_status,
        tool_error: normalized.tool_error,
        tool_observations: normalized.tool_observations,
        is_sidechain: normalized.is_sidechain,
        is_meta: normalized.is_meta,
        is_compact_summary: normalized.is_compact_summary,
        timestamp_raw: normalized.timestamp_raw,
        session_location: normalized.session_location,
        location_provenance: normalized.location_provenance,
    })
}

pub(crate) fn error(code: &'static str, message: impl Into<String>) -> LearnError {
    LearnError::Diagnose {
        code,
        message: message.into(),
    }
}

pub(crate) fn digest(bytes: &[u8]) -> String {
    let hash = Sha256::digest(bytes);
    let mut output = String::with_capacity(7 + hash.len() * 2);
    output.push_str("sha256:");
    for byte in hash {
        use std::fmt::Write as _;
        let _ = write!(output, "{byte:02x}");
    }
    output
}

pub(crate) fn build_snapshot(
    session: SessionMetadata,
    children: Vec<ChildSession>,
    sources: Vec<SourceSnapshot>,
    records: Vec<EvidenceRecord>,
    overlap: CurrentOverlap,
    coverage: Coverage,
) -> Result<InspectionSnapshot, LearnError> {
    let mut snapshot = InspectionSnapshot {
        schema_version: 1,
        digest: String::new(),
        session,
        children,
        sources,
        records,
        overlap,
        coverage,
    };
    refresh_snapshot_digest(&mut snapshot)?;
    Ok(snapshot)
}

fn refresh_snapshot_digest(snapshot: &mut InspectionSnapshot) -> Result<(), LearnError> {
    snapshot.digest.clear();
    let bytes = serde_json::to_vec(snapshot).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("cannot encode snapshot: {e}"),
        )
    })?;
    if bytes.len() > MAX_SNAPSHOT_BYTES {
        return Err(error(
            "diagnose_snapshot_limit",
            format!("normalized snapshot exceeds {MAX_SNAPSHOT_BYTES} bytes"),
        ));
    }
    snapshot.digest = digest(&bytes);
    let complete_bytes = serde_json::to_vec(snapshot).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("cannot encode snapshot: {e}"),
        )
    })?;
    if complete_bytes.len() > MAX_SNAPSHOT_BYTES {
        return Err(error(
            "diagnose_snapshot_limit",
            "normalized snapshot exceeds its byte limit",
        ));
    }
    Ok(())
}

fn validate_snapshot(snapshot: &InspectionSnapshot) -> Result<(), LearnError> {
    if snapshot.schema_version != 1 {
        return Err(error(
            "diagnose_snapshot_version",
            "unsupported snapshot schema version",
        ));
    }
    if snapshot.records.len() > MAX_RECORDS || snapshot.sources.len() > MAX_FAMILY + 1 {
        return Err(error(
            "diagnose_snapshot_limit",
            "snapshot record or family count exceeds its bound",
        ));
    }
    if snapshot.session.thread_id.trim().is_empty() || snapshot.sources.is_empty() {
        return Err(error(
            "diagnose_snapshot_invalid",
            "snapshot is missing its source identity",
        ));
    }
    let source_ids = snapshot
        .sources
        .iter()
        .map(|source| source.source_id.as_str())
        .collect::<std::collections::HashSet<_>>();
    let mut source_threads =
        std::collections::HashMap::<&str, std::collections::HashSet<&str>>::new();
    source_threads
        .entry(snapshot.session.source_id.as_str())
        .or_default()
        .insert(snapshot.session.thread_id.as_str());
    for child in &snapshot.children {
        source_threads
            .entry(child.source_id.as_str())
            .or_default()
            .insert(child.thread_id.as_str());
    }
    if source_ids.len() != snapshot.sources.len()
        || snapshot.session.source_id != snapshot.sources[0].source_id
        || snapshot.sources.iter().any(|source| {
            source.source_id != source.canonical_path
                || source.captured_length > source.initial_length
                || source.captured_length > MAX_SOURCE_BYTES as u64
                || !source.prefix_digest.starts_with("sha256:")
                || source.format.as_deref().is_some_and(|format| {
                    !matches!(
                        format,
                        "codex-jsonl"
                            | "claude-jsonl"
                            | "opencode-sqlite-2.0.12"
                            | "opencode-export-json"
                    )
                })
                || (source.harness.as_deref() == Some("opencode") && source.format.is_none())
                || source.companions.len() > 2
                || source.companions.iter().any(|companion| {
                    companion.present
                        != (companion.device.is_some()
                            && companion.inode.is_some()
                            && companion.length.is_some()
                            && companion
                                .length
                                .is_some_and(|length| length <= MAX_SOURCE_BYTES as u64)
                            && companion.modified_ns.is_some()
                            && companion
                                .digest
                                .as_deref()
                                .is_some_and(|value| value.starts_with("sha256:")))
                })
                || source.captured_length.saturating_add(
                    source
                        .companions
                        .iter()
                        .filter_map(|companion| companion.length)
                        .sum::<u64>(),
                ) > MAX_FAMILY_SOURCE_BYTES as u64
        })
        || snapshot.coverage.record_count != snapshot.records.len()
        || snapshot.records.iter().any(|record| {
            let source = snapshot
                .sources
                .iter()
                .find(|source| source.source_id == record.anchor.source_id);
            let sqlite_anchor = source
                .is_some_and(|source| source.format.as_deref() == Some("opencode-sqlite-2.0.12"));
            let export_anchor = source
                .is_some_and(|source| source.format.as_deref() == Some("opencode-export-json"));
            !source_ids.contains(record.anchor.source_id.as_str())
                || (!sqlite_anchor
                    && !export_anchor
                    && record.anchor.byte_start >= record.anchor.byte_end)
                || (!sqlite_anchor
                    && !export_anchor
                    && record.anchor.byte_end > source.map_or(0, |source| source.captured_length))
                || ((sqlite_anchor || export_anchor)
                    && (record.anchor.native_id.as_deref().is_none_or(str::is_empty)
                        || record.anchor.session_id.as_deref()
                            != Some(record.session_thread_id.as_str())))
                || (sqlite_anchor && record.anchor.storage_sequence.is_none())
                || !record.anchor.record_digest.starts_with("sha256:")
                || !source_threads
                    .get(record.anchor.source_id.as_str())
                    .is_some_and(|threads| threads.contains(record.session_thread_id.as_str()))
                || serde_json::to_vec(record).is_ok_and(|record| record.len() > MAX_RECORD_BYTES)
        })
    {
        return Err(error(
            "diagnose_snapshot_invalid",
            "record anchor references an unknown source",
        ));
    }
    let mut check = snapshot.clone();
    let expected = check.digest.clone();
    refresh_snapshot_digest(&mut check)?;
    if check.digest != expected {
        return Err(error(
            "diagnose_snapshot_invalid",
            "snapshot digest does not match its contents",
        ));
    }
    Ok(())
}

fn load_snapshot(path: &Path) -> Result<InspectionSnapshot, LearnError> {
    let metadata = fs::metadata(path).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("cannot stat snapshot: {e}"),
        )
    })?;
    if !metadata.is_file() || metadata.len() > MAX_SNAPSHOT_BYTES as u64 {
        return Err(error(
            "diagnose_snapshot_limit",
            "snapshot file exceeds the supported byte limit",
        ));
    }
    let mut file = File::open(path).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("cannot read snapshot: {e}"),
        )
    })?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take((MAX_SNAPSHOT_BYTES + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|e| {
            error(
                "diagnose_snapshot_invalid",
                format!("cannot read snapshot: {e}"),
            )
        })?;
    if bytes.len() > MAX_SNAPSHOT_BYTES {
        return Err(error(
            "diagnose_snapshot_limit",
            "snapshot file exceeds the supported byte limit",
        ));
    }
    let snapshot: InspectionSnapshot = serde_json::from_slice(&bytes).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("invalid snapshot JSON: {e}"),
        )
    })?;
    if snapshot.records.iter().any(|record| {
        serde_json::to_vec(record).is_ok_and(|record| record.len() > MAX_RECORD_BYTES)
    }) {
        return Err(error(
            "diagnose_snapshot_limit",
            "snapshot contains an oversized record",
        ));
    }
    validate_snapshot(&snapshot)?;
    Ok(snapshot)
}

fn write_snapshot(path: &Path, snapshot: &InspectionSnapshot) -> Result<(), LearnError> {
    validate_snapshot(snapshot)?;
    for source in &snapshot.sources {
        let source_path = PathBuf::from(&source.canonical_path);
        let existing = path.canonicalize().ok();
        let candidate = if let Some(existing) = existing {
            existing
        } else {
            let parent = path.parent().unwrap_or_else(|| Path::new("."));
            let parent = parent.canonicalize().map_err(|e| {
                error(
                    "diagnose_snapshot_invalid",
                    format!("cannot resolve snapshot directory: {e}"),
                )
            })?;
            parent.join(path.file_name().ok_or_else(|| {
                error(
                    "diagnose_snapshot_invalid",
                    "snapshot output path has no filename",
                )
            })?)
        };
        let source_meta = fs::metadata(&source_path).ok();
        let output_meta = fs::metadata(path).ok();
        if candidate == source_path
            || matches!((source_meta, output_meta), (Some(source), Some(output)) if file_id_equal(&source, &output))
        {
            return Err(error(
                "diagnose_snapshot_alias",
                "snapshot output aliases an inspected source",
            ));
        }
    }
    let bytes = serde_json::to_vec(snapshot).map_err(|e| {
        error(
            "diagnose_snapshot_invalid",
            format!("cannot encode snapshot: {e}"),
        )
    })?;
    if bytes.len() > MAX_SNAPSHOT_BYTES {
        return Err(error(
            "diagnose_snapshot_limit",
            "snapshot output exceeds its byte limit",
        ));
    }
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    let mut file = options.open(path).map_err(|e| {
        let code = if e.kind() == std::io::ErrorKind::AlreadyExists {
            "diagnose_snapshot_exists"
        } else {
            "diagnose_snapshot_write_failed"
        };
        error(
            code,
            format!("cannot create snapshot without overwriting: {e}"),
        )
    })?;
    if let Err(e) = file.write_all(&bytes) {
        drop(file);
        let _ = fs::remove_file(path);
        return Err(error(
            "diagnose_snapshot_write_failed",
            format!("cannot write snapshot: {e}"),
        ));
    }
    Ok(())
}

fn apply_cutoff(snapshot: &mut InspectionSnapshot, path: &Path) -> Result<(), LearnError> {
    let metadata = fs::metadata(path).map_err(|e| {
        error(
            "diagnose_cutoff_invalid",
            format!("cannot stat cutoff anchor: {e}"),
        )
    })?;
    if !metadata.is_file() || metadata.len() > 64 * 1024 {
        return Err(error(
            "diagnose_cutoff_invalid",
            "cutoff anchor exceeds 64 KiB",
        ));
    }
    let mut file = File::open(path).map_err(|e| {
        error(
            "diagnose_cutoff_invalid",
            format!("cannot read cutoff anchor: {e}"),
        )
    })?;
    let mut bytes = Vec::new();
    Read::by_ref(&mut file)
        .take(64 * 1024 + 1)
        .read_to_end(&mut bytes)
        .map_err(|e| {
            error(
                "diagnose_cutoff_invalid",
                format!("cannot read cutoff anchor: {e}"),
            )
        })?;
    if bytes.len() > 64 * 1024 {
        return Err(error(
            "diagnose_cutoff_invalid",
            "cutoff anchor exceeds 64 KiB",
        ));
    }
    let cutoff: CutoffAnchorFile = serde_json::from_slice(&bytes).map_err(|e| {
        error(
            "diagnose_cutoff_invalid",
            format!("invalid cutoff anchor JSON: {e}"),
        )
    })?;
    let canonical = cutoff.source_path.canonicalize().map_err(|e| {
        error(
            "diagnose_cutoff_invalid",
            format!("cannot resolve cutoff source: {e}"),
        )
    })?;
    let source_id = canonical.to_string_lossy();
    let Some(source) = snapshot
        .sources
        .iter()
        .find(|source| source.source_id == source_id)
    else {
        return Err(error(
            "diagnose_cutoff_invalid",
            "cutoff anchor belongs to a different source",
        ));
    };
    let Some(record) = snapshot
        .records
        .iter()
        .find(|record| record.anchor == cutoff.record_anchor)
    else {
        return Err(error(
            "diagnose_cutoff_invalid",
            "cutoff record is not in the inspected evidence",
        ));
    };
    if record.anchor.source_id != source.source_id {
        return Err(error(
            "diagnose_cutoff_invalid",
            "cutoff must identify a native record in the selected source",
        ));
    }
    revalidate_record_anchor(source, &cutoff.record_anchor).map_err(|_| {
        error(
            "diagnose_cutoff_invalid",
            "cutoff source changed after the anchor was inspected",
        )
    })?;
    let cutoff_instant = record.timestamp.as_deref().and_then(parse_rfc3339_nanos);
    let selected_source = source.source_id.clone();
    let selected_thread = snapshot.session.thread_id.clone();
    let database_sequence_cutoff = (source.format.as_deref() == Some("opencode-sqlite-2.0.12"))
        .then_some(cutoff.record_anchor.storage_sequence)
        .flatten();
    let children_before = snapshot.children.len();
    let mut eligible_child_threads = std::collections::HashSet::new();
    let mut omitted_unknown_child_time = false;
    snapshot.children.retain(|child| {
        let Some(cutoff_instant) = cutoff_instant else {
            omitted_unknown_child_time = true;
            return false;
        };
        let Some(started_at) = child.started_at.as_deref() else {
            omitted_unknown_child_time = true;
            return false;
        };
        let Some(started_at) = parse_rfc3339_nanos(started_at) else {
            omitted_unknown_child_time = true;
            return false;
        };
        if started_at <= cutoff_instant {
            eligible_child_threads.insert(child.thread_id.clone());
            true
        } else {
            false
        }
    });
    let before_cutoff = |record: &EvidenceRecord| {
        if record.session_thread_id == selected_thread {
            if let Some(sequence) = database_sequence_cutoff {
                return record
                    .anchor
                    .storage_sequence
                    .is_some_and(|record_sequence| record_sequence <= sequence);
            }
            return record.anchor.source_id == selected_source
                && record.anchor.record_index <= cutoff.record_anchor.record_index;
        }
        if !eligible_child_threads.contains(&record.session_thread_id) {
            return false;
        }
        let Some(cutoff_instant) = cutoff_instant else {
            omitted_unknown_child_time = true;
            return false;
        };
        match record.timestamp.as_deref().and_then(parse_rfc3339_nanos) {
            Some(record_instant) => record_instant <= cutoff_instant,
            None => {
                omitted_unknown_child_time = true;
                false
            }
        }
    };
    let prior_count = snapshot.records.len();
    snapshot.records.retain(before_cutoff);
    let retained_sources = snapshot
        .children
        .iter()
        .map(|child| child.source_id.as_str())
        .chain(std::iter::once(selected_source.as_str()))
        .collect::<std::collections::HashSet<_>>();
    snapshot
        .sources
        .retain(|source| retained_sources.contains(source.source_id.as_str()));
    let removed = prior_count.saturating_sub(snapshot.records.len());
    snapshot.coverage.omitted_records = snapshot.coverage.omitted_records.saturating_add(removed);
    if removed > 0 || children_before > snapshot.children.len() {
        snapshot.coverage.warnings.push(
            "records after the verified cutoff were excluded from the frozen evidence".into(),
        );
    }
    if omitted_unknown_child_time {
        snapshot.coverage.source_complete = false;
        snapshot.coverage.complete = false;
        snapshot.coverage.analysis_ready = false;
        snapshot.coverage.warnings.push("some linked-child records could not be placed before the cutoff because their event time was unknown".into());
    }
    snapshot.coverage.cutoff_verified = true;
    snapshot.coverage.cutoff_anchor = Some(cutoff.record_anchor);
    snapshot.coverage.record_count = snapshot.records.len();
    if snapshot.coverage.source_complete {
        snapshot.coverage.complete = true;
        snapshot.coverage.analysis_ready = true;
    }
    snapshot
        .coverage
        .warnings
        .retain(|warning| !warning.contains("no verified pre-orchestration cutoff"));
    Ok(())
}

/// Parse only RFC3339 instants that the supported timestamp library represents
/// without precision loss. Unsupported precision and leap seconds stay unknown.
pub(crate) fn parse_rfc3339_nanos(value: &str) -> Option<i128> {
    use time::{OffsetDateTime, format_description::well_known::Rfc3339};

    let bytes = value.as_bytes();
    let separator = bytes
        .iter()
        .position(|byte| *byte == b'T' || *byte == b't')?;
    let time_start = separator.checked_add(1)?;
    let second_start = time_start.checked_add(6)?;
    let second_end = second_start.checked_add(2)?;
    if bytes.get(second_start..second_end) == Some(b"60") {
        return None;
    }
    if bytes.get(time_start + 8) == Some(&b'.') {
        let fraction_start = time_start + 9;
        let fraction_end = bytes[fraction_start..]
            .iter()
            .position(|byte| matches!(byte, b'Z' | b'z' | b'+' | b'-'))
            .map(|offset| fraction_start + offset)?;
        let digits = &bytes[fraction_start..fraction_end];
        if digits.is_empty() || digits.len() > 9 || !digits.iter().all(u8::is_ascii_digit) {
            return None;
        }
    }
    OffsetDateTime::parse(value, &Rfc3339)
        .ok()
        .map(|instant| instant.unix_timestamp_nanos())
}

pub(crate) fn file_identity(metadata: &fs::Metadata) -> (u64, u64, u128) {
    #[cfg(unix)]
    let (device, inode) = {
        use std::os::unix::fs::MetadataExt;
        (metadata.dev(), metadata.ino())
    };
    #[cfg(not(unix))]
    let (device, inode) = (0, 0);
    let modified_ns = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(std::time::UNIX_EPOCH).ok())
        .map_or(0, |duration| duration.as_nanos());
    (device, inode, modified_ns)
}

fn file_id_equal(left: &fs::Metadata, right: &fs::Metadata) -> bool {
    let (left_device, left_inode, _) = file_identity(left);
    let (right_device, right_inode, _) = file_identity(right);
    left_device == right_device && left_inode == right_inode
}

#[cfg(test)]
mod timestamp_tests {
    use super::{
        Coverage, CurrentOverlap, DiagnosticHarness, InspectRequest, InspectionSnapshot, Intake,
        SessionMetadata, SourceSnapshot, build_snapshot, capture, digest, inspect,
        parse_rfc3339_nanos, refresh_snapshot_digest, validate_snapshot,
    };
    use rusqlite::Connection;
    use std::fs;
    use std::path::PathBuf;
    use tempfile::TempDir;

    #[test]
    fn rfc3339_cutoff_order_uses_instants_without_precision_loss() {
        let whole = parse_rfc3339_nanos("2026-09-27T10:00:00Z").unwrap();
        let later_fraction = parse_rfc3339_nanos("2026-09-27T10:00:00.100Z").unwrap();
        let same_offset = parse_rfc3339_nanos("2026-09-27T11:00:00+01:00").unwrap();
        assert!(whole < later_fraction);
        assert_eq!(whole, same_offset);
        assert!(parse_rfc3339_nanos("2026-09-27T10:00:00.1234567891Z").is_none());
        assert!(parse_rfc3339_nanos("2026-09-27T10:00:60Z").is_none());
    }

    #[test]
    fn legacy_snapshot_shape_without_claude_identity_fields_still_validates() {
        let source_id = "/synthetic/codex-rollout.jsonl";
        let source_bytes = b"{}\n";
        let snapshot = build_snapshot(
            SessionMetadata {
                harness: "codex".into(),
                thread_id: "thread-fixture".into(),
                session_id: None,
                parent_thread_id: None,
                parent_provenance: None,
                started_at: None,
                cwd: None,
                cli_version: Some("0.155.1".into()),
                history_mode: None,
                git: None,
                source_id: source_id.into(),
                transcript_id: None,
                project_namespace: None,
                agent_id: None,
                parent_agent_id: None,
                parent_tool_use_id: None,
                current_directory: None,
                fork_session_id: None,
                fork_boundary: None,
            },
            Vec::new(),
            vec![SourceSnapshot {
                source_id: source_id.into(),
                canonical_path: source_id.into(),
                device: 0,
                inode: 0,
                initial_length: source_bytes.len() as u64,
                captured_length: source_bytes.len() as u64,
                modified_ns: 0,
                prefix_digest: digest(source_bytes),
                harness: None,
                session_thread_id: None,
                transcript_id: None,
                agent_id: None,
                parent_agent_id: None,
                parent_tool_use_id: None,
                format: Some("codex-jsonl".into()),
                companions: Vec::new(),
            }],
            Vec::new(),
            CurrentOverlap::NotCurrent,
            Coverage {
                complete: true,
                source_complete: true,
                analysis_ready: true,
                cutoff_verified: false,
                cutoff_anchor: None,
                incomplete_tail: false,
                truncated: false,
                record_count: 0,
                malformed_records: 0,
                omitted_records: 0,
                warnings: Vec::new(),
            },
        )
        .unwrap();
        let serialized = serde_json::to_vec(&snapshot).unwrap();
        let legacy_shape: InspectionSnapshot = serde_json::from_slice(&serialized).unwrap();
        validate_snapshot(&legacy_shape).unwrap();
    }

    #[test]
    fn capture_rejects_forged_frozen_tool_projection_before_store_access() {
        let root = TempDir::new().unwrap();
        let home = root.path().join("codex-home");
        let source_path = home.join("sessions/2026/09/27/rollout-fixture.jsonl");
        fs::create_dir_all(source_path.parent().unwrap()).unwrap();
        fs::write(
            &source_path,
            concat!(
                "{\"type\":\"session_meta\",\"payload\":{\"id\":\"thread-forged-projection\",\"cli_version\":\"0.155.1\",\"cwd\":\"/historical\"}}\n",
                "{\"timestamp\":\"2026-09-27T10:01:00Z\",\"type\":\"turn_context\",\"payload\":{\"cwd\":\"/historical\"}}\n",
                "{\"timestamp\":\"2026-09-27T10:02:00Z\",\"type\":\"response_item\",\"id\":\"raw-tool-event\",\"payload\":{\"type\":\"function_call_output\",\"call_id\":\"call-raw\",\"output\":\"ordinary output\"}}\n"
            ),
        )
        .unwrap();
        let mut snapshot = super::codex::inspect_path(&home, &source_path).unwrap();
        snapshot.overlap = CurrentOverlap::NotCurrent;
        snapshot.coverage.analysis_ready = true;
        let selected = snapshot
            .records
            .iter_mut()
            .find(|record| record.anchor.native_id.as_deref() == Some("raw-tool-event"))
            .unwrap();
        selected.tool_status = Some("failed".into());
        selected.tool_error = Some("invented failure flag".into());
        refresh_snapshot_digest(&mut snapshot).unwrap();
        let snapshot_path = root.path().join("forged-snapshot.json");
        fs::write(&snapshot_path, serde_json::to_vec(&snapshot).unwrap()).unwrap();
        let selected = snapshot
            .records
            .iter()
            .find(|record| record.anchor.native_id.as_deref() == Some("raw-tool-event"))
            .unwrap();
        let request_path = root.path().join("capture.json");
        fs::write(
            &request_path,
            serde_json::to_vec(&serde_json::json!({
                "snapshot_path": snapshot_path,
                "snapshot_digest": snapshot.digest,
                "session_id": snapshot.session.thread_id,
                "anchor": selected.anchor,
                "incident_kind": "failed-tool",
                "item": {"mode":"existing", "id":0},
                "evidence": "analyst supplied synthetic evidence"
            }))
            .unwrap(),
        )
        .unwrap();
        let error = capture(&request_path).expect_err("forged normalized failure must be rejected");
        assert!(matches!(
            error,
            crate::LearnError::Diagnose {
                code: "diagnose_snapshot_invalid",
                ..
            }
        ));
    }

    #[test]
    fn capture_rejects_forged_failure_over_native_claude_success() {
        let root = TempDir::new().unwrap();
        let projects = root.path().join("projects");
        let session_id = "00000000-0000-4000-8000-000000000099";
        let source_path = projects
            .join("fixture-project")
            .join(format!("{session_id}.jsonl"));
        fs::create_dir_all(source_path.parent().unwrap()).unwrap();
        let records = [
            serde_json::json!({
                "type":"assistant", "uuid":"tool-call", "parentUuid":null,
                "sessionId":session_id, "timestamp":"2026-09-27T10:00:00Z", "cwd":"/historic",
                "message":{"id":"provider-call", "role":"assistant", "content":[
                    {"type":"tool_use", "id":"tool-success", "name":"Bash", "input":{"command":"true"}}
                ]}
            }),
            serde_json::json!({
                "type":"user", "uuid":"native-success", "parentUuid":"tool-call",
                "sessionId":session_id, "timestamp":"2026-09-27T10:01:00Z", "cwd":"/historic",
                "message":{"role":"user", "content":[
                    {"type":"tool_result", "tool_use_id":"tool-success", "is_error":false, "content":"completed successfully"}
                ]}
            }),
        ];
        fs::write(
            &source_path,
            records
                .iter()
                .map(|record| record.to_string())
                .collect::<Vec<_>>()
                .join("\n")
                + "\n",
        )
        .unwrap();
        let mut snapshot = super::claude::inspect_path(&projects, &source_path).unwrap();
        snapshot.overlap = CurrentOverlap::NotCurrent;
        snapshot.coverage.analysis_ready = true;
        let selected = snapshot
            .records
            .iter_mut()
            .find(|record| record.anchor.native_id.as_deref() == Some("native-success"))
            .unwrap();
        assert_eq!(selected.tool_status.as_deref(), Some("success"));
        selected.tool_status = Some("error".into());
        selected.tool_error = Some("invented native error".into());
        refresh_snapshot_digest(&mut snapshot).unwrap();
        let snapshot_path = root.path().join("forged-claude-snapshot.json");
        fs::write(&snapshot_path, serde_json::to_vec(&snapshot).unwrap()).unwrap();
        let selected = snapshot
            .records
            .iter()
            .find(|record| record.anchor.native_id.as_deref() == Some("native-success"))
            .unwrap();
        let request_path = root.path().join("capture.json");
        fs::write(
            &request_path,
            serde_json::to_vec(&serde_json::json!({
                "snapshot_path": snapshot_path,
                "snapshot_digest": snapshot.digest,
                "session_id": snapshot.session.thread_id,
                "anchor": selected.anchor,
                "incident_kind": "failed-tool",
                "item": {"mode":"existing", "id":0},
                "evidence": "analyst supplied synthetic evidence"
            }))
            .unwrap(),
        )
        .unwrap();
        let error =
            capture(&request_path).expect_err("forged failure must not override raw success");
        assert!(matches!(
            error,
            crate::LearnError::Diagnose {
                code: "diagnose_snapshot_invalid",
                ..
            }
        ));
    }

    #[test]
    fn opencode_native_wal_rows_are_inspected_without_changing_source_files() {
        let root = TempDir::new().unwrap();
        let db_path = root.path().join("opencode.db");
        let connection = Connection::open(&db_path).unwrap();
        connection
            .pragma_update(None, "journal_mode", "WAL")
            .unwrap();
        connection.execute_batch(
            r#"
            CREATE TABLE project(id TEXT PRIMARY KEY);
            CREATE TABLE session_v2 (
              id TEXT PRIMARY KEY, project_id TEXT NOT NULL, workspace_id TEXT,
              parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT,
              slug TEXT NOT NULL, directory TEXT NOT NULL, path TEXT, title TEXT,
              version TEXT NOT NULL, share_url TEXT, summary_additions INTEGER,
              summary_deletions INTEGER, summary_files INTEGER, summary_diffs TEXT,
              metadata TEXT, cost REAL DEFAULT 0 NOT NULL,
              tokens_input INTEGER DEFAULT 0 NOT NULL, tokens_output INTEGER DEFAULT 0 NOT NULL,
              tokens_reasoning INTEGER DEFAULT 0 NOT NULL, tokens_cache_read INTEGER DEFAULT 0 NOT NULL,
              tokens_cache_write INTEGER DEFAULT 0 NOT NULL, revert TEXT, permission TEXT,
              agent TEXT, model TEXT, time_created INTEGER NOT NULL, time_updated INTEGER NOT NULL,
              time_idle INTEGER, time_viewed INTEGER, idle_outcome TEXT, time_compacting INTEGER,
              time_archived INTEGER, time_suspended INTEGER,
              resume_attempts INTEGER DEFAULT 0 NOT NULL,
              FOREIGN KEY(project_id) REFERENCES project(id) ON DELETE CASCADE
            );
            CREATE TABLE session_message (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES session_v2(id) ON DELETE CASCADE,
              type TEXT NOT NULL, seq INTEGER NOT NULL, time_created INTEGER NOT NULL,
              time_updated INTEGER NOT NULL, data TEXT NOT NULL
            );
            CREATE UNIQUE INDEX session_message_session_seq_idx ON session_message(session_id,seq);
            CREATE INDEX session_message_session_type_seq_idx ON session_message(session_id,type,seq);
            CREATE INDEX session_message_session_time_created_id_idx ON session_message(session_id,time_created,id);
            CREATE INDEX session_message_time_created_idx ON session_message(time_created);
            INSERT INTO project(id) VALUES ('project_fixture');
            INSERT INTO session_v2(id,project_id,slug,directory,version,time_created,time_updated)
            VALUES ('ses_fixture','project_fixture','fixture-slug','/fixture/B','2.0.12',1700000000000,1700000000100);
            INSERT INTO session_v2(id,project_id,parent_id,fork_session_id,fork_boundary,slug,directory,version,time_created,time_updated)
            VALUES ('ses_child','project_fixture','ses_fixture','ses_ancestor','{"seq":1}','child-slug','/fixture/child-current','2.0.12',1700000000005,1700000000200);
            INSERT INTO session_v2(id,project_id,parent_id,slug,directory,version,time_created,time_updated)
            VALUES ('ses_selected_child','project_fixture','ses_fixture','selected-child-slug','/mutable/child-directory','2.0.12',1700000000006,1700000000200);
            INSERT INTO session_v2(id,project_id,slug,directory,version,time_created,time_updated)
            VALUES ('ses_no_previous','project_fixture','no-previous-slug','/fixture/B','2.0.12',1700000000000,1700000000200);
            INSERT INTO session_message(id,session_id,type,seq,time_created,time_updated,data)
            VALUES
              ('msg_user','ses_fixture','user',1,1700000000000,1700000000000,
               '{"text":"Synthetic question","time":{"created":1700000000000}}'),
              ('msg_failed_tool','ses_fixture','assistant',2,1700000000010,1700000000040,
               '{"agent":"build","model":{"id":"synthetic-model","providerID":"synthetic-provider","variant":"default"},"content":[{"type":"tool","id":"tool_fixture","name":"bash","state":{"status":"error","input":{"command":"false"},"error":{"type":"tool.execution","message":"Synthetic exit 1"}},"time":{"created":1700000000010,"ran":1700000000020,"completed":1700000000030}}],"time":{"created":1700000000010,"completed":1700000000040},"tokens":{"input":10,"output":3,"reasoning":2,"cache":{"read":7,"write":4}}}'),
              ('msg_location_switch','ses_fixture','location-switched',3,1700000000100,1700000000100,
               '{"location":{"directory":"/fixture/B"},"previous":{"location":{"directory":"/fixture/A"}},"time":{"created":1700000000100}}'),
              ('msg_after_switch','ses_fixture','assistant',4,1700000000110,1700000000120,
               '{"cwd":"/tool/actual","text":"after switch","time":{"created":1700000000110}}'),
              ('msg_child_copy','ses_child','user',1,1700000000005,1700000000005,
               '{"text":"materialized fork copy","time":{"created":1700000000005}}'),
              ('msg_selected_child','ses_selected_child','user',1,1700000000006,1700000000006,
               '{"text":"selected child has no recorded event cwd","time":{"created":1700000000006}}'),
              ('msg_child_gap','ses_child','assistant',3,1700000000030,1700000000030,
               '{"text":"row after sequence gap","time":{"created":1700000000030}}'),
              ('msg_no_previous_user','ses_no_previous','user',1,1700000000000,1700000000000,
               '{"text":"before switch","time":{"created":1700000000000}}'),
              ('msg_no_previous_switch','ses_no_previous','location-switched',2,1700000000100,1700000000100,
               '{"location":{"directory":"/fixture/B"},"time":{"created":1700000000100}}'),
              ('msg_no_previous_tool','ses_no_previous','assistant',3,1700000000110,1700000000120,
               '{"cwd":"/tool/no-previous","text":"after switch","time":{"created":1700000000110}}');
            "#,
        )
        .unwrap();
        let source_files = [
            db_path.clone(),
            PathBuf::from(format!("{}-wal", db_path.display())),
            PathBuf::from(format!("{}-shm", db_path.display())),
        ];
        assert!(source_files.iter().all(|path| path.exists()));
        let before = source_files
            .iter()
            .map(|path| fs::read(path).unwrap())
            .collect::<Vec<_>>();

        let inspected = inspect(&InspectRequest {
            harness: Some(DiagnosticHarness::Opencode),
            intake: Intake::Session {
                source_root: db_path.clone(),
                session_id: "ses_fixture".into(),
            },
            offset: 0,
            limit: 20,
            snapshot_out: None,
            cutoff_anchor: None,
        })
        .unwrap();

        assert_eq!(inspected.session.harness, "opencode");
        assert_eq!(inspected.session.session_id.as_deref(), Some("ses_fixture"));
        assert_eq!(inspected.records.len(), 7);
        assert_eq!(
            inspected.records[1].anchor.native_id.as_deref(),
            Some("msg_failed_tool")
        );
        assert_eq!(inspected.records[1].tool_status.as_deref(), Some("error"));
        assert_eq!(
            inspected.records[1].tool_error.as_deref(),
            Some("Synthetic exit 1")
        );
        assert_eq!(
            inspected.records[1].usage_record.as_ref().unwrap()["total_tokens"],
            26
        );
        assert_eq!(
            inspected.session.current_directory.as_deref(),
            Some("/fixture/B")
        );
        assert_eq!(
            inspected.records[0].session_location.as_deref(),
            Some("/fixture/A")
        );
        assert_eq!(
            inspected.records[0].location_provenance.as_deref(),
            Some("first location-switched.previous.location")
        );
        assert_eq!(
            inspected.records[1].cwd, None,
            "session location is not tool execution cwd"
        );
        assert_eq!(inspected.records[4].session_thread_id, "ses_child");
        assert_eq!(
            inspected.records[4].anchor.native_id.as_deref(),
            Some("msg_child_copy")
        );
        assert_eq!(inspected.records[5].session_thread_id, "ses_child");
        assert_eq!(
            inspected.records[5].session_location, None,
            "a child sequence gap prevents historical location inference"
        );
        assert_eq!(inspected.records[3].cwd.as_deref(), Some("/tool/actual"));
        assert_eq!(
            inspected.records[3].session_location.as_deref(),
            Some("/fixture/B")
        );
        assert_eq!(inspected.children.len(), 2);
        assert_eq!(
            inspected.children[0].fork_session_id.as_deref(),
            Some("ses_ancestor")
        );
        assert!(
            !inspected.coverage.complete,
            "gaps and materialized fork provenance must remain partial"
        );

        let no_previous = inspect(&InspectRequest {
            harness: Some(DiagnosticHarness::Opencode),
            intake: Intake::Session {
                source_root: db_path.clone(),
                session_id: "ses_no_previous".into(),
            },
            offset: 0,
            limit: 20,
            snapshot_out: None,
            cutoff_anchor: None,
        })
        .unwrap();
        assert_eq!(
            no_previous.records[0].session_location, None,
            "mutable session.directory must not fill an unanchored historical location"
        );
        assert_eq!(
            no_previous.records[2].session_location.as_deref(),
            Some("/fixture/B")
        );
        assert_eq!(
            no_previous.records[2].cwd.as_deref(),
            Some("/tool/no-previous")
        );

        let cutoff_path = root.path().join("cutoff.json");
        fs::write(
            &cutoff_path,
            serde_json::json!({
                "source_path": db_path.canonicalize().unwrap(),
                "record_anchor": inspected.records[1].anchor,
            })
            .to_string(),
        )
        .unwrap();
        let cutoff = inspect(&InspectRequest {
            harness: Some(DiagnosticHarness::Opencode),
            intake: Intake::Session {
                source_root: db_path.clone(),
                session_id: "ses_fixture".into(),
            },
            offset: 0,
            limit: 20,
            snapshot_out: None,
            cutoff_anchor: Some(cutoff_path),
        })
        .unwrap();
        assert!(
            cutoff.coverage.cutoff_verified,
            "an explicit assistant/tool failure anchor is a valid pre-orchestration boundary"
        );
        let cutoff_snapshot = build_snapshot(
            cutoff.session.clone(),
            cutoff.children.clone(),
            cutoff.sources.clone(),
            cutoff.records.clone(),
            cutoff.overlap.clone(),
            cutoff.coverage.clone(),
        )
        .unwrap();
        let cutoff_snapshot_path = root.path().join("verified-cutoff-snapshot.json");
        super::write_snapshot(&cutoff_snapshot_path, &cutoff_snapshot).unwrap();
        let selected = cutoff_snapshot
            .records
            .iter()
            .find(|record| record.anchor.native_id.as_deref() == Some("msg_failed_tool"))
            .unwrap();
        let capture_path = root.path().join("opencode-cutoff-capture.json");
        fs::write(
            &capture_path,
            serde_json::to_vec(&serde_json::json!({
                "snapshot_path": cutoff_snapshot_path,
                "snapshot_digest": cutoff_snapshot.digest,
                "session_id": cutoff_snapshot.session.thread_id,
                "anchor": selected.anchor,
                "incident_kind": "workflow-deviation",
                "item": {"mode":"existing", "id":0},
                "evidence": "pre-orchestration OpenCode fixture"
            }))
            .unwrap(),
        )
        .unwrap();
        let capture_error = capture(&capture_path).expect_err(
            "verified OpenCode cutoff should reach item validation before any store opens",
        );
        assert!(
            matches!(
                &capture_error,
                crate::LearnError::Diagnose {
                    code: "diagnose_capture_uncertain",
                    message,
                } if message.contains("historical working directory")
            ),
            "unexpected OpenCode cutoff capture result: {capture_error:?}"
        );
        assert!(!cutoff.records.iter().any(|record| {
            record.anchor.session_id.as_deref() == Some("ses_fixture")
                && record
                    .anchor
                    .storage_sequence
                    .is_some_and(|sequence| sequence > 2)
        }));
        assert!(
            cutoff
                .records
                .iter()
                .any(|record| record.anchor.native_id.as_deref() == Some("msg_child_copy"))
        );
        assert!(
            !cutoff
                .records
                .iter()
                .any(|record| record.anchor.native_id.as_deref() == Some("msg_child_gap"))
        );

        let selected_child = inspect(&InspectRequest {
            harness: Some(DiagnosticHarness::Opencode),
            intake: Intake::Session {
                source_root: db_path.clone(),
                session_id: "ses_selected_child".into(),
            },
            offset: 0,
            limit: 20,
            snapshot_out: None,
            cutoff_anchor: None,
        })
        .unwrap();
        assert_eq!(
            selected_child.session.parent_thread_id.as_deref(),
            Some("ses_fixture")
        );
        assert_eq!(
            selected_child.session.current_directory.as_deref(),
            Some("/mutable/child-directory")
        );
        let child_anchor = selected_child
            .records
            .iter()
            .find(|record| record.anchor.native_id.as_deref() == Some("msg_selected_child"))
            .unwrap()
            .anchor
            .clone();
        assert!(
            selected_child
                .records
                .iter()
                .find(|record| record.anchor.native_id.as_deref() == Some("msg_selected_child"))
                .unwrap()
                .cwd
                .is_none()
        );
        let mut selected_child_coverage = selected_child.coverage.clone();
        selected_child_coverage.analysis_ready = true;
        let selected_child_snapshot = super::build_snapshot(
            selected_child.session.clone(),
            selected_child.children.clone(),
            selected_child.sources.clone(),
            selected_child.records.clone(),
            CurrentOverlap::NotCurrent,
            selected_child_coverage,
        )
        .unwrap();
        let child_source =
            super::unique_source(&selected_child_snapshot, &selected_child.session.source_id)
                .unwrap();
        let child_identity = super::revalidate_record_anchor(child_source, &child_anchor).unwrap();
        assert_eq!(
            child_identity.native_parent_thread_id.as_deref(),
            Some("ses_fixture")
        );
        assert!(
            super::verified_family_member(&selected_child_snapshot, child_source, &child_identity)
                .unwrap()
        );
        let selected_child_snapshot_path = root.path().join("selected-child-snapshot.json");
        super::write_snapshot(&selected_child_snapshot_path, &selected_child_snapshot).unwrap();
        let selected_child_capture_path = root.path().join("selected-child-capture.json");
        fs::write(
            &selected_child_capture_path,
            serde_json::to_vec(&serde_json::json!({
                "snapshot_path": selected_child_snapshot_path,
                "snapshot_digest": selected_child_snapshot.digest,
                "session_id": selected_child.session.thread_id,
                "anchor": child_anchor,
                "incident_kind": "workflow-deviation",
                "item": {"mode":"existing", "id":0},
                "evidence": "no event cwd was invented from the mutable session directory"
            }))
            .unwrap(),
        )
        .unwrap();
        let child_capture_error = capture(&selected_child_capture_path)
            .expect_err("unknown OpenCode event cwd must remain uncaptured");
        assert!(matches!(
            child_capture_error,
            crate::LearnError::Diagnose {
                code: "diagnose_capture_uncertain",
                message,
            } if message.contains("historical working directory")
        ));
        let after_inspection = source_files
            .iter()
            .map(|path| fs::read(path).unwrap())
            .collect::<Vec<_>>();
        assert_eq!(
            before, after_inspection,
            "inspection must not write to DB, WAL, or SHM"
        );

        let saved_source = inspected.sources[0].clone();
        let saved_anchor = inspected.records[1].anchor.clone();
        connection.execute(
            "INSERT INTO session_message(id,session_id,type,seq,time_created,time_updated,data) VALUES ('msg_unrelated_append','ses_child','user',4,1700000000040,1700000000040,'{\"text\":\"later append\"}')",
            [],
        ).unwrap();
        let witness = super::revalidate_record_anchor(&saved_source, &saved_anchor).unwrap();
        assert_eq!(witness.anchor.native_id.as_deref(), Some("msg_failed_tool"));
        connection
            .execute(
                "UPDATE session_message SET data=?1 WHERE id='msg_failed_tool'",
                ["{\"text\":\"changed selected record\"}"],
            )
            .unwrap();
        assert!(
            super::revalidate_record_anchor(&saved_source, &saved_anchor).is_err(),
            "changing the selected row invalidates its witness"
        );

        let shm_path = PathBuf::from(format!("{}-shm", db_path.display()));
        fs::remove_file(&shm_path).unwrap();
        let no_shm_before = [
            fs::read(&db_path).unwrap(),
            fs::read(PathBuf::from(format!("{}-wal", db_path.display()))).unwrap(),
        ];
        assert!(!shm_path.exists());
        let reopened = inspect(&InspectRequest {
            harness: Some(DiagnosticHarness::Opencode),
            intake: Intake::Session {
                source_root: db_path.clone(),
                session_id: "ses_fixture".into(),
            },
            offset: 0,
            limit: 20,
            snapshot_out: None,
            cutoff_anchor: None,
        })
        .unwrap();
        assert_eq!(reopened.session.session_id.as_deref(), Some("ses_fixture"));
        assert_eq!(
            no_shm_before,
            [
                fs::read(&db_path).unwrap(),
                fs::read(PathBuf::from(format!("{}-wal", db_path.display()))).unwrap()
            ]
        );
        assert!(
            !shm_path.exists(),
            "inspection must not recreate a missing live SHM file"
        );
        drop(connection);
    }
}
