"""Calls retention: watermark, ``store prune``, status and long-window notices."""

from __future__ import annotations

import io
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from varde_data import calls_store
from varde_data.calls import open_calls
from varde_data.learn_store_mode import flip_domain_locked, learn_db_path
from varde_learn.loop import (
    calls,
    calls_retention,
    cli_calls,
    cli_guardrails,
    cli_store,
)

RETENTION_BACKEND = "varde_data.backends.sqlite.learn_calls_retention"
NOW = datetime.now(UTC).replace(microsecond=0)
PLUS_TWO = timezone(timedelta(hours=2))


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    flip_domain_locked(store, "calls", "sqlite")
    return store


def add(root: Path, stamp: str, command: str = "plan status") -> None:
    open_calls(root).append(
        {
            "ts": stamp,
            "command": command,
            "status": "success",
            "duration_s": 0.1,
            "session": "s1",
        }
    )


def ago(days: float) -> datetime:
    return NOW - timedelta(days=days)


def stored_ts(root: Path) -> list[str]:
    with closing(sqlite3.connect(learn_db_path(root))) as db:
        return [row[0] for row in db.execute("SELECT ts FROM cli_calls ORDER BY id")]


def store(*args: str) -> tuple[int, Io]:
    sink = Io()
    return cli_store.run(["prune", "--domain", "calls", *args, "--json"], sink), sink


def test_prune_deletes_only_old_rows_under_the_watermark(root: Path) -> None:
    add(root, ago(60).isoformat())  # old, under the watermark: deleted
    add(root, ago(40).strftime("%Y-%m-%dT%H:%M:%SZ"))  # deleted
    add(root, ago(20).isoformat())  # in window: kept
    add(root, ago(2).isoformat())  # in window: kept
    calls_store.mark_used(root, ago(45).isoformat())
    code, sink = store()
    assert code == 0, sink.stderr.getvalue()
    # the 40-day row is old but newer than the watermark, so it stays
    assert len(stored_ts(root)) == 3
    assert json.loads(sink.stdout.getvalue())["data"]["deleted"] == 1
    calls_store.mark_used(root, ago(1).isoformat())
    code, sink = store()
    assert code == 0
    assert len(stored_ts(root)) == 2
    assert json.loads(sink.stdout.getvalue())["data"]["deleted"] == 1


