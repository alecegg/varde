from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.loop.diagnose.codex import (
    discover_descendants,
    event_kind,
    inspect_id,
    inspect_path,
    parse_header,
    parse_source,
    scan_sessions,
)
from varde_learn.loop.diagnose.codex.discovery import Header, read_header
from varde_learn.loop.diagnose.codex.events import normalize_record
from varde_learn.loop.diagnose.model import (
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    NORMALIZED_RECORD_BUDGET_BYTES,
    NormalizedRecordBudget,
    RecordAnchor,
)
from varde_learn.loop.errors import Diagnose


def test_codex_normalizer_records_uncut_tool_output_length():
    record = normalize_record(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call_output",
                "output": "x" * 5_000,
            },
        },
        RecordAnchor("source", 0, 0, 1, "digest", "native"),
        "thread",
    )
    assert record.tool_output_length_bytes == 5_000
    assert record.tool_output_excerpt is not None
    assert len(record.tool_output_excerpt) == 1025


def _rollout(
    path: Path, version: str, *, padding: int = 0, body_padding: int = 0
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "type": "session_meta",
        "payload": {"id": "thread", "cli_version": version, "padding": "x" * padding},
    }
    event = {
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "assistant",
            "content": [],
            "padding": "x" * body_padding,
        },
    }
    path.write_text(json.dumps(header) + "\n" + json.dumps(event) + "\n")


