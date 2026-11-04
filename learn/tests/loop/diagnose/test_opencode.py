from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from varde_learn.loop.diagnose.model import (
    MAX_RECORDS,
    MAX_SOURCE_BYTES,
    NormalizedRecordBudget,
    RecordAnchor,
)
from varde_learn.loop.diagnose.opencode import (
    OPENCODE_VERSION,
    _normalize_message,
    discover_sessions,
    inspect_path,
)
from varde_learn.loop.errors import Diagnose


def test_opencode_normalizer_records_uncut_tool_output_length():
    record = _normalize_message(
        {
            "type": "assistant",
            "content": [{"type": "tool", "state": {"content": "x" * 5_000}}],
        },
        RecordAnchor("source", 0, 0, 1, "digest", "native"),
        "session",
    )
    assert record.tool_output_length_bytes is None
    assert record.tool_name is None
    assert record.tool_output_excerpt is None
    assert record.tool_observations[0].output_length_bytes == 5_000
    assert record.tool_observations[0].output_excerpt is not None
    assert len(record.tool_observations[0].output_excerpt) == 4096


def _database(
    path: Path, sessions: list[tuple[str, str, str, int]], messages=()
) -> None:
    db = sqlite3.connect(path)
    session_columns = (
        "id,project_id,workspace_id,parent_id,fork_session_id,fork_boundary,slug,"
        "directory,path,title,version,share_url,summary_additions,summary_deletions,"
        "summary_files,summary_diffs,metadata,cost,tokens_input,tokens_output,"
        "tokens_reasoning,tokens_cache_read,tokens_cache_write,revert,permission,"
        "agent,model,time_created,time_updated,time_idle,time_viewed,idle_outcome,"
        "time_compacting,time_archived,time_suspended,resume_attempts"
    )
    session_schema = (
        "CREATE TABLE session_v2 (id TEXT,project_id TEXT,workspace_id TEXT,"
        "parent_id TEXT,fork_session_id TEXT,fork_boundary TEXT,slug TEXT,"
        "directory TEXT,path TEXT,title TEXT,version TEXT,share_url TEXT,"
        "summary_additions INTEGER,summary_deletions INTEGER,summary_files TEXT,"
        "summary_diffs TEXT,metadata TEXT,cost REAL,tokens_input INTEGER,"
        "tokens_output INTEGER,tokens_reasoning INTEGER,tokens_cache_read INTEGER,"
        "tokens_cache_write INTEGER,revert TEXT,permission TEXT,agent TEXT,"
        "model TEXT,time_created INTEGER,time_updated INTEGER,time_idle INTEGER,"
        "time_viewed INTEGER,idle_outcome TEXT,time_compacting INTEGER,"
        "time_archived INTEGER,time_suspended INTEGER,resume_attempts INTEGER)"
    )
    db.execute(session_schema)
    message_schema = (
        "CREATE TABLE session_message (id TEXT,session_id TEXT,type TEXT,"
        "seq INTEGER,time_created INTEGER,time_updated INTEGER,data TEXT)"
    )
    db.execute(message_schema)
    for sid, cwd, version, created in sessions:
        values = [
            sid,
            "project",
            None,
            None,
            None,
            None,
            None,
            cwd,
            None,
            None,
            version,
            None,
            0,
            0,
            None,
            None,
            None,
            0,
            0,
            0,
            0,
            0,
            0,
            None,
            None,
            None,
            None,
            created,
            created,
            None,
            None,
            None,
            None,
            None,
            None,
            0,
        ]
        insert_query = (
            f"INSERT INTO session_v2 ({session_columns}) "  # noqa: S608 - Column names come from the fixture schema; values are parameterized.
            f"VALUES ({','.join('?' for _ in values)})"
        )
        db.execute(
            insert_query,
            values,
        )
    for mid, sid, kind, seq, obj in messages:
        db.execute(
            "INSERT INTO session_message VALUES (?,?,?,?,?,?,?)",
            (mid, sid, kind, seq, 1700000000000, 1700000000000, json.dumps(obj)),
        )
    db.commit()
    db.close()


def test_native_inspection_preserves_each_tool_block_and_usage(tmp_path: Path) -> None:
    path = tmp_path / "opencode.db"
    msg = {
        "id": "msg",
        "type": "assistant",
        "content": [
            {
                "type": "tool",
                "id": "first",
                "name": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "true"},
                    "content": [{"type": "text", "text": "successful output"}],
                },
            },
            {
                "type": "tool",
                "id": "second",
                "name": "bash",
                "state": {
                    "status": "error",
                    "input": {"command": "false"},
                    "error": {"message": "second failure"},
                },
            },
        ],
        "time": {"created": 1700000000000},
        "tokens": {
            "input": 10,
            "output": 3,
            "reasoning": 2,
            "cache": {"read": 7, "write": 4},
        },
    }
    _database(
        path,
        [("ses", str(tmp_path), OPENCODE_VERSION, 1700000000000)],
        [("msg", "ses", "assistant", 1, msg)],
    )
    result = inspect_path(path, "ses")
    assert result.schema_version == 2
    record = result.records[0]
    assert [item.tool_use_id for item in record.tool_observations] == [
        "first",
        "second",
    ]
    assert record.tool_observations[0].output_excerpt is not None
    assert "successful output" in record.tool_observations[0].output_excerpt
    assert record.tool_observations[1].error is not None
    assert "second failure" in record.tool_observations[1].error
    assert record.usage_record["total_tokens"] == 26
    assert result.session.cli_version == OPENCODE_VERSION