def test_mixed_formats_at_the_cutoff(root: Path) -> None:
    cutoff = ago(30)
    inside = (cutoff + timedelta(minutes=30)).astimezone(PLUS_TWO).isoformat()
    outside = (cutoff - timedelta(minutes=30)).astimezone(PLUS_TWO).isoformat()
    inside_z = (cutoff + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    outside_naive = (cutoff - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
    for stamp in (inside, outside, inside_z, outside_naive):
        add(root, stamp)
    calls_store.mark_used(root, NOW.isoformat())
    code, _ = store("--days", "30")
    assert code == 0
    assert sorted(stored_ts(root)) == sorted([inside, inside_z])


def test_no_watermark_and_dry_run_delete_nothing(root: Path) -> None:
    add(root, ago(90).isoformat())
    code, sink = store()
    assert code == 0
    assert json.loads(sink.stdout.getvalue())["data"]["deleted"] == 0
    calls_store.mark_used(root, NOW.isoformat())
    code, sink = store("--dry-run")
    data = json.loads(sink.stdout.getvalue())["data"]
    assert (code, data["deleted"], data["would_delete"]) == (0, 0, 1)
    assert len(stored_ts(root)) == 1


def test_refuses_with_the_jsonl_present_or_on_files(root: Path, tmp_path: Path) -> None:
    (root / "cli_calls.jsonl").write_text("")
    code, sink = store()
    assert code == 2
    assert "retire" in sink.stderr.getvalue()
    other = tmp_path / "files-store"
    other.mkdir()
    with pytest.raises(ValueError, match="not on sqlite"):
        calls_retention.prune_calls(other, 30)


def test_vacuum_shrinks_and_dry_run_vacuum_changes_nothing(root: Path) -> None:
    for index in range(3000):
        add(root, (ago(90) + timedelta(seconds=index)).isoformat(), f"cmd {index}")
    calls_store.mark_used(root, NOW.isoformat())
    path = learn_db_path(root)
    big = path.stat().st_size
    code, _ = store("--dry-run", "--vacuum")
    assert code == 0
    assert (path.stat().st_size, len(stored_ts(root))) == (big, 3000)
    code, sink = store("--vacuum")
    assert code == 0
    assert path.stat().st_size < big
    assert json.loads(sink.stdout.getvalue())["data"]["vacuum"]["bytes_after"] < big


def test_watermark_never_lowers(root: Path) -> None:
    calls_store.mark_used(root, ago(1).isoformat())
    calls_store.mark_used(root, ago(5).astimezone(PLUS_TWO).isoformat())
    assert calls_store.usage(root)["watermark"] == ago(1).isoformat()


@pytest.mark.parametrize(
    "text",
    [
        "[retention]\ncalls_days = 0\n",
        "[retention]\ncalls_days = true\n",
        '[retention]\ncalls_days = "9"\n',
    ],
)
def test_bad_config_is_rejected(root: Path, text: str) -> None:
    (root / "sweep.toml").write_text(text)
    code, _ = store()
    assert code == 2


def test_config_days_and_bad_summary_table(root: Path) -> None:
    (root / "sweep.toml").write_text(
        "[retention]\ncalls_days = 7\n[summary]\nenabled = 3\n"
    )
    assert calls_retention.retention_days() == 7
    (root / "sweep.toml").unlink()
    assert calls_retention.retention_days() == 30


def test_help_lists_prune_and_status_shows_watermark(root: Path) -> None:
    sink = Io()
    assert cli_store.run(["--help"], sink) == 0
    assert "prune" in sink.stdout.getvalue()
    add(root, ago(3).isoformat())
    calls_store.mark_used(root, ago(1).isoformat())
    sink = Io()
    assert cli_store.run(["status", "--json"], sink) == 0
    domain = json.loads(sink.stdout.getvalue())["data"]["domains"]["calls"]
    assert domain["watermark"] == ago(1).isoformat()
    assert domain["oldest_ts"] == ago(3).isoformat()


def test_prune_batch_lets_a_concurrent_append_succeed(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for index in range(6):
        add(root, (ago(90) + timedelta(seconds=index)).isoformat())
    calls_store.mark_used(root, NOW.isoformat())
    monkeypatch.setattr(RETENTION_BACKEND + ".BATCH", 2)
    appended: list[str] = []
    real = json.dumps

    def dumps_then_append(value: object) -> str:
        stamp = ago(0.5).isoformat()
        add(root, stamp, f"live {len(appended)}")
        appended.append(stamp)
        return real(value)

    monkeypatch.setattr(
        RETENTION_BACKEND + ".json",
        type("J", (), {"dumps": staticmethod(dumps_then_append)}),
    )
    code, _ = store()
    assert code == 0
    assert len(appended) == 3
    assert stored_ts(root) == appended


def test_reports_advance_the_watermark_and_warn_on_long_windows(
    root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    add(root, ago(2).isoformat())
    add(root, ago(1).isoformat())
    sink = Io()
    assert cli_calls.run(["calls", "--window", "7d", "--json"], sink) == 0
    meta = json.loads(sink.stdout.getvalue())["meta"]
    assert "retention_days" not in meta
    assert calls_store.usage(root)["watermark"] == ago(1).isoformat()
    sink = Io()
    assert cli_calls.run(["calls", "--window", "90d", "--json"], sink) == 0
    assert json.loads(sink.stdout.getvalue())["meta"]["retention_days"] == 30
    assert "30-day" in capsys.readouterr().err
    sink = Io()
    assert cli_guardrails.run(["guardrails", "--dead", "--window", "90d"], sink) == 2
    assert "calls_days" in sink.stderr.getvalue()
    sink = Io()
    assert cli_guardrails.run(["guardrails", "--dead", "--window", "30d"], sink) == 0


def test_note_calls_used_ignores_empty_rows(root: Path) -> None:
    calls_retention.note_calls_used([])
    assert calls_store.usage(root)["watermark"] is None
    calls_retention.note_calls_used(
        [
            calls.CallRow(
                ts=ago(3).isoformat(),
                command="x",
                status="success",
                duration_s=0.0,
                session=None,
            )
        ]
    )
    assert calls_store.usage(root)["watermark"] == ago(3).isoformat()


def test_no_long_window_notice_on_the_files_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = tmp_path / "files-store"
    store.mkdir()
    monkeypatch.setenv("VARDE_LEARN_STORE", str(store))
    sink = Io()
    assert cli_calls.run(["calls", "--window", "90d", "--json"], sink) == 0
    assert "retention_days" not in json.loads(sink.stdout.getvalue())["meta"]
    assert "retention" not in capsys.readouterr().err
    sink = Io()
    assert cli_guardrails.run(["guardrails", "--dead", "--window", "90d"], sink) == 0


def test_a_future_ts_does_not_lift_the_watermark_past_now(root: Path) -> None:
    calls_store.mark_used(root, (NOW + timedelta(days=400)).isoformat())
    mark = calls_store.usage(root)["watermark"]
    assert datetime.fromisoformat(mark) <= datetime.now(UTC)
