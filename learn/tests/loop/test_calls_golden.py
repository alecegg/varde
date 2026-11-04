"""The v1 JSON layout, the typed layout and the files log give identical reports."""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from varde_data.calls import open_calls
from varde_data.calls_store import typed_row
from varde_data.learn_store_mode import flip_domain_locked, learn_db_path
from varde_learn.loop import (
    calls,
    cli_calls,
    cli_guardrails,
    cli_how_report,
    guardrails,
)

V1_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE friction_events (seq INTEGER PRIMARY KEY, event TEXT NOT NULL);
CREATE TABLE analyzed (harness TEXT NOT NULL, session TEXT NOT NULL,
    row TEXT NOT NULL, PRIMARY KEY (harness, session));
CREATE TABLE digests (run_date TEXT PRIMARY KEY, text TEXT NOT NULL,
    candidates TEXT NOT NULL);
CREATE TABLE cli_calls (id INTEGER PRIMARY KEY, ts TEXT NOT NULL, session TEXT,
    command TEXT NOT NULL, row TEXT NOT NULL);
CREATE INDEX cli_calls_ts ON cli_calls(ts);
CREATE INDEX cli_calls_session ON cli_calls(session);
CREATE INDEX cli_calls_command ON cli_calls(command);
"""
PLUS_TWO = timezone(timedelta(hours=2))
COMMANDS = {
    "cli_calls": lambda io: cli_calls.run(["calls", "--window", "30d", "--json"], io),
    "cli_calls_all": lambda io: cli_calls.run(["calls", "--json"], io),
    "how_report": lambda io: cli_how_report.run(["how-report", "--json"], io),
    "guardrails": lambda io: cli_guardrails.run(["guardrails", "--json"], io),
}


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def fixture_rows() -> list[dict[str, object]]:
    now = datetime.now(UTC).replace(microsecond=0)
    guardrail = guardrails.load_registry()[0]["id"]
    formats = [
        lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        lambda t: t.isoformat(),
        lambda t: t.astimezone(PLUS_TWO).isoformat(),
        lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.250000+00:00"),
        lambda t: t.strftime("%Y-%m-%dT%H:%M:%S"),
    ]
    rows: list[dict[str, object]] = []
    for index in range(60):
        stamp = formats[index % len(formats)](now - timedelta(hours=index * 7))
        row: dict[str, object] = {
            "ts": stamp,
            "command": ("plan status", "doc how", "setup watch")[index % 3],
            "status": ("success", "failure", "blocked")[index % 3 if index % 5 else 0],
            "duration_s": 0.25 + index,
            "session": None if index % 4 == 0 else f"s{index % 3}",
        }
        if index % 11 == 0:
            row["guardrail"] = guardrail
        if index % 13 == 0:
            row["arg"] = "varde-docs/audit"
        rows.append(row)
    return rows


def build_files(root: Path, rows: list[dict[str, object]]) -> None:
    store = open_calls(root, "files")
    for row in rows:
        store.append(row)


def build_v1(root: Path, rows: list[dict[str, object]]) -> None:
    with closing(sqlite3.connect(learn_db_path(root))) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(V1_DDL)
        db.execute("PRAGMA user_version = 1")
        for row in rows:
            db.execute(
                "INSERT INTO cli_calls (ts, session, command, row) VALUES (?, ?, ?, ?)",
                (row["ts"], row.get("session"), row["command"], json.dumps(row)),
            )
        db.commit()
    flip_domain_locked(root, "calls", "sqlite")


def build_typed(root: Path, rows: list[dict[str, object]]) -> None:
    flip_domain_locked(root, "calls", "sqlite")
    store = open_calls(root)
    for row in rows:
        store.append(row)


def outputs(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("VARDE_LEARN_STORE", str(root))
    result = {}
    for name, command in COMMANDS.items():
        sink = Io()
        assert command(sink) == 0, sink.stderr.getvalue()
        result[name] = sink.stdout.getvalue()
    return result


def without_retention_notice(reports: dict[str, str]) -> dict[str, str]:
    return {
        name: text.replace('"retention_days":30,', "") for name, text in reports.items()
    }


def test_reports_are_byte_identical_across_layouts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = fixture_rows()
    builders = {"files": build_files, "v1": build_v1, "typed": build_typed}
    results = {}
    for name, build in builders.items():
        root = tmp_path / name
        root.mkdir()
        build(root, rows)
        results[name] = outputs(root, monkeypatch)
    assert (
        results["files"]["cli_calls"] and "plan status" in results["files"]["cli_calls"]
    )
    assert results["v1"] == results["typed"]
    # only the sqlite layouts prune, so only they add the retention notice
    assert without_retention_notice(results["typed"]) == results["files"]


def test_since_reads_agree_with_the_exact_filter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = fixture_rows()
    build_typed(tmp_path, rows)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    since = datetime.now(UTC) - timedelta(days=5)
    windowed = calls.read_calls_strict(since=since)
    everything = [
        row
        for row in calls.read_calls_strict()
        if (when := calls.parse_timestamp(row["ts"])) is not None and when >= since
    ]
    assert windowed == everything
    assert 0 < len(windowed) < len(rows)


MATRIX: list[object] = [
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
    },
    {
        "ts": "2026-10-22T10:00:00",
        "command": "c",
        "status": "failure",
        "duration_s": 0.0,
    },
    {
        "ts": "2026-10-22T10:00:00+05:30",
        "command": "c",
        "status": "blocked",
        "duration_s": 2.5,
    },
    {"ts": "", "command": "c", "status": "success", "duration_s": 1},
    {"ts": "garbage", "command": "c", "status": "success", "duration_s": 1},
    {"ts": 5, "command": "c", "status": "success", "duration_s": 1},
    {"ts": "2026-10-22T10:00:00Z", "command": "", "status": "success", "duration_s": 1},
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": None,
        "status": "success",
        "duration_s": 1,
    },
    {"ts": "2026-10-22T10:00:00Z", "command": "c", "status": "ok", "duration_s": 1},
    {"ts": "2026-10-22T10:00:00Z", "command": "c", "status": "success"},
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": True,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": -0.1,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": float("nan"),
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": float("inf"),
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": "1",
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "session": "s",
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "session": None,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "session": 7,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "guardrail": "g",
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "guardrail": None,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "guardrail": 3,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "arg": "a",
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "arg": None,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "arg": 4,
    },
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "c",
        "status": "success",
        "duration_s": 1,
        "extra": 1,
    },
    ["not", "a", "dict"],
    "text",
    None,
]


@pytest.mark.parametrize("value", MATRIX, ids=lambda value: repr(value)[:60])
def test_typed_row_agrees_with_valid_row(value: object) -> None:
    assert (typed_row(value) is not None) == calls._valid_row(value)
