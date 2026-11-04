from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from varde_learn.loop.diagnose import HARNESS_ADAPTERS, DiagnosticHarness, claude
from varde_learn.loop.diagnose.claude import (
    inspect_id,
    inspect_path,
    normalize_record,
)
from varde_learn.loop.diagnose.model import (
    MAX_SNAPSHOT_BYTES,
    NormalizedRecordBudget,
    RecordAnchor,
)


def _write(path: Path, session_id: str, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [{"sessionId": session_id, "cwd": "/fixture"}, *records]
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in lines)
    )


def _record(
    index: int,
    session_id: str,
    *,
    agent: str | None = None,
    tool: bool = False,
    text: str = "small",
) -> dict:
    content = (
        [{"type": "tool_use", "id": "call-1", "name": "Task", "input": {}}]
        if tool
        else [{"type": "text", "text": text}]
    )
    return {
        "type": "assistant",
        "uuid": f"record-{index}",
        "sessionId": session_id,
        "agentId": agent,
        "timestamp": "2026-09-27T10:00:00.000Z",
        "message": {"id": f"message-{index}", "role": "assistant", "content": content},
    }


def test_claude_adapter_registers_and_inspects_records(tmp_path: Path) -> None:
    session_id = "00000000-0000-4000-8000-000000000001"
    path = tmp_path / "projects" / "namespace" / f"{session_id}.jsonl"
    _write(path, session_id, [_record(0, session_id, tool=True)])
    assert DiagnosticHarness.CLAUDE in HARNESS_ADAPTERS
    snapshot = inspect_id(path.parents[1], session_id)
    assert snapshot.schema_version == 2
    assert snapshot.session.thread_id == f"claude:namespace:{session_id}"
    assert snapshot.records[1].kind == "tool_call"
    assert snapshot.records[1].tool_use_id == "call-1"
    assert snapshot.records[1].anchor.record_index == 1


def test_claude_inspection_links_verified_child_transcripts(tmp_path: Path) -> None:
    sid = "session-1"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    child = root / "project" / sid / "subagents" / "agent-child.jsonl"
    _write(main, sid, [_record(0, sid, tool=True)])
    _write(child, sid, [_record(0, sid, agent="child")])
    child.with_suffix(".meta.json").write_text(json.dumps({"toolUseId": "call-1"}))
    snapshot = inspect_path(root, child)
    assert snapshot.children[0].parent_thread_id == snapshot.session.thread_id
    assert (
        not snapshot.coverage.complete
    )  # The fixture header has no UUID, so its identity is incomplete.


def test_claude_normalizes_tool_results_and_bounds_excerpt() -> None:
    value = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call",
                    "content": "x" * 2000,
                    "is_error": True,
                },
            ],
        },
    }
    anchor = RecordAnchor("source", 0, 0, 1, "digest", "uuid")
    record = normalize_record(value, anchor, "thread")
    assert record.kind == "tool_result"
    assert record.tool_status == "error"
    assert record.detail_truncated
    assert record.tool_output_excerpt is not None
    assert len(record.tool_output_excerpt) == 1025
    assert record.tool_output_length_bytes == 2000


def test_claude_rejects_transcripts_outside_projects_root(tmp_path: Path) -> None:
    root = tmp_path / "projects"
    root.mkdir()
    outside = tmp_path / "outside.jsonl"
    _write(outside, "session", [])
    with pytest.raises(ValueError, match="outside"):
        inspect_path(root, outside)


def test_linked_claude_transcripts_share_normalized_record_budget(
    tmp_path: Path,
) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    child = root / "project" / sid / "subagents" / "agent-child.jsonl"
    text = "x" * 2_000
    _write(main, sid, [_record(i, sid, text=text) for i in range(200)])
    _write(child, sid, [_record(i, sid, agent="child", text=text) for i in range(600)])
    child.with_suffix(".meta.json").write_text(json.dumps({"toolUseId": "call-1"}))

    snapshot = inspect_path(root, child)

    budget = NormalizedRecordBudget()
    assert all(budget.try_add(record) for record in snapshot.records)
    assert snapshot.coverage.truncated
    main_records = [
        record
        for record in snapshot.records
        if record.session_thread_id == snapshot.session.thread_id
    ]
    child_records = [
        record
        for record in snapshot.records
        if record.session_thread_id != snapshot.session.thread_id
    ]
    assert len(main_records) == 201  # 200 records plus the transcript header
    assert 0 < len(child_records) < 600
    # Every retained child record carries its inherited child transcript
    # identity and parent tool id, which is what the shared budget charges.
    child_thread = snapshot.children[0].thread_id
    assert all(
        record.session_thread_id == child_thread
        and record.parent_tool_use_id == "call-1"
        for record in child_records
    )


