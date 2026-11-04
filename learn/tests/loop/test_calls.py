import json
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from varde_data.calls import open_calls
from varde_data.learn_store_mode import (
    StaleGeneration,
    exclusive_store_lock,
    flip_domain_locked,
)
from varde_learn.loop import calls
from varde_learn.loop.calls import BLOCKED, FAILURE
from varde_learn.loop.errors import StoreConfig, StoreIo


def row(ts, command="plan gate", status="success", session: str | None = "s1", **extra):
    return calls.CallRow(
        ts=ts,
        command=command,
        status=status,
        duration_s=0.25,
        session=session,
        **extra,
    )


def test_append_and_read_round_trip_with_private_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    call = row("2026-10-22T10:00:00Z", guardrail="plan-gate")

    assert calls.append_call(call)
    assert calls.read_calls() == [call]
    assert (tmp_path / calls.CALLS_NAME).stat().st_mode & 0o777 == 0o600


def test_arg_round_trips(tmp_path):
    entry = row("2026-10-22T00:00:00+00:00", command="doc how", arg="varde-docs/audit")

    assert calls.append_call(entry, tmp_path)
    assert calls.read_calls_strict(tmp_path) == [entry]


def test_append_restricts_existing_file_mode_and_repairs_tail(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    target = tmp_path / calls.CALLS_NAME
    target.write_text('{"old":true}', encoding="utf-8")
    target.chmod(0o644)

    assert calls.append_call(row("2026-10-22T10:00:00Z"))
    assert target.stat().st_mode & 0o777 == 0o600
    assert len(calls.read_calls(tmp_path)) == 1


def test_append_call_returns_false_when_store_is_unconfigured(monkeypatch):
    def unavailable():
        raise StoreConfig(Path("config.toml"), "bad")

    monkeypatch.setattr(calls, "resolve_store_dir", unavailable)

    assert not calls.append_call(row("2026-10-22T10:00:00Z"))


def test_append_call_returns_false_on_store_io(monkeypatch):
    def unavailable():
        raise StoreIo("resolve", Path("store"), OSError("unavailable"))

    monkeypatch.setattr(calls, "resolve_store_dir", unavailable)

    assert not calls.append_call(row("2026-10-22T10:00:00Z"))


def test_append_call_returns_false_on_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    monkeypatch.setattr(
        calls.os, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )

    assert not calls.append_call(row("2026-10-22T10:00:00Z"))


def test_append_call_returns_false_on_mkdir_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path / "missing")
    monkeypatch.setattr(
        Path, "mkdir", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )

    assert not calls.append_call(row("2026-10-22T10:00:00Z"))


