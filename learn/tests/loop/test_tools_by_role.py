from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path

from varde_learn.loop import cli_tools
from varde_learn.module import _LearnModule


class _Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


def _runner_db(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        "CREATE TABLE sessions (id TEXT PRIMARY KEY, role TEXT NOT NULL);"
        "CREATE TABLE events (seq INTEGER PRIMARY KEY, session_id TEXT, kind TEXT, "
        "payload TEXT, created_at TEXT);"
    )
    connection.execute("INSERT INTO sessions VALUES ('s1', 'builder')")
    events = [
        (
            "tool_intent",
            {"call_id": "c1", "tool": "exec", "phase": "running"},
            "2026-10-27T10:00:00+00:00",
        ),
        (
            "tool_result",
            {"call_id": "c1", "tool": None, "phase": "failed"},
            "2026-10-27T10:00:00.120000+00:00",
        ),
        (
            "tool_intent",
            {"call_id": "c2", "tool": "exec", "phase": "running"},
            "2026-10-27T10:01:00+00:00",
        ),
        (
            "tool_result",
            {"call_id": "c2", "phase": "completed"},
            "2026-10-27T10:01:00.080000+00:00",
        ),
        ("tool_intent", {"call_id": "c3", "tool": "exec"}, "2026-10-27T10:02:00+00:00"),
    ]
    for seq, (kind, payload, created_at) in enumerate(events, start=1):
        connection.execute(
            "INSERT INTO events VALUES (?, 's1', ?, ?, ?)",
            (seq, kind, json.dumps(payload), created_at),
        )
    connection.commit()
    connection.close()


def test_tools_by_role_pairs_events_and_reports_gaps(tmp_path: Path) -> None:
    database = tmp_path / "runner.sqlite3"
    _runner_db(database)

    report = cli_tools.summarize(database)

    assert report["rows"] == [
        {"role": "builder", "tool": "exec", "calls": 2, "failures": 1, "p50_ms": 100.0}
    ]
    assert report["provider_gaps"] == {
        "missing_phase": 1,
        "missing_outcome": 1,
        "missing_call_id": 0,
    }


def test_tools_by_role_cli_dispatches_json(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "work"
    database = working / ".cache" / "dashboard" / "runner.sqlite3"
    database.parent.mkdir(parents=True)
    _runner_db(database)
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    output = _Io()

    assert _LearnModule().run(["tools", "--by-role", "--json"], output) == 0
    data = json.loads(output.stdout.getvalue())["data"]
    assert data["rows"][0]["role"] == "builder"
    assert data["provider_gaps"]["missing_outcome"] == 1
    assert output.stderr.getvalue() == ""


def test_tools_by_role_friction_appends_failure_occurrence(
    tmp_path, monkeypatch
) -> None:
    from varde_data.friction import open_friction
    from varde_data.records.friction import Event, ItemAdded
    from varde_learn.loop import friction_repository

    repository = open_friction(tmp_path / "store")
    repository.import_events(
        [
            Event.at(
                "2026-10-27T10:00:00.000Z",
                None,
                ItemAdded("Tool failures: builder / exec", cli_tools.SOURCE),
            )
        ]
    )
    monkeypatch.setattr(friction_repository, "open_repository", lambda: repository)
    report = {
        "rows": [
            {"role": "builder", "tool": "exec", "failures": 2},
            {"role": "reviewer", "tool": "edit", "failures": 0},
        ]
    }

    assert cli_tools.append_failures(report) == 1
    result = repository.show("1")
    assert len(result.occurrences.items) == 1
    assert "2 failed exec call(s)" in result.occurrences.items[0].evidence
    assert "tool-stats-window-start=unbounded" in result.occurrences.items[0].evidence
    assert "tool-stats-failures=2" in result.occurrences.items[0].evidence

    assert cli_tools.append_failures(report) == 0
    result = repository.show("1")
    assert len(result.occurrences.items) == 1

    changed_count = {"rows": [{"role": "builder", "tool": "exec", "failures": 3}]}
    assert cli_tools.append_failures(changed_count) == 1
    result = repository.show("1")
    assert len(result.occurrences.items) == 2


def test_friction_since_window_dedupes_repeated_runs(monkeypatch, tmp_path) -> None:
    from varde_data.friction import open_friction
    from varde_data.records.friction import Event, ItemAdded
    from varde_learn.loop import friction_repository

    repository = open_friction(tmp_path / "store")
    repository.import_events(
        [
            Event.at(
                "2026-10-27T10:00:00.000Z",
                None,
                ItemAdded("Tool failures: builder / exec", cli_tools.SOURCE),
            )
        ]
    )
    monkeypatch.setattr(friction_repository, "open_repository", lambda: repository)
    report = {"rows": [{"role": "builder", "tool": "exec", "failures": 2}]}
    assert cli_tools.append_failures(report, "7d") == 1
    assert cli_tools.append_failures(report, "7d") == 0
    assert len(repository.show("1").occurrences.items) == 1
