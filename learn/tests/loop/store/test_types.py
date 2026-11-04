from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from varde_learn.loop.errors import Diagnose, StoreInvalid
from varde_learn.loop.store.types import (
    FrictionIncidentProvenance,
    FrictionStatus,
    HistoricalOccurrenceRequest,
    HistoricalWitness,
    PageRequest,
    StorePage,
    incident_conflict,
    incident_key,
    legacy_incident_key,
    normalize_scope_path,
    provenance_for,
    repository_context,
    sha256_digest,
    validate_page,
    validate_provenance,
    validate_witness,
)


def witness(**changes: object) -> HistoricalWitness:
    values: dict[str, object] = {
        "harness": "codex",
        "thread_id": "thread-1",
        "incident_kind": "failed-tool",
        "witness_id": None,
        "source_id": "source-1",
        "record_index": 2,
        "byte_start": 10,
        "byte_end": 20,
        "record_digest": sha256_digest(b"record"),
    }
    values.update(changes)
    return HistoricalWitness(**values)  # type: ignore[arg-type]


def test_friction_status_parse_is_case_insensitive() -> None:
    assert FrictionStatus.parse("OPEN") is FrictionStatus.OPEN
    assert FrictionStatus.parse("resolved") is FrictionStatus.RESOLVED
    assert FrictionStatus.parse("unknown") is None


def test_store_page_computes_next_offset_only_when_truncated() -> None:
    assert StorePage.new(["a", "b"], 6, PageRequest(offset=3, limit=2)).next_offset == 5
    assert not StorePage.new(["a"], 1, PageRequest()).truncated


@pytest.mark.parametrize(
    "page", [PageRequest(limit=0), PageRequest(limit=1001), PageRequest(offset=-1)]
)
def test_validate_page_rejects_out_of_range_values(page: PageRequest) -> None:
    with pytest.raises(StoreInvalid):
        validate_page(page)


def test_validate_page_returns_sqlite_values() -> None:
    assert validate_page(PageRequest(offset=8, limit=12)) == (12, 8)


def test_witness_and_provenance_validation_and_legacy_key() -> None:
    item = witness()
    validate_witness(item)
    current = incident_key(item)
    assert current.startswith("incident-v1:")
    assert legacy_incident_key(item) != current
    payload = FrictionIncidentProvenance(
        legacy_incident_key(item),
        1,
        item.harness,
        item.thread_id,
        item.incident_kind,
        item.witness_id,
        item.source_id,
        item.record_index,
        item.byte_start,
        item.byte_end,
        item.record_digest,
        sha256_digest(b"facts"),
    )
    validate_provenance(payload)
    with pytest.raises(StoreInvalid, match="source anchor"):
        validate_witness(witness(byte_end=9))


def test_native_witness_identity_uses_native_id() -> None:
    one = witness(witness_id="event-a", byte_start=10, byte_end=20)
    other_anchor = witness(witness_id="event-a", byte_start=100, byte_end=200)
    assert incident_key(one) == incident_key(other_anchor)


def test_provenance_for_hashes_sorted_canonical_json() -> None:
    source = witness()
    request = HistoricalOccurrenceRequest(
        "2026-10-14T12:00:00Z",
        "/repo",
        "/repo",
        "abc",
        "evidence",
        {"event": {"z": 1, "a": "é"}, "context": {}},
        source,
    )
    provenance = provenance_for(request)
    # Canonical payload spelled out independently of the implementation: sorted
    # keys, no whitespace, UTF-8 (é left unescaped). Stored provenance rows are
    # deduplicated by this digest, so the canonical form must not drift.
    canonical = (
        '{"at":"2026-10-14T12:00:00Z","cwd":"/repo",'
        '"facts":{"context":{},"event":{"a":"é","z":1}},'
        '"head_sha":"abc","repo_root":"/repo","version":1}'
    )
    assert (
        provenance.payload_digest
        == "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
    )
    validate_provenance(provenance)


def test_provenance_for_rejects_invalid_facts() -> None:
    request = HistoricalOccurrenceRequest(
        "at", "/repo", None, None, "evidence", {"event": []}, witness()
    )
    with pytest.raises(StoreInvalid, match="canonical historical facts"):
        provenance_for(request)


def test_incident_conflict_has_stable_diagnose_code() -> None:
    error = incident_conflict("incident-v1:abc")
    assert isinstance(error, Diagnose)
    assert error.code == "diagnose_incident_conflict"


def test_repository_context_returns_root_and_head(tmp_path: Path) -> None:
    context = repository_context(tmp_path)
    assert context.repo_root is None
    assert context.head_sha is None


def test_normalize_scope_path_handles_existing_and_missing_paths(
    tmp_path: Path,
) -> None:
    (tmp_path / "existing").mkdir()
    assert normalize_scope_path(Path("existing/.."), tmp_path) == tmp_path.resolve()
    assert (
        normalize_scope_path(Path("missing/../future"), tmp_path) == tmp_path / "future"
    )
