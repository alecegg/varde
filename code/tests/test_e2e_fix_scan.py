from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_code.index import paths as index_paths
from varde_code.query.params import QueryError
from varde_code.rules.dependency_facts import lua_bash
from varde_code.rules.dependency_facts.types import FileRow, ImportRow
from varde_code.rules.model import Diagnostic
from varde_code.scan import core


def test_scan_reads_python_index_without_index_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_dir = tmp_path / "config"
    monkeypatch.setattr(core, "index_service", lambda: None)
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: config_dir)
    monkeypatch.setattr(core, "run_rules", lambda *args: ([], []))

    db_path = index_paths.repo_db_path(repo_root)
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript("""
            CREATE TABLE files (
                id INTEGER PRIMARY KEY, path TEXT, is_test_path INTEGER
            );
            CREATE TABLE diagnostics (
                id INTEGER PRIMARY KEY, path TEXT, message TEXT, severity TEXT,
                file_id INTEGER
            );
        """)

    payload = core.scan_repo({"repoRoot": str(repo_root), "skipQuality": True})

    assert "/code/repos-py/" in str(db_path)
    assert payload["findings_summary"]["total"] == 0


def test_scan_missing_index_uses_python_index_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(core, "index_service", lambda: None)
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: tmp_path / "config")

    with pytest.raises(QueryError, match="index missing at") as error:
        core.scan_repo({"repoRoot": str(repo_root)})

    expected_path = index_paths.repo_db_path(repo_root)
    assert error.value.code == "index_missing"
    assert "/code/repos-py/" in str(expected_path)
    assert "/code/repos/" not in str(expected_path)


def test_scan_drops_unsupported_file_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(core, "index_service", lambda: None)
    monkeypatch.setattr(core, "run_rules", lambda *args: ([], []))
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: tmp_path / "config")

    db_path = index_paths.repo_db_path(repo_root)
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as connection:
        connection.executescript("""
            CREATE TABLE files (id INTEGER PRIMARY KEY, is_test_path INTEGER);
            CREATE TABLE diagnostics (
                id INTEGER PRIMARY KEY, path TEXT, message TEXT, severity TEXT,
                file_id INTEGER
            );
            INSERT INTO files VALUES (1, 0);
            INSERT INTO diagnostics VALUES (
                1, 'README.md', 'unsupported file type — skipped', 'info', 1
            );
            INSERT INTO diagnostics VALUES (
                2, 'src/main.py', 'syntax error', 'warning', 1
            );
        """)

    payload = core.scan_repo({"repoRoot": str(repo_root), "skipQuality": True})

    assert [item["path"] for item in payload["diagnostics"]] == ["src/main.py"]


def test_rule_diagnostics_block_scan_gate_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(core, "index_service", lambda: None)
    monkeypatch.setattr(
        core,
        "load_rules_with_details",
        lambda root: ([], [], SimpleNamespace(origins={})),
    )
    monkeypatch.setattr(
        core,
        "run_rules",
        lambda *args: (
            [],
            [
                Diagnostic(
                    "duplicate-code-clone",
                    "src/main.py",
                    "function span missing from source tree",
                )
            ],
        ),
    )
    monkeypatch.setattr(index_paths, "varde_config_dir", lambda: tmp_path / "config")

    db_path = index_paths.repo_db_path(repo_root)
    db_path.parent.mkdir(parents=True)
    db_path.touch()

    payload = core.scan_repo({"repoRoot": str(repo_root)})

    assert payload["diagnostics"][0]["blocking"] is True
    assert payload["gate"]["blocking_diagnostic_count"] == 1
    assert payload["gate"]["status"] == "unknown"


def test_lua_fact_accepts_stat_result_from_metadata_helper(tmp_path: Path):
    source_path = tmp_path / "main.lua"
    target_path = tmp_path / "helper.lua"
    source_path.touch()
    target_path.touch()
    source = FileRow(1, "main.lua", "main.lua", source_path)
    target = FileRow(2, "helper.lua", "helper.lua", target_path)
    imp = ImportRow(1, source.id, "helper")

    fact = lua_bash.lua_fact(
        tmp_path,
        {source.id: source, target.id: target},
        {"helper.lua": [target.id]},
        [target],
        source,
        imp,
    )

    assert fact is not None
    assert fact.to_file_id == target.id
