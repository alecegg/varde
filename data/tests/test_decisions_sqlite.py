import json
from pathlib import Path
from typing import cast

import pytest
from varde_data.backends.sqlite.decisions import SqliteDecisions
from varde_data.decisions import decision_store_files, open_decisions
from varde_data.records.decisions import DecisionProjection


def test_factory_paths_and_audit_mirror(tmp_path: Path) -> None:
    repo = open_decisions(tmp_path)
    assert repo.project(
        DecisionProjection("source", "d1", "question", "title", "body", {})
    )
    assert repo.dismiss("d1")
    paths = decision_store_files(tmp_path)
    assert paths == (
        tmp_path / "decisions.sqlite3",
        tmp_path / "decisions.sqlite3-wal",
        tmp_path / "decisions.sqlite3-shm",
        tmp_path / "decisions.audit.jsonl",
    )
    assert paths[-1].read_text(encoding="utf-8").count("\n") == 1
    repo.close()


def test_factory_memory_and_unknown(tmp_path: Path) -> None:
    repo = open_decisions(tmp_path, "memory")
    assert repo.project(
        DecisionProjection("source", "d1", "question", "title", "body", {})
    )
    repo.close()
    try:
        open_decisions(tmp_path, "files")
    except ValueError as exc:
        assert "unknown decisions backend" in str(exc)
    else:
        raise AssertionError("unknown backend was accepted")


def test_sqlite_durability_write_rollback_and_surrogate(tmp_path: Path) -> None:
    repo = SqliteDecisions(tmp_path)
    assert repo.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert repo.db.execute("PRAGMA synchronous").fetchone()[0] == 2
    with pytest.raises(UnicodeEncodeError):
        repo.submit_answer("bad", "bad", "agent", "\ud800")
    assert repo.db.in_transaction is False
    row = repo.submit_answer("good", "good", "agent", "answer").entry
    assert row.status == "stored"
    repo.close()


def test_audit_mirror_repairs_torn_tail_and_resyncs(tmp_path: Path) -> None:
    repo = SqliteDecisions(tmp_path)
    repo.project(DecisionProjection("source", "d1", "question", "title", "body", {}))
    repo.dismiss("d1")
    path = tmp_path / "decisions.audit.jsonl"
    original_lines = path.read_text(encoding="utf-8").splitlines()
    assert len(original_lines) == 1
    path.write_text(original_lines[0] + "\nnot an object\n{torn", encoding="utf-8")
    repo.close()

    reopened = SqliteDecisions(tmp_path)
    assert path.read_text(encoding="utf-8").splitlines() == [
        original_lines[0],
        "not an object",
    ]
    path.unlink()
    reopened.close()
    resynced = SqliteDecisions(tmp_path)
    payloads = [json.loads(line) for line in path.read_text().splitlines()]
    assert [row["seq"] for row in payloads] == [1]
    resynced.close()


def test_sqlite_version_increments_for_each_write(tmp_path: Path) -> None:
    repo = SqliteDecisions(tmp_path)
    observer = SqliteDecisions(tmp_path)
    initial = cast("int", repo.version().value)
    repo.project(DecisionProjection("source", "d1", "question", "title", "body", {}))
    after_project = cast("int", repo.version().value)
    assert after_project == initial + 1
    assert cast("int", observer.version().value) == after_project
    answer = repo.submit_answer("d1", "key", "agent", "answer").entry
    assert cast("int", repo.version().value) == after_project + 1
    repo.transition_entry(answer.entry_id, "sending", "stored", "started")
    assert cast("int", repo.version().value) == after_project + 2
    assert cast("int", observer.version().value) == after_project + 2
    observer.close()
    repo.close()


def test_write_exception_rolls_back_and_connection_recovers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = SqliteDecisions(tmp_path)
    answer = repo.submit_answer("d1", "key", "agent", "answer").entry
    original = repo._insert_audit
    monkeypatch.setattr(
        repo,
        "_insert_audit",
        lambda *args: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )
    with pytest.raises(RuntimeError, match="audit failed"):
        repo.transition_entry(answer.entry_id, "sending", "stored", "started")
    assert repo.db.in_transaction is False
    current = repo.get_entry_by_id(answer.entry_id)
    assert current is not None and current.status == "stored"
    monkeypatch.setattr(repo, "_insert_audit", original)
    assert repo.project(DecisionProjection("source", "d2", "question", "t", "b", {}))
    repo.close()
