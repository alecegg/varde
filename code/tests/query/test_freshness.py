from __future__ import annotations

import sqlite3

from varde_code.query import dispatch


def test_dispatch_rejects_database_from_another_source_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "index.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE slice_meta(key TEXT, value INTEGER)")
        db.execute("INSERT INTO slice_meta VALUES ('source_root', 42)")

    result = dispatch("hotspots", {"repoRoot": str(repo), "dbPath": str(db_path)})

    assert result["data"]["error"]["code"] == "index_stale"
    assert result["data"]["error"]["message"] == (
        "dbPath index was built for another source root or predates "
        "source-root validation"
    )


def test_diagnostic_modes_do_not_reject_database_source_root(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    db_path = tmp_path / "index.db"
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE slice_meta(key TEXT, value INTEGER)")
        db.execute("INSERT INTO slice_meta VALUES ('source_root', 42)")

    result = dispatch("detect_changes", {"repoRoot": str(repo), "dbPath": str(db_path)})

    assert result["ok"] is True
