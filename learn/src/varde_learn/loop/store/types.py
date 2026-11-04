"""Friction store data types and validation helpers."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from enum import StrEnum
from pathlib import Path
from typing import Any, TypeVar

from ..errors import Diagnose, StoreGitCheck, StoreInvalid

DEFAULT_PAGE_LIMIT = 100
MAX_PAGE_LIMIT = 1_000
HISTORICAL_IDENTITY_VERSION = 1
MAX_HISTORICAL_FACTS_BYTES = 1_048_576
T = TypeVar("T")


class FrictionStatus(StrEnum):
    OPEN = "open"
    RESOLVED = "resolved"
    PROMOTED = "promoted"
    ARCHIVED = "archived"

    def as_str(self) -> str:
        return self.value

    @classmethod
    def parse(cls, value: str) -> FrictionStatus | None:
        try:
            return cls(value.lower())
        except ValueError:
            return None


@dataclass
class FrictionItem:
    id: int
    slug: str
    title: str
    source: str
    repo_root: str | None
    status: str
    target: str | None
    created_at: str
    tags: list[str] = dataclass_field(default_factory=list)


@dataclass
class StorePage[T]:
    items: list[T]
    total: int
    offset: int
    limit: int
    truncated: bool
    next_offset: int | None

    @classmethod
    def new(cls, items: list[T], total: int, page: PageRequest) -> StorePage[T]:
        next_offset = page.offset + len(items)
        if next_offset >= total or next_offset > (1 << 64) - 1:
            next_offset = None
        return cls(
            items, total, page.offset, page.limit, next_offset is not None, next_offset
        )


@dataclass(frozen=True)
class PageRequest:
    offset: int = 0
    limit: int = DEFAULT_PAGE_LIMIT


@dataclass
class FrictionListRequest:
    status: FrictionStatus | None
    source: str | None
    repo_root: Path | None
    global_: bool
    text: str | None
    cwd: Path
    page: PageRequest
    tag: str | None = None


@dataclass
class FrictionIncidentProvenance:
    incident_key: str
    identity_version: int
    harness: str
    thread_id: str
    incident_kind: str
    witness_id: str | None
    source_id: str
    record_index: int
    byte_start: int
    byte_end: int
    record_digest: str
    payload_digest: str


@dataclass
class FrictionOccurrence:
    id: int
    item_id: int
    at: str
    cwd: str
    repo_root: str | None
    head_sha: str | None
    evidence: str
    cost: str | None
    provenance: FrictionIncidentProvenance | None = None


@dataclass
class HistoricalWitness:
    harness: str
    thread_id: str
    incident_kind: str
    witness_id: str | None
    source_id: str
    record_index: int
    byte_start: int
    byte_end: int
    record_digest: str


@dataclass
class HistoricalItemMode:
    kind: str
    item_id: int | None = None
    source: str | None = None
    title: str | None = None
    target: str | None = None
    repo_root: str | None = None

    @classmethod
    def append(cls, item_id: int) -> HistoricalItemMode:
        return cls("append", item_id=item_id)

    @classmethod
    def create(
        cls, source: str, title: str, target: str | None, repo_root: str | None
    ) -> HistoricalItemMode:
        return cls(
            "create", source=source, title=title, target=target, repo_root=repo_root
        )


@dataclass
class HistoricalOccurrenceRequest:
    at: str
    cwd: str
    repo_root: str | None
    head_sha: str | None
    evidence: str
    canonical_facts: dict[str, Any]
    witness: HistoricalWitness


@dataclass
class HistoricalCaptureRequest:
    mode: HistoricalItemMode
    occurrence: HistoricalOccurrenceRequest


@dataclass
class HistoricalCaptureResult:
    item: FrictionItem
    occurrence: FrictionOccurrence
    created: bool


@dataclass
class FrictionStatusChange:
    id: int
    item_id: int
    at: str
    from_status: str
    to_status: str
    reason: str


@dataclass
class FrictionRecurrence:
    adoption_id: int
    adoption_at: str
    summary: str
    item: FrictionItem
    occurrence: FrictionOccurrence


@dataclass
class FrictionRecurrenceReport:
    page: StorePage[FrictionRecurrence]
    skipped_invalid_timestamps: int


@dataclass
class FrictionShow:
    item: FrictionItem
    occurrences: StorePage[FrictionOccurrence]
    status_changes: StorePage[FrictionStatusChange]


@dataclass
class FrictionExportItem:
    item: FrictionItem
    occurrences: list[FrictionOccurrence]
    status_changes: list[FrictionStatusChange]


@dataclass
class FrictionAddMode:
    kind: str
    source: str | None = None
    title: str | None = None
    target: str | None = None
    global_: bool = False
    item_id: int | None = None

    @classmethod
    def create(
        cls, source: str, title: str, target: str | None, global_: bool
    ) -> FrictionAddMode:
        return cls("create", source=source, title=title, target=target, global_=global_)

    @classmethod
    def append(cls, item_id: int) -> FrictionAddMode:
        return cls("append", item_id=item_id)


@dataclass
class FrictionAddRequest:
    mode: FrictionAddMode
    evidence: str
    cwd: Path
    tags: list[str] = dataclass_field(default_factory=list)


@dataclass
class AdoptionRecordRequest:
    item_ids: list[int]
    summary: str
    files: list[str]
    commit_sha: str | None
    eval_before: str | None
    eval_after: str | None


@dataclass
class AdoptionRecord:
    id: int
    at: str
    summary: str
    files: list[str]
    commit_sha: str | None
    eval_before: str | None
    eval_after: str | None
    item_ids: list[int]


@dataclass
class RepositoryContext:
    repo_root: str | None = None
    head_sha: str | None = None


def repository_context(cwd: Path) -> RepositoryContext:
    try:
        root = subprocess.run(  # noqa: S603 - Runs a fixed Git repository-root query.
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH.
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise StoreGitCheck(cwd, str(error)) from error
    if root.returncode:
        if "not a git repository" in root.stderr:
            return RepositoryContext()
        raise StoreGitCheck(cwd, root.stderr)
    try:
        head = subprocess.run(  # noqa: S603 - Reads the repository's current commit with fixed Git argv.
            ["git", "-C", str(cwd), "rev-parse", "--verify", "HEAD"],  # noqa: S607 - Git is resolved from PATH.
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as error:
        raise StoreGitCheck(cwd, str(error)) from error
    return RepositoryContext(
        root.stdout.strip(), head.stdout.strip() if head.returncode == 0 else None
    )


def require_nonblank(value: str, field: str) -> None:
    if not value.strip():
        raise invalid_store_input(f"{field} must not be blank")


def invalid_store_input(message: str) -> StoreInvalid:
    return StoreInvalid(message)


def validate_tag(tag: str) -> str:
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,23}", tag):
        raise invalid_store_input(
            f"invalid tag `{tag}`; use a lowercase slug (1-24 letters, digits, or "
            "hyphens)"
        )
    return tag


def incident_conflict(key: str) -> Diagnose:
    return Diagnose(
        "diagnose_incident_conflict",
        f"historical incident `{key}` already exists with different or imported "
        "evidence",
    )


def provenance_for(
    occurrence: HistoricalOccurrenceRequest,
) -> FrictionIncidentProvenance:
    witness = occurrence.witness
    validate_witness(witness)
    for value, field in (
        (occurrence.at, "historical time"),
        (occurrence.cwd, "historical cwd"),
        (occurrence.evidence, "evidence"),
    ):
        require_nonblank(value, field)
    facts = occurrence.canonical_facts
    if (
        not isinstance(facts, dict)
        or "event" not in facts
        or set(facts) - {"event", "context"}
        or not isinstance(facts["event"], dict)
        or ("context" in facts and not isinstance(facts["context"], dict))
    ):
        raise invalid_store_input(
            "canonical historical facts must contain only parsed event and "
            "historical context objects"
        )
    payload = {
        "version": HISTORICAL_IDENTITY_VERSION,
        "at": occurrence.at,
        "cwd": occurrence.cwd,
        "repo_root": occurrence.repo_root,
        "head_sha": occurrence.head_sha,
        "facts": facts,
    }
    try:
        payload_bytes = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise invalid_store_input(f"cannot encode canonical facts: {error}") from error
    if len(payload_bytes) > MAX_HISTORICAL_FACTS_BYTES:
        raise invalid_store_input(
            "canonical historical facts exceed the supported size"
        )
    return FrictionIncidentProvenance(
        incident_key(witness),
        HISTORICAL_IDENTITY_VERSION,
        witness.harness,
        witness.thread_id,
        witness.incident_kind,
        witness.witness_id,
        witness.source_id,
        witness.record_index,
        witness.byte_start,
        witness.byte_end,
        witness.record_digest,
        sha256_digest(payload_bytes),
    )


def validate_witness(witness: HistoricalWitness) -> None:
    for value, field in (
        (witness.harness, "harness"),
        (witness.thread_id, "thread ID"),
        (witness.incident_kind, "incident kind"),
        (witness.source_id, "source ID"),
    ):
        require_nonblank(value, field)
        if len(value.encode()) > 4096 or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 for char in value
        ):
            raise invalid_store_input(f"{field} exceeds its supported format")
    if witness.harness not in {"codex", "claude", "opencode"}:
        raise invalid_store_input("unsupported historical harness")
    if witness.incident_kind not in {
        "failed-tool",
        "repeated-work",
        "workflow-deviation",
    }:
        raise invalid_store_input("unsupported historical incident kind")
    if witness.witness_id is not None:
        require_nonblank(witness.witness_id, "witness ID")
        if len(witness.witness_id.encode()) > 4096 or any(
            ord(char) < 32 or 127 <= ord(char) <= 159 for char in witness.witness_id
        ):
            raise invalid_store_input("witness ID exceeds its supported format")
    if (
        witness.byte_end < witness.byte_start
        or max(witness.record_index, witness.byte_start, witness.byte_end)
        > (1 << 63) - 1
        or not is_sha256_digest(witness.record_digest)
    ):
        raise invalid_store_input("historical source anchor is invalid")


def validate_provenance(provenance: FrictionIncidentProvenance) -> None:
    if provenance.identity_version != HISTORICAL_IDENTITY_VERSION:
        raise invalid_store_input(
            f"unsupported incident identity version `{provenance.identity_version}`"
        )
    witness = HistoricalWitness(
        provenance.harness,
        provenance.thread_id,
        provenance.incident_kind,
        provenance.witness_id,
        provenance.source_id,
        provenance.record_index,
        provenance.byte_start,
        provenance.byte_end,
        provenance.record_digest,
    )
    validate_witness(witness)
    if (
        provenance.incident_key != incident_key(witness)
        and (
            witness.witness_id is not None
            or provenance.incident_key != legacy_incident_key(witness)
        )
    ) or not is_sha256_digest(provenance.payload_digest):
        raise invalid_store_input(
            "incident provenance key or payload digest is invalid"
        )


def incident_key(witness: HistoricalWitness) -> str:
    event = (
        {"native_id": witness.witness_id}
        if witness.witness_id is not None
        else {
            "record_index": witness.record_index,
            "record_digest": witness.record_digest,
        }
    )
    material = {
        "identity_version": HISTORICAL_IDENTITY_VERSION,
        "harness": witness.harness,
        "thread_id": witness.thread_id,
        "incident_kind": witness.incident_kind,
        "event": event,
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"incident-v1:{sha256_hex(encoded)}"


def legacy_incident_key(witness: HistoricalWitness) -> str:
    material = {
        "identity_version": HISTORICAL_IDENTITY_VERSION,
        "harness": witness.harness,
        "thread_id": witness.thread_id,
        "incident_kind": witness.incident_kind,
        "event": {
            "record_index": witness.record_index,
            "byte_start": witness.byte_start,
            "byte_end": witness.byte_end,
            "record_digest": witness.record_digest,
        },
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"incident-v1:{sha256_hex(encoded)}"


def is_sha256_digest(value: str) -> bool:
    digest = value[7:] if value.startswith("sha256:") else ""
    return len(digest) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in digest
    )


def sha256_digest(data: bytes) -> str:
    return f"sha256:{sha256_hex(data)}"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def validate_page(page: PageRequest) -> tuple[int, int]:
    if page.limit == 0 or page.limit > MAX_PAGE_LIMIT:
        raise invalid_store_input(f"page limit must be between 1 and {MAX_PAGE_LIMIT}")
    if page.offset < 0 or page.offset > (1 << 63) - 1:
        raise invalid_store_input("page offset exceeds the supported range")
    return page.limit, page.offset


def normalize_scope_path(path: Path, cwd: Path) -> Path:
    absolute = path if path.is_absolute() else cwd / path
    try:
        return absolute.resolve(strict=True)
    except OSError:
        stack: list[str] = []
        for part in absolute.parts:
            if part in ("", ".", "/"):
                continue
            if part == "..":
                if stack:
                    stack.pop()
                continue
            stack.append(part)
        return Path("/" + "/".join(stack))
