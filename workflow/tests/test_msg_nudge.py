from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_workflow import cli
from varde_workflow.nudges import append, load


def test_append_and_load_use_separate_nudge_log(tmp_path: Path) -> None:
    now = datetime(2026, 10, 23, 12, tzinfo=UTC)

    record = append(tmp_path, "orchestrator-4", "stalled", now=now)

    assert record == {
        "event": "main-nudge",
        "address": "orchestrator-4",
        "at": "2026-10-23T12:00:00Z",
        "reason": "stalled",
    }
    path = tmp_path / ".cache" / "inbox" / "nudges.jsonl"
    assert json.loads(path.read_text()) == record
    assert load(tmp_path) == [record]
    assert not (path.parent / "deliveries.jsonl").exists()
    assert not (path.parent / "messages.jsonl").exists()


def test_load_skips_malformed_lines_and_returns_multiple_appends(
    tmp_path: Path,
) -> None:
    first = append(
        tmp_path,
        "orchestrator-1",
        "idle-unread",
        now=datetime(2026, 10, 23, 12, tzinfo=UTC),
    )
    log = tmp_path / ".cache" / "inbox" / "nudges.jsonl"
    with log.open("a", encoding="utf-8") as stream:
        stream.write("{malformed\n")
    second = append(
        tmp_path,
        "orchestrator-2",
        "other",
        now=datetime(2026, 10, 23, 13, tzinfo=UTC),
    )

    assert load(tmp_path) == [first, second]


@pytest.mark.parametrize("reason", ["idle-unread", "stalled", "other"])
def test_cli_nudge_records_reason_without_sending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str
) -> None:
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)

    assert cli.run(["msg", "nudge", "--to", "worker-2", "--reason", reason]) == 0
    assert load(tmp_path)[0]["reason"] == reason
    assert not (tmp_path / ".cache" / "inbox" / "messages.jsonl").exists()


def test_nudge_rejects_invalid_reason(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown nudge reason"):
        append(tmp_path, "worker", "urgent")


def test_nudge_help_snapshot() -> None:
    help_output = cli.help_text("msg nudge")
    assert "Usage: varde msg nudge --to <SLOT> --reason <REASON>" in help_output
    assert "It sends nothing" in help_output
