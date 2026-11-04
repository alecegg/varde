import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import varde_learn.loop.review.ledger as ledger_module
from varde_learn.loop.review.ledger import (
    fingerprint,
    import_analyzed,
    mark,
    read_all,
    read_index,
    select_pending,
    write_imported,
)


def _mark(store_dir: Path, row: dict, latest_by_key: dict | None = None) -> dict:
    index = read_index(store_dir) if latest_by_key is None else latest_by_key
    return mark(store_dir, row, latest_by_key=index)


def test_unchanged_is_skipped_and_growth_requeues_with_resume() -> None:
    session = {
        "harness": "codex",
        "session_id": "s1",
        "fingerprint": {"size": 12, "lines": 2},
    }
    ledger = [{**session, "status": "analyzed", "source": "review"}]
    assert select_pending([session], ledger) == []
    missing_fingerprint = {"harness": "codex", "session_id": "s1", "status": "analyzed"}
    assert select_pending([session], [missing_fingerprint]) == []
    grown = {**session, "fingerprint": {"size": 20, "lines": 4}}
    assert select_pending([grown], ledger)[0]["resume_position"] == 2


def test_mark_persists_fingerprint_version_and_resets_attempts(tmp_path: Path) -> None:
    _mark(
        tmp_path,
        {"harness": "codex", "session_id": "s1", "status": "failed"},
    )
    _mark(
        tmp_path,
        {"harness": "codex", "session_id": "s1", "status": "failed"},
    )
    row = _mark(
        tmp_path,
        {
            "harness": "codex",
            "session_id": "s1",
            "status": "analyzed",
            "source": "review",
            "fingerprint": {"size": 10, "lines": 2},
        },
    )
    assert row["version"] == 1
    assert row["fingerprint"] == {"size": 10, "lines": 2}
    assert row["attempts"] == 0
    assert read_all(tmp_path) == [row]