def test_usage_survives_normalized_record_budget_exhaustion(tmp_path: Path) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    filler = [_record(i, sid, text="x" * 4096) for i in range(600)]
    usage = _record(600, sid, text="x" * 4096)
    usage["timestamp"] = "2026-10-20T12:00:00Z"
    usage["message"]["usage"] = {
        "input_tokens": 12,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 4,
        "output_tokens": 5,
    }
    usage["message"]["id"] = "billable-call"
    _write(main, sid, [*filler, usage])

    snapshot = inspect_path(root, main)

    calls = [
        record
        for record in [*snapshot.records, *snapshot.usage_records]
        if record.usage_record
    ]
    assert len(calls) == 1
    assert calls[0].provider_message_id == "billable-call"
    assert calls[0].usage_record == usage["message"]["usage"]
    assert calls[0].detail_truncated
    assert calls[0].text_excerpt is None


def test_usage_after_record_limit_is_retained(tmp_path: Path, monkeypatch) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    usage = _record(1, sid)
    usage["message"]["usage"] = {"input_tokens": 9, "output_tokens": 2}
    monkeypatch.setattr(claude, "MAX_RECORDS", 2)
    _write(main, sid, [_record(0, sid), usage])

    snapshot = inspect_path(root, main)

    calls = [
        record
        for record in [*snapshot.records, *snapshot.usage_records]
        if record.usage_record
    ]
    assert len(calls) == 1
    assert calls[0].usage_record == usage["message"]["usage"]


def test_usage_after_source_byte_limit_is_retained(tmp_path: Path, monkeypatch) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    usage = _record(1, sid)
    usage["message"]["usage"] = {"input_tokens": 11, "output_tokens": 3}
    _write(main, sid, [_record(0, sid), usage])
    monkeypatch.setattr(claude, "MAX_SOURCE_BYTES", 256)

    snapshot = inspect_path(root, main)

    calls = [
        record
        for record in [*snapshot.records, *snapshot.usage_records]
        if record.usage_record
    ]
    assert len(calls) == 1
    assert calls[0].usage_record == usage["message"]["usage"]


def test_duplicate_message_usage_keeps_snapshot_with_max_output() -> None:
    records = [
        normalize_record(
            {
                "type": "assistant",
                "timestamp": f"2026-10-20T12:00:0{index}Z",
                "message": {
                    "id": "same-message",
                    "usage": {"input_tokens": index, "output_tokens": output},
                },
            },
            RecordAnchor("source", index, index, index + 1, f"digest-{index}", None),
            "thread",
            "transcript",
        )
        for index, output in ((1, 8), (2, 4))
    ]

    claude._deduplicate_usage(records, [], None)

    assert records[0].usage_record == {"input_tokens": 1, "output_tokens": 8}
    assert records[1].usage_record is None


def test_usage_supplements_stay_out_of_snapshot_records(tmp_path: Path) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    rows = []
    for number in range(1, 400):
        row = _record(number, sid)
        row["uuid"] = f"00000000-0000-4000-8000-{number:012d}"
        row["message"]["id"] = f"call-{number}"
        row["message"]["usage"] = {"input_tokens": 1, "output_tokens": number}
        row["message"]["content"] = [{"type": "text", "text": "x" * 3000}]
        rows.append(row)
    _write(main, sid, [_record(0, sid), *rows])

    snapshot = inspect_path(root, main)

    stored = len(json.dumps([asdict(record) for record in snapshot.records]))
    assert stored <= MAX_SNAPSHOT_BYTES
    counted = [
        r for r in [*snapshot.records, *snapshot.usage_records] if r.usage_record
    ]
    assert len(counted) == 399


def test_usage_records_without_ids_are_each_counted(
    tmp_path: Path, monkeypatch
) -> None:
    sid = "00000000-0000-4000-8000-000000000001"
    root = tmp_path / "projects"
    main = root / "project" / f"{sid}.jsonl"
    rows = []
    for number in range(1, 4):
        row = _record(number, sid)
        row.pop("uuid", None)
        row["message"].pop("id", None)
        row["message"]["usage"] = {"input_tokens": number, "output_tokens": 1}
        rows.append(row)
    monkeypatch.setattr(claude, "MAX_SOURCE_BYTES", 256)
    _write(main, sid, [_record(0, sid), *rows])

    snapshot = inspect_path(root, main)

    counted = [
        r for r in [*snapshot.records, *snapshot.usage_records] if r.usage_record
    ]
    assert len(counted) == 3