def test_append_call_returns_false_on_nonserializable_row(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    invalid = row("2026-10-22T10:00:00Z")
    cast("dict[str, object]", invalid)["guardrail"] = object()

    assert not calls.append_call(invalid)


def test_concurrent_appends_preserve_every_row(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    rows = [row(f"2026-10-22T10:00:{second:02d}Z") for second in range(20)]

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert all(executor.map(calls.append_call, rows))

    assert sorted(item["ts"] for item in calls.read_calls(tmp_path)) == sorted(
        item["ts"] for item in rows
    )


def test_read_calls_skips_malformed_lines(tmp_path):
    invalid = [
        {
            "ts": "2026-10-22",
            "command": "x",
            "status": "success",
            "duration_s": True,
            "session": None,
        },
        {
            "ts": "2026-10-22",
            "command": "x",
            "status": "success",
            "duration_s": math.nan,
            "session": None,
        },
        {
            "ts": "bad",
            "command": "x",
            "status": "success",
            "duration_s": 0,
            "session": None,
        },
        {
            "ts": "2026-10-22",
            "command": "x",
            "status": "success",
            "duration_s": 0,
            "session": None,
            "guardrail": 3,
        },
        {
            "ts": "2026-10-22",
            "command": "doc how",
            "status": "success",
            "duration_s": 0,
            "session": None,
            "arg": 3,
        },
    ]
    content = "\n".join(
        [json.dumps(value) for value in invalid]
        + ['{"command":"incomplete"}', "not-json"]
    )
    (tmp_path / calls.CALLS_NAME).write_text(content + "\n")

    assert calls.read_calls(tmp_path) == []


def test_read_calls_strict_raises_for_unreadable_store(tmp_path):
    (tmp_path / calls.CALLS_NAME).mkdir()
    with pytest.raises(StoreIo, match="read CLI calls"):
        calls.read_calls_strict(tmp_path)


def test_mark_retries_obeys_window_and_session():
    start = datetime(2026, 10, 22, 10, tzinfo=UTC)

    def iso(value):
        return value.isoformat().replace("+00:00", "Z")

    rows = [
        row(iso(start), status="failure"),
        row(iso(start + timedelta(seconds=120)), status="failure"),
        row(iso(start + timedelta(seconds=241)), status="failure"),
        row(iso(start + timedelta(seconds=30)), status="failure", session="other"),
        row(iso(start + timedelta(seconds=40)), status="failure", session=None),
        row(iso(start + timedelta(seconds=50)), status="failure"),
        row(iso(start + timedelta(seconds=60)), status="success"),
    ]

    marked = calls.mark_retries(rows)

    assert [item.get("retry") for item in marked] == [
        False,
        True,
        False,
        False,
        False,
        True,
        True,
    ]


def test_mark_retries_uses_chronological_utc_and_preserves_input():
    rows = [
        row("2026-10-22T12:00:00+02:00", status=calls.FAILURE),
        row("2026-10-22T10:02:01Z", status=calls.FAILURE),
        row("2026-10-22T10:02:00Z", status=calls.SUCCESS),
        row("2026-10-22T10:02:00", status=calls.SUCCESS),
    ]
    original = [dict(item) for item in rows]

    marked = calls.mark_retries(rows, window_s=120)

    assert [item.get("retry") for item in marked] == [False, False, True, True]
    assert rows == original


def test_mark_retries_failed_then_success_and_custom_window():
    start = datetime(2026, 10, 22, 10, tzinfo=UTC)

    def iso(value):
        return value.isoformat()

    rows = [
        row(iso(start), status=calls.FAILURE),
        row(iso(start + timedelta(seconds=121)), status=calls.SUCCESS),
        row(iso(start + timedelta(seconds=122)), status=calls.SUCCESS),
    ]

    assert [item.get("retry") for item in calls.mark_retries(rows)] == [
        False,
        False,
        False,
    ]
    assert [item.get("retry") for item in calls.mark_retries(rows, window_s=122)] == [
        False,
        True,
        True,
    ]


def test_rank_commands_reports_command_session_and_iso_week_rates():
    rows = [
        row("2026-10-19T10:00:00Z", status="failure"),
        row("2026-10-19T10:01:00Z", status="success"),
        row("2026-10-26T10:00:00Z", status="failure", session="s2"),
    ]

    ranked = calls.rank_commands(rows)

    assert ranked["commands"][0] == {
        "key": "plan gate",
        "calls": 3,
        "failures": 2,
        "retries": 1,
        "failure_rate": 2 / 3,
        "retry_rate": 1 / 3,
    }
    assert {item["key"]: item["calls"] for item in ranked["sessions"]} == {
        "s1": 2,
        "s2": 1,
    }
    assert {item["key"]: item["calls"] for item in ranked["weeks"]} == {
        "2026-W43": 2,
        "2026-W44": 1,
    }


def test_guardrail_and_blocked_rows_do_not_rank_or_seed_retries():
    rows = [
        row("2026-10-19T10:00:00Z", status=FAILURE),
        {**row("2026-10-19T10:00:10Z", status=FAILURE), "guardrail": "g"},
        row("2026-10-19T10:00:20Z", status=BLOCKED),
    ]
    ranked = calls.rank_commands(rows)
    assert ranked["commands"] == [
        {
            "key": "plan gate",
            "calls": 1,
            "failures": 1,
            "retries": 0,
            "failure_rate": 1.0,
            "retry_rate": 0.0,
        }
    ]


@pytest.mark.parametrize("value", ["30d", "2h"])
def test_parse_window_accepts_valid_durations(value):
    assert calls.parse_window(value).total_seconds() > 0


@pytest.mark.parametrize("value", ["0d", "5x", "d", "-1d", "1.5d"])
def test_parse_window_rejects_invalid_durations(value):
    with pytest.raises(ValueError):
        calls.parse_window(value)


def test_rank_commands_buckets_weeks_in_utc_at_year_boundary():
    ranked = calls.rank_commands(
        [row("2027-01-01T00:30:00+02:00"), row("2027-01-04T00:30:00Z")]
    )

    assert {item["key"]: item["calls"] for item in ranked["weeks"]} == {
        "2026-W53": 1,
        "2027-W01": 1,
    }


def test_session_ranking_keeps_null_distinct_from_literal_none():
    ranked = calls.rank_commands(
        [
            row("2026-10-22T10:00:00Z", session=None),
            row("2026-10-22T10:00:00Z", session="None"),
        ]
    )

    assert {item["key"]: item["calls"] for item in ranked["sessions"]} == {
        None: 1,
        "None": 1,
    }


def test_failed_append_is_counted_and_logged(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    before = calls.dropped_calls()

    with exclusive_store_lock(tmp_path):
        assert not calls.append_call(row("2026-10-22T10:00:00Z"))

    assert calls.dropped_calls() == before + 1
    log = tmp_path / calls.DROPPED_LOG_NAME
    assert "Locked" in log.read_text().splitlines()[-1]
    assert log.stat().st_mode & 0o777 == 0o600
    assert calls.read_calls(tmp_path) == []


def test_append_refused_after_flip_is_counted_not_written(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    assert calls.append_call(row("2026-10-22T10:00:00Z"))
    store = open_calls(tmp_path)
    flip_domain_locked(tmp_path, "calls", "sqlite")
    before = calls.dropped_calls()

    with pytest.raises(StaleGeneration):
        store.append(row("2026-10-22T10:00:01Z"))
    assert len((tmp_path / calls.CALLS_NAME).read_text().splitlines()) == 1

    assert calls.append_call(row("2026-10-22T10:00:02Z"))
    assert calls.dropped_calls() == before
    assert [item["ts"] for item in calls.read_calls(tmp_path)] == [
        "2026-10-22T10:00:02Z"
    ]


def test_unwritable_drop_log_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    (tmp_path / calls.DROPPED_LOG_NAME).mkdir()
    before = calls.dropped_calls()

    with exclusive_store_lock(tmp_path):
        assert not calls.append_call(row("2026-10-22T10:00:00Z"))

    assert calls.dropped_calls() == before + 1


def test_drop_log_stops_at_cap_with_one_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    monkeypatch.setattr(calls, "DROPPED_LOG_MAX_BYTES", 400)
    before = calls.dropped_calls()

    with exclusive_store_lock(tmp_path):
        for _ in range(12):
            assert not calls.append_call(row("2026-10-22T10:00:00Z"))

    log = tmp_path / calls.DROPPED_LOG_NAME
    lines = log.read_text().splitlines()
    assert lines.count(calls.CAP_MARKER.decode().strip()) == 1
    assert lines[-1] == calls.CAP_MARKER.decode().strip()
    assert log.stat().st_size <= 400 + len(calls.CAP_MARKER)
    assert calls.dropped_calls() == before + 12


def test_sqlite_lock_contention_is_counted_as_a_drop(tmp_path, monkeypatch):
    monkeypatch.setattr(calls, "resolve_store_dir", lambda: tmp_path)
    flip_domain_locked(tmp_path, "calls", "sqlite")
    before = calls.dropped_calls()

    with exclusive_store_lock(tmp_path):
        assert not calls.append_call(row("2026-10-22T10:00:00Z"))

    assert calls.dropped_calls() == before + 1
    assert (tmp_path / calls.DROPPED_LOG_NAME).read_text().count("Locked") == 1


SESSION_VARS = (
    "CLAUDE_SESSION_ID",
    "CLAUDE_CODE_SESSION_ID",
    "CODEX_THREAD_ID",
    "VARDE_TOZ_SESSION",
)


@pytest.mark.parametrize("name", SESSION_VARS)
def test_session_id_reads_each_variable_alone(monkeypatch, name):
    for var in SESSION_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(name, "x")
    assert calls.session_id() == "x"


def test_session_id_is_null_when_no_variable_is_set(monkeypatch):
    for var in SESSION_VARS:
        monkeypatch.delenv(var, raising=False)
    assert calls.session_id() is None


def test_session_id_precedence_follows_variable_order(monkeypatch):
    for position, name in enumerate(SESSION_VARS):
        monkeypatch.setenv(name, f"v{position}")
    for position, name in enumerate(SESSION_VARS):
        assert calls.session_id() == f"v{position}"
        monkeypatch.delenv(name)


def test_recorded_row_uses_claude_code_session_id(tmp_path, monkeypatch):
    for var in SESSION_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "x")
    assert calls.append_call(
        row("2026-10-22T10:00:00Z", session=calls.session_id()), tmp_path
    )
    assert [item["session"] for item in calls.read_calls_strict(tmp_path)] == ["x"]
