"""In-place upgrade of ``cli_calls`` from the JSON-blob layout to typed columns."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path

import pytest
from varde_data.backends.sqlite import learn_calls_upgrade as upgrade
from varde_data.backends.sqlite.learn_calls import typed_row
from varde_data.backends.sqlite.learn_schema import SCHEMA_VERSION, connect
from varde_data.calls import open_calls
from varde_data.errors import LearnStoreIo
from varde_data.learn_store_mode import flip_domain_locked, learn_db_path

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
VALID = [
    {
        "ts": "2026-10-22T10:00:00Z",
        "command": "plan status",
        "status": "success",
        "duration_s": 0.5,
        "session": "s1",
    },
    {
        "ts": "2026-10-22T10:00:01+00:00",
        "command": "setup watch",
        "status": "failure",
        "duration_s": 3,
        "session": None,
    },
    {
        "ts": "2026-10-22T12:00:02.5+02:00",
        "command": "doc how",
        "status": "blocked",
        "duration_s": 0.0,
        "session": "s2",
        "guardrail": "g1",
        "arg": "skill/step",
    },
]
INVALID = [
    {"ts": "not a time", "command": "x", "status": "success", "duration_s": 1},
    {"ts": "2026-10-22T10:00:00Z", "command": "x", "status": "odd", "duration_s": 1},
    {"ts": "2026-10-22T10:00:00Z", "command": "x", "status": "success"},
]


def make_v1(root: Path, rows: Sequence[object], raw: list[str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = learn_db_path(root)
    with closing(sqlite3.connect(path)) as db:
        db.execute("PRAGMA journal_mode = WAL")
        db.executescript(V1_DDL)
        db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        texts = [json.dumps(row) for row in rows] + (raw or [])
        for text in texts:
            value = json.loads(text) if text.startswith("{") else {}
            db.execute(
                "INSERT INTO cli_calls (ts, session, command, row) VALUES (?, ?, ?, ?)",
                (
                    str(value.get("ts", "")),
                    value.get("session"),
                    str(value.get("command", "")),
                    text,
                ),
            )
        db.commit()
    return path


def columns(path: Path) -> list[str]:
    with closing(sqlite3.connect(path)) as db:
        return [c[1] for c in db.execute("PRAGMA table_info(cli_calls)")]


def table_rows(path: Path) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(path)) as db:
        return db.execute("SELECT * FROM cli_calls ORDER BY id").fetchall()


def test_upgrade_copies_valid_rows_and_quarantines_the_rest(tmp_path: Path) -> None:
    mixed = [VALID[0], INVALID[0], VALID[1], INVALID[1], VALID[2], INVALID[2]]
    path = make_v1(tmp_path, mixed, raw=["garbage", "[1]"])
    connect(tmp_path).close()
    assert columns(path) == [
        "id",
        "ts",
        "command",
        "status",
        "duration_s",
        "session",
        "guardrail",
        "arg",
    ]
    assert table_rows(path) == [
        (1, "2026-10-22T10:00:00Z", "plan status", "success", 0.5, "s1", None, None),
        (
            3,
            "2026-10-22T10:00:01+00:00",
            "setup watch",
            "failure",
            3.0,
            None,
            None,
            None,
        ),
        (
            5,
            "2026-10-22T12:00:02.5+02:00",
            "doc how",
            "blocked",
            0.0,
            "s2",
            "g1",
            "skill/step",
        ),
    ]
    skipped = (tmp_path / upgrade.SKIPPED_NAME).read_text().splitlines()
    assert len(skipped) == 5  # copied (3) plus skipped (5) is the v1 count (8)
    assert skipped == [*(json.dumps(item) for item in INVALID), "garbage", "[1]"]
    assert (tmp_path / upgrade.SKIPPED_NAME).stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION == 1
        assert db.execute(
            "SELECT value FROM meta WHERE key='calls_layout'"
        ).fetchone() == ("2",)
        names = {
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")
        }
    assert {"cli_calls_ts", "cli_calls_session", "cli_calls_command"} <= names


def test_upgrade_makes_a_private_backup_of_the_v1_database(tmp_path: Path) -> None:
    path = make_v1(tmp_path, VALID)
    connect(tmp_path).close()
    backup = path.with_name(path.name + upgrade.BACKUP_SUFFIX)
    assert backup.stat().st_mode & 0o777 == 0o600
    assert "row" in columns(backup)
    with closing(sqlite3.connect(backup)) as db:
        assert db.execute("SELECT COUNT(*) FROM cli_calls").fetchone() == (3,)


def test_upgraded_rows_read_back_as_the_original_dicts(tmp_path: Path) -> None:
    make_v1(tmp_path, VALID)
    flip_domain_locked(tmp_path, "calls", "sqlite")
    rows = open_calls(tmp_path).read_strict()
    assert rows[0] == VALID[0]
    assert rows[1] == {**VALID[1], "duration_s": 3.0}
    assert rows[2] == VALID[2]


def test_forced_mismatch_rolls_back_to_the_intact_v1_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_v1(tmp_path, VALID)
    monkeypatch.setattr(upgrade, "_verify_copy", lambda *_: "forced mismatch")
    with pytest.raises(LearnStoreIo, match="forced mismatch"):
        connect(tmp_path)
    assert "row" in columns(path)
    assert len(table_rows(path)) == 3
    assert not (tmp_path / upgrade.SKIPPED_NAME).exists()
    monkeypatch.undo()
    connect(tmp_path).close()
    assert "row" not in columns(path)


def test_typed_layout_is_not_upgraded_again(tmp_path: Path) -> None:
    connect(tmp_path).close()
    connect(tmp_path).close()
    assert (
        not learn_db_path(tmp_path).with_name("learn.sqlite3.calls-v1-backup").exists()
    )


def test_v1_era_connection_still_reads_friction_and_fails_its_call_insert(
    tmp_path: Path,
) -> None:
    path = make_v1(tmp_path, VALID)
    connect(tmp_path).close()
    with closing(sqlite3.connect(path)) as old:
        assert old.execute("SELECT COUNT(*) FROM friction_events").fetchone() == (0,)
        with pytest.raises(sqlite3.OperationalError):
            old.execute(
                "INSERT INTO cli_calls (ts, session, command, row) "
                "VALUES ('t', NULL, 'c', '{}')"
            )
    assert len(table_rows(path)) == 3


def test_busy_appender_waits_for_the_upgrade_and_is_not_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = make_v1(tmp_path, VALID)
    flip_domain_locked(tmp_path, "calls", "sqlite")
    started = threading.Event()
    real = upgrade._verify_copy

    def slow(*args: object) -> str | None:
        started.set()
        time.sleep(0.4)
        return real(*args)  # type: ignore[arg-type]

    monkeypatch.setattr(upgrade, "_verify_copy", slow)
    opener = threading.Thread(target=lambda: connect(tmp_path).close())
    opener.start()
    assert started.wait(5)
    row = {**VALID[0], "ts": "2026-10-23T00:00:00Z"}
    open_calls(tmp_path).append(row)
    opener.join()
    assert "row" not in columns(path)
    assert [r[1] for r in table_rows(path)][-1] == row["ts"]
    assert len(table_rows(path)) == 4


def test_vacuum_failure_is_only_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    connection = connect(tmp_path)
    connection.execute("BEGIN IMMEDIATE")  # VACUUM cannot run inside a transaction
    upgrade._vacuum(connection)
    connection.rollback()
    connection.close()
    assert "VACUUM after the calls layout upgrade failed" in caplog.text


def test_typed_row_rules() -> None:
    base = VALID[0]
    assert typed_row(base) == (
        "2026-10-22T10:00:00Z",
        "plan status",
        "success",
        0.5,
        "s1",
        None,
        None,
    )
    bad = [
        {**base, "ts": ""},
        {**base, "command": ""},
        {**base, "status": "x"},
        {**base, "duration_s": True},
        {**base, "duration_s": -1},
        {**base, "duration_s": float("nan")},
        {**base, "duration_s": float("inf")},
        {**base, "session": 3},
        {**base, "guardrail": None},
        {**base, "arg": 1},
        {**base, "ts": "nope"},
        "text",
        None,
    ]
    assert all(typed_row(item) is None for item in bad)


def test_append_rejects_an_invalid_row(tmp_path: Path) -> None:
    flip_domain_locked(tmp_path, "calls", "sqlite")
    with pytest.raises(ValueError, match="typed layout"):
        open_calls(tmp_path).append({"ts": "t", "command": "c"})