def test_mark_rejects_analyzed_rows_without_fingerprint_or_key(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        _mark(tmp_path, {"harness": "codex", "session_id": "s1", "status": "analyzed"})
    with pytest.raises(ValueError, match="harness and session"):
        _mark(tmp_path, {"harness": "codex", "status": "failed"})


def test_mark_uses_and_updates_cached_key_lookup(tmp_path: Path, monkeypatch) -> None:
    key = ("codex", "s1")
    latest: dict[tuple[str, str], dict[str, Any]] = {
        key: {"harness": "codex", "session_id": "s1", "attempts": 1}
    }

    def unexpected_read(_store_dir):
        raise AssertionError("cached lookup should avoid rereading the ledger")

    monkeypatch.setattr(ledger_module, "read_all", unexpected_read)
    row = mark(
        tmp_path,
        {"harness": "codex", "session_id": "s1", "status": "failed"},
        latest_by_key=latest,
    )
    assert row["attempts"] == 2
    assert latest[key] == row


def test_third_failure_is_skipped_with_last_error(tmp_path: Path) -> None:
    result: dict[str, Any] = {}
    for _ in range(3):
        result = _mark(
            tmp_path,
            {
                "harness": "claude",
                "session_id": "s1",
                "status": "failed",
                "reason": "parse failure",
            },
        )
    assert result["status"] == "skipped"
    assert result["attempts"] == 3
    assert result["reason"] == "too large or unreadable"
    assert result["last_error"] == "parse failure"
    assert (
        select_pending([{"harness": "claude", "session_id": "s1"}], read_all(tmp_path))
        == []
    )


def test_grown_skipped_requeues_and_resets_attempts_except_ignored(
    tmp_path: Path,
) -> None:
    prior = {
        "harness": "claude",
        "session_id": "s1",
        "status": "skipped",
        "attempts": 3,
        "fingerprint": {"size": 10, "lines": 2},
        "reason": "too large or unreadable",
    }
    current = {
        "harness": "claude",
        "session_id": "s1",
        "fingerprint": {"size": 12, "lines": 3},
    }
    pending = select_pending([current], [prior])
    assert pending[0]["attempts"] == 0
    assert pending[0]["resume_position"] == 2
    pending[0].pop("attempts")
    result = _mark(
        tmp_path,
        {**pending[0], "status": "failed", "reason": "new failure"},
    )
    assert result["attempts"] == 1
    ignored = {**prior, "reason": "ignored by configuration"}
    assert select_pending([current], [ignored]) == []


def test_sweep_import_is_idempotent_and_review_result_replaces_sweep(
    tmp_path: Path,
) -> None:
    legacy = [{"harness": "codex", "session": "s1"}]
    expected = import_analyzed(legacy)
    assert write_imported(tmp_path, legacy) == expected
    assert write_imported(tmp_path, legacy) == []
    session = {"harness": "codex", "session_id": "s1"}
    assert select_pending([session], read_all(tmp_path)) == [session]
    _mark(
        tmp_path,
        {
            **expected[0],
            "source": "review",
            "status": "analyzed",
            "fingerprint": {"size": 1, "lines": 1},
        },
    )
    assert select_pending([session], read_all(tmp_path)) == []


def test_rate_limited_then_failed_starts_failure_count_at_one(tmp_path: Path) -> None:
    session = {"harness": "codex", "session_id": "s1"}
    limited = _mark(tmp_path, {**session, "status": "rate_limited"})
    assert select_pending([session], [limited]) == [session]
    failed = _mark(tmp_path, {**session, "status": "failed", "reason": "error"})
    assert failed["attempts"] == 1
    assert select_pending([session], [failed]) == [session]


def test_fingerprint_counts_unterminated_line_and_ignores_malformed_ledger_lines(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text('{"a":1}\n{"b":2}', encoding="utf-8")
    assert fingerprint(transcript)["lines"] == 2
    (tmp_path / "reviewed.jsonl").write_text(
        "broken\n"
        + json.dumps({"harness": "x", "session_id": "s", "status": "failed"}),
        encoding="utf-8",
    )
    assert len(read_all(tmp_path)) == 1
    _mark(tmp_path, {"harness": "x", "session_id": "s", "status": "failed"})
    records = read_all(tmp_path)
    assert len(records) == 1
    assert records[0]["attempts"] == 1


def test_session_alias_and_key_validation() -> None:
    fingerprint_data = {"size": 10, "lines": 2}
    legacy = {
        "harness": "codex",
        "session": "s1",
        "status": "analyzed",
        "fingerprint": fingerprint_data,
    }
    session = {
        "harness": "codex",
        "session_id": "s1",
        "fingerprint": fingerprint_data,
    }
    assert select_pending([session], [legacy]) == []
    assert select_pending([session], [{"harness": "codex"}]) == [session]
    assert import_analyzed([{"harness": "codex"}]) == []


@pytest.mark.parametrize(
    ("columns", "expected_time"),
    [
        ("time_created INTEGER, time_updated INTEGER", 30),
        ("time_created INTEGER", 20),
    ],
)
def test_opencode_fingerprint_uses_latest_supported_time_column(
    tmp_path: Path, columns: str, expected_time: int
) -> None:
    database = tmp_path / "opencode ?#%.db"
    with sqlite3.connect(database) as db:
        db.execute(f"CREATE TABLE session_message (session_id TEXT, {columns})")
        if "time_updated" in columns:
            db.executemany(
                "INSERT INTO session_message VALUES (?, ?, ?)",
                [("s1", 10, 30), ("s1", 20, 25)],
            )
        else:
            db.executemany(
                "INSERT INTO session_message VALUES (?, ?)",
                [("s1", 10), ("s1", 20)],
            )
    assert fingerprint(database, "s1") == {
        "messages": 2,
        "max_message_time": expected_time,
    }


def test_opencode_growth_resumes_from_message_count() -> None:
    session = {
        "harness": "opencode",
        "session_id": "s1",
        "fingerprint": {"messages": 5, "max_message_time": 20},
    }
    prior = {**session, "status": "analyzed", "source": "review"}
    grown = {
        **session,
        "fingerprint": {"messages": 6, "max_message_time": 30},
    }
    assert select_pending([grown], [prior])[0]["resume_position"] == 5