def test_codex_162_1_inspects_by_id_and_path(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-test.jsonl"
    _rollout(path, "0.162.1")
    by_id = inspect_id(tmp_path, "thread")
    by_path = inspect_path(tmp_path, path)
    assert by_id.schema_version == 2
    assert by_path.schema_version == 2
    assert by_id.session.cli_version == "0.162.1"
    assert by_path.session.cli_version == "0.162.1"


def test_empty_rollout_does_not_make_discovery_uncertain(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions" / "2026" / "08" / "22"
    empty = sessions / "rollout-empty.jsonl"
    empty.parent.mkdir(parents=True)
    empty.touch()
    valid = sessions / "rollout-valid.jsonl"
    _rollout(valid, "0.162.1")

    discovery = scan_sessions(tmp_path)

    assert discovery.uncertain is False
    assert [path for path, _header in discovery.sessions] == [valid]
    assert inspect_id(tmp_path, "thread").session.cli_version == "0.162.1"


@pytest.mark.parametrize(
    "version", ["0.165.0-alpha.3", "0.155.1-rc1", "0.162.0-alpha.17.2"]
)
def test_codex_verified_version_forms_are_accepted(version: str) -> None:
    header = parse_header(
        {
            "type": "session_meta",
            "payload": {"id": "thread", "cli_version": version},
        }
    )
    assert header.session.cli_version == version


@pytest.mark.parametrize("version", ["0.162.0", "0.162.1-rc1"])
def test_codex_unverified_version_forms_are_rejected(version: str) -> None:
    with pytest.raises(Diagnose) as error:
        parse_header(
            {
                "type": "session_meta",
                "payload": {"id": "thread", "cli_version": version},
            }
        )
    assert error.value.code == "diagnose_codex_version_unsupported"


def test_inspect_path_rejects_unverified_version(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-test.jsonl"
    _rollout(path, "0.190.0")
    with pytest.raises(Diagnose) as error:
        inspect_path(tmp_path, path)
    assert error.value.code == "diagnose_codex_version_unsupported"
    assert "Varde cannot read this file" in str(error.value)


def test_unverified_large_rollout_reports_version_not_header_limit(
    tmp_path: Path,
) -> None:
    path = tmp_path / "sessions" / "rollout-test.jsonl"
    _rollout(path, "0.190.0", body_padding=MAX_RECORD_BYTES + 1024)
    with pytest.raises(Diagnose, match="0.190.0"):
        inspect_id(tmp_path, "thread")


def test_oversized_header_reports_header_limit(tmp_path: Path) -> None:
    path = tmp_path / "sessions" / "rollout-test.jsonl"
    _rollout(path, "0.162.1", padding=MAX_RECORD_BYTES + 1024)
    with pytest.raises(Diagnose, match="per-file header read limit"):
        inspect_id(tmp_path, "thread")


def test_codex_header_requires_verified_version_and_preserves_parent_provenance() -> (
    None
):
    header = parse_header(
        {
            "type": "session_meta",
            "payload": {
                "id": "thread",
                "cli_version": "0.155.1+local",
                "parent_thread_id": "parent",
                "timestamp": "2026-09-27T10:00:00Z",
            },
        }
    )
    assert header.session.thread_id == "thread"
    assert header.session.parent_thread_id == "parent"
    assert header.session.parent_provenance == "session_meta.parent_thread_id"


def test_codex_event_kind_maps_response_items() -> None:
    assert (
        event_kind({"type": "response_item", "payload": {"type": "function_call"}})
        == "tool_call"
    )
    assert (
        event_kind({"type": "response_item", "payload": {"type": "message"}})
        == "message"
    )


def test_codex_descendants_exclude_ambiguous_identity_but_keep_unique_children() -> (
    None
):
    def header(thread: str, parent: str | None) -> Header:
        session = parse_header(
            {
                "type": "session_meta",
                "payload": {
                    "id": thread,
                    "cli_version": "0.155.1",
                    "parent_thread_id": parent,
                },
            }
        ).session
        return Header(session)

    sessions = [
        (Path("a"), header("dup", "root")),
        (Path("b"), header("dup", "other")),
        (Path("c"), header("unique", "root")),
    ]
    children, ambiguous = discover_descendants("root", sessions)
    assert ambiguous
    assert [child[1].session.thread_id for child in children] == ["unique"]


def test_selected_root_duplicates_in_cycle_keep_explicit_family() -> None:
    def header(thread: str, parent: str | None) -> Header:
        session = parse_header(
            {
                "type": "session_meta",
                "payload": {
                    "id": thread,
                    "cli_version": "0.155.1",
                    "parent_thread_id": parent,
                },
            }
        ).session
        return Header(session)

    sessions = [
        (Path("selected"), header("root", "leaf")),
        (Path("copy"), header("root", None)),
        (Path("leaf"), header("leaf", "root")),
    ]
    children, ambiguous = discover_descendants("root", sessions)
    assert not ambiguous
    assert [child[1].session.thread_id for child in children] == ["leaf"]


def test_nested_ambiguity_keeps_verified_ancestor() -> None:
    def header(thread: str, parent: str | None) -> Header:
        session = parse_header(
            {
                "type": "session_meta",
                "payload": {
                    "id": thread,
                    "cli_version": "0.155.1",
                    "parent_thread_id": parent,
                },
            }
        ).session
        return Header(session)

    sessions = [
        (Path("child"), header("child", "root")),
        (Path("first"), header("duplicate", "child")),
        (Path("second"), header("duplicate", "child")),
    ]
    children, ambiguous = discover_descendants("root", sessions)
    assert ambiguous
    assert [child[1].session.thread_id for child in children] == ["child"]


def test_unrelated_duplicates_do_not_taint_unique_family() -> None:
    def header(thread: str, parent: str | None) -> Header:
        session = parse_header(
            {
                "type": "session_meta",
                "payload": {
                    "id": thread,
                    "cli_version": "0.155.1",
                    "parent_thread_id": parent,
                },
            }
        ).session
        return Header(session)

    sessions = [
        (Path("child"), header("child", "root")),
        (Path("grandchild"), header("grandchild", "child")),
        (Path("first"), header("duplicate", "unrelated")),
        (Path("second"), header("duplicate", "unrelated")),
    ]
    children, ambiguous = discover_descendants("root", sessions)
    assert not ambiguous
    assert [child[1].session.thread_id for child in children] == ["child", "grandchild"]


def test_codex_parse_source_tracks_anchors_and_incomplete_tail(tmp_path: Path) -> None:
    path = tmp_path / "rollout-1.jsonl"
    records = [
        {"type": "session_meta", "payload": {"id": "thread", "cli_version": "0.155.1"}},
        {
            "type": "response_item",
            "timestamp": "2026-09-27T10:00:00Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "hello"}],
            },
        },
    ]
    path.write_bytes(("\n".join(json.dumps(item) for item in records) + "\n{").encode())
    parsed = parse_source(path, 1024 * 1024, 100, NormalizedRecordBudget())
    assert parsed.header.session.thread_id == "thread"
    assert parsed.records[0].text_excerpt == "hello"
    assert parsed.records[0].anchor.record_index == 1
    assert parsed.incomplete_tail
    assert parsed.omitted_records == 2


def test_parsing_charges_inherited_identity_before_retaining_each_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large-inherited-rollout.jsonl"
    values = [
        {
            "type": "session_meta",
            "payload": {"id": "t" * 65_536, "cli_version": "0.155.1"},
        },
        {"type": "turn_context", "payload": {"cwd": "c" * 32_768}},
        *(
            {
                "type": "response_item",
                "timestamp": "2026-09-27T10:00:00Z",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": f"event-{index}"}],
                },
            }
            for index in range(40)
        ),
    ]
    path.write_text("\n".join(json.dumps(value) for value in values) + "\n")
    budget = NormalizedRecordBudget()
    parsed = parse_source(path, MAX_SOURCE_BYTES, MAX_RECORDS, budget)
    assert budget.used_bytes <= NORMALIZED_RECORD_BUDGET_BYTES
    assert len(parsed.records) < 41
    assert parsed.truncated and parsed.omitted_records > 0
    assert all(
        len(record.session_thread_id) == 65_536 and record.cwd == "c" * 32_768
        for record in parsed.records
    )


def test_header_discovery_rejects_header_larger_than_remaining_budget(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large-header.jsonl"
    value = {
        "type": "session_meta",
        "payload": {"id": "thread", "cli_version": "0.155.1", "padding": "x" * 200},
    }
    path.write_text(json.dumps(value) + "\n")
    with pytest.raises(Diagnose, match="byte budget"):
        read_header(path, 128)
