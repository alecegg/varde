from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest
from varde_data.backends.sqlite.decisions import SqliteDecisions
from varde_data.errors import Invalid

FIXTURES = Path(__file__).parent / "fixtures" / "decisions"


@pytest.mark.parametrize(
    "fixture", sorted(FIXTURES.glob("v0_*.sqlite3")), ids=lambda p: p.name
)
def test_migrates_legacy_databases(tmp_path: Path, fixture: Path) -> None:
    target = tmp_path / "decisions.sqlite3"
    shutil.copy2(fixture, target)
    before = _rows(target)

    repo = SqliteDecisions(tmp_path)
    after = _rows(target)
    for old_table, new_table in zip(before, after, strict=True):
        assert [row[: len(old_table[0])] for row in new_table] == old_table
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT version FROM meta").fetchone()[0] == 0
    repo.close()

    repo = SqliteDecisions(tmp_path)
    with sqlite3.connect(target) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT version FROM meta").fetchone()[0] == 0
    answer = repo.submit_answer("retry-decision", "retry-key", "main", "answer")
    replay = repo.submit_answer("retry-decision", "retry-key", "main", "answer")
    assert answer.entry == replay.entry
    assert not answer.replayed and replay.replayed
    repo.close()


def test_refuses_newer_schema(tmp_path: Path) -> None:
    SqliteDecisions(tmp_path).close()
    with sqlite3.connect(tmp_path / "decisions.sqlite3") as db:
        db.execute("PRAGMA user_version = 2")
    with pytest.raises(Invalid, match="newer"):
        SqliteDecisions(tmp_path)


def _rows(path: Path) -> tuple[list[tuple[object, ...]], ...]:
    with sqlite3.connect(path) as db:
        return (
            db.execute("SELECT * FROM decisions ORDER BY rowid").fetchall(),
            db.execute("SELECT * FROM answers ORDER BY rowid").fetchall(),
            db.execute("SELECT * FROM audit ORDER BY rowid").fetchall(),
        )
