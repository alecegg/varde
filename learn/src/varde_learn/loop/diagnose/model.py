"""Shared, bounded diagnose report types and harness dispatch contract."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Protocol

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_FAMILY_SOURCE_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 256 * 1024
MAX_RECORDS = 10_000
MAX_PAGE_LIMIT = 1_000
MAX_FAMILY = 32
MAX_DISCOVERY_FILES = 5_000
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
NORMALIZED_RECORD_BUDGET_BYTES = MAX_SNAPSHOT_BYTES - 128 * 1024
SNAPSHOT_SCHEMA_VERSION = 2


def rendered_length_bytes(value: Any) -> int | None:
    """Return the UTF-8 byte length of a value's normalized output rendering."""
    if value is None:
        return None
    rendered = (
        value
        if isinstance(value, str)
        else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    )
    return len(rendered.encode("utf-8"))


class DiagnosticHarness(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    OPENCODE = "opencode"
    PI = "pi"


class CurrentOverlap(StrEnum):
    CURRENT = "current"
    NOT_CURRENT = "not_current"
    UNKNOWN = "unknown"


@dataclass
class GitMetadata:
    commit_hash: str | None = None
    branch: str | None = None
    repository_url: str | None = None


@dataclass
class SessionMetadata:
    harness: str
    thread_id: str
    session_id: str | None
    parent_thread_id: str | None
    parent_provenance: str | None
    started_at: str | None
    cwd: str | None
    cli_version: str | None
    history_mode: str | None
    git: GitMetadata | None
    source_id: str
    transcript_id: str | None = None
    project_namespace: str | None = None
    current_directory: str | None = None


@dataclass
class SourceSnapshot:
    source_id: str
    canonical_path: str
    device: int | None = None
    inode: int | None = None
    length: int | None = None
    modified_ns: int | None = None
    digest: str | None = None
    companions: list[SourceCompanion] = field(default_factory=list)
    session_thread_id: str | None = None
    transcript_id: str | None = None


@dataclass
class SourceCompanion:
    path: str
    present: bool
    device: int | None = None
    inode: int | None = None
    length: int | None = None
    modified_ns: int | None = None
    digest: str | None = None


@dataclass
class RecordAnchor:
    source_id: str
    record_index: int
    byte_start: int
    byte_end: int
    record_digest: str
    native_id: str | None
    session_id: str | None = None
    storage_sequence: int | None = None
    context_digest: str | None = None


@dataclass
class ToolObservation:
    block_type: str
    tool_use_id: str | None = None
    tool_name: str | None = None
    input_excerpt: str | None = None
    output_excerpt: str | None = None
    status: str | None = None
    error: str | None = None
    detail_truncated: bool = False
    output_length_bytes: int | None = None


@dataclass
class EvidenceRecord:
    session_thread_id: str
    anchor: RecordAnchor
    timestamp: str | None = None
    kind: str = ""
    role: str | None = None
    text_excerpt: str | None = None
    tool_name: str | None = None
    tool_input_excerpt: str | None = None
    tool_output_excerpt: str | None = None
    tool_output_length_bytes: int | None = None
    tool_status: str | None = None
    tool_error: str | None = None
    tool_observations: list[ToolObservation] = field(default_factory=list)
    detail_truncated: bool = False
    unknown_payload_excerpt: str | None = None
    turn_id: str | None = None
    response_id: str | None = None
    cwd: str | None = None
    git_head: str | None = None
    failure_reason: str | None = None
    compacted_before_tokens: int | None = None
    usage_total: Any = None
    usage_last: Any = None
    usage_record: Any = None
    transcript_id: str | None = None
    provider_message_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    parent_native_id: str | None = None
    branch_from_id: str | None = None
    tool_use_id: str | None = None
    parent_tool_use_id: str | None = None
    is_sidechain: bool | None = None
    is_meta: bool | None = None
    is_compact_summary: bool | None = None
    timestamp_raw: Any = None
    session_location: str | None = None
    location_provenance: str | None = None


@dataclass
class ChildSession:
    thread_id: str
    source_id: str
    parent_thread_id: str | None
    started_at: str | None
    relationship_evidence: str
    transcript_id: str | None = None
    agent_id: str | None = None
    parent_agent_id: str | None = None
    parent_tool_use_id: str | None = None
    fork_session_id: str | None = None
    fork_boundary: Any = None


@dataclass
class Coverage:
    complete: bool
    source_complete: bool
    analysis_ready: bool
    cutoff_verified: bool
    cutoff_anchor: RecordAnchor | None
    incomplete_tail: bool
    truncated: bool
    record_count: int
    malformed_records: int
    omitted_records: int
    unknown_events: int = 0
    inherited_events: int = 0
    warnings: list[str] = field(default_factory=list)
    skipped_records: int = 0


@dataclass
class SnapshotIdentity:
    digest: str


@dataclass
class InspectionSnapshot:
    schema_version: int
    digest: str
    session: SessionMetadata
    children: list[ChildSession]
    sources: list[SourceSnapshot]
    records: list[EvidenceRecord]
    overlap: CurrentOverlap
    coverage: Coverage
    redacted: int = 0
    usage_records: list[EvidenceRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return _without_none(asdict(self))


@dataclass
class Inspection:
    session: SessionMetadata
    children: list[ChildSession]
    sources: list[SourceSnapshot]
    records: list[EvidenceRecord]
    overlap: CurrentOverlap
    coverage: Coverage
    snapshot: SnapshotIdentity
    redacted: int = 0
    usage_records: list[EvidenceRecord] = field(default_factory=list)


@dataclass
class NormalizedRecordBudget:
    used_bytes: int = 0

    def try_add(self, record: Any) -> bool:
        size = _serialized_size(record)
        if (
            size is None
            or size > MAX_RECORD_BYTES
            or self.used_bytes + size > NORMALIZED_RECORD_BUDGET_BYTES
        ):
            return False
        self.used_bytes += size
        return True

    def try_replace(self, old: Any, new: Any) -> bool:
        old_size, new_size = _serialized_size(old), _serialized_size(new)
        if old_size is None or new_size is None or new_size > MAX_RECORD_BYTES:
            return False
        next_size = max(0, self.used_bytes - old_size) + new_size
        if next_size > NORMALIZED_RECORD_BUDGET_BYTES:
            return False
        self.used_bytes = next_size
        return True


def _serialized_size(value: Any) -> int | None:
    try:
        return len(
            json.dumps(
                value, default=_json_default, separators=(",", ":"), ensure_ascii=False
            ).encode()
        )
    except TypeError, ValueError:
        return None


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(type(value).__name__)


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None and item != []
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    if isinstance(value, StrEnum):
        return value.value
    return value


class HarnessAdapter(Protocol):
    """Dispatch seam implemented by provider-specific diagnose adapters."""

    harness: DiagnosticHarness

    def discover(
        self, *, repo: Any, roots: dict[str, Any], limit: int
    ) -> list[Any]: ...

    def inspect(self, request: Any) -> Inspection: ...


HARNESS_ADAPTERS: dict[DiagnosticHarness, HarnessAdapter] = {}


def register_harness(adapter: HarnessAdapter) -> None:
    HARNESS_ADAPTERS[DiagnosticHarness(adapter.harness)] = adapter


def harness_adapter(harness: DiagnosticHarness | str) -> HarnessAdapter:
    selected = DiagnosticHarness(harness)
    if selected not in HARNESS_ADAPTERS:
        if selected is DiagnosticHarness.CODEX:
            from . import codex as codex
        elif selected is DiagnosticHarness.CLAUDE:
            from . import claude as claude
        elif selected is DiagnosticHarness.PI:
            from . import pi as pi
        else:
            from . import opencode as opencode
    return HARNESS_ADAPTERS[selected]
