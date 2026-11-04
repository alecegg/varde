import json
from datetime import date
from pathlib import Path

import pytest
from varde_data.backends.files.ledger import FilesLedger
from varde_data.backends.sqlite.learn_ledger import SqliteLedger
from varde_data.learn_handlers import ledger as handlers
from varde_data.learn_store_mode import (
    StaleGeneration,
    exclusive_store_lock,
    flip_domain_locked,
    read_learn_mode,
)
from varde_data.ledger import open_ledger


def _seed(root: Path) -> None:
    (root / "analyzed.jsonl").write_text(
        '{"session":"s1","harness":"h","analyzed_at":"t0"}\n'
        "garbage\n"
        '{"session":"s2","harness":"h","analyzed_at":"t1","summary":"x",'
        '"metrics":{"n":1},"friction_added":["f"],"extra":true}\n'
        '{"session":"s1","harness":"h","analyzed_at":"t2","summary":null}\n'
    )
    files = FilesLedger(root)
    files.write_digest(date(2026, 10, 1), "d1", [{"title": "c"}])
    files.write_digest(date(2026, 10, 2), "d2", [])
    (root / "digests" / "not-a-date.json").write_text("{}")


def _flip(root: Path) -> None:
    with exclusive_store_lock(root):
        flip_domain_locked(root, "ledger", "sqlite")


def test_migrate_verify_keeps_absent_fields_and_drops_unknown_keys(
    tmp_path: Path,
) -> None:
    _seed(tmp_path)
    expected = FilesLedger(tmp_path).analyzed()
    assert handlers.migrate(tmp_path, dry_run=True) == {
        "ok": True,
        "analyzed": 2,
        "digests": 2,
    }
    assert not (tmp_path / "learn.sqlite3").exists()
    assert handlers.migrate(tmp_path, dry_run=False)["ok"] is True
    assert (tmp_path / "learn.sqlite3.ledger-backup").is_file()
    _flip(tmp_path)
    ledger = open_ledger(tmp_path)
    assert isinstance(ledger, SqliteLedger)
    assert ledger.analyzed() == expected
    assert ledger.analyzed()[1].metrics == {"n": 1}
    assert ledger.analyzed()[0].metrics is None
    assert ledger.read_digest(date(2026, 10, 1)).candidates == [{"title": "c"}]  # type: ignore[union-attr]
    assert handlers.rows(tmp_path) == 2
    assert handlers.verify(tmp_path)["ok"] is True


def test_migrate_is_idempotent_and_verify_detects_drift(tmp_path: Path) -> None:
    _seed(tmp_path)
    handlers.migrate(tmp_path, dry_run=False)
    handlers.migrate(tmp_path, dry_run=False)
    assert handlers.verify(tmp_path)["ok"] is True
    FilesLedger(tmp_path).mark("h", "new", "t", "s")
    result = handlers.verify(tmp_path)
    assert result["ok"] is False
    assert result["mismatch"] == ["analyzed"]


def test_retire_removes_only_imported_sources(tmp_path: Path) -> None:
    _seed(tmp_path)
    handlers.migrate(tmp_path, dry_run=False)
    _flip(tmp_path)
    assert handlers.retire(tmp_path)["removed"] == [
        "analyzed.jsonl",
        "digests/2026-10-01.json",
        "digests/2026-10-02.json",
    ]
    assert (tmp_path / "digests" / "not-a-date.json").exists()
    assert handlers.verify(tmp_path)["ok"] is True
    assert len(open_ledger(tmp_path).analyzed()) == 2


def test_post_flip_writes_do_not_block_verify_or_retire(tmp_path: Path) -> None:
    _seed(tmp_path)
    handlers.migrate(tmp_path, dry_run=False)
    _flip(tmp_path)
    ledger = open_ledger(tmp_path)
    ledger.mark("h", "later", "t9", "new")
    ledger.mark("h", "s2", "t9", "rewritten")
    ledger.write_digest(date(2026, 10, 3), "d3", [])
    ledger.write_digest(date(2026, 10, 1), "d1b", [])
    assert handlers.verify(tmp_path)["ok"] is True
    handlers.retire(tmp_path)
    assert {r.session for r in ledger.analyzed()} == {"s1", "s2", "later"}


def test_verify_fails_when_a_source_row_is_missing(tmp_path: Path) -> None:
    _seed(tmp_path)
    handlers.migrate(tmp_path, dry_run=False)
    _flip(tmp_path)
    with (tmp_path / "analyzed.jsonl").open("a") as source:
        source.write('{"session":"lost","harness":"h","analyzed_at":"t"}\n')
    assert handlers.verify(tmp_path)["mismatch"] == ["analyzed"]


def test_other_domain_flip_does_not_stale_the_ledger(tmp_path: Path) -> None:
    _flip(tmp_path)
    ledger = open_ledger(tmp_path)
    with exclusive_store_lock(tmp_path):
        flip_domain_locked(tmp_path, "friction", "sqlite")
    ledger.mark("h", "s", "t", "x")
    assert [r.session for r in ledger.analyzed()] == ["s"]


def test_empty_keys_are_not_reported_like_files(tmp_path: Path) -> None:
    files_root, sqlite_root = tmp_path / "f", tmp_path / "s"
    sqlite_root.mkdir()
    _flip(sqlite_root)
    for ledger in (FilesLedger(files_root), SqliteLedger(sqlite_root)):
        ledger.mark("h", "", "t", "x")
        ledger.mark("", "s", "t", "x")
        ledger.mark("h", "s", "", "x")
        assert ledger.analyzed() == []


def test_writer_refused_after_domain_leaves_sqlite(tmp_path: Path) -> None:
    _flip(tmp_path)
    stale = SqliteLedger(tmp_path)
    with exclusive_store_lock(tmp_path):
        flip_domain_locked(tmp_path, "ledger", "files")
    with pytest.raises(StaleGeneration):
        stale.mark("h", "s", "t", "x")
    with pytest.raises(StaleGeneration):
        stale.write_digest(date(2026, 1, 1), "x", [])
    assert not (tmp_path / "analyzed.jsonl").exists()


def test_files_writer_refused_after_flip_and_mark_is_exact(tmp_path: Path) -> None:
    _flip(tmp_path)
    with pytest.raises(StaleGeneration):
        FilesLedger(tmp_path).mark("h", "s", "t", "x")
    ledger = open_ledger(tmp_path)
    ledger.mark("h", "s", "t", "x")
    assert json.loads(json.dumps(ledger.analyzed()[0].__dict__)) == {
        "session": "s",
        "harness": "h",
        "analyzed_at": "t",
        "summary": "x",
        "metrics": {},
        "friction_added": [],
    }
    assert read_learn_mode(tmp_path).ledger == "sqlite"