def test_native_inspection_requires_session_when_database_is_ambiguous(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opencode.db"
    _database(
        path,
        [
            ("one", str(tmp_path), OPENCODE_VERSION, 1),
            ("two", str(tmp_path), OPENCODE_VERSION, 2),
        ],
    )
    with pytest.raises(Diagnose, match="multiple sessions"):
        inspect_path(path)


def test_native_inspection_reads_database_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "opencode.db"
    _database(path, [("one", str(tmp_path), OPENCODE_VERSION, 1)])
    before = path.read_bytes()
    inspect_path(path, "one")
    assert path.read_bytes() == before


def test_native_inspection_streams_large_database_without_read_bytes(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "opencode.db"
    _database(path, [("one", str(tmp_path), OPENCODE_VERSION, 1)])
    with path.open("ab") as database:
        database.write(b" " * (MAX_SOURCE_BYTES + 1))
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: pytest.fail("SQLite inspection must not call read_bytes"),
    )

    result = inspect_path(path, "one")

    assert result.session.session_id == "one"
    assert result.coverage.complete
    assert result.sources[0].length == path.stat().st_size


def test_oversized_export_returns_incomplete_snapshot(
    tmp_path: Path,
) -> None:
    path = tmp_path / "large-export.json"
    path.write_text(
        json.dumps({"info": {"id": "large"}, "padding": "x" * MAX_SOURCE_BYTES})
    )

    result = inspect_path(path)

    assert result.session.session_id == "large-export"
    assert not result.coverage.complete
    assert result.coverage.incomplete_tail
    assert result.coverage.warnings
    assert result.sources[0].length == path.stat().st_size


def test_json_export_read_error_is_reported_as_diagnose(
    tmp_path: Path, monkeypatch
) -> None:
    path = tmp_path / "export.json"
    path.write_text(json.dumps({"messages": []}))
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: (_ for _ in ()).throw(OSError("read denied")),
    )

    with pytest.raises(Diagnose, match="cannot read OpenCode path"):
        inspect_path(path)


def test_export_bounds_retained_records_and_keeps_original_indexes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "export.json"
    messages = [
        {
            "id": f"m{i}",
            "type": "assistant",
            "text": "small",
            "time": {"created": "2026-09-27T10:00:00Z"},
        }
        for i in range(MAX_RECORDS + 2)
    ]
    path.write_text(json.dumps({"info": {"id": "s" * 512}, "messages": messages}))
    result = inspect_path(path)
    assert result.coverage.truncated
    assert (
        result.coverage.omitted_records > 0
        or result.coverage.record_count == MAX_RECORDS
    )
    assert all(record.session_thread_id == "s" * 512 for record in result.records)
    assert result.records[-1].anchor.record_index < len(messages)


def test_discovery_filters_repo_and_marks_parent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = tmp_path / "opencode.db"
    _database(
        path,
        [
            ("inside", str(repo), OPENCODE_VERSION, 10),
            ("outside", str(tmp_path), OPENCODE_VERSION, 11),
        ],
    )
    sessions = discover_sessions(path, repo)
    assert [item.session_id for item in sessions] == ["inside"]


def test_native_location_backfill_recharges_shared_record_budget(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opencode.db"
    messages = [
        (
            f"msg-{index}",
            "session",
            "assistant",
            index,
            {
                "id": f"msg-{index}",
                "type": "assistant",
                "text": "small",
                "time": {"created": 1_700_000_000_000 + index},
            },
        )
        for index in range(1, 26)
    ]
    messages.append(
        (
            "location-switch",
            "session",
            "location-switched",
            26,
            {
                "id": "location-switch",
                "type": "location-switched",
                "previous": {"location": {"directory": "p" * 100_000}},
                "location": {"directory": "/fixture/new"},
                "time": {"created": 1_700_000_000_100},
            },
        )
    )
    _database(
        path,
        [("session", str(tmp_path), OPENCODE_VERSION, 1_700_000_000_000)],
        messages,
    )
    result = inspect_path(path, "session")
    backfilled = [
        record for record in result.records if record.session_location == "p" * 100_000
    ]
    budget = NormalizedRecordBudget()
    assert all(budget.try_add(record) for record in result.records)
    assert 0 < len(backfilled) < 25
    assert result.records[-1].session_location == "/fixture/new"
    assert result.coverage.truncated


def test_conflicting_location_switch_history_uses_latest_directory(
    tmp_path: Path,
) -> None:
    path = tmp_path / "opencode.db"
    messages = [
        (
            "first-switch",
            "session",
            "location-switched",
            1,
            {
                "id": "first-switch",
                "type": "location-switched",
                "previous": {"location": {"directory": "/before"}},
                "location": {"directory": "/current"},
                "time": {"created": 1_700_000_000_000},
            },
        ),
        (
            "conflicting-switch",
            "session",
            "location-switched",
            2,
            {
                "id": "conflicting-switch",
                "type": "location-switched",
                "previous": {"location": {"directory": "/unexpected"}},
                "location": {"directory": "/latest"},
                "time": {"created": 1_700_000_000_001},
            },
        ),
        (
            "after-switch",
            "session",
            "assistant",
            3,
            {
                "id": "after-switch",
                "type": "assistant",
                "text": "after",
                "time": {"created": 1_700_000_000_002},
            },
        ),
    ]
    _database(
        path,
        [("session", str(tmp_path), OPENCODE_VERSION, 1_700_000_000_000)],
        messages,
    )
    result = inspect_path(path, "session")
    assert any(
        "location-switch history has conflicting previous.location evidence" in warning
        for warning in result.coverage.warnings
    )
    assert [record.session_location for record in result.records] == [
        "/current",
        "/latest",
        "/latest",
    ]
