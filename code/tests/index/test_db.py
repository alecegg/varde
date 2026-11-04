from __future__ import annotations

from varde_code.index.db import (
    SCHEMA_VERSION,
    TABLES,
    build_version_fingerprint,
    initialize,
)
from varde_code.index.paths import repo_db_path, repo_identity


def test_schema_tables_and_generated_columns(tmp_path):
    connection = initialize(tmp_path / "index.db")
    names = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert names - {
        "lexical_config",
        "lexical_data",
        "lexical_docsize",
        "lexical_idx",
    } == set(TABLES)
    assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    columns = {
        row[1]: row[2] for row in connection.execute("PRAGMA table_xinfo(files)")
    }
    assert columns["is_test_path"] == "BOOLEAN"
    assert columns["is_tooling_path"] == "BOOLEAN"
    connection.execute("INSERT INTO files(path) VALUES ('src/test_widget.py')")
    assert connection.execute("SELECT is_test_path FROM files").fetchone()[0] == 1
    connection.close()


def test_schema_indexes_and_build_fingerprint(tmp_path):
    connection = initialize(tmp_path / "index.db")
    indexes = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'"
        )
    }
    assert "idx_resolved_edges_from" in indexes
    assert "idx_entities_name" in indexes
    assert (
        connection.execute(
            "SELECT value FROM slice_meta WHERE key='build_version'"
        ).fetchone()[0]
        == build_version_fingerprint()
    )
    assert isinstance(build_version_fingerprint(), int)
    connection.close()


def test_repo_paths_are_isolated_and_canonical(monkeypatch, tmp_path):
    config = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    first = tmp_path / "one" / "repo"
    second = tmp_path / "two" / "repo"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    a = repo_db_path(first)
    assert a == repo_db_path(first / ".")
    b = repo_db_path(second)
    assert a.parent.parent == config / "code" / "repos-py"
    assert a.name == b.name == "index.db"
    assert a != b
    assert a.parent.name.startswith("repo-")
    assert repo_identity(first) != repo_identity(second)
